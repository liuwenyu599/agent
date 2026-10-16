"""Contracts for bounded, durable writing-agent orchestration."""
from __future__ import annotations

import asyncio
import json

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


def test_langgraph_run_persists_once_and_is_idempotent():
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

            def _should_section(self, *_args):
                return False

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
                return "一、工作安排\n围绕群众需求开展法治宣传，明确责任分工。"

            @staticmethod
            def _clean_markdown(value):
                return value

            async def _regenerate_if_needed_async(self, *_args):
                return _args[-2], None

            @staticmethod
            def _quality_result(_candidate, topic=""):
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
            return [event async for event in graph.stream()]

        events = asyncio.run(collect_stream())
        first = next(data for kind, data in events if kind == "done")
        second = asyncio.run(graph.execute())

        assert first == second
        assert first["generation_mode"] == "agent"
        assert any(kind == "stage" and data["key"] == "planner"
                   and data["status"] == "running" for kind, data in events)
        assert any(kind == "delta" and data["text"] for kind, data in events)
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


def test_review_node_applies_the_current_users_active_content_rules():
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

        assert result["quality_level"] == "D"
        assert any(
            issue["source"] == "user_rule" and issue["severity"] == "critical"
            for issue in result["quality_issues"]
        )
    finally:
        db.close()


def test_real_async_writing_service_runs_complex_mock_task_through_graph(monkeypatch):
    from app.application.shared.async_writing_assistant import AsyncWritingAssistant
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
