"""LangGraph orchestration for complex, grounded writing tasks."""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any, AsyncIterator, TypedDict

from fastapi import HTTPException
from langgraph.graph import END, START, StateGraph
from langgraph.config import get_stream_writer

from app.application.format_check.check_engine import FormatCheckEngine
from app.application.writing.agent_graph.persistence import AgentRunStore, json_digest
from app.application.writing.agent_graph.tools import BoundedToolExecutor, ToolExecutionError
from app.application.writing.content_check import ContentChecker
from app.application.writing.quality_gate import merge_level
from app.application.writing import task_parser
from app.application.writing.paragraph_suggestions import content_hash
from app.core.config import settings
from app.core.monitoring import (
    WRITING_AGENT_NODE_LATENCY,
    WRITING_AGENT_REPAIRS,
    WRITING_AGENT_RUNS,
    WRITING_AGENT_TOOL_CALLS,
)
from app.infrastructure.repositories.format_check import SqlAlchemyFormatRuleRepository


class WritingAgentState(TypedDict, total=False):
    run_id: str
    task_id: str
    user_id: str
    context: dict[str, Any]
    outline_only: bool
    base_version: int
    base_content: str
    section_plan: list[dict[str, Any]]
    sources: list[dict[str, Any]]
    candidate: str
    quality: dict[str, Any]
    content_check: dict[str, Any]
    quality_level: str
    quality_issues: list[dict[str, Any]]
    repair_round: int
    result: dict[str, Any]
    rejected: bool


STAGE_LABELS = {
    "planner": "正在理解需求",
    "research": "正在检索资料",
    "writer": "正在生成正文",
    "review": "正在校验",
    "repair": "正在修复",
    "finalize": "正在整理结果",
    "reject": "质量检查未通过",
}


def _jsonable(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def _merge_sources(groups: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for group in groups:
        for item in group or []:
            key = str(item.get("chunk_id") or item.get("doc_id") or item.get("source") or item)
            if key in seen:
                continue
            seen.add(key)
            out.append(_jsonable(item))
    return out


class WritingAgentGraph:
    """A bounded graph whose durable source of truth is the application's own tables."""

    def __init__(self, service: Any, store: AgentRunStore, run: Any):
        self.service = service
        self.store = store
        self.run = run
        self.max_repairs = settings.WRITING_AGENT_MAX_REPAIR_ROUNDS
        self.graph = self._compile()

    def _compile(self):
        graph = StateGraph(WritingAgentState)
        graph.add_node("planner", self._planner)
        graph.add_node("research", self._research)
        graph.add_node("writer", self._writer)
        graph.add_node("review", self._review)
        graph.add_node("repair", self._repair)
        graph.add_node("finalize", self._finalize)
        graph.add_node("reject", self._reject)
        graph.add_edge(START, "planner")
        graph.add_edge("planner", "research")
        graph.add_edge("research", "writer")
        graph.add_edge("writer", "review")
        graph.add_conditional_edges("review", self._after_review, {
            "repair": "repair", "finalize": "finalize", "reject": "reject",
        })
        graph.add_edge("repair", "review")
        graph.add_edge("finalize", END)
        graph.add_edge("reject", END)
        return graph.compile()

    def _attempt(self, node: str, state: WritingAgentState) -> int:
        if node in {"review", "repair"}:
            return int(state.get("repair_round") or 0) + 1
        return 1

    async def _durable(self, node: str, state: WritingAgentState, work):
        self.store.db.refresh(self.run)
        if self.run.status == "cancelled":
            raise HTTPException(status_code=409, detail="生成已取消")
        attempt = self._attempt(node, state)
        completed = self.store.completed_step(self.run.id, node, attempt)
        if completed:
            # A resumed run starts with the latest durable state. Replaying an
            # earlier node's output (for example the original writer candidate)
            # must not overwrite a later repair already present in that state.
            return {
                key: value for key, value in dict(completed.output_json or {}).items()
                if key not in state
            }
        self.store.begin_step(self.run, node, attempt, _jsonable(dict(state)))
        started = time.monotonic()
        try:
            output = _jsonable(await work())
            elapsed = time.monotonic() - started
            self.store.complete_step(self.run, node, attempt, output, elapsed)
            WRITING_AGENT_NODE_LATENCY.labels(node).observe(elapsed)
            return output
        except Exception as exc:
            recoverable = not isinstance(exc, HTTPException) or exc.status_code >= 500
            self.store.fail_step(
                self.run, node, attempt, str(getattr(exc, "detail", exc)),
                recoverable=recoverable,
            )
            raise

    async def _planner(self, state: WritingAgentState):
        async def work():
            ctx = dict(state.get("context") or {})
            request = next((
                str(item.get("content") or "")
                for item in reversed(ctx.get("history") or [])
                if item.get("role") == "user" and item.get("content")
            ), "")
            # 前端的一句话入口已经调用 /plan，由 AI 直接理解原话并把结果写进
            # planned_context。复杂链路复用该结果，避免开始写作前再等一次同样的模型调用。
            already_planned = (ctx.get("planning_completed")
                               and ctx.get("planning_request_hash") == content_hash(request))
            if request and not already_planned:
                interpreted = await self.service._interpret_async(
                    request, ctx, has_draft=False)
                if interpreted:
                    self.service._merge_interpretation(ctx, interpreted)
                    ctx["planning_completed"] = True
                    ctx["planning_request_hash"] = content_hash(request)
                ctx["document_type"] = task_parser.resolved_document_type(
                    request, ctx.get("document_type"))
            if not ctx.get("title"):
                ctx["title"] = task_parser.build_title(ctx) or ""
            self.service._complete_default_authority(ctx)
            task_parser.compute_missing(ctx)
            section_plan = []
            if self.service._should_section(ctx, bool(state.get("outline_only"))):
                section_plan = await self.service._section_plan_async(ctx)
            return {
                "context": ctx,
                "section_plan": section_plan,
                "repair_round": int(state.get("repair_round") or 0),
            }
        return await self._durable("planner", state, work)

    @staticmethod
    def _search_schemas() -> list[dict[str, Any]]:
        parameter = {
            "type": "object",
            "properties": {"query": {"type": "string", "maxLength": 200}},
            "required": ["query"],
            "additionalProperties": False,
        }
        return [
            {"type": "function", "function": {
                "name": "search_knowledge", "description": "检索本用户有权访问的知识库事实与规范",
                "parameters": parameter,
            }},
            {"type": "function", "function": {
                "name": "search_exemplars", "description": "检索同文种范文，仅学习结构和风格",
                "parameters": parameter,
            }},
        ]

    async def _research(self, state: WritingAgentState):
        async def work():
            ctx = dict(state.get("context") or {})
            user_id = str(state["user_id"])
            retrieve = getattr(self.service, "_retrieve_async", None)
            groups: list[list[dict[str, Any]]] = [
                await retrieve(ctx, user_id) if callable(retrieve)
                else self.service._retrieve(ctx, user_id)
            ]

            async def search(args: dict[str, Any], *, exemplar: bool = False):
                query = str(args.get("query") or "").strip()[:200]
                if not query:
                    return []
                suffix = f"同类范文 体例 {query}" if exemplar else query
                return _jsonable(
                    await retrieve(ctx, user_id, extra_query=suffix)
                    if callable(retrieve) else
                    self.service._retrieve(ctx, user_id, extra_query=suffix))

            async def search_knowledge(args):
                return await search(args)

            async def search_exemplars(args):
                return await search(args, exemplar=True)

            tool_model = self.service.assistant
            tool_complete = getattr(tool_model, "acomplete_with_tools", None)
            request = next((
                str(item.get("content") or "")
                for item in reversed(ctx.get("history") or [])
                if item.get("role") == "user" and item.get("content")
            ), "")
            grounding_cues = (
                "依据", "根据", "结合", "引用", "法规", "政策", "案例", "数据",
                "文号", "统计", "材料", "范文", "知识库", "附件",
            )
            needs_model_search = bool(ctx.get("kb_ids")) or any(
                cue in request for cue in grounding_cues)
            # 普通长文已有一次确定性检索，无需再让模型先决定“要不要检索”。
            # 有明确资料/知识库要求时才开放多轮工具调用。
            if callable(tool_complete) and needs_model_search:
                executor = BoundedToolExecutor(
                    model=tool_model,
                    tools={
                        "search_knowledge": search_knowledge,
                        "search_exemplars": search_exemplars,
                    },
                    schemas=self._search_schemas(),
                    max_rounds=settings.WRITING_AGENT_MAX_TOOL_ROUNDS,
                )
                messages = [
                    {"role": "system", "content": (
                        "你是资料检索智能体。根据写作任务判断是否需要补充检索。"
                        "只调用给定工具，知识库内容用于事实依据，范文只用于结构与风格。"
                        "资料足够后用一句话说明检索完成。")},
                    {"role": "user", "content": json.dumps({
                        "文种": ctx.get("document_type"), "标题": ctx.get("title"),
                        "主题": ctx.get("topic"), "原始需求": request[:800],
                    }, ensure_ascii=False)},
                ]
                try:
                    loop = await executor.run(messages)
                    for record in loop.calls:
                        result = record.result if isinstance(record.result, list) else []
                        groups.append(result)
                        source_ids = [str(item.get("doc_id") or item.get("chunk_id") or "")
                                      for item in result if isinstance(item, dict)]
                        research_step = self.store.step(self.run.id, "research", 1)
                        self.store.record_tool_call(
                            run_id=self.run.id,
                            step_id=research_step.id if research_step else None,
                            agent_name="research",
                            tool_name=record.name,
                            arguments_summary=json.dumps({
                                "query_chars": len(str(record.arguments.get("query") or "")),
                                "query_hash": json_digest(record.arguments)[:12],
                            }, ensure_ascii=False),
                            result_summary=f"返回 {len(result)} 条资料" + ("（缓存）" if record.cached else ""),
                            source_ids=[item for item in source_ids if item],
                            duration_seconds=record.duration_seconds,
                        )
                        WRITING_AGENT_TOOL_CALLS.labels(record.name, "cached" if record.cached else "completed").inc()
                except NotImplementedError:
                    # Legacy/mock gateways keep the deterministic scoped retrieval above.
                    pass
                except ToolExecutionError as exc:
                    research_step = self.store.step(self.run.id, "research", 1)
                    self.store.record_tool_call(
                        run_id=self.run.id,
                        step_id=research_step.id if research_step else None,
                        agent_name="research",
                        tool_name="rejected_tool_call",
                        arguments_summary="{}",
                        result_summary=type(exc).__name__,
                        source_ids=[],
                        status="rejected",
                    )
                    WRITING_AGENT_TOOL_CALLS.labels(
                        "rejected_tool_call", "rejected").inc()
            return {"sources": _merge_sources(groups)}
        return await self._durable("research", state, work)

    async def _writer(self, state: WritingAgentState):
        async def work():
            emit = get_stream_writer()
            ctx = dict(state.get("context") or {})
            user_id = str(state["user_id"])
            task = self.service._get_owned(str(state["task_id"]), user_id)
            template = self.service._load_template(ctx.get("template_id"))
            attachment_ctx = self.service._attachment_context(task, ctx)
            plan = list(state.get("section_plan") or [])
            if plan:
                initial_sources = list(state.get("sources") or [])
                sections: list[str] = []
                groups: list[list[dict[str, Any]]] = [initial_sources]
                stream_section = getattr(
                    self.service, "_generate_one_section_stream_async", None)
                if callable(stream_section):
                    provisional: list[str] = []
                    def on_delta(delta: str) -> None:
                        provisional.append(delta)
                        emit({"text": delta})
                    first, first_sources = await stream_section(
                        ctx, plan[0], 0, plan, user_id, attachment_ctx,
                        template, on_delta=on_delta)
                    if first.strip() != "".join(provisional):
                        emit({"replace": first.strip()})
                else:
                    first, first_sources = await self.service._generate_one_section_async(
                        ctx, plan[0], 0, plan, user_id, attachment_ctx, template)
                    emit({"text": first.strip()})
                sections.append(first.strip())
                groups.append(first_sources)
                async def later_sections():
                    generate_sections = getattr(self.service, "_generate_sections_async", None)
                    if (callable(generate_sections)
                            and settings.WRITING_SECTION_MAX_CONCURRENCY > 1):
                        for result in await generate_sections(
                            ctx, plan, user_id, attachment_ctx, template, start_index=1):
                            yield result
                    else:
                        for index in range(1, len(plan)):
                            yield await self.service._generate_one_section_async(
                                ctx, plan[index], index, plan, user_id,
                                attachment_ctx, template)
                async for later, later_sources in later_sections():
                    later = later.strip()
                    sections.append(later)
                    groups.append(later_sources)
                    emit({"text": "\n\n" + later})
                candidate = "\n\n".join(sections).strip()
                sources = _merge_sources(groups)
            else:
                instruction = self.service._build_draft_instruction(
                    ctx, bool(state.get("outline_only")), template)
                sources = list(state.get("sources") or [])
                assistant = getattr(self.service, "_draft_assistant", None)
                if callable(getattr(assistant, "achat_stream", None)):
                    prompt_async = getattr(self.service, "_draft_prompt_async", None)
                    system = (await prompt_async(
                        instruction, sources, attachment_ctx, user_id, template)
                        if callable(prompt_async) else self.service._draft_prompt(
                            instruction, sources, attachment_ctx, user_id, template))
                    parts = []
                    async for delta in assistant.achat_stream(
                        message=instruction, history=[], sources=sources, user_role="user",
                        system_prompt=system, attachment_context=attachment_ctx,
                    ):
                        if delta:
                            parts.append(delta)
                            emit({"text": delta})
                    candidate = self.service._clean_markdown("".join(parts))
                else:
                    candidate = self.service._clean_markdown(await self.service._llm_draft_async(
                        instruction, sources, attachment_ctx, user_id, template=template))
                candidate, _ = await self.service._regenerate_if_needed_async(
                    instruction, sources, attachment_ctx, user_id, template, candidate, ctx)
            if not candidate.strip():
                raise HTTPException(status_code=502, detail="模型未返回内容，请重试")
            return {"candidate": candidate, "sources": _jsonable(sources)}
        return await self._durable("writer", state, work)

    async def _review(self, state: WritingAgentState):
        async def work():
            candidate = str(state.get("candidate") or "")
            ctx = dict(state.get("context") or {})
            quality = self.service._quality_result(
                candidate, topic=str(ctx.get("title") or ctx.get("topic") or ""))
            content_check = ContentChecker().check(
                candidate,
                sources=list(state.get("sources") or []),
                header_docnum=ctx.get("document_number"),
            )

            rule_repo = SqlAlchemyFormatRuleRepository(self.store.db)
            rule_repo.ensure_user_defaults(str(state["user_id"]))
            active_rules = [
                {
                    "target": rule.target,
                    "checks": rule.checks,
                    "severity": rule.severity,
                }
                for rule in rule_repo.list_for_check(str(state["user_id"]), None)
            ]
            rule_issues = FormatCheckEngine(None).check_text_rules(candidate, active_rules)
            mapped_rule_issues = [
                {
                    "source": "user_rule",
                    "severity": "review",
                    "message": str(issue.get("suggestion") or issue.get("expected") or "规则校验未通过"),
                }
                for issue in rule_issues
            ]
            quality["issues"] = [
                *list(quality.get("issues") or []),
                *mapped_rule_issues,
                *list(content_check.get("issues") or []),
            ]
            user_rule_level = "B" if mapped_rule_issues else "A"
            content_level = "B" if content_check.get("issues") else "A"
            quality["level"] = merge_level(
                str(quality.get("level") or "D"), user_rule_level, content_level)
            quality["passed"] = quality["level"] != "D"
            return {
                "quality": quality,
                "content_check": content_check,
                "quality_level": str(quality.get("level") or "D"),
                "quality_issues": list(quality.get("issues") or []),
            }
        return await self._durable("review", state, work)

    def _after_review(self, state: WritingAgentState) -> str:
        if state.get("quality_level") != "D":
            return "finalize"
        if int(state.get("repair_round") or 0) < self.max_repairs:
            return "repair"
        return "reject"

    async def _repair(self, state: WritingAgentState):
        async def work():
            ctx = dict(state.get("context") or {})
            task = self.service._get_owned(str(state["task_id"]), str(state["user_id"]))
            template = self.service._load_template(ctx.get("template_id"))
            attachment_ctx = self.service._attachment_context(task, ctx)
            instruction = self.service._build_draft_instruction(
                ctx, bool(state.get("outline_only")), template)
            round_no = int(state.get("repair_round") or 0) + 1
            prompt = self.service._retry_prompt(
                instruction, str(state.get("candidate") or ""),
                dict(state.get("quality") or {}), round_no)
            candidate = self.service._clean_markdown(await self.service._llm_draft_async(
                prompt, list(state.get("sources") or []), attachment_ctx,
                str(state["user_id"]), template=template))
            if not candidate.strip():
                raise HTTPException(status_code=502, detail="修复智能体未返回内容")
            WRITING_AGENT_REPAIRS.labels("attempted").inc()
            self.run.retry_count = round_no
            self.store.db.commit()
            return {"candidate": candidate, "repair_round": round_no}
        return await self._durable("repair", state, work)

    async def _finalize(self, state: WritingAgentState):
        async def work():
            user_id = str(state["user_id"])
            task = self.service._get_owned(str(state["task_id"]), user_id)
            payload = self.service._finalize_draft(
                task,
                dict(state.get("context") or {}),
                str(state.get("candidate") or ""),
                list(state.get("sources") or []),
                user_id,
                expected_state=(str(state.get("base_content") or ""),
                                int(state.get("base_version") or 0)),
            )
            payload["generation_mode"] = "agent"
            payload["agent_run_id"] = self.run.id
            payload["repair_rounds"] = int(state.get("repair_round") or 0)
            payload["content_check"] = state.get("content_check") or {}
            return {"result": payload}
        return await self._durable("finalize", state, work)

    async def _reject(self, state: WritingAgentState):
        async def work():
            return {"rejected": True}
        return await self._durable("reject", state, work)

    def initial_state(self) -> WritingAgentState:
        state = dict(self.run.state_json or {})
        state.update({
            "run_id": self.run.id,
            "task_id": self.run.task_id,
            "user_id": self.run.user_id,
            "base_version": self.run.base_version,
            "repair_round": int(state.get("repair_round") or 0),
        })
        return state

    async def _claim_or_wait(self) -> dict[str, Any] | None:
        """Claim the run or attach by waiting for the worker that already owns it."""
        if self.store.claim(self.run):
            return None
        deadline = time.monotonic() + settings.WRITING_AGENT_RUN_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            await asyncio.sleep(0.25)
            self.store.db.expire_all()
            self.run = self.store.get_owned(
                self.run.id, self.run.task_id, self.run.user_id)
            if self.run.status == "completed":
                return dict((self.run.state_json or {}).get("result") or {})
            if self.run.status == "interrupted" and self.store.claim(self.run):
                return None
            if self.run.status == "cancelled":
                raise HTTPException(status_code=409, detail="生成已取消")
            if self.run.status == "failed":
                raise HTTPException(
                    status_code=422,
                    detail=self.run.error_message or "智能写作运行失败",
                )
        raise HTTPException(status_code=504, detail="正在运行的写作任务等待超时，可稍后恢复")

    async def execute(self) -> dict[str, Any]:
        if self.run.status == "completed":
            return dict((self.run.state_json or {}).get("result") or {})
        attached_result = await self._claim_or_wait()
        if attached_result is not None:
            return attached_result
        try:
            async with asyncio.timeout(settings.WRITING_AGENT_RUN_TIMEOUT_SECONDS):
                state = await self.graph.ainvoke(self.initial_state())
            if state.get("rejected"):
                message = "生成结果连续修复后仍存在硬伤，未保存该版本。"
                self.store.fail_run(self.run, "WRITING_QUALITY_GATE_D", message, recoverable=False)
                WRITING_AGENT_RUNS.labels("agent", "failed").inc()
                raise HTTPException(status_code=422, detail={
                    "code": "WRITING_QUALITY_GATE_D", "message": message,
                    "issues": state.get("quality_issues") or [],
                    "retry_count": state.get("repair_round") or 0,
                    "run_id": self.run.id,
                })
            result = dict(state.get("result") or {})
            self.store.finish(self.run, result)
            WRITING_AGENT_RUNS.labels("agent", "completed").inc()
            return result
        except asyncio.CancelledError:
            self.store.fail_run(self.run, "CLIENT_DISCONNECTED", "客户端连接中断", recoverable=True)
            WRITING_AGENT_RUNS.labels("agent", "interrupted").inc()
            raise
        except TimeoutError as exc:
            self.store.fail_run(self.run, "RUN_TIMEOUT", "智能写作运行超时，可稍后恢复", recoverable=True)
            WRITING_AGENT_RUNS.labels("agent", "interrupted").inc()
            raise HTTPException(status_code=504, detail="智能写作运行超时，可稍后恢复") from exc
        except HTTPException:
            raise
        except Exception as exc:
            self.store.fail_run(self.run, "AGENT_RUN_FAILED", str(exc), recoverable=True)
            WRITING_AGENT_RUNS.labels("agent", "interrupted").inc()
            raise

    async def stream(self) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        if self.run.status == "completed":
            yield "done", dict((self.run.state_json or {}).get("result") or {})
            return
        yield "stage", {
            "run_id": self.run.id, "key": "planner",
            "label": STAGE_LABELS["planner"], "status": "running", "attempt": 1,
        }
        attached_result = await self._claim_or_wait()
        if attached_result is not None:
            yield "done", attached_result
            return
        aggregate = self.initial_state()
        writer_streamed = False
        try:
            async with asyncio.timeout(settings.WRITING_AGENT_RUN_TIMEOUT_SECONDS):
                async for mode, update in self.graph.astream(
                    aggregate, stream_mode=["updates", "custom"],
                ):
                    if mode == "custom":
                        if isinstance(update, dict) and update.get("text"):
                            writer_streamed = True
                            yield "delta", {"text": update["text"]}
                        elif isinstance(update, dict) and "replace" in update:
                            writer_streamed = True
                            yield "replace", {"text": update["replace"]}
                        continue
                    for node, output in update.items():
                        aggregate.update(output or {})
                        yield "stage", {
                            "run_id": self.run.id, "key": node,
                            "label": STAGE_LABELS.get(node, node), "status": "completed",
                            "attempt": self._attempt(node, aggregate),
                        }
                        next_node = {
                            "planner": "research", "research": "writer",
                            "writer": "review", "repair": "review",
                        }.get(node)
                        if node == "review":
                            next_node = self._after_review(aggregate)
                        if next_node in STAGE_LABELS:
                            yield "stage", {
                                "run_id": self.run.id, "key": next_node,
                                "label": STAGE_LABELS[next_node], "status": "running",
                                "attempt": self._attempt(next_node, aggregate),
                            }
                        if node == "writer" and aggregate.get("candidate") and not writer_streamed:
                            yield "delta", {"text": aggregate["candidate"]}
                        if node == "review":
                            yield "quality", {
                                "run_id": self.run.id,
                                "level": aggregate.get("quality_level"),
                                "issue_count": len(aggregate.get("quality_issues") or []),
                                "repair_round": aggregate.get("repair_round") or 0,
                            }
            if aggregate.get("rejected"):
                message = "生成结果连续修复后仍存在硬伤，未保存该版本。"
                self.store.fail_run(self.run, "WRITING_QUALITY_GATE_D", message, recoverable=False)
                raise HTTPException(status_code=422, detail={
                    "code": "WRITING_QUALITY_GATE_D", "message": message,
                    "issues": aggregate.get("quality_issues") or [],
                    "retry_count": aggregate.get("repair_round") or 0,
                    "run_id": self.run.id,
                })
            result = dict(aggregate.get("result") or {})
            self.store.finish(self.run, result)
            WRITING_AGENT_RUNS.labels("agent", "completed").inc()
            yield "done", result
        except asyncio.CancelledError:
            self.store.fail_run(self.run, "CLIENT_DISCONNECTED", "客户端连接中断", recoverable=True)
            raise
        except TimeoutError as exc:
            self.store.fail_run(self.run, "RUN_TIMEOUT", "智能写作运行超时，可稍后恢复", recoverable=True)
            raise HTTPException(status_code=504, detail="智能写作运行超时，可稍后恢复") from exc
