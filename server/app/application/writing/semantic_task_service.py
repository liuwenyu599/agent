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

from fastapi import HTTPException

from app.application.writing import task_parser
from app.application.writing.intent_interpreter import SEMANTIC_FIELDS
from app.application.writing.task_service import REVISE_MODES, WritingTaskService
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

    def _answer_only(self, message, ctx, content):
        if self.assistant:
            try:
                reply = self.assistant.complete(self._answer_messages(message, ctx, content),
                                                temperature=0.3, max_tokens=1000)
                if reply and reply.strip():
                    return reply.strip()
            except Exception:
                pass
        return "暂时无法回答。请补充要讨论的问题或需要修改的具体内容。"

    # ------------------------------------------------------------------ context
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

    # --------------------------------------------------------------- creation
    def create_task(self, user_id: str, message: str,
                    session_id: Optional[str] = None,
                    template_id: Optional[str] = None,
                    kb_ids: Optional[List[str]] = None,
                    planned_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        from app.infrastructure.database.models.writing_task import WritingTaskModel

        ctx = task_parser.empty_context()
        changes: List[str] = []
        it: Optional[Dict[str, Any]] = None

        if planned_context:
            # /plan is server-produced LLM output. Reuse it verbatim for known task keys instead
            # of parsing the same sentence again with regex.
            for key in tuple(ctx.keys()):
                if key in planned_context and key not in ("history", "missing_fields"):
                    ctx[key] = planned_context[key]
            ctx["template_id"] = None
            ctx["template_name"] = None
        else:
            it = self._interpret(message, ctx, has_draft=False)
            if it:
                changes = self._merge_interpretation(ctx, it)

        if not ctx.get("title"):
            # This is rendering convenience based on already-understood fields, not instruction
            # parsing. The model remains the source of document_type/topic semantics.
            derived = task_parser.build_title(ctx)
            if derived:
                ctx["title"] = derived

        if template_id:
            tmpl = self._load_template(template_id)
            if tmpl:
                ctx["template_id"] = tmpl["id"]
                ctx["template_name"] = tmpl["name"]
        if kb_ids:
            ctx["kb_ids"] = [x for x in kb_ids if x]
        self._complete_default_authority(ctx)

        missing = task_parser.compute_missing(ctx)
        self._push_history(ctx, "user", message)
        task = WritingTaskModel(
            user_id=user_id, session_id=session_id, context=ctx, status="collecting")
        self.db.add(task)
        self.db.commit()
        self.db.refresh(task)

        reply = (it or {}).get("reply") or self._collecting_reply(ctx, changes, missing, message)
        self._push_history(ctx, "assistant", reply)
        task.context = ctx
        self.db.commit()
        return {**self._to_dict(task), "reply": reply, "content_changed": False}

    def plan_task(self, user_id: str, message: str) -> Dict[str, Any]:
        """Plan only from model semantics; never take a keyword/regex fast path."""
        ctx = task_parser.empty_context()
        it = self._interpret(message, ctx, has_draft=False)
        if it:
            self._merge_interpretation(ctx, it)

        if not ctx.get("title"):
            derived = task_parser.build_title(ctx)
            if derived:
                ctx["title"] = derived
        task_parser.compute_missing(ctx)

        try:
            from app.application.organization.service import OrganizationService
            org_ctx = OrganizationService(self.db).user_context(user_id)
        except Exception:
            org_ctx = {"dept_code": "", "dept_name": "", "short_name": "",
                       "agent": None, "scopes": ["GLOBAL"]}

        doc_type = str(ctx.get("document_type") or "")
        fields: List[Dict[str, str]] = []
        for key, label in (("document_type", "文种"), ("recipient", "报送对象"),
                           ("authority", "发文机关"), ("time_range", "时间范围"),
                           ("purpose", "用途"), ("topic", "主题")):
            value = ctx.get(key)
            if value:
                fields.append({"label": label, "value": str(value)})

        # Material discovery is a recommendation only. It no longer depends on lexical cues such
        # as “参考/根据/材料”; the actual draft RAG path remains permission-scoped.
        materials = self._plan_materials(ctx, user_id, org_ctx)
        knowledge = self._plan_knowledge(user_id, org_ctx)

        return {
            "doc_type": doc_type,
            "target": ctx.get("purpose") or ctx.get("topic") or message[:40],
            "audience": ctx.get("recipient") or "",
            "department": org_ctx.get("dept_name") or org_ctx.get("short_name") or "",
            "agent": (org_ctx.get("agent") or {}).get("name") or "",
            "title": ctx.get("title") or "",
            "source": "llm",
            "planned_context": {
                k: v for k, v in ctx.items() if k not in ("history", "missing_fields")
            },
            "fields": fields,
            "materials": materials,
            "knowledge": knowledge,
            "template_id": "",
            "template_name": "",
            "scopes": org_ctx.get("scopes") or ["GLOBAL"],
            "kb_ids": [k["id"] for k in knowledge],
            "ai_actions": self._plan_actions(doc_type),
        }

    # ------------------------------------------------------------------- chat
    def chat(self, task_id: str, user_id: str, message: str) -> Dict[str, Any]:
        task = self._get_owned(task_id, user_id)
        ctx = dict(task.context or {})
        has_draft = bool((task.current_content or "").strip())
        self._push_history(ctx, "user", message)

        it = self._interpret(message, ctx, has_draft=has_draft)
        if not it:
            # Normally unreachable with the new interpreter, but keep fail-closed semantics.
            reply = self._answer_only(message, ctx, task.current_content or "")
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

        intent = it.get("intent") or "answer"
        if intent == "revise_content" and has_draft:
            instruction = it.get("revision_instruction") or message
            mode = it.get("revision_mode") or "revise"
            result = self.revise(task_id, user_id, instruction=instruction, mode=mode)
            result["context_changes"] = changes
            latest_ctx = dict(task.context or {})
            self._push_history(latest_ctx, "assistant", result["reply"])
            task.context = latest_ctx
            self.db.commit()
            return result

        if intent in ("draft", "outline"):
            result = self.draft(task_id, user_id, outline_only=(intent == "outline"))
            result["context_changes"] = changes
            latest_ctx = dict(task.context or {})
            self._push_history(latest_ctx, "assistant", result["reply"])
            task.context = latest_ctx
            self.db.commit()
            return result

        # Structural field changes are applied to the canonical document representation. This is
        # what makes “落款改成X/日期改成Y” visibly true rather than just a chat claim.
        content_changed = False
        if has_draft and intent == "update_context" and before_ctx != ctx:
            note = self._sync_structured_fields(task, user_id)
            content_changed = bool(note)
            if note:
                changes = list(changes) + [note]

        reply = it.get("reply") or self._answer_only(message, ctx, task.current_content or "")
        if changes:
            reply += "\n\n已应用：" + "；".join(changes) + "。"
        self._push_history(ctx, "assistant", reply)
        task.context = ctx
        self.db.commit()
        return {**self._to_dict(task), "reply": reply,
                "content_changed": content_changed, "context_changes": changes}

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

    def revise(self, task_id: str, user_id: str, instruction: str,
               mode: str = "revise", selection: Optional[str] = None) -> Dict[str, Any]:
        task = self._get_owned(task_id, user_id)
        current = self._canonicalize_body((task.current_content or "").strip(),
                                          dict(task.context or {}))
        if not current:
            raise HTTPException(status_code=409, detail="当前还没有草稿，请先起草")

        ctx = dict(task.context or {})
        mode_desc = REVISE_MODES.get(mode, REVISE_MODES["revise"])
        prompt = self._build_revise_prompt(current, instruction, mode_desc, selection, ctx)
        sources = self._retrieve(ctx, user_id, extra_query=instruction)
        attachment_ctx = self._attachment_context(task, ctx)
        revised = self._llm_revise(prompt, sources, attachment_ctx, user_id)
        if not revised.strip():
            raise HTTPException(status_code=502, detail="模型未返回内容，请重试")

        revised = self._canonicalize_body(revised.strip(), ctx)
        if revised == current:
            reply = (
                "我已按你的指令逐项对照当前正文，但没有产生实际文字变化，"
                "因此没有伪造“已修改”状态，也没有生成新版本。"
            )
            return {**self._to_dict(task), "reply": reply,
                    "content_changed": False, "context_changes": []}

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
        quality = QualityGate().evaluate(
            revised, body_only=True, document_type=ctx.get("document_type") or "",
            word_count_target=ctx.get("word_count_target"))
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
        _, version = self._snapshot(task, user_id, note=f"AI 修改：{instruction[:30]}")
        task.version_no = version
        task.updated_at = now_local()
        self.db.commit()

        summary = self._revision_diff(current, revised)
        reply = self._revise_reply(version, summary, citation_warnings, instruction)
        return {**self._to_dict(task), "reply": reply, "content_changed": True,
                "quality": quality, "content_check": content_check,
                "postprocess_events": events, "context_changes": [],
                "references": references, "revision_summary": summary}

    def save_version(self, task_id: str, user_id: str, content: str,
                     note: Optional[str] = None) -> Dict[str, Any]:
        task = self._get_owned(task_id, user_id)
        canonical = self._canonicalize_body(content, dict(task.context or {}))
        return super().save_version(task_id, user_id, canonical, note)
