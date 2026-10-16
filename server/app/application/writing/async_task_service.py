"""Async production writing service.

All long model I/O is awaited. Deterministic SQL/RAG/post-processing helpers stay shared with the
mature synchronous service chain so item-1..5/9..15 guarantees are not forked or weakened.
"""
from __future__ import annotations

import re
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

from fastapi import HTTPException
from sqlalchemy import select, update

from app.application.writing import task_parser
from app.application.writing import prompt_snapshot
from app.application.writing.async_intent_interpreter import AsyncWritingIntentInterpreter
from app.application.writing.ops_task_service import LOCAL_OPERATIONS
from app.application.writing.paragraph_suggestions import ParagraphSuggestionMixin, content_hash
from app.application.writing.quality_gate import QualityGate
from app.application.writing.agent_graph.graph import WritingAgentGraph
from app.application.writing.agent_graph.persistence import AgentRunStore
from app.application.writing.agent_graph.routing import (
    classify_writing_route,
    graph_enabled_for_user,
)
from app.application.writing.sectioned_generation_service import SectionedGenerationWritingTaskService, _SPEECH_TYPES
from app.application.writing.task_service import REVISE_MODES, _sse
from app.core.timeutil import now_local
from app.core.config import settings
from app.infrastructure.database.models.writing_suggestion import WritingSuggestionModel
from app.infrastructure.database.models.writing_task import WritingTaskModel


def _http_error_message(detail: Any) -> str:
    if isinstance(detail, dict):
        return str(detail.get("message") or detail.get("detail") or "生成失败，请重试")
    return str(detail)


class AsyncWritingTaskService(ParagraphSuggestionMixin, SectionedGenerationWritingTaskService):
    """Final production writing service for ASGI routes."""

    def __init__(self, db, assistant=None, rag=None, attachments=None):
        super().__init__(db, assistant=assistant, rag=rag, attachments=attachments)
        self.interpreter = AsyncWritingIntentInterpreter(assistant) if assistant else None
        self._draft_memory_cache: dict[tuple[str, str], str] = {}

    # ---------------------------------------------------- 起草提示 + 训练留痕

    def _record_prompt(self, base: str, card: str, instruction: str, sources,
                       attachment_ctx, user_id: str, kind: str = "draft") -> None:
        """留痕一次真实的模型调用输入。改写路径与起草路径共用。

        改写也必须记：`EvalCaptureWritingTaskService` 配的是「最近一个 AI 版本 →
        用户终稿」，而最新那个 AI 版本往往来自一次改写而不是首次起草。
        只记起草的话，样本输入反而是最初那一版指令，跟输出对不上。
        """
        prompt_snapshot.record(
            prompt_snapshot.current_task(),
            base_system=base,
            style_card=card,
            instruction=instruction,
            sources=sources,
            attachment_context=attachment_ctx,
            kind=kind,
            user_id=user_id or prompt_snapshot.current_user(),
        )

    def _draft_prompt(self, instruction: str, sources, attachment_ctx, user_id: str,
                      template: Optional[Dict[str, Any]] = None) -> str:
        """组装起草用的 system，并把「撤卡的底稿 + 本次风格卡 + 当时的资料」留痕。

        原先每个起草入口都各自写两行（拼底稿、拼风格卡），这里收敛成一处，
        顺带把快照记下来——三处以外的入口同样忘了留，不如统一收口。

        留痕只在 ``SFT_SNAPSHOT_DIR`` 配置了时发生，否则 record 直接返回 False，
        除了这一次函数调用没有任何额外开销。
        """
        base = self._draft_system(user_id, template)
        style = self._example_style_block(instruction, user_id)
        # Only accepted edits from the current user and document type influence tone.
        current_task = self.db.get(WritingTaskModel, prompt_snapshot.current_task())
        doc_type = (str((current_task.context or {}).get("document_type") or "")
                    if current_task and current_task.user_id == user_id else
                    task_parser.explicit_document_type(instruction) or "")
        cache_key = (user_id, doc_type)
        if cache_key not in self._draft_memory_cache:
            self._draft_memory_cache[cache_key] = self._accepted_style_memory(user_id, doc_type)
        memory = self._draft_memory_cache[cache_key]
        if current_task and current_task.user_id == user_id and current_task.current_content:
            rule = (
                "\n\n【继续生成】沿用当前稿的主题、文种、事实、对象和已采纳段落；"
                "只修正表达并补足明确缺口。下面是当前稿首尾摘录，勿另起无关文稿。\n"
            )
            # QwenGateway._shrink_system cuts an oversized system prompt from the
            # front. Keep feedback, exemplar boundaries and the current draft in
            # its 8192-token system allowance instead of letting it cut the tail.
            budget = max(1200, int((settings.MODEL_CTX_LIMIT - 512) * 0.75 * 0.5))
            space = max(0, budget - len(base) - len(memory) - len(rule))
            excerpt_budget = min(1200, space // 3)
            style = self._bounded_style(style, space - excerpt_budget)
            excerpt_budget = min(1200, max(0, budget - len(base) - len(memory)
                                           - len(rule) - len(style)))
            excerpt = self._head_tail(current_task.current_content, excerpt_budget)
            if excerpt:
                base += rule + excerpt
        card = style + memory
        self._record_prompt(base, card, instruction, sources, attachment_ctx, user_id,
                            kind="draft")
        return base + card

    @staticmethod
    def _head_tail(content: str, limit: int) -> str:
        if limit < 80:
            return ""
        if len(content) <= limit:
            return content
        headings = [line.strip()[:60] for line in content.splitlines() if re.match(
            r"^\s*(?:[一二三四五六七八九十]+、|（[一二三四五六七八九十]+）|\d+[、.．])",
            line)]
        outline = ""
        if headings:
            outline = "\n【章节线索】" + "；".join(headings)[:limit // 4]
        marker = "\n……\n"
        remaining = limit - len(marker) - len(outline)
        front = remaining // 2
        back = remaining - front
        return content[:front] + outline + marker + content[-back:]

    @staticmethod
    def _bounded_style(card: str, limit: int) -> str:
        if len(card) <= limit:
            return card
        if limit < 100:
            return ""
        marker = "\n（范文已节选）\n"
        tail = min(150, (limit - len(marker)) // 3)
        return card[:limit - len(marker) - tail] + marker + card[-tail:]

    async def _interpret_async(self, message: str, ctx: Dict[str, Any],
                               has_draft: bool = False):
        if not self.interpreter:
            return None
        result = await self.interpreter.interpret_async(
            message,
            context=ctx,
            has_draft=has_draft,
            history=(ctx.get("history") or [])[-6:],
        )
        if not result:
            return None
        # Preserve GroundedWritingTaskService's deterministic literal precedence.
        result.update(self._literal_overrides(message))
        return result

    # ----------------------------------------------------------- model helpers
    async def _answer_only_async(self, message, ctx, content):
        if self.assistant:
            try:
                reply = await self.assistant.acomplete(
                    self._answer_messages(message, ctx, content), temperature=0.3, max_tokens=1000)
                if reply and reply.strip():
                    return reply.strip()
            except Exception:
                pass
        return "暂时无法回答。请补充要讨论的问题或需要修改的具体内容。"

    async def _llm_draft_async(self, instruction: str, sources, attachment_ctx, user_id,
                               template: Optional[Dict[str, Any]] = None) -> str:
        if not self.assistant:
            raise HTTPException(status_code=503, detail="模型服务不可用")
        system = self._draft_prompt(instruction, sources, attachment_ctx, user_id, template)
        system += (
            "\n\n【计算纪律】不要凭语言模型心算派生金额、比例或合计。凡正文必须给出由多个数字推导的结果，"
            "应确保运算关系明确且结果精确；最终文本还会由程序做确定性复核。"
        )
        return await self.assistant.achat(
            message=instruction, history=[], sources=sources, user_role="user",
            system_prompt=system, attachment_context=attachment_ctx,
        ) or ""

    async def _llm_revise_once_async(self, prompt: str, sources, attachment_ctx, user_id) -> str:
        if not self.assistant:
            raise HTTPException(status_code=503, detail="模型服务不可用")
        agent = self._agent_prompt(user_id)
        from app.application.writing.task_service import REVISION_RULES
        system = (agent + "\n" if agent else "") + REVISION_RULES
        card = self._example_style_block(prompt, user_id)
        self._record_prompt(system, card, prompt, sources, attachment_ctx, user_id, kind="revise")
        system += card
        system += (
            "\n\n若用户要求规范化、仿写、按单位口径调整，应以以上知识库风格卡的结构和措辞习惯作为风格依据；"
            "不要迁移历史稿的事实。"
        )
        return await self.assistant.achat(
            message=prompt, history=[], sources=sources, user_role="user",
            system_prompt=system, attachment_context=attachment_ctx,
        ) or ""

    async def _llm_revise_async(self, prompt: str, sources, attachment_ctx, user_id) -> str:
        """QualityRetryWritingTaskService semantics, with awaited model calls."""
        candidate = await self._llm_revise_once_async(prompt, sources, attachment_ctx, user_id)
        quality = self._quality_result(candidate)
        retry_no = 0
        while quality.get("level") == "D" and retry_no < 2:
            retry_no += 1
            retry_prompt = self._retry_prompt(prompt, candidate, quality, retry_no)
            candidate = await self._llm_revise_once_async(
                retry_prompt, sources, attachment_ctx, user_id)
            quality = self._quality_result(candidate)
        if quality.get("level") == "D":
            raise HTTPException(status_code=422, detail={
                "code": "WRITING_QUALITY_GATE_D",
                "message": "生成结果连续两次修复后仍存在硬伤，未保存该版本。",
                "issues": quality.get("issues") or [],
                "retry_count": 2,
            })
        return candidate

    # ------------------------------------------------------------- create/plan
    async def create_task_async(self, user_id: str, message: str,
                                session_id: Optional[str] = None,
                                template_id: Optional[str] = None,
                                kb_ids: Optional[List[str]] = None,
                                planned_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        from app.infrastructure.database.models.writing_task import WritingTaskModel

        ctx = task_parser.empty_context()
        changes: List[str] = []
        interpreted = None
        if planned_context:
            for key in tuple(ctx.keys()):
                if key in planned_context and key not in ("history", "missing_fields"):
                    ctx[key] = planned_context[key]
            ctx["template_id"] = None
            ctx["template_name"] = None
            # Strict literals can still be refreshed from the original sentence.
            literal = self._literal_overrides(message)
            changes = task_parser.merge_context(ctx, literal)
        else:
            interpreted = await self._interpret_async(message, ctx, has_draft=False)
            if interpreted:
                changes = self._merge_interpretation(ctx, interpreted)
            else:
                parsed = task_parser.parse_message(message)
                if not task_parser.explicit_document_type(message):
                    parsed.pop("document_type", None)
                changes = task_parser.merge_context(ctx, parsed)
        ctx["document_type"] = task_parser.resolved_document_type(
            message, ctx.get("document_type"))

        if not ctx.get("title"):
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

        reply = (interpreted or {}).get("reply") or self._collecting_reply(
            ctx, changes, missing, message)
        self._push_history(ctx, "assistant", reply)
        task.context = ctx
        self.db.commit()
        return {**self._to_dict(task), "reply": reply, "content_changed": False}

    async def plan_task_async(self, user_id: str, message: str) -> Dict[str, Any]:
        ctx = task_parser.empty_context()
        literal_plan = task_parser.parse_message(message)
        interpreted = await self._interpret_async(message, ctx, has_draft=False)
        if interpreted:
            self._merge_interpretation(ctx, interpreted)
            source = "llm"
        else:
            source = "rule"
        # Explicit document wording and dates win over model guesses; the model fills only gaps.
        literal_keys = ("time_range", "word_count_target",
                        "document_number_enabled", "document_number", "document_date")
        task_parser.merge_context(ctx, {k: literal_plan[k] for k in literal_keys
                                        if k in literal_plan})
        ctx["document_type"] = task_parser.resolved_document_type(
            message, ctx.get("document_type"))
        for key in ("topic", "title", "recipient", "authority"):
            if not ctx.get(key) and literal_plan.get(key):
                ctx[key] = literal_plan[key]

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
        # Preserve existing quick-plan policy: materials are searched only when explicitly useful.
        material_cues = ("参考", "结合", "根据", "依据", "材料", "范文", "案例", "政策", "文件")
        materials = self._plan_materials(ctx, user_id, org_ctx) \
            if any(cue in message for cue in material_cues) else []
        knowledge = self._plan_knowledge(user_id, org_ctx)
        return {
            "doc_type": doc_type,
            "target": ctx.get("purpose") or ctx.get("topic") or message[:40],
            "audience": ctx.get("recipient") or "",
            "department": org_ctx.get("dept_name") or org_ctx.get("short_name") or "",
            "agent": (org_ctx.get("agent") or {}).get("name") or "",
            "title": ctx.get("title") or "",
            "source": source,
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

    # --------------------------------------------------------------- revisions
    def _assert_revision_client_base(self, task, version, digest) -> None:
        if (version is None or digest is None or
                version != (task.version_no or 0) or
                digest != content_hash(self._to_dict(task)["current_content"])):
            raise HTTPException(status_code=409,
                                detail="正文已变化或客户端版本过旧，请刷新后重试")

    def _claim_revision_state(self, task, user_id: str, expected_state) -> None:
        # Lightweight service tests use an in-memory task stand-in. Persisted
        # production tasks always take the conditional SQL update below.
        if not getattr(task, "id", None):
            if (getattr(task, "current_content", None), getattr(task, "version_no", None)) \
                    != expected_state:
                raise HTTPException(status_code=409,
                                    detail="修改期间正文已变化，未覆盖新版本，请刷新后重试")
            return
        expected_content, expected_version = expected_state
        result = self.db.execute(update(WritingTaskModel).where(
            WritingTaskModel.id == task.id,
            WritingTaskModel.user_id == user_id,
            WritingTaskModel.current_content == expected_content,
            WritingTaskModel.version_no == expected_version,
        ).values(updated_at=WritingTaskModel.updated_at))
        if result.rowcount != 1:
            self.db.rollback()
            raise HTTPException(status_code=409,
                                detail="修改期间正文已变化，未覆盖新版本，请刷新后重试")
        self.db.refresh(task)

    def _supersede_pending_suggestions(self, task_id: str, user_id: str) -> bool:
        pending = self.db.scalars(select(WritingSuggestionModel).where(
            WritingSuggestionModel.task_id == task_id,
            WritingSuggestionModel.user_id == user_id,
            WritingSuggestionModel.status == "pending",
        )).all()
        for row in pending:
            row.status = "superseded"
            self._event(row, "supersede")
        return bool(pending)

    async def patch_section_async(self, task_id: str, user_id: str, target: str,
                                  instruction: str, mode: str = "revise", operation: str = "patch_section",
                                  position: str = "after", end_target: Optional[str] = None,
                                  current_override: Optional[str] = None,
                                  client_base_version: Optional[int] = None,
                                  client_base_hash: Optional[str] = None) -> Dict[str, Any]:
        task = self._get_owned(task_id, user_id)
        if current_override is not None:
            self._assert_revision_client_base(task, client_base_version, client_base_hash)
        expected_state = (task.current_content, task.version_no)
        ctx = dict(task.context or {})
        current = self._canonicalize_body(
            (current_override if current_override is not None else task.current_content or "").strip(), ctx)
        if not current:
            raise HTTPException(status_code=409, detail="当前还没有草稿，请先起草")
        resolved = self._local_span(current, target, operation, position, end_target)
        if not resolved:
            return {
                **self._to_dict(task),
                "reply": (f"没有安全执行修改：无法把“{target or '未指定目标'}”唯一定位到当前正文。"
                          "请选中具体原文，或明确到某一段/某一节后再修改；系统没有退化成整篇重写。"),
                "content_changed": False,
                "context_changes": [],
                "operation": operation,
                "patch_target": target,
            }
        start, end, fragment = resolved
        mode_desc = REVISE_MODES.get(mode, REVISE_MODES["revise"])
        prompt = self._local_prompt(fragment, instruction, mode_desc, operation)
        sources = self._retrieve(ctx, user_id, extra_query=instruction)
        attachment_ctx = self._attachment_context(task, ctx)
        replacement = "" if operation == "delete_range" else (await self._llm_revise_async(
            prompt, sources, attachment_ctx, user_id)).strip()
        if not replacement and operation != "delete_range":
            raise HTTPException(status_code=502, detail="模型未返回局部修改内容，请重试")
        if (operation == "patch_section" and replacement == fragment and
                current == (task.current_content or "").strip()):
            return {**self._to_dict(task),
                    "reply": "目标片段核对后没有产生实际文字变化，因此未创建新版本。",
                    "content_changed": False, "context_changes": [],
                    "operation": "patch_section", "patch_target": target}

        revised = self._splice_local(current, start, end, replacement, operation)
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
        from app.application.writing.content_check import ContentChecker
        quality = QualityGate().evaluate(
            revised, body_only=True, document_type=ctx.get("document_type") or "",
            word_count_target=ctx.get("word_count_target"))
        content_check = ContentChecker().check(revised, sources=sources, header_docnum=doc_number)
        if content_check["issues"]:
            quality["issues"] = list(quality.get("issues") or []) + content_check["issues"]
            if quality.get("level") == "A":
                quality["level"] = "B"
        references = self._reference_labels(sources) or list(ctx.get("references") or [])
        ctx["references"] = references
        self._claim_revision_state(task, user_id, expected_state)
        task.context = ctx
        task.current_content = revised
        self.db.flush()
        document_id, version = self._snapshot(
            task, user_id, note=f"AI 局部修改：{instruction[:30]}", commit=False)
        task.document_id = document_id
        task.version_no = version
        task.updated_at = now_local()
        suggestions_reset = (
            self._supersede_pending_suggestions(task_id, user_id)
            if getattr(task, "id", None) else False
        )
        self.db.commit()
        summary = self._revision_diff(current, revised)
        verb = {"append_to_section": "补充", "insert_paragraph": "插入新段落", "delete_range": "删除"}.get(operation, "修改")
        reply = (f"“{target}”已完成{verb}。"
                 + self._revise_reply(version, summary, citation_warnings, instruction))
        if suggestions_reset:
            reply += " 原有逐段建议已失效，请按新稿重新获取建议。"
        return {**self._to_dict(task), "reply": reply, "content_changed": True,
                "quality": quality, "content_check": content_check,
                "postprocess_events": events, "context_changes": [],
                "references": references, "revision_summary": summary,
                "operation": operation, "patch_target": target}

    async def revise_async(self, task_id: str, user_id: str, instruction: str,
                           mode: str = "revise", selection: Optional[str] = None,
                           current_override: Optional[str] = None,
                           client_base_version: Optional[int] = None,
                           client_base_hash: Optional[str] = None) -> Dict[str, Any]:
        if selection and selection.strip():
            return await self.patch_section_async(
                task_id, user_id, target=selection, instruction=instruction, mode=mode,
                current_override=current_override,
                client_base_version=client_base_version,
                client_base_hash=client_base_hash)
        task = self._get_owned(task_id, user_id)
        if current_override is not None:
            self._assert_revision_client_base(task, client_base_version, client_base_hash)
        expected_state = (task.current_content, task.version_no)
        current = (current_override if current_override is not None else task.current_content or "").strip()
        if not current:
            raise HTTPException(status_code=409, detail="当前还没有草稿，请先起草")
        ctx = dict(task.context or {})
        literal = self._literal_overrides(instruction)
        literal_changes = []
        if literal:
            literal_changes = task_parser.merge_context(ctx, literal)
            task_parser.compute_missing(ctx)
        mode_desc = REVISE_MODES.get(mode, REVISE_MODES["revise"])
        prompt = self._build_revise_prompt(current, instruction, mode_desc, None, ctx)
        sources = self._retrieve(ctx, user_id, extra_query=instruction)
        attachment_ctx = self._attachment_context(task, ctx)
        revised = await self._llm_revise_async(prompt, sources, attachment_ctx, user_id)
        if not revised.strip():
            raise HTTPException(status_code=502, detail="模型未返回内容，请重试")
        revised = self._canonicalize_body(revised, ctx)
        changes = task_parser.merge_context(ctx, task_parser.parse_message(instruction))
        task_parser.compute_missing(ctx)
        context_changes = list(dict.fromkeys([*literal_changes, *changes]))
        if revised.strip() == current and current == (task.current_content or "").strip():
            self._claim_revision_state(task, user_id, expected_state)
            if context_changes:
                task.context = ctx
                task.updated_at = now_local()
                self.db.commit()
                return {**self._to_dict(task),
                        "reply": "任务信息已更新：" + "；".join(context_changes) + "。正文未改，未生成新版本。",
                        "content_changed": False, "context_changes": context_changes}
            self.db.rollback()
            self.db.refresh(task)
            return {**self._to_dict(task),
                    "reply": "对照您的要求检查了当前文档，没有需要实际改动的地方，正文保持原样，也未生成新版本。",
                    "content_changed": False, "context_changes": []}

        revised, events, doc_number, doc_date = self._postprocess(revised, ctx)
        revised = self._canonicalize_body(revised, ctx)
        revised, citation_warnings = self._guard_external_document_numbers(revised, sources, ctx)
        from app.application.writing.content_check import ContentChecker
        quality = QualityGate().evaluate(
            revised, body_only=True, document_type=ctx.get("document_type") or "",
            word_count_target=ctx.get("word_count_target"))
        content_check = ContentChecker().check(revised, sources=sources, header_docnum=doc_number)
        if content_check["issues"]:
            quality["issues"] = list(quality.get("issues") or []) + content_check["issues"]
            if quality.get("level") == "A":
                quality["level"] = "B"
        if citation_warnings:
            ctx["citation_warnings"] = citation_warnings
        else:
            ctx.pop("citation_warnings", None)
        if doc_number:
            ctx["document_number"] = doc_number
        if doc_date:
            ctx["document_date"] = doc_date
        references = self._reference_labels(sources) or list(ctx.get("references") or [])
        ctx["references"] = references
        self._claim_revision_state(task, user_id, expected_state)
        task.context = ctx
        task.current_content = revised
        self.db.flush()
        document_id, version = self._snapshot(
            task, user_id, note=f"AI 修改：{instruction[:30]}", commit=False)
        task.document_id = document_id
        task.version_no = version
        task.updated_at = now_local()
        suggestions_reset = (
            self._supersede_pending_suggestions(task_id, user_id)
            if getattr(task, "id", None) else False
        )
        self.db.commit()
        reply = f"已按您的要求修改当前文档（{mode_desc.split('：')[0]}），保存为 v{version}。"
        if suggestions_reset:
            reply += " 原有逐段建议已失效，请按新稿重新获取建议。"
        if citation_warnings:
            reply += f"系统同时移除了 {len(citation_warnings)} 处无法核实的具体文号，请确认资料来源后再补回。"
        if context_changes:
            reply += "任务信息同步更新：" + "；".join(context_changes) + "。"
        return {**self._to_dict(task), "reply": reply, "content_changed": True,
                "quality": quality, "content_check": content_check,
                "postprocess_events": events, "context_changes": context_changes,
                "references": references}

    # ----------------------------------------------------------- draft/retries
    async def _regenerate_if_needed_async(self, instruction: str, sources, attachment_ctx,
                                          user_id: str, template: Optional[Dict[str, Any]],
                                          text: str, ctx: Dict[str, Any]) -> Tuple[str, Optional[str]]:
        from app.application.writing.postprocessor import detect_outline_degeneration
        candidate = text
        reasons: List[str] = []
        retries_used = 0

        degenerate = bool(detect_outline_degeneration(candidate))
        doc_type = str(ctx.get("document_type") or "")
        heading_count = len(re.findall(
            r"(?m)^\s*(一|二|三|四|五|六|七|八|九|十)+、", candidate))
        word_target = ctx.get("word_count_target")
        compact_letter = (
            "函" in doc_type and (
                heading_count > 6 or (
                    not word_target and
                    (len(re.sub(r"\s+", "", candidate)) > 1500 or heading_count > 5)
                )
            )
        )
        if degenerate or compact_letter:
            retries_used = 1
            if degenerate:
                retry_instruction = instruction + (
                    "\n\n【重写要求】上一版只有章节标题和占位说明，是提纲不是公文。"
                    "逐节展开为完整段落，不得出现‘略’‘待补充’等占位文字。")
                reason = "检测到初稿只有提纲，已自动重写为完整成文。"
            else:
                target_rule = (
                    f"仍然不少于 {word_target} 字，同时把一级条目合并到 3-5 个。"
                    if word_target else
                    "合并重复事项，将正文压缩为 3-5 个自然段或部分，通常控制在 800-1200 字。"
                )
                retry_instruction = instruction + "\n\n【精简重写要求】" + target_rule
                reason = "检测到函件被写成了长篇报告体例，已自动精简。"
            try:
                retried = self._clean_markdown(await self._llm_draft_async(
                    retry_instruction, sources, attachment_ctx, user_id, template=template))
                if retried.strip() and not detect_outline_degeneration(retried):
                    candidate = retried
                    reasons.append(reason)
            except Exception:
                pass

        quality = self._quality_result(
            candidate, topic=str(ctx.get("title") or ctx.get("topic") or ""))
        while quality.get("level") == "D" and retries_used < 2:
            retries_used += 1
            retry_instruction = self._retry_prompt(
                instruction, candidate, quality, retries_used)
            try:
                candidate = self._clean_markdown(await self._llm_draft_async(
                    retry_instruction, sources, attachment_ctx, user_id, template=template))
            except Exception:
                break
            quality = self._quality_result(
                candidate, topic=str(ctx.get("title") or ctx.get("topic") or ""))
            reasons.append(f"QualityGate 检测到硬伤，已按具体问题自动修复第 {retries_used} 次。")
        return candidate, ("".join(reasons) if reasons else None)

    async def _section_plan_async(self, ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
        if not self.assistant:
            return self._fallback_plan(ctx)
        total = int(ctx.get("word_count_target") or 2200)
        original_request = next((str(item.get("content") or "").strip()
                                 for item in ctx.get("history") or []
                                 if item.get("role") == "user" and item.get("content")), "")
        prompt = (
            "为一篇司法行政机关正式材料规划一级章节。只返回 JSON 数组，不要正文、Markdown 或解释。"
            "数组 3-6 项，每项字段必须为 heading、focus、target_chars。"
            "报告、方案等可用‘一、…’格式；致辞稿、讲话稿、发言稿和主持词的 heading 必须为空，"
            "正文按自然段推进。focus 用一句话说明本节只写什么；target_chars 为本节目标字数。"
            "章节之间职责不能重叠，目标字数合计应接近全文目标。\n"
            f"文种：{ctx.get('document_type') or '正式材料'}\n"
            f"主题：{ctx.get('topic') or ctx.get('title') or ''}\n"
            f"用途：{ctx.get('purpose') or ''}\n"
            f"时间范围：{ctx.get('time_range') or ''}\n全文目标字数：{total}"
            f"\n用户原始需求：{original_request}"
        )
        import json
        try:
            raw = await self.assistant.acomplete(
                [{"role": "user", "content": prompt}], temperature=0.1, max_tokens=900)
            match = re.search(r"\[[\s\S]*\]", raw or "")
            data = json.loads(match.group(0) if match else raw)
            plan: List[Dict[str, Any]] = []
            for item in data if isinstance(data, list) else []:
                heading = str(item.get("heading") or "").strip()
                focus = str(item.get("focus") or "").strip()
                try:
                    chars = int(item.get("target_chars") or 0)
                except (TypeError, ValueError):
                    chars = 0
                if focus:
                    plan.append({"heading": heading[:80], "focus": focus[:240],
                                 "target_chars": max(300, min(chars or total // 4, max(1200, total)))})
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

    async def _generate_one_section_async(self, ctx: Dict[str, Any], section: Dict[str, Any],
                                          index: int, plan: List[Dict[str, Any]], user_id: str,
                                          attachment_ctx: str, template) -> Tuple[str, List[Dict]]:
        previous = [x["heading"] or x["focus"] for x in plan[:index]]
        following = [x["heading"] or x["focus"] for x in plan[index + 1:]]
        instruction = self._section_instruction(ctx, section, previous, following)
        sources = self._retrieve(ctx, user_id, extra_query=f"{section['heading']} {section['focus']}")
        candidate = self._normalize_section(
            self._clean_markdown(await self._llm_draft_async(
                instruction, sources, attachment_ctx, user_id, template=template)),
            section["heading"],
        )
        if self._section_is_short(candidate, section["target_chars"]):
            expanded = self._normalize_section(
                self._clean_markdown(await self._llm_draft_async(
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
            issues = [str(x.get("message") or x.get("type") or "")
                      for x in quality.get("issues") or []
                      if isinstance(x, dict) and x.get("severity") == "critical"]
            repair = instruction + (
                "\n\n上一版当前章节未通过质量检查，只重写这一节，不得生成其他章节。必须修复："
                + "；".join(issues or ["章节正文质量不合格"])
                + "\n上一版：\n" + candidate[:5000]
            )
            candidate = self._normalize_section(
                self._clean_markdown(await self._llm_draft_async(
                    repair, sources, attachment_ctx, user_id, template=template)),
                section["heading"],
            )
            quality = QualityGate().evaluate(candidate, body_only=True)
        if quality.get("level") == "D":
            raise HTTPException(status_code=422, detail={
                "code": "WRITING_SECTION_QUALITY_D",
                "message": f"{section['heading']} 连续两次修复后仍未通过质量门，全文未保存。",
                "section": section["heading"], "issues": quality.get("issues") or [],
            })
        return candidate, sources

    async def draft_async(self, task_id: str, user_id: str,
                          outline_only: bool = False) -> Dict[str, Any]:
        task = self._get_owned(task_id, user_id)
        agent_graph = self._prepare_agent_graph(task, user_id, outline_only)
        if agent_graph is not None:
            return await agent_graph.execute()
        expected_state = (task.current_content, task.version_no)
        prompt_snapshot.enter_task(
            task_id, user_id, session_id=getattr(task, "session_id", "") or "")
        ctx = dict(task.context or {})
        template = self._load_template(ctx.get("template_id"))
        attachment_ctx = self._attachment_context(task, ctx)
        if self._should_section(ctx, outline_only):
            plan = await self._section_plan_async(ctx)
            sections: List[str] = []
            source_groups: List[List[Dict]] = []
            for index, section in enumerate(plan):
                text, sources = await self._generate_one_section_async(
                    ctx, section, index, plan, user_id, attachment_ctx, template)
                sections.append(text)
                source_groups.append(sources)
            assembled = "\n\n".join(sections).strip()
            if not assembled:
                raise HTTPException(status_code=502, detail="模型未返回内容，请重试")
            payload = self._finalize_draft(
                task, ctx, assembled, self._merge_sources(source_groups), user_id,
                expected_state=expected_state)
            payload["generation_mode"] = "sectioned"
            payload["section_plan"] = plan
            payload["reply"] = "长文已按章节分别检索、生成并组装。" + payload["reply"]
            return payload

        instruction = self._build_draft_instruction(ctx, outline_only, template)
        sources = self._retrieve(ctx, user_id)
        text = self._clean_markdown(await self._llm_draft_async(
            instruction, sources, attachment_ctx, user_id, template=template))
        if not text.strip():
            raise HTTPException(status_code=502, detail="模型未返回内容，请重试")
        text, retry_reason = await self._regenerate_if_needed_async(
            instruction, sources, attachment_ctx, user_id, template, text, ctx)
        payload = self._finalize_draft(task, ctx, text, sources, user_id,
                                       expected_state=expected_state)
        if retry_reason:
            payload["reply"] = retry_reason + payload["reply"]
        return payload

    def _finalize_draft(self, task, ctx, text, sources, user_id,
                        expected_state=None):
        """Reject a completely different continuation before changing the saved document."""
        if expected_state is not None:
            # A conditional no-op update obtains a row lock until the version save
            # commits, so a concurrent save cannot slip between check and write.
            expected_content, expected_version = expected_state
            result = self.db.execute(update(WritingTaskModel).where(
                WritingTaskModel.id == task.id,
                WritingTaskModel.user_id == user_id,
                WritingTaskModel.current_content == expected_content,
                WritingTaskModel.version_no == expected_version,
            ).values(updated_at=WritingTaskModel.updated_at))
            if result.rowcount != 1:
                self.db.rollback()
                raise HTTPException(status_code=409,
                                    detail="生成期间正文已变化，未覆盖新版本，请刷新后重试")
            self.db.refresh(task)

        if task.current_content:
            old_lines = set(task.current_content.splitlines())
            new_lines = set(text.splitlines())
            accepted = self.db.scalars(select(WritingSuggestionModel.final_content).where(
                WritingSuggestionModel.task_id == task.id,
                WritingSuggestionModel.user_id == user_id,
                WritingSuggestionModel.status == "accepted",
                WritingSuggestionModel.final_content.is_not(None),
            )).all()
            if any(line in old_lines and line not in new_lines for line in accepted):
                raise HTTPException(status_code=422,
                                    detail="新稿丢失了已采纳的逐段修改，未替换当前版本")
        old = re.sub(r"\s+", "", task.current_content or "")
        new = re.sub(r"\s+", "", text or "")
        if len(old) >= 120:
            def grams(value: str) -> set[str]:
                value = value[:8000]
                return {value[i:i + 4] for i in range(max(0, len(value) - 3))}

            old_grams, new_grams = grams(old), grams(new)
            overlap = (len(old_grams & new_grams) / max(1, min(len(old_grams), len(new_grams))))
            if len(new) < len(old) * 0.55 or overlap < 0.18:
                raise HTTPException(
                    status_code=422,
                    detail="新稿与当前稿差异过大，未替换已保存版本。请用逐段建议修改具体段落，或新建任务重新起草。",
                )
        return super()._finalize_draft(task, ctx, text, sources, user_id)

    async def draft_stream_async(self, task_id: str, user_id: str,
                                 outline_only: bool = False) -> AsyncIterator[str]:
        try:
            task = self._get_owned(task_id, user_id)
            agent_graph = self._prepare_agent_graph(task, user_id, outline_only)
            if agent_graph is not None:
                yield _sse({
                    "type": "run", "run_id": agent_graph.run.id, "route": "agent",
                })
                async for event_type, data in agent_graph.stream():
                    if event_type == "delta":
                        yield _sse({"type": "delta", **data})
                    elif event_type == "done":
                        yield _sse({"type": "done", "data": data})
                    else:
                        yield _sse({"type": event_type, **data})
                return
            if graph_enabled_for_user(settings, user_id):
                yield _sse({"type": "run", "run_id": "", "route": "fast"})
            expected_state = (task.current_content, task.version_no)
            prompt_snapshot.enter_task(
                task_id, user_id, session_id=getattr(task, "session_id", "") or "")
            ctx = dict(task.context or {})
            template = self._load_template(ctx.get("template_id"))
            attachment_ctx = self._attachment_context(task, ctx)
            if self._should_section(ctx, outline_only):
                plan = await self._section_plan_async(ctx)
                sections: List[str] = []
                source_groups: List[List[Dict]] = []
                for index, section in enumerate(plan):
                    text, sources = await self._generate_one_section_async(
                        ctx, section, index, plan, user_id, attachment_ctx, template)
                    sections.append(text)
                    source_groups.append(sources)
                    yield _sse({"type": "delta", "text": text + "\n\n"})
                payload = self._finalize_draft(
                    task, ctx, "\n\n".join(sections).strip(),
                    self._merge_sources(source_groups), user_id,
                    expected_state=expected_state)
                payload["generation_mode"] = "sectioned"
                payload["section_plan"] = plan
                payload["reply"] = "长文已按章节分别检索、生成并组装。" + payload["reply"]
                yield _sse({"type": "done", "data": payload})
                return

            instruction = self._build_draft_instruction(ctx, outline_only, template)
            sources = self._retrieve(ctx, user_id)
            system = self._draft_prompt(instruction, sources, attachment_ctx, user_id, template)
            parts: List[str] = []
            async for delta in self.assistant.achat_stream(
                message=instruction, history=[], sources=sources, user_role="user",
                system_prompt=system, attachment_context=attachment_ctx):
                if delta:
                    parts.append(delta)
                    yield _sse({"type": "delta", "text": delta})
            text = self._clean_markdown("".join(parts))
            if not text.strip():
                yield _sse({"type": "error", "message": "模型未返回内容，请重试"})
                return
            text, retry_reason = await self._regenerate_if_needed_async(
                instruction, sources, attachment_ctx, user_id, template, text, ctx)
            payload = self._finalize_draft(task, ctx, text, sources, user_id,
                                           expected_state=expected_state)
            if retry_reason:
                payload["reply"] = retry_reason + payload["reply"]
            yield _sse({"type": "done", "data": payload})
        except HTTPException as exc:
            yield _sse({"type": "error", "message": _http_error_message(exc.detail)})
        except Exception as exc:
            yield _sse({"type": "error", "message": f"生成中断：{exc}"})

    # ------------------------------------------------------ agent orchestration
    def _prepare_agent_graph(self, task, user_id: str,
                             outline_only: bool) -> Optional[WritingAgentGraph]:
        if not graph_enabled_for_user(settings, user_id):
            return None
        ctx = dict(task.context or {})
        attachment_ctx = self._attachment_context(task, ctx)
        route = classify_writing_route(ctx, outline_only, bool(attachment_ctx))
        if settings.WRITING_AGENT_GRAPH_COMPLEX_ONLY and route != "agent":
            return None
        store = AgentRunStore(self.db)
        initial_state = {
            "task_id": task.id,
            "user_id": user_id,
            "context": ctx,
            "outline_only": outline_only,
            "base_version": int(task.version_no or 0),
            "base_content": task.current_content or "",
            "repair_round": 0,
        }
        active = store.active_for_task(task.id, user_id)
        if active and (
            active.base_version != int(task.version_no or 0)
            or active.base_content_hash != content_hash(task.current_content or "")
        ):
            store.fail_run(
                active, "STALE_BASE", "正文已变化，旧的智能体运行不能继续", recoverable=False)
        run, _created = store.get_or_create(
            task_id=task.id,
            user_id=user_id,
            route="agent",
            base_version=int(task.version_no or 0),
            base_content=task.current_content or "",
            initial_state=initial_state,
        )
        return WritingAgentGraph(self, store, run)

    def get_agent_run(self, task_id: str, user_id: str, run_id: str) -> Dict[str, Any]:
        self._get_owned(task_id, user_id)
        store = AgentRunStore(self.db)
        return store.public_dict(store.get_owned(run_id, task_id, user_id))

    async def resume_agent_run_async(self, task_id: str, user_id: str,
                                     run_id: str) -> Dict[str, Any]:
        task = self._get_owned(task_id, user_id)
        store = AgentRunStore(self.db)
        run = store.get_owned(run_id, task_id, user_id)
        if run.status == "completed":
            return {
                "run": store.public_dict(run),
                "data": dict((run.state_json or {}).get("result") or {}),
            }
        if run.status == "cancelled":
            raise HTTPException(status_code=409, detail="该运行已取消，不能恢复")
        if run.status == "failed":
            raise HTTPException(status_code=409, detail="该运行已终止，请重新生成")
        if (run.base_version != int(task.version_no or 0)
                or run.base_content_hash != content_hash(task.current_content or "")):
            store.fail_run(run, "STALE_BASE", "正文已变化，不能恢复旧运行", recoverable=False)
            raise HTTPException(status_code=409, detail="正文已变化，不能恢复旧运行")
        result = await WritingAgentGraph(self, store, run).execute()
        return {"run": store.public_dict(run), "data": result}

    def cancel_agent_run(self, task_id: str, user_id: str,
                         run_id: str) -> Dict[str, Any]:
        self._get_owned(task_id, user_id)
        store = AgentRunStore(self.db)
        run = store.get_owned(run_id, task_id, user_id)
        store.cancel(run)
        return store.public_dict(run)

    # ---------------------------------------------------------------- chat ops
    async def chat_async(self, task_id: str, user_id: str, message: str) -> Dict[str, Any]:
        task = self._get_owned(task_id, user_id)
        prompt_snapshot.enter_task(
            task_id, user_id, session_id=getattr(task, "session_id", "") or "")
        ctx = dict(task.context or {})
        has_draft = bool((task.current_content or "").strip())
        self._push_history(ctx, "user", message)
        interpreted = await self._interpret_async(message, ctx, has_draft=has_draft)
        if not interpreted:
            reply = await self._answer_only_async(message, ctx, task.current_content or "")
            self._push_history(ctx, "assistant", reply)
            task.context = ctx
            self.db.commit()
            return {**self._to_dict(task), "reply": reply, "content_changed": False}

        before_ctx = dict(ctx)
        changes = self._merge_interpretation(ctx, interpreted)
        task_parser.compute_missing(ctx)
        task.context = ctx
        task.updated_at = now_local()
        self.db.commit()
        operation = interpreted.get("operation") or "answer"

        if operation in (*LOCAL_OPERATIONS, "rewrite_document") and not has_draft:
            reply = "当前还没有草稿，请先起草，再告诉我需要修改的段落或内容。"
            self._push_history(ctx, "assistant", reply)
            task.context = ctx
            self.db.commit()
            return {**self._to_dict(task), "reply": reply,
                    "content_changed": False, "context_changes": changes,
                    "operation": operation}

        if operation in LOCAL_OPERATIONS and has_draft:
            result = await self.patch_section_async(
                task_id, user_id,
                target=interpreted.get("patch_target") or "",
                instruction=interpreted.get("revision_instruction") or message,
                mode=interpreted.get("revision_mode") or "revise", operation=operation,
                position=interpreted.get("position") or "after", end_target=interpreted.get("end_target"))
        elif operation == "rewrite_document" and has_draft:
            result = await self.revise_async(
                task_id, user_id,
                instruction=interpreted.get("revision_instruction") or message,
                mode=interpreted.get("revision_mode") or "rewrite")
        elif operation in ("draft_document", "outline"):
            result = await self.draft_async(
                task_id, user_id, outline_only=(operation == "outline"))
        else:
            content_changed = False
            if has_draft and operation == "set_fields" and before_ctx != ctx:
                note = self._sync_structured_fields(task, user_id)
                content_changed = bool(note)
                if note:
                    changes = list(changes) + [note]
            reply = interpreted.get("reply") or await self._answer_only_async(message, ctx, task.current_content or "")
            if changes:
                reply += "\n\n已应用：" + "；".join(changes) + "。"
            self._push_history(ctx, "assistant", reply)
            task.context = ctx
            self.db.commit()
            return {**self._to_dict(task), "reply": reply,
                    "content_changed": content_changed, "context_changes": changes,
                    "operation": operation, "routing": interpreted.get("routing") or "legacy"}

        result["context_changes"] = changes
        latest_ctx = dict(task.context or {})
        self._push_history(latest_ctx, "assistant", result["reply"])
        task.context = latest_ctx
        self.db.commit()
        return result
