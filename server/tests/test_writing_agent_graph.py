"""Contracts for bounded, durable writing-agent orchestration."""
from __future__ import annotations

import asyncio
import json
from datetime import timedelta

import pytest

from app.application.writing.agent_graph.persistence import AgentRunStore
from app.application.writing.agent_graph.graph import WritingAgentGraph
from app.application.writing.agent_graph.routing import classify_writing_route
from app.application.writing.agent_graph.tools import (
    BoundedToolExecutor,
    ToolAccessError,
    ToolBudgetExceeded,
    ToolExecutionError,
)


def test_complexity_router_keeps_simple_requests_on_fast_path():
    route = classify_writing_route(
        {"document_type": "通知", "word_count_target": 800, "history": []},
        outline_only=False,
        has_attachments=False,
    )
    assert route == "fast"


def test_template_only_request_keeps_streaming_fast_path():
    assert classify_writing_route({
        "document_type": "通知",
        "word_count_target": 800,
        "template_id": "selected-template",
        "history": [{"role": "user", "content": "写一份800字通知"}],
    }) == "fast"


def test_complexity_router_uses_latest_user_requirement():
    assert classify_writing_route({
        "history": [
            {"role": "user", "content": "请依据法规写一份材料"},
            {"role": "assistant", "content": "已了解"},
            {"role": "user", "content": "不用引用资料，写一份简短通知"},
        ],
        "word_count_target": 600,
    }) == "fast"


@pytest.mark.parametrize("same_request", [True, False])
def test_agent_planner_reuses_ai_plan_only_for_unchanged_request(same_request):
    from types import SimpleNamespace
    from app.application.writing.paragraph_suggestions import content_hash

    request = "写一份志愿服务倡议书"
    calls = []

    async def interpret(*_args, **_kwargs):
        calls.append(request)
        return None

    async def durable(_node, _state, work):
        return await work()

    graph = WritingAgentGraph.__new__(WritingAgentGraph)
    graph.service = SimpleNamespace(
        _interpret_async=interpret,
        _complete_default_authority=lambda _ctx: None,
        _should_section=lambda *_args: False,
    )
    graph._durable = durable
    context = {
        "document_type": "倡议书", "title": "志愿服务倡议书",
        "planning_completed": True,
        "planning_request_hash": content_hash(request if same_request else "另一个旧需求"),
        "history": [{"role": "user", "content": request}],
    }
    output = asyncio.run(graph._planner({"context": context}))
    assert len(calls) == (0 if same_request else 1)
    assert output["context"]["document_type"] == "倡议书"


@pytest.mark.parametrize(
    "context,has_attachments",
    [
        ({"word_count_target": 1800}, False),
        ({"kb_ids": ["kb-1"]}, False),
        ({"history": [{"role": "user", "content": "请依据相关法规和案例起草材料"}]}, False),
        ({}, True),
    ],
)
def test_complexity_router_sends_grounded_or_long_work_to_agent(context, has_attachments):
    assert classify_writing_route(context, False, has_attachments) == "agent"


class _ScriptedToolModel:
    def __init__(self, responses):
        self.responses = list(responses)
        self.messages = []

    async def acomplete_with_tools(self, messages, **_kwargs):
        self.messages.append(messages)
        return self.responses.pop(0)


def _tool_call(call_id: str, name: str, arguments: dict):
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments, ensure_ascii=False)},
    }


def test_bounded_tool_executor_supports_multiple_rounds_and_deduplicates_calls():
    model = _ScriptedToolModel([
        {"role": "assistant", "content": "", "tool_calls": [
            _tool_call("c1", "search_knowledge", {"query": "行政复议"}),
        ]},
        {"role": "assistant", "content": "", "tool_calls": [
            _tool_call("c2", "search_knowledge", {"query": "行政复议"}),
        ]},
        {"role": "assistant", "content": "资料已足够", "tool_calls": []},
    ])
    calls = []

    async def search_knowledge(args):
        calls.append(args)
        return [{"doc_id": "d1", "title": "行政复议规范"}]

    executor = BoundedToolExecutor(
        model=model,
        tools={"search_knowledge": search_knowledge},
        schemas=[{"type": "function", "function": {"name": "search_knowledge"}}],
        max_rounds=4,
    )
    result = asyncio.run(executor.run([{"role": "user", "content": "检索资料"}]))

    assert result.content == "资料已足够"
    assert len(calls) == 1
    assert [item.cached for item in result.calls] == [False, True]


def test_bounded_tool_executor_rejects_unlisted_tools():
    model = _ScriptedToolModel([
        {"role": "assistant", "content": "", "tool_calls": [
            _tool_call("c1", "read_other_users_data", {}),
        ]},
    ])
    executor = BoundedToolExecutor(model=model, tools={}, schemas=[], max_rounds=2)
    with pytest.raises(ToolAccessError):
        asyncio.run(executor.run([{"role": "user", "content": "开始"}]))


def test_bounded_tool_executor_rejects_malformed_arguments():
    model = _ScriptedToolModel([{
        "role": "assistant",
        "content": "",
        "tool_calls": [{
            "id": "c1",
            "type": "function",
            "function": {"name": "search_knowledge", "arguments": "{bad-json"},
        }],
    }])
    executor = BoundedToolExecutor(
        model=model,
        tools={"search_knowledge": lambda _args: []},
        schemas=[{"type": "function", "function": {"name": "search_knowledge"}}],
        max_rounds=2,
    )

    with pytest.raises(ToolExecutionError, match="参数不是有效 JSON"):
        asyncio.run(executor.run([{"role": "user", "content": "开始"}]))


def test_bounded_tool_executor_stops_at_round_budget():
    model = _ScriptedToolModel([
        {"role": "assistant", "content": "", "tool_calls": [
            _tool_call("c1", "search_knowledge", {"query": "一"}),
        ]},
        {"role": "assistant", "content": "", "tool_calls": [
            _tool_call("c2", "search_knowledge", {"query": "二"}),
        ]},
    ])

    async def search_knowledge(_args):
        return []

    executor = BoundedToolExecutor(
        model=model,
        tools={"search_knowledge": search_knowledge},
        schemas=[{"type": "function", "function": {"name": "search_knowledge"}}],
        max_rounds=1,
    )
    with pytest.raises(ToolBudgetExceeded):
        asyncio.run(executor.run([{"role": "user", "content": "开始"}]))


def test_bounded_tool_executor_allows_final_answer_after_last_tool_round():
    model = _ScriptedToolModel([
        {"role": "assistant", "content": "", "tool_calls": [
            _tool_call("c1", "search_knowledge", {"query": "行政复议"}),
        ]},
        {"role": "assistant", "content": "检索完成", "tool_calls": []},
    ])
    executor = BoundedToolExecutor(
        model=model,
        tools={"search_knowledge": lambda _args: []},
        schemas=[{"type": "function", "function": {"name": "search_knowledge"}}],
        max_rounds=1,
    )

    result = asyncio.run(executor.run([{"role": "user", "content": "开始"}]))

    assert result.content == "检索完成"
    assert len(result.calls) == 1


def test_agent_run_store_reuses_one_active_run_and_persists_steps():
    from app.infrastructure.database import Base, SessionLocal, engine
    from app.infrastructure.database.models.identity import UserModel
    from app.infrastructure.database.models.writing_task import WritingTaskModel
    from sqlalchemy import select

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        user = db.scalars(select(UserModel)).first()
        assert user is not None
        task = WritingTaskModel(user_id=user.id, context={}, current_content="", version_no=0)
        db.add(task)
        db.commit()
        db.refresh(task)
        store = AgentRunStore(db)
        first, created = store.get_or_create(
            task_id=task.id,
            user_id=user.id,
            route="agent",
            base_version=0,
            base_content="",
            initial_state={"task_id": task.id, "user_id": user.id},
        )
        second, created_again = store.get_or_create(
            task_id=task.id,
            user_id=user.id,
            route="agent",
            base_version=0,
            base_content="",
            initial_state={"task_id": task.id, "user_id": user.id},
        )
        assert created is True
        assert created_again is False
        assert second.id == first.id

        store.start(first)
        store.complete_step(first, "planner", 1, {"section_plan": []}, 0.02)
        db.expire_all()
        loaded = store.get_owned(first.id, task.id, user.id)
        assert loaded.status == "running"
        assert loaded.current_node == "planner"
        assert loaded.state_json["section_plan"] == []
        assert store.completed_step(loaded.id, "planner", 1).output_json == {
            "section_plan": []
        }
        summary = AgentRunStore._summary({
            "context": {"history": [{"content": "不应进入审计摘要的原始需求"}]},
            "candidate": "不应进入审计摘要的正文",
        })
        assert "原始需求" not in summary
        assert "正文" not in summary
    finally:
        db.close()


def test_agent_run_store_reclaims_only_after_run_and_model_timeouts(monkeypatch):
    from app.core.config import settings
    from app.core.timeutil import now_local
    from app.infrastructure.database import Base, SessionLocal, engine
    from app.infrastructure.database.models.identity import UserModel
    from app.infrastructure.database.models.writing_task import WritingTaskModel
    from sqlalchemy import select

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        user = db.scalars(select(UserModel)).first()
        assert user is not None
        monkeypatch.setattr(settings, "WRITING_AGENT_RUN_TIMEOUT_SECONDS", 30)
        monkeypatch.setattr(settings, "MODEL_TIMEOUT", 20)
        task = WritingTaskModel(user_id=user.id, context={}, current_content="", version_no=0)
        db.add(task)
        db.commit()
        db.refresh(task)
        store = AgentRunStore(db)
        run, _ = store.get_or_create(
            task_id=task.id,
            user_id=user.id,
            route="agent",
            base_version=0,
            base_content="",
            initial_state={"task_id": task.id, "user_id": user.id},
        )
        store.start(run)
        run.updated_at = now_local() - timedelta(seconds=31)
        db.commit()

        assert store.claim(run) is False
        db.refresh(run)
        assert run.status == "running"

        run.updated_at = now_local() - timedelta(seconds=51)
        db.commit()
        assert store.claim(run) is True
        db.refresh(run)
        assert run.status == "running"
        assert run.error_code is None

        reused, created = store.get_or_create(
            task_id=task.id,
            user_id=user.id,
            route="agent",
            base_version=0,
            base_content="",
            initial_state={"task_id": task.id, "user_id": user.id},
        )
        assert created is False
        assert reused.id == run.id
    finally:
        db.close()


def test_planner_enriches_a_fuzzy_request_without_a_closed_genre_list():
    from app.infrastructure.database import Base, SessionLocal, engine
    from app.infrastructure.database.models.identity import UserModel
    from app.infrastructure.database.models.writing_task import WritingTaskModel
    from sqlalchemy import select

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        user = db.scalars(select(UserModel)).first()
        assert user is not None
        context = {
            "history": [{"role": "user", "content": "给明天活动写个开场暖场词"}],
            "missing_fields": [],
        }
        task = WritingTaskModel(user_id=user.id, context=context, current_content="", version_no=0)
        db.add(task)
        db.commit()
        db.refresh(task)

        class FakeService:
            async def _interpret_async(self, *_args, **_kwargs):
                return {
                    "document_type": "活动开场暖场词",
                    "title": "法治宣传活动开场暖场词",
                    "recipient": "参加活动的干部群众",
                    "authority": "白云区司法局",
                }

            @staticmethod
            def _merge_interpretation(ctx, interpreted):
                ctx.update(interpreted)

            @staticmethod
            def _complete_default_authority(_ctx):
                return None

            @staticmethod
            def _should_section(*_args):
                return False

        store = AgentRunStore(db)
        state = {
            "task_id": task.id,
            "user_id": user.id,
            "context": context,
            "base_version": 0,
            "base_content": "",
            "repair_round": 0,
        }
        run, _ = store.get_or_create(
            task_id=task.id,
            user_id=user.id,
            route="agent",
            base_version=0,
            base_content="",
            initial_state=state,
        )

        result = asyncio.run(WritingAgentGraph(FakeService(), store, run)._planner(state))

        assert result["context"]["document_type"] == "活动开场暖场词"
        assert result["context"]["title"] == "法治宣传活动开场暖场词"
        assert result["context"]["recipient"] == "参加活动的干部群众"
        assert result["context"]["authority"] == "白云区司法局"
    finally:
        db.close()


def test_research_uses_the_latest_user_request():
    from app.infrastructure.database import Base, SessionLocal, engine
    from app.infrastructure.database.models.identity import UserModel
    from app.infrastructure.database.models.writing_task import WritingTaskModel
    from sqlalchemy import select

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        user = db.scalars(select(UserModel)).first()
        assert user is not None
        context = {
            "document_type": "讲话稿",
            "history": [
                {"role": "user", "content": "先写一份旧主题材料"},
                {"role": "assistant", "content": "好的"},
                {"role": "user", "content": "改为依据现行普法政策，面向社区群众写法治宣传讲话稿"},
            ],
        }
        task = WritingTaskModel(user_id=user.id, context=context, current_content="", version_no=0)
        db.add(task)
        db.commit()
        db.refresh(task)
        model = _ScriptedToolModel([
            {"role": "assistant", "content": "资料足够", "tool_calls": []},
        ])

        class FakeService:
            assistant = model

            @staticmethod
            def _retrieve(*_args, **_kwargs):
                return []

        state = {
            "task_id": task.id,
            "user_id": user.id,
            "context": context,
            "repair_round": 0,
        }
        store = AgentRunStore(db)
        run, _ = store.get_or_create(
            task_id=task.id,
            user_id=user.id,
            route="agent",
            base_version=0,
            base_content="",
            initial_state=state,
        )

        asyncio.run(WritingAgentGraph(FakeService(), store, run)._research(state))

        request = json.loads(model.messages[0][1]["content"])["原始需求"]
        assert request == context["history"][-1]["content"]
    finally:
        db.close()


@pytest.mark.parametrize("use_streaming", [False, True])
@pytest.mark.parametrize("entry,mode", [
    ("stream", "tokens"), ("stream", "sections"), ("stream", "repair"),
    ("execute", "tokens"), ("execute", "sections"),
])
def test_langgraph_run_persists_once_and_is_idempotent(use_streaming, entry, mode):
    from app.infrastructure.database import Base, SessionLocal, engine
    from app.infrastructure.database.models.identity import UserModel
    from app.infrastructure.database.models.writing_task import WritingTaskModel
    from sqlalchemy import select

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        user = db.scalars(select(UserModel)).first()
        assert user is not None
        task = WritingTaskModel(
            user_id=user.id,
            context={"document_type": "通知", "title": "关于开展法治宣传的通知"},
            current_content="",
            version_no=0,
        )
        db.add(task)
        db.commit()
        db.refresh(task)

        class FakeService:
            assistant = None

            def __init__(self):
                self.finalize_calls = 0
                self.saw_first_delta = False
                self.writer_calls = 0
                self.model_calls = 0
                self.reviews = 0

            @property
            def _draft_assistant(self):
                return self if use_streaming else None

            def _draft_prompt(self, *_args):
                return "起草通知"

            async def achat_stream(self, **_kwargs):
                self.writer_calls += 1
                yield "一、工作安排\n"
                # 后半稿仍在生成时，客户端已经应当收到第一批文字。
                await asyncio.sleep(0.05)
                if entry == "stream":
                    assert self.saw_first_delta
                yield "围绕群众需求开展法治宣传，明确责任分工。"

            def _should_section(self, *_args):
                return mode == "sections"

            async def _section_plan_async(self, _ctx):
                return [{"heading": "安排"}, {"heading": "要求"}]

            async def _generate_one_section_async(self, _ctx, _section, index, *_args):
                self.writer_calls += 1
                return f"  第{index + 1}节内容。\n", []

            async def _generate_one_section_stream_async(self, _ctx, _section,
                                                          index, *_args, on_delta):
                self.writer_calls += 1
                on_delta("  第1节内容。\n")
                await asyncio.sleep(0.02)
                return "第1节内容。", []

            async def _interpret_async(self, *_args, **_kwargs):
                return None

            @staticmethod
            def _complete_default_authority(_ctx):
                return None

            def _retrieve(self, *_args, **_kwargs):
                return [{"doc_id": "d1", "content": "法治宣传应贴近群众需求。"}]

            def _get_owned(self, task_id, _user_id):
                return db.get(WritingTaskModel, task_id)

            def _load_template(self, _template_id):
                return None

            def _attachment_context(self, *_args):
                return None

            def _build_draft_instruction(self, *_args):
                return "起草通知"

            async def _llm_draft_async(self, *_args, **_kwargs):
                self.model_calls += 1
                if mode == "repair" and (use_streaming or self.model_calls > 1):
                    return "修复稿：围绕群众需求开展法治宣传，明确责任分工。"
                return "一、工作安排\n围绕群众需求开展法治宣传，明确责任分工。"

            def _retry_prompt(self, *_args):
                return "只修复本轮质量问题"

            @staticmethod
            def _clean_markdown(value):
                return value

            async def _regenerate_if_needed_async(self, *_args):
                return _args[-2], None

            def _quality_result(self, _candidate, topic=""):
                self.reviews += 1
                if mode == "repair" and self.reviews <= 2:
                    return {"level": "D", "issues": []}
                return {"level": "A", "issues": []}

            def _finalize_draft(self, row, _ctx, text, _sources, _user_id,
                                expected_state=None):
                assert expected_state == ("", 0)
                self.finalize_calls += 1
                row.current_content = text
                row.version_no = 1
                db.commit()
                return {"task_id": row.id, "current_content": text, "version_no": 1}

        store = AgentRunStore(db)
        initial = {
            "task_id": task.id, "user_id": user.id, "context": task.context,
            "outline_only": False, "base_version": 0, "base_content": "",
            "repair_round": 0,
        }
        run, _ = store.get_or_create(
            task_id=task.id, user_id=user.id, route="agent",
            base_version=0, base_content="", initial_state=initial,
        )
        service = FakeService()
        graph = WritingAgentGraph(service, store, run)
        async def collect_stream():
            collected = []
            async for event in graph.stream():
                if event[0] == "delta":
                    service.saw_first_delta = True
                collected.append(event)
            return collected

        events = asyncio.run(collect_stream()) if entry == "stream" else []
        first = (next(data for kind, data in events if kind == "done")
                 if entry == "stream" else asyncio.run(graph.execute()))
        second = asyncio.run(graph.execute())

        assert first == second
        assert first["generation_mode"] == "agent"
        if entry == "stream":
            assert any(kind == "stage" and data["key"] == "planner"
                       and data["status"] == "running" for kind, data in events)
            deltas = "".join(data["text"] for kind, data in events if kind == "delta")
            assert deltas
            visible = ""
            for kind, data in events:
                if kind == "delta":
                    visible += data["text"]
                elif kind == "replace":
                    visible = data["text"]
            if mode == "repair":
                assert first["repair_rounds"] == 2
                assert first["current_content"].startswith("修复稿：")
                assert deltas == "一、工作安排\n围绕群众需求开展法治宣传，明确责任分工。"
                assert service.writer_calls == (1 if use_streaming else 0)
            elif mode == "sections":
                assert any(kind == "replace" for kind, _data in events)
                assert visible == first["current_content"]
            else:
                assert deltas == first["current_content"]
            assert any(kind == "quality" and data["level"] == "A" for kind, data in events)
        assert service.finalize_calls == 1
        assert store.get_owned(run.id, task.id, user.id).status == "completed"
    finally:
        db.close()


def test_production_service_admits_only_complex_tasks_when_flagged(monkeypatch):
    from app.application.writing.async_task_service import AsyncWritingTaskService
    from app.core.config import settings
    from app.infrastructure.database import Base, SessionLocal, engine
    from app.infrastructure.database.models.identity import UserModel
    from app.infrastructure.database.models.writing_task import WritingTaskModel
    from sqlalchemy import select

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        user = db.scalars(select(UserModel)).first()
        assert user is not None
        monkeypatch.setattr(settings, "WRITING_AGENT_GRAPH_ENABLED", True)
        monkeypatch.setattr(settings, "WRITING_AGENT_ROLLOUT_PERCENT", 100)
        monkeypatch.setattr(settings, "WRITING_AGENT_GRAPH_COMPLEX_ONLY", True)
        service = AsyncWritingTaskService.__new__(AsyncWritingTaskService)
        service.db = db
        service.attachments = None

        simple = WritingTaskModel(
            user_id=user.id, context={"word_count_target": 800}, current_content="", version_no=0)
        complex_task = WritingTaskModel(
            user_id=user.id, context={"word_count_target": 1800}, current_content="", version_no=0)
        db.add_all([simple, complex_task])
        db.commit()

        assert service._prepare_agent_graph(simple, user.id, False) is None
        graph = service._prepare_agent_graph(complex_task, user.id, False)
        assert isinstance(graph, WritingAgentGraph)
        assert graph.run.route == "agent"
    finally:
        db.close()


def test_review_node_keeps_user_content_rules_advisory():
    from app.infrastructure.database import Base, SessionLocal, engine
    from app.infrastructure.database.models.format_check import FormatRuleModel
    from app.infrastructure.database.models.identity import UserModel
    from app.infrastructure.database.models.writing_task import WritingTaskModel
    from sqlalchemy import select

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        user = db.scalars(select(UserModel)).first()
        assert user is not None
        task = WritingTaskModel(user_id=user.id, context={}, current_content="", version_no=0)
        db.add_all([task, FormatRuleModel(
            name="个人禁用表达",
            target="content",
            checks={"forbidden_words": ["测试禁用词"]},
            severity="error",
            is_active=True,
            is_default=False,
            ruleset="custom",
            created_by=user.id,
        )])
        db.commit()
        db.refresh(task)

        class FakeService:
            @staticmethod
            def _quality_result(_candidate, topic=""):
                return {"level": "A", "passed": True, "issues": []}

        store = AgentRunStore(db)
        state = {
            "task_id": task.id,
            "user_id": user.id,
            "context": {},
            "candidate": "这是一段包含测试禁用词的正文。",
            "sources": [],
            "repair_round": 0,
        }
        run, _ = store.get_or_create(
            task_id=task.id,
            user_id=user.id,
            route="agent",
            base_version=0,
            base_content="",
            initial_state=state,
        )

        result = asyncio.run(WritingAgentGraph(FakeService(), store, run)._review(state))

        assert result["quality_level"] == "B"
        assert any(
            issue["source"] == "user_rule" and issue["severity"] == "review"
            for issue in result["quality_issues"]
        )
    finally:
        db.close()


def test_real_async_writing_service_runs_complex_mock_task_through_graph(monkeypatch):
    from app.application.shared.async_writing_assistant import AsyncWritingAssistant
    from app.application.writing import prompt_snapshot
    from app.application.writing.async_task_service import AsyncWritingTaskService
    from app.core.config import settings
    from app.infrastructure.ai.mock import MockLLMGateway
    from app.infrastructure.database import Base, SessionLocal, engine
    from app.infrastructure.database.models.identity import UserModel
    from app.infrastructure.database.models.writing_task import WritingTaskModel
    from sqlalchemy import select

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        user = db.scalars(select(UserModel)).first()
        assert user is not None
        monkeypatch.setattr(settings, "WRITING_AGENT_GRAPH_ENABLED", True)
        monkeypatch.setattr(settings, "WRITING_AGENT_ROLLOUT_PERCENT", 100)
        monkeypatch.setattr(settings, "WRITING_AGENT_GRAPH_COMPLEX_ONLY", True)
        entered_tasks = []
        real_enter_task = prompt_snapshot.enter_task

        def capture_enter_task(task_id, user_id, session_id=""):
            entered_tasks.append((task_id, user_id, session_id))
            return real_enter_task(task_id, user_id, session_id=session_id)

        monkeypatch.setattr(prompt_snapshot, "enter_task", capture_enter_task)
        task = WritingTaskModel(
            user_id=user.id,
            context={
                "document_type": "工作总结",
                "title": "法治宣传工作总结",
                "topic": "法治宣传",
                "word_count_target": 1800,
                "history": [{"role": "user", "content": "写一篇法治宣传工作总结，约1800字"}],
            },
            current_content="",
            version_no=0,
        )
        db.add(task)
        db.commit()
        db.refresh(task)
        service = AsyncWritingTaskService(
            db, assistant=AsyncWritingAssistant(MockLLMGateway()), rag=None, attachments=None)

        result = asyncio.run(service.draft_async(task.id, user.id))

        assert result["generation_mode"] == "agent"
        assert result["agent_run_id"]
        assert result["version_no"] == 1
        assert result["current_content"]
        assert entered_tasks[0][:2] == (task.id, user.id)
        assert db.get(WritingTaskModel, task.id).current_content == result["current_content"]
        resumed = asyncio.run(service.resume_agent_run_async(
            task.id, user.id, result["agent_run_id"]))
        assert resumed["data"] == result
        assert db.get(WritingTaskModel, task.id).version_no == 1
    finally:
        db.close()


def test_agent_quality_failure_never_saves_document(monkeypatch):
    from fastapi import HTTPException
    from app.application.shared.async_writing_assistant import AsyncWritingAssistant
    from app.application.writing.async_task_service import AsyncWritingTaskService
    from app.core.config import settings
    from app.infrastructure.ai.mock import MockLLMGateway
    from app.infrastructure.database import Base, SessionLocal, engine
    from app.infrastructure.database.models.identity import UserModel
    from app.infrastructure.database.models.writing_agent import WritingAgentRunModel
    from app.infrastructure.database.models.writing_task import WritingTaskModel
    from sqlalchemy import select

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        user = db.scalars(select(UserModel)).first()
        assert user is not None
        monkeypatch.setattr(settings, "WRITING_AGENT_GRAPH_ENABLED", True)
        monkeypatch.setattr(settings, "WRITING_AGENT_ROLLOUT_PERCENT", 100)
        monkeypatch.setattr(settings, "WRITING_AGENT_GRAPH_COMPLEX_ONLY", True)
        task = WritingTaskModel(
            user_id=user.id,
            context={
                "document_type": "通知", "title": "测试通知", "topic": "测试",
                "word_count_target": 800, "kb_ids": ["kb-1"],
                "history": [{"role": "user", "content": "依据知识库写一份通知"}],
            },
            current_content="",
            version_no=0,
        )
        db.add(task)
        db.commit()
        db.refresh(task)
        service = AsyncWritingTaskService(
            db, assistant=AsyncWritingAssistant(MockLLMGateway()), rag=None, attachments=None)
        monkeypatch.setattr(service, "_quality_result", lambda *_args, **_kwargs: {
            "level": "D",
            "issues": [{"severity": "critical", "message": "机械重复：测试硬伤"}],
        })

        with pytest.raises(HTTPException) as error:
            asyncio.run(service.draft_async(task.id, user.id))

        assert error.value.status_code == 422
        db.expire_all()
        saved = db.get(WritingTaskModel, task.id)
        assert saved.version_no == 0
        assert saved.current_content == ""
        run = db.scalars(select(WritingAgentRunModel).where(
            WritingAgentRunModel.task_id == task.id)).first()
        assert run.status == "failed"
        assert run.retry_count == 2
    finally:
        db.close()
