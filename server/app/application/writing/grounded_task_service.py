"""Grounded writing service: exemplar imitation + deterministic calculation checks.

- RAG facts remain evidence sources.
- Style exemplars are compact structured cards (top_k=1), never full historical articles.
- Exemplar retrieval explicitly prefixes the detected document type so same-type examples rank first.
- Arithmetic is verified by Python after generation/revision.
- Explicit literal values are protected deterministically after semantic routing.
"""
from __future__ import annotations

import os
from typing import Any, Dict, Iterator, List, Optional

from fastapi import HTTPException

from app.application.writing import task_parser
from app.application.writing.calculation_guard import verify_and_fix_calculations
from app.application.writing.semantic_task_service import SemanticWritingTaskService
from app.application.shared.prompt_budget import compact_style_examples

_STYLE_ADAPTER_ENV = "WRITING_STYLE_ADAPTER"


def style_adapter_active() -> bool:
    """风格是否已经蒸馏到模型权重里。

    这是一道**运行期开关**，目的很直白：训练是可以选择不做的事。
    配了这个变量说明模型本身已经会这套写法，推理时就不再灌那张 1100 字风格卡
    （灌了等于把学过的东西再说一遍，白占上下文）；不配则退回今天的行为，
    一字不变。所以「训了」和「没训」共用同一套代码，只差一个环境变量，
    不会出现训到一半、adapter 撤了之后质量突然塌掉的中间态。
    """
    return bool((os.getenv(_STYLE_ADAPTER_ENV) or "").strip())


class GroundedWritingTaskService(SemanticWritingTaskService):
    """Production writing service with grounded style cards and arithmetic guardrails."""

    @staticmethod
    def _literal_overrides(message: str) -> Dict[str, Any]:
        parsed = task_parser.parse_message(message or "")
        allowed = (
            "document_date",
            "document_number_enabled",
            "document_number",
            "word_count_target",
        )
        return {k: parsed[k] for k in allowed if k in parsed}

    @staticmethod
    def _exemplar_query(message: str) -> str:
        """Make the requested document type an explicit ranking signal.

        Historical examples share many generic official-writing words. Without a strong type
        signal a semantically similar report can outrank a notice/request. Prefixing the
        server-parsed type keeps retrieval compatible with the existing RAG API while making
        same-type matching deterministic at the query-contract level.
        """
        raw = (message or "").strip()
        parsed = task_parser.parse_message(raw)
        doc_type = str(parsed.get("document_type") or "").strip()
        if not doc_type:
            return raw
        return f"文种：{doc_type}\n同文种范文优先：{doc_type}\n{raw}"

    def _interpret(self, message: str, ctx: Dict[str, Any], has_draft: bool = False):
        result = super()._interpret(message, ctx, has_draft=has_draft)
        if not result:
            return None
        result.update(self._literal_overrides(message))
        return result

    def plan_task(self, user_id: str, message: str) -> Dict[str, Any]:
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

    def _example_style_block(self, query: str, user_id: str) -> str:
        """Retrieve one doc-type-aware exemplar and inject only a structured style card."""
        if style_adapter_active():
            # 风格已经在权重里了，再塞一张卡只是白占上下文。
            # 留着这段返回值是为了让「撤卡」成为一个可回滚的运行期开关，
            # 而不是改代码：哪天 adapter 不想要了，删掉环境变量就回到原路。
            return ""
        if not self.rag:
            return ""
        try:
            examples = self.rag.search_examples(
                query=self._exemplar_query(query),
                user_id=user_id,
                top_k=1,
                max_chars=1200,
            ) or []
        except Exception:
            examples = []
        cards = compact_style_examples(examples, max_chars=1100)
        if not cards:
            return ""
        return (
            "\n\n【知识库范文风格卡】\n"
            "只学习以下同文种优先范文提炼出的结构层级、段落节奏、固定套语、过渡方式和结尾方式；"
            "禁止迁移范文中的具体单位、人名、数字、日期、文号和个案事实。"
            "本次事实只能来自用户输入、附件和本轮 RAG 资料。\n\n" + cards
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
            "\n\n若用户要求规范化、仿写、按单位口径调整，应以以上知识库风格卡的结构和措辞习惯作为风格依据；"
            "不要迁移历史稿的事实。"
        )
        return self.assistant.chat(
            message=prompt,
            history=[],
            sources=sources,
            user_role="user",
            system_prompt=system,
            attachment_context=attachment_ctx,
        ) or ""

    def revise(self, task_id: str, user_id: str, instruction: str,
               mode: str = "revise", selection: Optional[str] = None) -> Dict[str, Any]:
        literal = self._literal_overrides(instruction)
        if literal:
            task = self._get_owned(task_id, user_id)
            ctx = dict(task.context or {})
            task_parser.merge_context(ctx, literal)
            task_parser.compute_missing(ctx)
            task.context = ctx
            self.db.commit()
        return super().revise(task_id, user_id, instruction, mode, selection)

    def _postprocess(self, text: str, ctx: Dict[str, Any]):
        processed, events, doc_number, doc_date = super()._postprocess(text, ctx)
        processed, calc_events = verify_and_fix_calculations(processed)
        events = list(events or []) + calc_events
        return processed, events, doc_number, doc_date
