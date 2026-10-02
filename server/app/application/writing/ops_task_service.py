"""Executable writing operations on top of the grounded writing service.

The semantic interpreter decides *what* the user wants; this layer decides *how* that operation
mutates the document. In particular, ``patch_section`` never sends the whole document to the
model. It resolves one deterministic span, asks the model for only the replacement fragment, and
splices that fragment back into the authoritative document. If a target is ambiguous, it fails
closed instead of silently escalating to a full-document rewrite.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException

from app.application.writing import task_parser
from app.application.writing.grounded_task_service import GroundedWritingTaskService
from app.application.writing.task_service import REVISE_MODES
from app.core.timeutil import now_local


_PARAGRAPH_TARGET_RE = re.compile(
    r"第\s*([0-9０-９一二三四五六七八九十百零〇两]+)\s*段"
)
_TOP_HEADING_RE = re.compile(r"^\s*[一二三四五六七八九十百]+、")
_SUB_HEADING_RE = re.compile(r"^\s*[（(][一二三四五六七八九十百]+[）)]")
_NUM_HEADING_RE = re.compile(r"^\s*\d+[\.、．]")

_CN_DIGITS = {
    "零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
}


def _cn_number(value: str) -> Optional[int]:
    value = value.strip().translate(str.maketrans("０１２３４５６７８９", "0123456789"))
    if value.isdigit():
        n = int(value)
        return n if n > 0 else None
    if value == "十":
        return 10
    if "百" in value:
        left, _, right = value.partition("百")
        hundreds = _CN_DIGITS.get(left, 1) if left else 1
        tail = _cn_number(right) if right else 0
        return hundreds * 100 + (tail or 0)
    if "十" in value:
        left, _, right = value.partition("十")
        tens = _CN_DIGITS.get(left, 1) if left else 1
        ones = _CN_DIGITS.get(right, 0) if right else 0
        return tens * 10 + ones
    if len(value) == 1:
        return _CN_DIGITS.get(value)
    return None


class OpsWritingTaskService(GroundedWritingTaskService):
    """Production writing service that executes structured writing operations."""

    # ----------------------------------------------------------- target resolve
    @staticmethod
    def _paragraph_spans(text: str) -> List[Tuple[int, int]]:
        """Return non-empty paragraph spans while preserving blank-line separators outside them."""
        spans: List[Tuple[int, int]] = []
        start = 0
        for sep in re.finditer(r"\n[ \t]*\n+", text):
            raw_start, raw_end = start, sep.start()
            while raw_start < raw_end and text[raw_start].isspace():
                raw_start += 1
            while raw_end > raw_start and text[raw_end - 1].isspace():
                raw_end -= 1
            if raw_start < raw_end:
                spans.append((raw_start, raw_end))
            start = sep.end()
        raw_start, raw_end = start, len(text)
        while raw_start < raw_end and text[raw_start].isspace():
            raw_start += 1
        while raw_end > raw_start and text[raw_end - 1].isspace():
            raw_end -= 1
        if raw_start < raw_end:
            spans.append((raw_start, raw_end))
        return spans

    @staticmethod
    def _line_records(text: str) -> List[Tuple[int, int, str]]:
        records: List[Tuple[int, int, str]] = []
        pos = 0
        for raw in text.splitlines(keepends=True):
            end = pos + len(raw)
            records.append((pos, end, raw.rstrip("\r\n")))
            pos = end
        if pos < len(text):
            records.append((pos, len(text), text[pos:]))
        return records

    @classmethod
    def _section_span(cls, text: str, target: str) -> Optional[Tuple[int, int]]:
        target = target.strip()
        records = cls._line_records(text)
        matches = [i for i, (_, _, line) in enumerate(records) if line.strip() == target]
        if len(matches) != 1:
            return None
        idx = matches[0]
        line = records[idx][2]
        if _TOP_HEADING_RE.match(line):
            heading_re = _TOP_HEADING_RE
        elif _SUB_HEADING_RE.match(line):
            heading_re = _SUB_HEADING_RE
        elif _NUM_HEADING_RE.match(line):
            heading_re = _NUM_HEADING_RE
        else:
            return None
        start = records[idx][0]
        end = len(text)
        for j in range(idx + 1, len(records)):
            if heading_re.match(records[j][2]):
                end = records[j][0]
                while end > start and text[end - 1].isspace():
                    end -= 1
                break
        return (start, end) if start < end else None

    @classmethod
    def _resolve_patch_target(cls, text: str, target: str) -> Optional[Tuple[int, int, str]]:
        """Resolve a tool target to exactly one deterministic span.

        Resolution order is conservative: ordinal paragraph -> exact section heading -> unique
        literal excerpt. Ambiguity returns None and must be clarified; it never becomes a full
        rewrite implicitly.
        """
        target = (target or "").strip().strip("“”\"'《》")
        if not target:
            return None

        m = _PARAGRAPH_TARGET_RE.fullmatch(target)
        if m:
            index = _cn_number(m.group(1))
            spans = cls._paragraph_spans(text)
            if index and index <= len(spans):
                start, end = spans[index - 1]
                return start, end, text[start:end]
            return None

        section = cls._section_span(text, target)
        if section:
            start, end = section
            return start, end, text[start:end]

        # Literal excerpts are useful when the UI sends the user's selected text. Require one and
        # only one occurrence so a repeated sentence can never mutate an arbitrary location.
        if len(target) >= 4 and text.count(target) == 1:
            start = text.index(target)
            end = start + len(target)
            return start, end, text[start:end]
        return None

    @staticmethod
    def _build_patch_prompt(fragment: str, instruction: str, mode_desc: str) -> str:
        return (
            "这是【局部正文修改】操作，不是全文重写。\n"
            f"修改模式：{mode_desc}\n"
            f"用户要求：{instruction}\n\n"
            "【目标片段】\n"
            f"{fragment}\n"
            "【目标片段结束】\n\n"
            "只返回修改后的目标片段本身。禁止返回目标片段之外的正文；禁止补标题、主送机关、"
            "文号、落款或日期；未要求改变的事实必须保留。不要解释，不要 Markdown 包裹。"
        )

    # --------------------------------------------------------------- chat ops
    def chat(self, task_id: str, user_id: str, message: str) -> Dict[str, Any]:
        task = self._get_owned(task_id, user_id)
        ctx = dict(task.context or {})
        has_draft = bool((task.current_content or "").strip())
        self._push_history(ctx, "user", message)

        it = self._interpret(message, ctx, has_draft=has_draft)
        if not it:
            reply = "这条指令暂时没有可靠理解，因此没有改动文档。请重新表述后再试。"
            self._push_history(ctx, "assistant", reply)
            task.context = ctx
            self.db.commit()
            return {**self._to_dict(task), "reply": reply, "content_changed": False}

        before_ctx = dict(ctx)
        changes = self._merge_interpretation(ctx, it)
        task_parser.compute_missing(ctx)
        task.context = ctx
        task.updated_at = now_local()
        self.db.commit()

        operation = it.get("operation") or {
            "update_context": "set_fields",
            "revise_content": "rewrite_document",
            "draft": "draft_document",
            "outline": "outline",
            "answer": "answer",
            "clarify": "clarify",
        }.get(it.get("intent") or "answer", "answer")

        if operation == "patch_section" and has_draft:
            result = self.patch_section(
                task_id,
                user_id,
                target=it.get("patch_target") or "",
                instruction=it.get("revision_instruction") or message,
                mode=it.get("revision_mode") or "revise",
            )
            result["context_changes"] = changes
            latest_ctx = dict(task.context or {})
            self._push_history(latest_ctx, "assistant", result["reply"])
            task.context = latest_ctx
            self.db.commit()
            return result

        if operation == "rewrite_document" and has_draft:
            result = super().revise(
                task_id,
                user_id,
                instruction=it.get("revision_instruction") or message,
                mode=it.get("revision_mode") or "rewrite",
                selection=None,
            )
            result["context_changes"] = changes
            latest_ctx = dict(task.context or {})
            self._push_history(latest_ctx, "assistant", result["reply"])
            task.context = latest_ctx
            self.db.commit()
            return result

        if operation in ("draft_document", "outline"):
            result = self.draft(task_id, user_id, outline_only=(operation == "outline"))
            result["context_changes"] = changes
            latest_ctx = dict(task.context or {})
            self._push_history(latest_ctx, "assistant", result["reply"])
            task.context = latest_ctx
            self.db.commit()
            return result

        content_changed = False
        if has_draft and operation == "set_fields" and before_ctx != ctx:
            note = self._sync_structured_fields(task, user_id)
            content_changed = bool(note)
            if note:
                changes = list(changes) + [note]

        reply = it.get("reply") or "已理解。"
        if changes:
            reply += "\n\n已应用：" + "；".join(changes) + "。"
        self._push_history(ctx, "assistant", reply)
        task.context = ctx
        self.db.commit()
        return {
            **self._to_dict(task),
            "reply": reply,
            "content_changed": content_changed,
            "context_changes": changes,
            "operation": operation,
            "routing": it.get("routing") or "legacy",
        }

    # ---------------------------------------------------------- local mutation
    def patch_section(self, task_id: str, user_id: str, target: str,
                      instruction: str, mode: str = "revise") -> Dict[str, Any]:
        task = self._get_owned(task_id, user_id)
        ctx = dict(task.context or {})
        current = self._canonicalize_body((task.current_content or "").strip(), ctx)
        if not current:
            raise HTTPException(status_code=409, detail="当前还没有草稿，请先起草")

        resolved = self._resolve_patch_target(current, target)
        if not resolved:
            reply = (
                f"没有安全执行修改：无法把“{target or '未指定目标'}”唯一定位到当前正文。"
                "请选中具体原文，或明确到某一段/某一节后再修改；系统没有退化成整篇重写。"
            )
            return {
                **self._to_dict(task),
                "reply": reply,
                "content_changed": False,
                "context_changes": [],
                "operation": "patch_section",
                "patch_target": target,
            }

        start, end, fragment = resolved
        mode_desc = REVISE_MODES.get(mode, REVISE_MODES["revise"])
        prompt = self._build_patch_prompt(fragment, instruction, mode_desc)
        sources = self._retrieve(ctx, user_id, extra_query=instruction)
        attachment_ctx = self._attachment_context(task, ctx)
        replacement = self._llm_revise(prompt, sources, attachment_ctx, user_id).strip()
        if not replacement:
            raise HTTPException(status_code=502, detail="模型未返回局部修改内容，请重试")

        # A local operation is allowed to generate only the selected span. The backend owns the
        # splice; the model never receives or reconstructs the untouched remainder of the document.
        if replacement == fragment:
            return {
                **self._to_dict(task),
                "reply": "目标片段核对后没有产生实际文字变化，因此未创建新版本。",
                "content_changed": False,
                "context_changes": [],
                "operation": "patch_section",
                "patch_target": target,
            }

        revised = current[:start] + replacement + current[end:]
        revised, events, doc_number, doc_date = self._postprocess(revised, ctx)
        revised = self._canonicalize_body(revised, {
            **ctx,
            **({"document_number": doc_number} if doc_number else {}),
            **({"document_date": doc_date} if doc_date else {}),
        })
        revised, citation_warnings = self._guard_external_document_numbers(revised, sources, ctx)

        if citation_warnings:
            ctx["citation_warnings"] = citation_warnings
        else:
            ctx.pop("citation_warnings", None)
        if doc_number:
            ctx["document_number"] = doc_number
        if doc_date:
            ctx["document_date"] = doc_date

        from app.application.writing.quality_gate import QualityGate
        from app.application.writing.content_check import ContentChecker
        quality = QualityGate().evaluate(revised, topic=ctx.get("title") or "")
        content_check = ContentChecker().check(
            revised, sources=sources, header_docnum=doc_number)
        if content_check["issues"]:
            quality["issues"] = list(quality.get("issues") or []) + content_check["issues"]
            if quality.get("level") == "A":
                quality["level"] = "B"

        references = self._reference_labels(sources) or list(ctx.get("references") or [])
        ctx["references"] = references
        task.context = ctx
        task.current_content = revised
        self.db.flush()
        _, version = self._snapshot(task, user_id, note=f"AI 局部修改：{instruction[:30]}")
        task.version_no = version
        task.updated_at = now_local()
        self.db.commit()

        summary = self._revision_diff(current, revised)
        reply = f"已只修改定位到的目标片段并保存为 v{version}，未让模型重生成其余正文。"
        if summary:
            reply += "\n\n本次实际变化：\n" + summary
        return {
            **self._to_dict(task),
            "reply": reply,
            "content_changed": True,
            "quality": quality,
            "content_check": content_check,
            "postprocess_events": events,
            "context_changes": [],
            "references": references,
            "revision_summary": summary,
            "operation": "patch_section",
            "patch_target": target,
        }

    def revise(self, task_id: str, user_id: str, instruction: str,
               mode: str = "revise", selection: Optional[str] = None) -> Dict[str, Any]:
        """Direct /revise selections use the same local splice path as chat tool ops."""
        if selection and selection.strip():
            return self.patch_section(
                task_id, user_id, target=selection, instruction=instruction, mode=mode)
        return super().revise(task_id, user_id, instruction, mode, selection=None)
