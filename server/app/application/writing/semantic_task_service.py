"""Model-routed writing service.

This layer is intentionally small and sits on top of the mature WritingTaskService.
It changes three architectural rules without rewriting document/version/RAG plumbing:

1. User instruction semantics are interpreted by the LLM only. Regex/keyword parsers never
   decide whether a message means draft/revise/change-title/etc.
2. Title/recipient/document number are structural fields, not body text. Authority/date are
   canonicalized to exactly one sign-off block at the tail so legacy/model output cannot
   accumulate duplicate headers/signatures across revisions.
3. A revision returns a concrete before/after summary in the assistant conversation. The editor
   remains the authoritative full document, but users no longer have to hunt for what changed.
"""
from __future__ import annotations

import difflib
import re
import zlib
from typing import Any, Dict, List, Optional

from app.application.writing import task_parser
from app.application.writing.intent_interpreter import SEMANTIC_FIELDS
from app.application.writing.task_service import WritingTaskService
from app.core.timeutil import now_local


_DATE_ONLY_RE = re.compile(
    r"^(?:20\d{2}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日|"
    r"[二〇零○一二三四五六七八九]{4}\s*年.+日)$"
)
_SIGNOFF_ONLY_RE = re.compile(
    r"^[\u4e00-\u9fa5（）()]{2,40}(?:政府|办公厅|办公室|委员会|局|厅|部|署|所|处|院|中心)$"
)
_DOCNUM_ONLY_RE = re.compile(
    r"^[\u4e00-\u9fa5A-Za-z]{1,16}[〔\[【［].{2,18}[〕\]】］]\s*[0-9０-９]{1,8}\s*号$"
)

# 模型残留的字段标签行（「报送对象：」「主送机关：××」）：不是正文，确定性剥掉。
_RECIPIENT_LABEL_LINE_RE = re.compile(
    r"^(?:报送对象|主送机关|主送|发文对象|收文单位)(?:\s*[：:]|$)"
)


class SemanticWritingTaskService(WritingTaskService):
    """WritingTaskService with model-only semantic routing and canonical structure."""

    @staticmethod
    def _answer_messages(message, ctx, content):
        messages = [{"role": "system", "content": (
            "你是司法行政写作助手。请直接回答用户问题，或解释你理解的修改要求并询问必要信息。"
            "本轮仅回答，不执行任何文档修改，不声称已保存、已更新或已生成版本。"
            "结合当前正文与最近对话，用自然简洁的中文回答。\n当前正文：\n" + content
        )}]
        messages.extend({"role": h["role"], "content": h["content"]}
                        for h in (ctx.get("history") or [])[-6:]
                        if h.get("role") in ("user", "assistant") and h.get("content"))
        if not messages or messages[-1].get("content") != message:
            messages.append({"role": "user", "content": message})
        return messages

    @staticmethod
    def _merge_interpretation(ctx: Dict[str, Any], it: Dict[str, Any]) -> List[str]:
        """Merge model-extracted fields without re-parsing the user's sentence locally."""
        updates: Dict[str, Any] = {}
        for key in SEMANTIC_FIELDS:
            value = it.get(key)
            if value is None:
                continue
            if key == "key_facts":
                merged = list(dict.fromkeys((ctx.get("key_facts") or []) + (value or [])))
                if merged != (ctx.get("key_facts") or []):
                    updates[key] = merged
            elif ctx.get(key) != value:
                updates[key] = value
        return task_parser.merge_context(ctx, updates)

    # ---------------------------------------------------------- canonical body
    @staticmethod
    def _canonicalize_body(text: str, ctx: Dict[str, Any]) -> str:
        """Make document structure single-source-of-truth.

        The editor already renders title/recipient/document-number from task_context, so these
        lines must not live in current_content. Sign-off/date are kept in the body view for now,
        but are reconstructed from context so there can be at most one of each.
        """
        if not text:
            text = ""
        lines = [line.rstrip() for line in text.replace("\r\n", "\n").split("\n")]

        title = str(ctx.get("title") or "").strip()
        docnum = str(ctx.get("document_number") or "").strip()

        # Strip duplicated structural header lines from the leading area. We only remove exact
        # structured values (or a standalone current doc-number), never arbitrary prose.
        # 主送机关行回归正文（由模型按文种判断书写），这里只剥字段标签垃圾行。
        cleaned: List[str] = []
        nonempty_seen = 0
        for raw in lines:
            s = raw.strip()
            in_header = nonempty_seen < 10
            if s:
                nonempty_seen += 1
            if in_header and s:
                if title and s == title:
                    continue
                if _RECIPIENT_LABEL_LINE_RE.match(s):
                    continue
                if docnum and s == docnum:
                    continue
                if docnum and _DOCNUM_ONLY_RE.fullmatch(s):
                    # Current document number is a structured UI/export field. Historic cited
                    # document numbers inside prose are not standalone header lines and survive.
                    continue
            cleaned.append(raw)

        while cleaned and not cleaned[-1].strip():
            cleaned.pop()

        # Remove all structural tail rows from the final block, including stale values from a
        # previous revision. Only standalone lines near the tail are touched.
        tail_start = max(0, len(cleaned) - 10)
        body = cleaned[:tail_start]
        tail: List[str] = []
        for raw in cleaned[tail_start:]:
            s = raw.strip()
            if s and (_SIGNOFF_ONLY_RE.fullmatch(s) or _DATE_ONLY_RE.fullmatch(s)):
                continue
            tail.append(raw)
        cleaned = body + tail
        while cleaned and not cleaned[-1].strip():
            cleaned.pop()

        authority = str(ctx.get("authority") or "").strip()
        doc_date = str(ctx.get("document_date") or "").strip()
        if authority:
            if cleaned and cleaned[-1].strip():
                cleaned.append("")
            cleaned.append(authority)
        if doc_date:
            cleaned.append(doc_date)

        # Collapse excessive blank lines introduced by repeated legacy structural rows.
        out: List[str] = []
        blank = False
        for raw in cleaned:
            is_blank = not raw.strip()
            if is_blank and blank:
                continue
            out.append(raw)
            blank = is_blank
        return "\n".join(out).strip()

    def _postprocess(self, text: str, ctx: Dict[str, Any]):
        processed, events, doc_number, doc_date = super()._postprocess(text, ctx)
        canonical_ctx = dict(ctx)
        if doc_number:
            canonical_ctx["document_number"] = doc_number
        if doc_date:
            canonical_ctx["document_date"] = doc_date
        return self._canonicalize_body(processed, canonical_ctx), events, doc_number, doc_date

    def _draft_system(self, user_id: str, template: Optional[Dict[str, Any]] = None) -> str:
        base = super()._draft_system(user_id, template)
        return base + (
            "\n\n【结构字段硬边界】标题、当前文号、发文机关署名和成文日期"
            "全部由系统结构化管理。你只输出正文主体：从主送机关行（如该文种需要）"
            "或正文第一段开始，到正文最后一句结束。"
            "禁止输出标题、当前文号、落款单位、成文日期；系统会统一渲染，"
            "否则会造成重复标题和重复落款。主送机关行按文种规范判断是否输出"
            "（通知、函、请示等通常需要，宣传材料、讲话稿等不需要），"
            "绝不要输出「报送对象：」「主送机关：」这类字段标签或空标签行。"
        )

    def _build_revise_prompt(self, current: str, instruction: str,
                             mode_desc: str, selection: Optional[str],
                             ctx: Dict[str, Any]) -> str:
        prompt = super()._build_revise_prompt(current, instruction, mode_desc, selection, ctx)
        return prompt + (
            "\n\n结构边界：只返回修改后的正文主体全文。不要输出标题、当前文号、"
            "发文机关署名或成文日期；这些字段由系统单独渲染。"
            "主送机关行属于正文的一部分，原样保留（除非用户要求修改）。"
        )

    def _sync_structured_fields(self, task, user_id: str) -> str:
        current = (task.current_content or "").strip()
        if not current:
            return ""
        canonical = self._canonicalize_body(current, dict(task.context or {}))
        if canonical == current:
            return ""
        task.current_content = canonical
        self.db.flush()
        _, version = self._snapshot(task, user_id, note="结构字段同步")
        task.version_no = version
        task.updated_at = now_local()
        self.db.commit()
        return f"正文结构已同步（v{version}）"

    # --------------------------------------------------------------- revisions
    @staticmethod
    def _revision_diff(before: str, after: str, limit: int = 4) -> str:
        """Human-readable paragraph-level before/after summary for the chat pane."""
        old = [x.strip() for x in before.splitlines() if x.strip()]
        new = [x.strip() for x in after.splitlines() if x.strip()]
        matcher = difflib.SequenceMatcher(a=old, b=new, autojunk=False)
        rows: List[str] = []
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                continue
            if tag == "replace":
                old_text = " ".join(old[i1:i2])[:180]
                new_text = " ".join(new[j1:j2])[:180]
                rows.append(f"原：{old_text}\n改：{new_text}")
            elif tag == "delete":
                rows.append("删除：" + " ".join(old[i1:i2])[:180])
            elif tag == "insert":
                rows.append("新增：" + " ".join(new[j1:j2])[:180])
            if len(rows) >= limit:
                break
        return "\n\n".join(rows)

    # 「改完了」这句话的措辞变体：原先恒为「已按你的指令修改正文并保存为 vN。」
    _REVISE_OPENERS = (
        "改好了，存成 v{version}。",
        "已经改完并存为 v{version}。",
        "这一部分改过了，新版本是 v{version}。",
    )

    def _revise_reply(self, version: int, summary: str,
                      citation_warnings, seed: str) -> str:
        """修改完成后的回复：说清楚改了什么，而不只是报个版本号。

        原先只有一句套话 + 版本号，用户看着改动量一无所知；而 ``_revision_diff``
        算出的 summary 虽然也回传了（前端可对照），但那是一大段前后对照文本，
        不适合整段塞进对话。这里提炼成「改了几处、什么类型」的一句话。
        """
        h = zlib.crc32((seed or "").encode("utf-8"))
        openers = self._REVISE_OPENERS
        parts = [openers[h % len(openers)].format(version=version)]

        text = summary or ""
        changed = text.count("原：")
        added = text.count("新增：")
        removed = text.count("删除：")
        detail = []
        if changed:
            detail.append(f"改写了 {changed} 处表述")
        if added:
            detail.append(f"补进了 {added} 处内容")
        if removed:
            detail.append(f"删掉了 {removed} 处")
        if detail:
            parts.append("这次主要是" + "、".join(detail) + "，可以对照正文看一下。")
        if citation_warnings:
            parts.append(f"另外有 {len(citation_warnings)} 处文号核实不到依据，"
                         "已替换成「相关文件」，确认来源后再补回。")
        return "".join(parts)

    def save_version(self, task_id: str, user_id: str, content: str,
                     note: Optional[str] = None, formatting: Optional[Dict] = None) -> Dict[str, Any]:
        task = self._get_owned(task_id, user_id)
        canonical = self._canonicalize_body(content, dict(task.context or {}))
        return super().save_version(task_id, user_id, canonical, note, formatting)
