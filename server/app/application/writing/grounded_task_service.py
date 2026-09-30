"""Grounded writing service: exemplar imitation + deterministic calculation checks.

This is the production-facing layer above SemanticWritingTaskService.
- RAG facts remain evidence sources.
- Full published knowledge-base documents are separately retrieved as style exemplars.
- Arithmetic is verified by Python after generation/revision; the LLM is not trusted as a calculator.
"""
from __future__ import annotations

from typing import Any, Dict, Iterator, List, Optional

from fastapi import HTTPException

from app.application.writing.calculation_guard import verify_and_fix_calculations
from app.application.writing.semantic_task_service import SemanticWritingTaskService


class GroundedWritingTaskService(SemanticWritingTaskService):
    """Production writing service with style exemplars and arithmetic guardrails."""

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
        # The actual exemplar block is query-dependent, so this only keeps the shared base.
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
        # chat_stream currently has no examples= argument, therefore the exemplar contract is
        # injected into system_prompt explicitly so streaming and non-streaming behavior match.
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

    def _postprocess(self, text: str, ctx: Dict[str, Any]):
        processed, events, doc_number, doc_date = super()._postprocess(text, ctx)
        processed, calc_events = verify_and_fix_calculations(processed)
        events = list(events or []) + calc_events
        return processed, events, doc_number, doc_date
