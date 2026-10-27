"""Section-by-section generation for long official documents.

Long drafts are planned once, then each first-level section is generated independently with a
section-specific RAG query. The backend assembles sections and runs the existing deterministic
finalize pipeline / QualityGate / version snapshot once. A failed section is retried locally; the
service never falls back to regenerating the whole long document merely because one chapter is bad.

本层只保留「分节这件事」的确定性规则：是否分节、兜底骨架、章节指令、章节清洗。
真正的模型调用在异步生产入口（``AsyncWritingTaskService``）里，避免同步副本与生产实现分叉。
"""
from __future__ import annotations

import re
from typing import Any, Dict, List

from app.application.writing.section_policy import (
    default_section_plan,
    is_speech_type,
    needs_sectioning,
)
from app.application.writing.structured_field_service import StructuredFieldWritingTaskService
from app.core.timeutil import now_local


class SectionedGenerationWritingTaskService(StructuredFieldWritingTaskService):
    """Use section generation for long-form drafts while preserving all lower-layer guarantees."""

    @staticmethod
    def _should_section(ctx: Dict[str, Any], outline_only: bool = False) -> bool:
        if outline_only:
            return False
        # 未知文种照常起草：报告骨架不是安全的兜底。
        return needs_sectioning(
            str(ctx.get("document_type") or "").strip(),
            int(ctx.get("word_count_target") or 0),
        )

    @staticmethod
    def _fallback_plan(ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
        """模型规划失败时的兜底骨架（规则见 section_policy.default_section_plan）。"""
        return default_section_plan(
            str(ctx.get("document_type") or ""),
            int(ctx.get("word_count_target") or 2200),
        )

    @staticmethod
    def _plan_meets_length(plan: List[Dict[str, Any]], total: int) -> bool:
        """Reject model plans that cannot plausibly meet the requested length."""
        return bool(plan) and 0.8 * total <= sum(p["target_chars"] for p in plan) <= 1.2 * total

    @staticmethod
    def _section_is_short(text: str, target: int) -> bool:
        return len(re.sub(r"\s+", "", text)) < int(target * 0.8)

    @staticmethod
    def _section_instruction(ctx: Dict[str, Any], section: Dict[str, Any],
                             previous_headings: List[str], next_headings: List[str]) -> str:
        key_facts = "；".join(str(x) for x in (ctx.get("key_facts") or [])[:12])
        speech = is_speech_type(str(ctx.get("document_type") or ""))
        # heading 为空 = 本节不加小标题、接续上文写（讲话稿/发言稿等连续行文体例）
        heading = str(section.get("heading") or "").strip()
        heading_line = (
            f"当前章节标题：{heading}\n"
            if heading else
            "当前章节：不设小标题，直接接续上文连贯行文，不要另起「一、二、三」式标题。\n"
        )
        return (
            "这是长文分章节生成任务，只写当前这一节，不要生成其他章节。\n"
            f"全文文种：{ctx.get('document_type') or '正式材料'}\n"
            f"全文主题：{ctx.get('topic') or ctx.get('title') or ''}\n"
            f"全文用途：{ctx.get('purpose') or ''}\n"
            f"当前日期：{now_local().year}年{now_local().month}月{now_local().day}日。"
            "只作为本次时间背景，不照搬旧范文日期。\n"
            f"用户原始需求：{next((str(x.get('content') or '') for x in ctx.get('history') or [] if x.get('role') == 'user'), '')}\n"
            + heading_line
            + f"本节职责：{section['focus']}\n"
            f"本节目标字数：约 {section['target_chars']} 字\n"
            f"前文章节（禁止重复）：{'、'.join(previous_headings) or '无'}\n"
            f"后续章节（内容留给后文，不要提前展开）：{'、'.join(next_headings) or '无'}\n"
            f"已确认关键事实：{key_facts or '以本节检索材料为准'}\n"
            # 无小标题时不能说「从标题开始」，也不能强制事项分层——
            # 讲话稿/发言稿按自然段推进才是它们的体例。
            + ("输出直接从本节正文开始，不要另起章节标题。" if not heading
               else "输出必须从当前章节标题开始，随后写完整正式段落。")
            + ("\n保持现场讲话语气，使用连贯自然段，不列任务清单或小标题。" if speech
               else "\n本节内部按需组织层次：事项较多时可用「（一）」「1．」「（1）」分层，"
                    "内容连贯的场合直接写成连贯段落即可，不要为了分层而分层。" if not heading
               else "\n涉及多个事项时用“（一）”“1．”“（1）”组织本节层级，"
                    "事项超过 3 条不得写成连续叙述段落。")
            + "\n不得输出全文标题、文号、发文机关署名或成文日期；"
            "主送机关行只允许出现在全文最开头（即第一个分段的开头，且该文种需要主送时），"
            "其余分段不得输出；"
            "不得用'略''待补充'等占位文字；不得重复前文。"
        )

    @staticmethod
    def _normalize_section(text: str, heading: str) -> str:
        text = (text or "").strip()
        if not text:
            return ""
        # heading 为空表示「本节不要小标题」（讲话稿、发言稿等连续行文体例）。
        # 此时不做标题注入，也不用标题去切分正文——按内容自然推进即可。
        if not heading:
            return text
        # Model sometimes repeats the document title before the requested chapter; discard anything
        # before the exact requested heading. If it omitted the heading, backend adds it once.
        pos = text.find(heading)
        if pos >= 0:
            text = text[pos:]
        elif not text.startswith(heading):
            text = heading + "\n" + text
        # Stop accidental spill into the next same-level chapter; the next chapter is generated with
        # its own context and evidence.
        lines = text.splitlines()
        kept = [lines[0]]
        for line in lines[1:]:
            s = line.strip()
            if re.match(r"^[一二三四五六七八九十]+、", s) and s != heading:
                break
            kept.append(line)
        return "\n".join(kept).strip()

    @staticmethod
    def _merge_sources(groups: List[List[Dict]]) -> List[Dict]:
        out: List[Dict] = []
        seen = set()
        for group in groups:
            for item in group or []:
                key = item.get("chunk_id") or (item.get("doc_id"), item.get("source"))
                if key in seen:
                    continue
                seen.add(key)
                out.append(item)
        return out
