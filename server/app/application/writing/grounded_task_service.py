"""Grounded writing service: exemplar imitation + deterministic calculation checks.

This is the production-facing layer above SemanticWritingTaskService.
- RAG facts remain evidence sources.
- Full published knowledge-base documents are separately retrieved as style exemplars.
- Arithmetic is verified by Python after generation/revision; the LLM is not trusted as a calculator.
- Explicit literal values (date/doc-number) are protected deterministically after semantic routing.
- /plan keeps a narrow, non-mutating fast path for unambiguous create instructions to avoid an
  unnecessary 14B round-trip; chat/revision intent routing remains model-driven.
"""
from __future__ import annotations

from typing import Any, Dict, Iterator, List, Optional

from fastapi import HTTPException

from app.application.writing import task_parser
from app.application.writing.calculation_guard import verify_and_fix_calculations
from app.application.writing.semantic_task_service import SemanticWritingTaskService


class GroundedWritingTaskService(SemanticWritingTaskService):
    """Production writing service with style exemplars and arithmetic guardrails."""

    # ---------------------------------------------------------- literal guards
    @staticmethod
    def _literal_overrides(message: str) -> Dict[str, Any]:
        """Protect explicit user-written values without using regex to choose an action.

        The semantic model still decides intent. This helper only preserves values whose exact
        spelling must not be changed by the model: sign-off date and document-number controls.
        A word-count target is also literal/numeric and safe to preserve.
        """
        parsed = task_parser.parse_message(message or "")
        allowed = (
            "document_date",
            "document_number_enabled",
            "document_number",
            "word_count_target",
        )
        return {k: parsed[k] for k in allowed if k in parsed}

    def _interpret(self, message: str, ctx: Dict[str, Any], has_draft: bool = False):
        result = super()._interpret(message, ctx, has_draft=has_draft)
        if not result:
            return None
        # User literal wins over model omission/mis-copy. This does not change intent.
        result.update(self._literal_overrides(message))
        return result

    # -------------------------------------------------------- planning fast path
    def plan_task(self, user_id: str, message: str) -> Dict[str, Any]:
        """Use a narrow deterministic shortcut only for clear, non-mutating planning.

        If document type + core topic/title are both explicit, planning does not need a 14B call
        and does not search materials. Ambiguous requests continue through the semantic model.
        This shortcut never handles chat edits or document mutations.
        """
        ctx = task_parser.empty_context()
        literal_plan = task_parser.parse_message(message)
        task_parser.merge_context(ctx, literal_plan)
        has_clear_core = bool(
            ctx.get("document_type") and
            (ctx.get("topic") or ctx.get("title") or task_parser.build_title(ctx))
        )
        if not has_clear_core:
            return super().plan_task(user_id, message)

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

        # Fast path intentionally skips material retrieval; real drafting still performs scoped RAG.
        knowledge = self._plan_knowledge(user_id, org_ctx)
        template = self._plan_template(doc_type, org_ctx)
        return {
            "doc_type": doc_type,
            "target": ctx.get("purpose") or ctx.get("topic") or message[:40],
            "audience": ctx.get("recipient") or "",
            "department": org_ctx.get("dept_name") or org_ctx.get("short_name") or "",
            "agent": (org_ctx.get("agent") or {}).get("name") or "",
            "title": ctx.get("title") or "",
            "source": "rule_fast",
            "planned_context": {
                k: v for k, v in ctx.items() if k not in ("history", "missing_fields")
            },
            "fields": fields,
            "materials": [],
            "knowledge": knowledge,
            "template_id": template.get("id") or "",
            "template_name": template.get("name") or "",
            "scopes": org_ctx.get("scopes") or ["GLOBAL"],
            "kb_ids": [k["id"] for k in knowledge],
            "ai_actions": self._plan_actions(doc_type),
        }

    # ------------------------------------------------------------- exemplars
    def _example_style_block(self, query: str, user_id: str) -> str:
        """Retrieve full published examples and turn them into an explicit imitation contract."""
        if not self.rag:
            return ""
        try:
            examples = self.rag.search_examples(
                query=query,
                user_id=user_id,
                top_k=2,
                max_chars=2600,
            ) or []
        except Exception:
            examples = []
        if not examples:
            return ""

        refs = "\n\n".join(
            f"【本单位范文{i + 1}：{e.get('title') or '未命名'}】\n{e.get('content') or ''}"
            for i, e in enumerate(examples)
        )
        return (
            "\n\n【知识库范文模仿契约】\n"
            "下面不是普通事实资料，而是本单位已经发布的写作范文。写作时必须先抽取其"
            "篇章结构、段落长度、层级数量、常用称谓、固定套语、过渡方式、结尾方式和正式程度，"
            "再用本次任务事实重写；不得只把范文当作事实引用。\n"
            "优先模仿：1）结构层级；2）段落节奏；3）固定套语和过渡句；4）同文种的结尾方式；"
            "5）本单位常用措辞。\n"
            "禁止照搬范文中的具体人名、单位名、数字、日期、文号和个案事实。若范文与用户明确要求冲突，"
            "以用户要求为准。\n\n" + refs
        )

    def _draft_system(self, user_id: str, template: Optional[Dict[str, Any]] = None) -> str:
        return super()._draft_system(user_id, template)

    def _llm_draft(self, instruction: str, sources, attachment_ctx, user_id,
                   template: Optional[Dict[str, Any]] = None) -> str:
        if not self.assistant:
            raise HTTPException(status_code=503, detail="模型服务不可用")
        system = self._draft_system(user_id, template)
        system += self._example_style_block(instruction, user_id)
        system += (
            "\n\n【计算纪律】不要凭语言模型心算派生金额、比例或合计。凡正文必须给出由多个数字推导的结果，"
            "应确保运算关系明确且结果精确；最终文本还会由程序做确定性复核。"
        )
        return self.assistant.chat(
            message=instruction,
            history=[],
            sources=sources,
            user_role="user",
            system_prompt=system,
            attachment_context=attachment_ctx,
        ) or ""

    def _llm_draft_stream(self, instruction: str, sources, attachment_ctx, user_id,
                          template: Optional[Dict[str, Any]] = None) -> Iterator[str]:
        if not self.assistant:
            raise HTTPException(status_code=503, detail="模型服务不可用")
        system = self._draft_system(user_id, template)
        system += self._example_style_block(instruction, user_id)
        system += (
            "\n\n【计算纪律】不要凭语言模型心算派生金额、比例或合计；派生结果必须可由原始数字复核。"
        )
        return self.assistant.chat_stream(
            message=instruction,
            history=[],
            sources=sources,
            user_role="user",
            system_prompt=system,
            attachment_context=attachment_ctx,
        )

    def _llm_revise(self, prompt: str, sources, attachment_ctx, user_id) -> str:
        if not self.assistant:
            raise HTTPException(status_code=503, detail="模型服务不可用")
        agent = self._agent_prompt(user_id)
        from app.application.writing.task_service import REVISION_RULES
        system = (agent + "\n" if agent else "") + REVISION_RULES
        system += self._example_style_block(prompt, user_id)
        system += (
            "\n\n若用户要求规范化、仿写、按单位口径调整，应以以上知识库范文的结构和措辞习惯作为风格依据；"
            "不要只修改事实词语而保持原有外部风格。"
        )
        return self.assistant.chat(
            message=prompt,
            history=[],
            sources=sources,
            user_role="user",
            system_prompt=system,
            attachment_context=attachment_ctx,
        ) or ""

    # --------------------------------------------------------------- revisions
    def revise(self, task_id: str, user_id: str, instruction: str,
               mode: str = "revise", selection: Optional[str] = None) -> Dict[str, Any]:
        # Direct /revise calls bypass the intent interpreter, so preserve exact literal values
        # before the model rewrites the body. The model still decides prose; it cannot override
        # a date/doc-number the user explicitly typed in this instruction.
        literal = self._literal_overrides(instruction)
        if literal:
            task = self._get_owned(task_id, user_id)
            ctx = dict(task.context or {})
            task_parser.merge_context(ctx, literal)
            task_parser.compute_missing(ctx)
            task.context = ctx
            self.db.commit()
        return super().revise(task_id, user_id, instruction, mode, selection)

    # -------------------------------------------------------------- postprocess
    def _postprocess(self, text: str, ctx: Dict[str, Any]):
        processed, events, doc_number, doc_date = super()._postprocess(text, ctx)
        processed, calc_events = verify_and_fix_calculations(processed)
        events = list(events or []) + calc_events
        return processed, events, doc_number, doc_date
