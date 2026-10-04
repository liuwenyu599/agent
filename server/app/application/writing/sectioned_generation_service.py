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

_LONG_DOC_TYPES = {
    "报告", "工作报告", "工作情况报告", "工作总结", "总结", "方案", "实施方案",
    "工作方案", "规划", "意见", "调研报告", "汇报材料",
}
_DEFAULT_SECTIONS = {
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
        return target >= 1800 or (doc_type in _LONG_DOC_TYPES and target == 0)

    @staticmethod
    def _fallback_plan(ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
        doc_type = str(ctx.get("document_type") or "报告")
        key = "方案" if "方案" in doc_type else ("工作总结" if "总结" in doc_type else "报告")
        items = _DEFAULT_SECTIONS[key]
        total = int(ctx.get("word_count_target") or 2200)
        per = max(350, total // len(items))
        return [
            {"heading": heading, "focus": focus, "target_chars": per}
            for heading, focus in items
        ]

    def _section_plan(self, ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Ask the model only for a compact chapter plan; deterministic fallback on any failure."""
        if not self.assistant:
            return self._fallback_plan(ctx)
        total = int(ctx.get("word_count_target") or 2200)
        prompt = (
            "为一篇司法行政机关正式材料规划一级章节。只返回 JSON 数组，不要正文、Markdown 或解释。"
            "数组 3-6 项，每项字段必须为 heading、focus、target_chars。heading 必须使用"
            "‘一、…’‘二、…’格式；focus 用一句话说明本节只写什么；target_chars 为本节目标字数。"
            "章节之间职责不能重叠，目标字数合计应接近全文目标。\n"
            f"文种：{ctx.get('document_type') or '报告'}\n"
            f"主题：{ctx.get('topic') or ctx.get('title') or ''}\n"
            f"用途：{ctx.get('purpose') or ''}\n"
            f"时间范围：{ctx.get('time_range') or ''}\n"
            f"全文目标字数：{total}"
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
                if heading and focus and re.match(r"^[一二三四五六七八九十]+、", heading):
                    plan.append({
                        "heading": heading[:80],
                        "focus": focus[:240],
                        "target_chars": max(300, min(chars or total // 4, 1200)),
                    })
            if 3 <= len(plan) <= 6:
                return plan
        except Exception:
            pass
        return self._fallback_plan(ctx)

    @staticmethod
    def _section_instruction(ctx: Dict[str, Any], section: Dict[str, Any],
                             previous_headings: List[str], next_headings: List[str]) -> str:
        key_facts = "；".join(str(x) for x in (ctx.get("key_facts") or [])[:12])
        return (
            "这是长文分章节生成任务，只写当前这一节，不要生成其他章节。\n"
            f"全文文种：{ctx.get('document_type') or '正式材料'}\n"
            f"全文主题：{ctx.get('topic') or ctx.get('title') or ''}\n"
            f"全文用途：{ctx.get('purpose') or ''}\n"
            f"当前章节：{section['heading']}\n"
            f"本节职责：{section['focus']}\n"
            f"本节目标字数：约 {section['target_chars']} 字\n"
            f"前文章节（禁止重复）：{'、'.join(previous_headings) or '无'}\n"
            f"后续章节（内容留给后文，不要提前展开）：{'、'.join(next_headings) or '无'}\n"
            f"已确认关键事实：{key_facts or '以本节检索材料为准'}\n"
            "输出必须从当前章节标题开始，随后写完整正式段落。涉及多个事项时用“（一）”“1．”“（1）”"
            "组织本节层级，事项超过 3 条不得写成连续叙述段落。不得输出全文标题、主送机关、文号、"
            "发文机关署名或成文日期；不得用‘略’‘待补充’等占位文字；不得重复前文。"
        )

    @staticmethod
    def _normalize_section(text: str, heading: str) -> str:
        text = (text or "").strip()
        if not text:
            return ""
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
        previous = [x["heading"] for x in plan[:index]]
        following = [x["heading"] for x in plan[index + 1:]]
        instruction = self._section_instruction(ctx, section, previous, following)
        sources = self._retrieve(
            ctx, user_id,
            extra_query=f"{section['heading']} {section['focus']}"
        )
        candidate = self._clean_markdown(
            self._llm_draft(instruction, sources, attachment_ctx, user_id, template=template)
        )
        candidate = self._normalize_section(candidate, section["heading"])

        quality = QualityGate().evaluate(candidate, topic=section["heading"])
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
            quality = QualityGate().evaluate(candidate, topic=section["heading"])
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
                sections.append(text)
                source_groups.append(sources)
                # Existing clients already understand delta; one complete chapter per delta avoids
                # exposing half-generated text that may later fail its local quality retry.
                yield _sse({"type": "delta", "text": text + "\n\n"})
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
