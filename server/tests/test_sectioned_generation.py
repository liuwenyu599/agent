from app.application.writing.sectioned_generation_service import SectionedGenerationWritingTaskService
from app.application.writing import task_parser
from app.infrastructure.ai.mock import MockLLMGateway
from app.application.writing.quality_gate import QualityGate
from app.application.writing.async_task_service import AsyncWritingTaskService
import asyncio
import threading
import time
from types import SimpleNamespace

import pytest


def test_long_report_uses_sectioned_generation_without_explicit_word_target():
    assert SectionedGenerationWritingTaskService._should_section({
        "document_type": "工作总结", "word_count_target": None,
    }) is True
    assert SectionedGenerationWritingTaskService._should_section({
        "document_type": "通知", "word_count_target": None,
    }) is False
    assert SectionedGenerationWritingTaskService._should_section({
        "document_type": "通知", "word_count_target": 2000,
    }) is False
    assert SectionedGenerationWritingTaskService._should_section({
        "document_type": "新闻稿", "word_count_target": 2000,
    }) is False
    assert SectionedGenerationWritingTaskService._fallback_plan({
        "document_type": "新闻稿", "word_count_target": 2000,
    }) == []
    assert SectionedGenerationWritingTaskService._should_section({
        "document_type": "工作总结", "word_count_target": 3000,
    }, outline_only=True) is False


def test_fallback_plan_is_multi_section_and_budgeted():
    """兜底计划只规定「每节写什么」，不再规定小标题。

    此前 heading 写死「一、基本情况」这类报告骨架，未匹配文种一律落到「报告」，
    导致讲话稿、发言稿等连续行文体例被套上不相称的小标题——这是「讲话稿怎么有
    小标题」的根因。现改为heading 留空，由模型按文种体例自行决定是否设小标题。
    """
    plan = SectionedGenerationWritingTaskService._fallback_plan({
        "document_type": "工作总结", "word_count_target": 2400,
    })
    assert len(plan) == 4
    # heading 统一留空 = 不注入小标题
    assert all(item["heading"] == "" for item in plan)
    # 内容要求（focus）必须保留，否则各节无从区分
    assert all(item["focus"] for item in plan)
    assert all(item["target_chars"] >= 350 for item in plan)
    assert sum(item["target_chars"] for item in plan) == 2400


def test_short_model_plan_cannot_override_requested_length():
    plan = [{"target_chars": 300}] * 4
    assert not SectionedGenerationWritingTaskService._plan_meets_length(plan, 4000)
    assert SectionedGenerationWritingTaskService._plan_meets_length(
        SectionedGenerationWritingTaskService._fallback_plan({
            "document_type": "报告", "word_count_target": 4000,
        }), 4000)
    assert SectionedGenerationWritingTaskService._section_is_short("正文" * 390, 1000)
    assert not SectionedGenerationWritingTaskService._section_is_short("正文" * 410, 1000)


def test_normalize_section_adds_expected_heading_and_stops_next_section_spill():
    raw = "全文标题\n一、基本情况\n第一段。\n第二段。\n二、主要工作\n不应属于本节。"
    result = SectionedGenerationWritingTaskService._normalize_section(raw, "一、基本情况")
    assert result == "一、基本情况\n第一段。\n第二段。"
    assert "二、主要工作" not in result

    missing_heading = SectionedGenerationWritingTaskService._normalize_section(
        "这里是正文第一段。\n这里是正文第二段。", "三、存在问题"
    )
    assert missing_heading.startswith("三、存在问题\n")


def test_section_instruction_reserves_neighbor_content_and_structured_fields():
    ctx = {
        "document_type": "工作总结",
        "topic": "公共法律服务工作",
        "purpose": "年度总结",
        "key_facts": ["开展法律咨询活动", "推进村居法律顾问服务"],
    }
    section = {"heading": "二、主要做法和成效", "focus": "写主要做法", "target_chars": 600}
    text = SectionedGenerationWritingTaskService._section_instruction(
        ctx, section, ["一、基本情况"], ["三、存在问题", "四、下一步工作"]
    )
    assert "只写当前这一节" in text
    assert "前文章节（禁止重复）：一、基本情况" in text
    assert "后续章节（内容留给后文，不要提前展开）：三、存在问题、四、下一步工作" in text
    assert "不得输出全文标题、主送机关、文号" in text


def test_one_sentence_speech_is_not_a_plan_or_a_required_field_form():
    parsed = task_parser.parse_message("给领导写一篇法治宣传活动致辞稿")
    assert parsed["document_type"] == "致辞稿"
    ctx = task_parser.empty_context()
    task_parser.merge_context(ctx, parsed)
    assert "主送对象" not in task_parser.compute_missing(ctx)
    assert "发文机关（落款单位）" not in ctx["missing_fields"]

    plan = SectionedGenerationWritingTaskService._fallback_plan(ctx)
    assert all(not item["heading"] for item in plan)
    assert "欢迎" in plan[0]["focus"]
    assert "祝愿" in plan[-1]["focus"]
    assert not any("实施步骤" in item["focus"] or "保障措施" in item["focus"] for item in plan)


def test_speech_rejects_scheme_shaped_model_plan():
    class Assistant:
        def complete(self, *args, **kwargs):
            return '[{"heading":"一、总体要求","focus":"明确工作目标","target_chars":600},' \
                   '{"heading":"二、实施步骤","focus":"安排各阶段任务","target_chars":600},' \
                   '{"heading":"三、保障措施","focus":"明确责任分工","target_chars":600}]'

    svc = SectionedGenerationWritingTaskService.__new__(SectionedGenerationWritingTaskService)
    svc.assistant = Assistant()
    plan = svc._section_plan({"document_type": "致辞稿", "topic": "法治宣传活动",
                              "word_count_target": 1800})
    assert all(not item["heading"] for item in plan)
    assert "欢迎" in plan[0]["focus"]


def test_mock_sections_follow_distinct_foci_and_pass_repetition_gate():
    ctx = {"document_type": "工作总结", "word_count_target": 2400}
    plan = SectionedGenerationWritingTaskService._fallback_plan(ctx)
    sections = [MockLLMGateway._writing_draft(
        SectionedGenerationWritingTaskService._section_instruction(ctx, item, [], []))
        for item in plan]
    assert len(set(sections)) == len(sections)
    assert QualityGate().evaluate("\n\n".join(sections), body_only=True)["level"] != "D"


def test_explicit_speech_type_overrides_wrong_model_guess_in_planning():
    svc = AsyncWritingTaskService.__new__(AsyncWritingTaskService)
    svc.db = None
    svc.rag = None

    async def wrong_guess(*args, **kwargs):
        return {"document_type": "方案", "topic": "法治宣传活动"}

    svc._interpret_async = wrong_guess
    svc._plan_knowledge = lambda *args, **kwargs: []
    plan = asyncio.run(svc.plan_task_async("u1", "给领导写一篇法治宣传活动致辞稿"))
    assert plan["source"] == "llm"
    assert plan["doc_type"] == "致辞稿"
    assert plan["template_id"] == ""


def test_model_keeps_requested_genre_despite_topic_keyword():
    assert task_parser.explicit_document_type("写一篇方案发布会新闻稿") == "新闻稿"
    svc = AsyncWritingTaskService.__new__(AsyncWritingTaskService)
    svc.db = None
    svc.rag = None

    async def model_plan(*args, **kwargs):
        return {"document_type": "新闻稿", "topic": "方案发布会", "title": "方案发布会举行"}

    svc._interpret_async = model_plan
    svc._plan_knowledge = lambda *args, **kwargs: []
    plan = asyncio.run(svc.plan_task_async("u1", "写一篇方案发布会新闻稿"))
    assert plan["doc_type"] == "新闻稿"
    assert plan["title"] == "方案发布会举行"
    assert plan["planned_context"]["recipient"] is None


def test_plan_fields_expose_word_count_target_from_instruction():
    """用户指令里的「800字」必须进规划字段（卡片可见），否则用户以为字数没生效。"""
    svc = AsyncWritingTaskService.__new__(AsyncWritingTaskService)
    svc.db = None
    svc.rag = None

    async def model_plan(*args, **kwargs):
        return {"document_type": "通知", "topic": "社区矫正教育帮扶工作"}

    svc._interpret_async = model_plan
    svc._plan_knowledge = lambda *args, **kwargs: []
    plan = asyncio.run(svc.plan_task_async(
        "u1",
        "写一份800字的社区矫正教育帮扶工作通知，要求包含标题、主送机关、工作目标、"
        "主要任务（分3条）、工作要求、落款。"))
    assert plan["planned_context"]["word_count_target"] == 800
    assert plan["planned_context"]["planning_completed"] is True
    labels = {f["label"]: f["value"] for f in plan["fields"]}
    assert labels.get("字数目标") == "800"


def test_unlisted_genre_drafting_does_not_inherit_official_document_outline():
    svc = AsyncWritingTaskService.__new__(AsyncWritingTaskService)
    instruction = svc._build_draft_instruction({
        "document_type": "新闻稿", "topic": "方案发布会",
        "history": [{"role": "user", "content": "写一篇方案发布会新闻稿"}],
    }, outline_only=False)
    assert "文种：新闻稿" in instruction
    assert "用户原始需求：写一篇方案发布会新闻稿" in instruction
    assert "正文按事项分条组织" not in instruction
    assert "不套公文层级" in instruction


def test_async_production_planner_keeps_speech_as_continuous_prose():
    class Assistant:
        async def acomplete(self, *args, **kwargs):
            return '[{"heading":"","focus":"欢迎来宾并点明活动","target_chars":600},' \
                   '{"heading":"","focus":"谈活动意义与实际体验","target_chars":600},' \
                   '{"heading":"","focus":"表达期待并致谢","target_chars":600}]'

    svc = AsyncWritingTaskService.__new__(AsyncWritingTaskService)
    svc.assistant = Assistant()
    ctx = {"document_type": "致辞稿", "topic": "法治宣传活动", "word_count_target": 1800}
    plan = asyncio.run(svc._section_plan_async(ctx))
    assert [item["focus"] for item in plan] == [
        "欢迎来宾并点明活动", "谈活动意义与实际体验", "表达期待并致谢"]
    assert all(item["heading"] == "" for item in plan)


def test_async_retrieval_uses_worker_owned_session_without_blocking_loop(monkeypatch):
    from app.application.knowledge.rag_service import RagService
    from app.infrastructure.database import SessionLocal

    main_thread = threading.get_ident()
    outer = SessionLocal()
    seen = []
    def slow_search(worker, **_kwargs):
        seen.append((worker.db is outer, threading.get_ident()))
        time.sleep(0.08)
        return [{"doc_id": "example", "content": "资料"}]
    monkeypatch.setattr(RagService, "search", slow_search)
    service = AsyncWritingTaskService(
        outer, assistant=None,
        rag=SimpleNamespace(embedder=None, vector_store=None), attachments=None)

    async def exercise():
        pending = asyncio.create_task(service._retrieve_async({"topic": "普法"}, "u1"))
        await asyncio.sleep(0.01)
        assert not pending.done()
        await asyncio.sleep(0.01)  # The event loop remains responsive during slow_search.
        return await pending

    try:
        assert asyncio.run(exercise())[0]["doc_id"] == "example"
        assert seen == [(False, seen[0][1])]
        assert seen[0][1] != main_thread
    finally:
        outer.close()


def test_first_section_emits_tokens_before_completion_and_keeps_checked_result(monkeypatch):
    from unittest.mock import AsyncMock

    finish = asyncio.Event()
    first_seen = asyncio.Event()
    emitted = []

    class Assistant:
        async def achat_stream(self, **_kwargs):
            yield "首段正文"
            await finish.wait()
            yield "继续展开。"

    service = AsyncWritingTaskService.__new__(AsyncWritingTaskService)
    service.assistant = None
    service.long_form_assistant = Assistant()
    service._retrieve_async = AsyncMock(return_value=[])
    service._draft_model_system_async = AsyncMock(return_value="写作规则")
    service._section_is_short = lambda *_args: False
    monkeypatch.setattr(QualityGate, "evaluate", lambda *_args, **_kwargs: {"level": "A"})

    def on_delta(delta):
        emitted.append(delta)
        first_seen.set()

    async def exercise():
        pending = asyncio.create_task(service._generate_one_section_stream_async(
            {"document_type": "报告"},
            {"heading": "一、工作成效", "focus": "总结工作", "target_chars": 300},
            0, [{"heading": "一、工作成效", "focus": "总结工作"}],
            "u1", "", None, on_delta=on_delta))
        await asyncio.wait_for(first_seen.wait(), 1)
        assert emitted == ["首段正文"]
        assert not pending.done()
        finish.set()
        return await pending

    final, _ = asyncio.run(exercise())
    assert final.startswith("一、工作成效")
    assert "首段正文继续展开" in final


def test_sectioned_sse_replaces_provisional_first_section_before_done(monkeypatch):
    import json
    from app.application.writing import async_task_service

    monkeypatch.setattr(async_task_service, "graph_enabled_for_user",
                        lambda *_args: False)
    finish = asyncio.Event()
    service = AsyncWritingTaskService.__new__(AsyncWritingTaskService)
    task = SimpleNamespace(current_content="", version_no=0, context={}, session_id="")
    service._get_owned = lambda *_args: task
    service._prepare_agent_graph = lambda *_args: None
    service._load_template = lambda *_args: None
    service._attachment_context = lambda *_args: None
    service._should_section = lambda *_args: True
    async def plan(_ctx):
        return [{"heading": "一、", "focus": "先写"}, {"heading": "二、", "focus": "再写"}]
    async def first(*_args, on_delta):
        on_delta("未校验首段")
        await finish.wait()
        return "通过校验的首段", []
    async def later(*_args):
        return "第二段", []
    service._section_plan_async = plan
    service._generate_one_section_stream_async = first
    service._generate_one_section_async = later
    service._merge_sources = lambda groups: []
    service._finalize_draft = lambda _task, _ctx, content, *_args, **_kwargs: {
        "current_content": content, "reply": "完成"}

    def decode(raw):
        return json.loads(raw.removeprefix("data: ").strip())

    async def collect():
        stream = service.draft_stream_async("task-a", "user-a")
        first_event = decode(await anext(stream))
        assert first_event == {"type": "delta", "text": "未校验首段"}
        finish.set()
        return first_event, [decode(part) async for part in stream]

    first_event, rest = asyncio.run(collect())
    assert [event["type"] for event in rest] == ["replace", "delta", "done"]
    assert rest[0]["text"] == "通过校验的首段"
    assert rest[0]["text"] + rest[1]["text"] == rest[2]["data"]["current_content"]


def test_sectioned_sse_shows_second_section_while_third_is_pending(monkeypatch):
    import json
    from app.application.writing import async_task_service

    monkeypatch.setattr(async_task_service, "graph_enabled_for_user", lambda *_: False)
    monkeypatch.setattr(async_task_service.settings, "WRITING_SECTION_MAX_CONCURRENCY", 1)
    service = AsyncWritingTaskService.__new__(AsyncWritingTaskService)
    task = SimpleNamespace(current_content="", version_no=0, context={}, session_id="")
    service._get_owned = lambda *_: task
    service._prepare_agent_graph = lambda *_: None
    service._load_template = lambda *_: None
    service._attachment_context = lambda *_: None
    service._should_section = lambda *_: True
    async def plan(_ctx):
        return [{"heading": str(i), "focus": str(i)} for i in range(3)]
    async def first(*_args, on_delta):
        on_delta("第一段")
        return "第一段", []
    finish_third = asyncio.Event()
    async def later(_ctx, _section, index, *_args):
        if index == 2:
            await finish_third.wait()
        return f"第{index + 1}段", []
    service._section_plan_async = plan
    service._generate_one_section_stream_async = first
    service._generate_one_section_async = later
    service._merge_sources = lambda _groups: []
    service._finalize_draft = lambda _task, _ctx, content, *_args, **_kwargs: {
        "current_content": content, "reply": "完成"}

    async def exercise():
        stream = service.draft_stream_async("task-a", "user-a")
        first_event = json.loads((await anext(stream))[6:])
        second_event = await asyncio.wait_for(anext(stream), 1)
        assert first_event["text"] == "第一段"
        assert json.loads(second_event[6:])["text"] == "\n\n第2段"
        finish_third.set()
        return [json.loads(event[6:]) async for event in stream]

    rest = asyncio.run(exercise())
    assert rest[-1]["type"] == "done"
    assert rest[-1]["data"]["current_content"] == "第一段\n\n第2段\n\n第3段"


@pytest.mark.parametrize("limit", [1, 2])
def test_section_generation_respects_concurrency_limit_and_order(monkeypatch, limit):
    from app.application.writing.async_task_service import settings
    monkeypatch.setattr(settings, "WRITING_SECTION_MAX_CONCURRENCY", limit)
    service = AsyncWritingTaskService.__new__(AsyncWritingTaskService)
    active = 0
    maximum = 0
    async def generate(_ctx, _section, index, *_args):
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        await asyncio.sleep(0.02 if index == 0 else 0.005)
        active -= 1
        return str(index), []
    service._generate_one_section_async = generate
    result = asyncio.run(service._generate_sections_async(
        {}, [{"heading": str(i)} for i in range(4)], "u", "", None))
    assert [text for text, _sources in result] == ["0", "1", "2", "3"]
    assert maximum == limit
