"""Section-by-section generation for long official documents.

Long drafts are planned once, then each first-level section is generated independently with a
section-specific RAG query. The backend assembles sections and runs the existing deterministic
postprocess / QualityGate / version snapshot once. A failed section is retried locally; the service
never falls back to regenerating the whole long document merely because one chapter is bad.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterator, List, Optional, Tuple

from fastapi import HTTPException

from app.application.writing.quality_gate import QualityGate
from app.application.writing.structured_field_service import StructuredFieldWritingTaskService
from app.application.writing.task_service import _sse
from app.core.timeutil import now_local

_LONG_DOC_TYPES = {
    "报告", "工作报告", "工作情况报告", "工作总结", "总结", "方案", "实施方案",
    "工作方案", "调研报告",
}
_SPEECH_TYPES = ("致辞", "讲话", "发言", "主持词")
_DEFAULT_SECTIONS = {
    "讲话稿": [
        ("", "面向听众自然开场，点明活动场合、主题和来宾，表达欢迎或感谢"),
        ("", "结合本次主题说明背景、意义和与听众有关的实际经历"),
        ("", "围绕主题谈具体体会、共同愿景或倡议，保持现场讲话语气"),
        ("", "自然收束，表达祝愿、感谢或期待，适合现场口头宣读"),
    ],
    "主持词": [
        ("", "宣布会议开始，说明会议名称、时间和参加人员"),
        ("", "按议程串联各环节，介绍发言单位和议题"),
        ("", "小结会议成效并提出贯彻要求，自然收束"),
    ],
    "工作总结": [
        ("一、工作开展情况", "概括阶段工作主线、推进过程和主要完成情况"),
        ("二、主要做法和成效", "按重点工作提炼做法、机制和有依据的成效"),
        ("三、存在问题", "客观分析短板及原因，不虚构问题数据"),
        ("四、下一步工作安排", "结合问题提出具体、可执行的后续举措"),
    ],
    "报告": [
        ("一、基本情况", "交代背景、范围和总体情况"),
        ("二、主要工作情况", "展开工作过程、主要做法和有依据的成效"),
        ("三、存在问题", "归纳当前问题和制约因素"),
        ("四、下一步工作", "提出下一阶段具体工作安排"),
    ],
    "方案": [
        ("一、总体要求", "说明工作目标、原则和总体安排"),
        ("二、主要任务", "分层展开核心任务和具体举措"),
        ("三、实施步骤", "明确阶段安排、时间逻辑和推进方式"),
        ("四、保障措施", "明确责任、协同、督导和风险控制"),
    ],
}


class SectionedGenerationWritingTaskService(StructuredFieldWritingTaskService):
    """Use section generation for long-form drafts while preserving all lower-layer guarantees."""

    @staticmethod
    def _should_section(ctx: Dict[str, Any], outline_only: bool = False) -> bool:
        if outline_only:
            return False
        target = int(ctx.get("word_count_target") or 0)
        doc_type = str(ctx.get("document_type") or "").strip()
        # 未知文种照常起草：报告骨架不是安全的兜底。
        is_speech = any(x in doc_type for x in _SPEECH_TYPES)
        # 短篇现场材料用带文种约束的单次流式起草，避免先等一次完整 JSON
        # 章节规划。长篇仍分节，以便逐节检索和质量检查。未给字数时沿用
        # 长篇路径，避免把用户期望的完整讲话压成短稿。
        if is_speech:
            return target == 0 or target > 1200
        return doc_type in _LONG_DOC_TYPES and (target >= 1800 or target == 0)

    @staticmethod
    def _fallback_plan(ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
        """模型规划失败时的兜底。

        heading 一律留空：不硬塞「一、基本情况」这类报告骨架。
        此前未匹配文种会落到「报告」四段式，导致讲话稿、发言稿等连续行文体例
        被套上不相称的小标题。这里只保留「本节写什么」的内容要求，
        标题与层次交给模型按文种体例自行决定。
        """
        doc_type = str(ctx.get("document_type") or "")
        # 主持词不是致辞：前者串联议程，后者向来宾致意。共用一套计划会互相串味。
        if "主持词" in doc_type:
            key = "主持词"
        elif any(x in doc_type for x in _SPEECH_TYPES):
            key = "讲话稿"
        else:
            key = ("方案" if "方案" in doc_type
                   else "工作总结" if "总结" in doc_type
                   else "报告" if doc_type in _LONG_DOC_TYPES else None)
        if key is None:
            return []
        items = _DEFAULT_SECTIONS[key]
        total = int(ctx.get("word_count_target") or 2200)
        # 短稿不该被硬拆成 4 节：800 字发言稿分4 节每节只有 200 字，
        # 切得太碎反而破坏「连续行文」的连贯感（讲话是顺着讲的，不是分段念的）。
        # 讲话类按篇幅缩到 3 节，其余文种维持 4 节。
        is_speech = key in ("讲话稿", "主持词")
        if is_speech and total < 1200:
            items = items[:3]
        # 下限不能用固定 350：短稿分 3~4 节时 350×N 会把全文强行拉长近一倍，
        # 产出「说不到那么长还硬撑」的水文。下限取 min(350, 平均的一半)，
        # 保证「下限不超过实际平均」——total 偏小时按实际均分，偏大时保底有内容可写。
        per = max(min(350, total // len(items) // 2), total // len(items))
        return [
            # heading 置空 = 不要小标题；focus 保留该节应覆盖的内容。
            {"heading": "", "focus": focus, "target_chars": per}
            for _heading, focus in items
        ]

    @staticmethod
    def _plan_meets_length(plan: List[Dict[str, Any]], total: int) -> bool:
        """Reject model plans that cannot plausibly meet the requested length."""
        return bool(plan) and 0.8 * total <= sum(p["target_chars"] for p in plan) <= 1.2 * total

    @staticmethod
    def _section_is_short(text: str, target: int) -> bool:
        return len(re.sub(r"\s+", "", text)) < int(target * 0.8)

    def _section_plan(self, ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Ask the model only for a compact chapter plan; deterministic fallback on any failure."""
        if not self.assistant:
            return self._fallback_plan(ctx)
        total = int(ctx.get("word_count_target") or 2200)
        original_request = next((str(item.get("content") or "").strip()
                                 for item in ctx.get("history") or []
                                 if item.get("role") == "user" and item.get("content")), "")
        prompt = (
            "为一篇司法行政机关正式材料规划章节。只返回 JSON 数组，不要正文、Markdown 或解释。"
            "数组 3-6 项，每项字段为 heading、focus、target_chars。\n"
            "heading 是本节的小标题，**由你按该文种的体例自行决定用什么形式**："
            "报告、方案等可用「一、××」「（一）××」；致辞稿、讲话稿、发言稿、主持词等连续行文体例"
            "请把 heading 留空字符串，表示本节直接接续上文写、不要插入小标题。"
            "切勿把所有文种一律套用「一、二、三」。\n"
            "focus 用一句话说明本节只写什么（写内容要求，不要写标题格式）；"
            "target_chars 为本节目标字数。章节之间职责不能重叠，目标字数合计应接近全文目标。\n"
            f"文种：{ctx.get('document_type') or '正式材料'}\n"
            f"主题：{ctx.get('topic') or ctx.get('title') or ''}\n"
            f"用途：{ctx.get('purpose') or ''}\n"
            f"时间范围：{ctx.get('time_range') or ''}\n"
            f"全文目标字数：{total}"
            f"\n用户原始需求：{original_request}"
        )
        try:
            raw = self.assistant.complete(
                [{"role": "user", "content": prompt}], temperature=0.1, max_tokens=900
            ) or ""
            match = re.search(r"\[[\s\S]*\]", raw)
            data = json.loads(match.group(0) if match else raw)
            plan: List[Dict[str, Any]] = []
            for item in data if isinstance(data, list) else []:
                heading = str(item.get("heading") or "").strip()
                focus = str(item.get("focus") or "").strip()
                try:
                    chars = int(item.get("target_chars") or 0)
                except (TypeError, ValueError):
                    chars = 0
                # heading 允许为空：代表该节不要小标题（连续行文体例）。
                # 原先强制匹配「一、二、」会把这类plan 整条丢弃并退回兜底骨架，
                # 而兜底骨架只有报告/方案/总结三种，正是讲话稿被套成报告体例的来源。
                if focus:
                    plan.append({
                        "heading": heading[:80],
                        "focus": focus[:240],
                        "target_chars": max(300, min(chars or total // 4, max(1200, total))),
                    })
            speech = any(x in str(ctx.get("document_type") or "") for x in _SPEECH_TYPES)
            if speech and any(
                item["heading"] or any(bad in item["focus"] for bad in
                    ("总体要求", "实施步骤", "保障措施", "责任分工", "工作方案"))
                for item in plan
            ):
                return self._fallback_plan(ctx)
            if 3 <= len(plan) <= 6 and self._plan_meets_length(plan, total):
                return plan
        except Exception:
            pass
        return self._fallback_plan(ctx)

    @staticmethod
    def _section_instruction(ctx: Dict[str, Any], section: Dict[str, Any],
                             previous_headings: List[str], next_headings: List[str]) -> str:
        key_facts = "；".join(str(x) for x in (ctx.get("key_facts") or [])[:12])
        speech = any(x in str(ctx.get("document_type") or "") for x in _SPEECH_TYPES)
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
            + "\n不得输出全文标题、主送机关、文号、发文机关署名或成文日期；"
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

    def _generate_one_section(self, ctx: Dict[str, Any], section: Dict[str, Any],
                              index: int, plan: List[Dict[str, Any]], user_id: str,
                              attachment_ctx: str, template) -> Tuple[str, List[Dict]]:
        previous = [x["heading"] or x["focus"] for x in plan[:index]]
        following = [x["heading"] or x["focus"] for x in plan[index + 1:]]
        instruction = self._section_instruction(ctx, section, previous, following)
        sources = self._retrieve(
            ctx, user_id,
            extra_query=f"{section['heading']} {section['focus']}"
        )
        candidate = self._clean_markdown(
            self._llm_draft(instruction, sources, attachment_ctx, user_id, template=template)
        )
        candidate = self._normalize_section(candidate, section["heading"])

        if self._section_is_short(candidate, section["target_chars"]):
            expanded = self._normalize_section(
                self._clean_markdown(self._llm_draft(
                    instruction + "\n\n上一版篇幅明显不足。请依据已提供的事实和材料，"
                    "完整展开当前章节的过程、结果及必要的承接句；不得补造数据或事例。"
                    "仍只输出这一节。\n上一版：\n" + candidate[:5000],
                    sources, attachment_ctx, user_id, template=template)),
                section["heading"],
            )
            if (len(expanded) > len(candidate)
                    and QualityGate().evaluate(expanded, body_only=True).get("level") != "D"):
                candidate = expanded

        quality = QualityGate().evaluate(candidate, body_only=True)
        retry_no = 0
        while quality.get("level") == "D" and retry_no < 2:
            retry_no += 1
            issues = [
                str(x.get("message") or x.get("type") or "")
                for x in quality.get("issues") or []
                if isinstance(x, dict) and x.get("severity") == "critical"
            ]
            repair = (
                instruction + "\n\n上一版当前章节未通过质量检查，只重写这一节，不得生成其他章节。"
                "必须修复：" + "；".join(issues or ["章节正文质量不合格"])
                + "\n上一版：\n" + candidate[:5000]
            )
            candidate = self._clean_markdown(
                self._llm_draft(repair, sources, attachment_ctx, user_id, template=template)
            )
            candidate = self._normalize_section(candidate, section["heading"])
            quality = QualityGate().evaluate(candidate, body_only=True)
        if quality.get("level") == "D":
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "WRITING_SECTION_QUALITY_D",
                    "message": f"{section['heading']} 连续两次修复后仍未通过质量门，全文未保存。",
                    "section": section["heading"],
                    "issues": quality.get("issues") or [],
                },
            )
        return candidate, sources

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

    def _sectioned_draft(self, task_id: str, user_id: str) -> Dict[str, Any]:
        task = self._get_owned(task_id, user_id)
        ctx = dict(task.context or {})
        template = self._load_template(ctx.get("template_id"))
        attachment_ctx = self._attachment_context(task, ctx)
        plan = self._section_plan(ctx)
        sections: List[str] = []
        source_groups: List[List[Dict]] = []
        for index, section in enumerate(plan):
            text, sources = self._generate_one_section(
                ctx, section, index, plan, user_id, attachment_ctx, template
            )
            sections.append(text)
            source_groups.append(sources)
        assembled = "\n\n".join(sections).strip()
        if not assembled:
            raise HTTPException(status_code=502, detail="模型未返回内容，请重试")
        payload = self._finalize_draft(
            task, ctx, assembled, self._merge_sources(source_groups), user_id
        )
        payload["generation_mode"] = "sectioned"
        payload["section_plan"] = plan
        payload["reply"] = "长文已按章节分别检索、生成并组装。" + payload["reply"]
        return payload

    def draft(self, task_id: str, user_id: str,
              outline_only: bool = False) -> Dict[str, Any]:
        task = self._get_owned(task_id, user_id)
        ctx = dict(task.context or {})
        if self._should_section(ctx, outline_only):
            return self._sectioned_draft(task_id, user_id)
        return super().draft(task_id, user_id, outline_only=outline_only)

    def draft_stream(self, task_id: str, user_id: str,
                     outline_only: bool = False) -> Iterator[str]:
        task = self._get_owned(task_id, user_id)
        ctx = dict(task.context or {})
        if not self._should_section(ctx, outline_only):
            yield from super().draft_stream(task_id, user_id, outline_only=outline_only)
            return
        try:
            template = self._load_template(ctx.get("template_id"))
            attachment_ctx = self._attachment_context(task, ctx)
            plan = self._section_plan(ctx)
            sections: List[str] = []
            source_groups: List[List[Dict]] = []
            for index, section in enumerate(plan):
                text, sources = self._generate_one_section(
                    ctx, section, index, plan, user_id, attachment_ctx, template
                )
                text = text.strip()
                sections.append(text)
                source_groups.append(sources)
                # Existing clients already understand delta; one complete chapter per delta avoids
                # exposing half-generated text that may later fail its local quality retry.
                yield _sse({"type": "delta", "text": ("\n\n" if index else "") + text})
            assembled = "\n\n".join(sections).strip()
            payload = self._finalize_draft(
                task, ctx, assembled, self._merge_sources(source_groups), user_id
            )
            payload["generation_mode"] = "sectioned"
            payload["section_plan"] = plan
            payload["reply"] = "长文已按章节分别检索、生成并组装。" + payload["reply"]
            yield _sse({"type": "done", "data": payload})
        except HTTPException as exc:
            yield _sse({"type": "error", "message": str(exc.detail)})
        except Exception as exc:
            yield _sse({"type": "error", "message": f"分章节生成中断：{exc}"})
