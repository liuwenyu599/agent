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
    assert "不得输出全文标题、文号" in text
    assert "主送机关行只允许出现在全文最开头" in text


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
        async def acomplete(self, *args, **kwargs):
            return '[{"heading":"一、总体要求","focus":"明确工作目标","target_chars":600},' \
                   '{"heading":"二、实施步骤","focus":"安排各阶段任务","target_chars":600},' \
                   '{"heading":"三、保障措施","focus":"明确责任分工","target_chars":600}]'

    svc = AsyncWritingTaskService.__new__(AsyncWritingTaskService)
    svc.assistant = Assistant()
    plan = asyncio.run(svc._section_plan_async(
        {"document_type": "致辞稿", "topic": "法治宣传活动", "word_count_target": 1800}))
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


def test_model_guessed_signoff_date_is_not_used_in_planning():
    svc = AsyncWritingTaskService.__new__(AsyncWritingTaskService)
    svc.db = None
    svc.rag = None

    async def guessed_date(*args, **kwargs):
        return {"document_type": "通知", "topic": "召开工作会议",
                "document_date": "2026年10月26日"}

    svc._interpret_async = guessed_date
    svc._plan_knowledge = lambda *args, **kwargs: []
    plan = asyncio.run(svc.plan_task_async("u1", "写一份召开工作会议的通知"))
    assert plan["planned_context"]["document_date"] is None


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


def test_short_speech_streams_without_a_second_model_plan():
    import json
    from unittest.mock import AsyncMock

    class Assistant:
        async def achat_stream(self, **_kwargs):
            yield "各位来宾，"
            yield "欢迎参加法治宣传活动。"

    service = AsyncWritingTaskService.__new__(AsyncWritingTaskService)
    service.assistant = Assistant()
    service.long_form_assistant = None
    task = SimpleNamespace(current_content="", version_no=0, session_id="", context={
        "document_type": "致辞稿", "word_count_target": 800,
        "topic": "法治宣传活动", "history": [{"role": "user", "content": "写一篇800字致辞稿"}],
    })
    service._get_owned = lambda *_: task
    service._prepare_agent_graph = lambda *_: None
    service._load_template = lambda *_: None
    service._attachment_context = lambda *_: None
    service._section_plan_async = AsyncMock(side_effect=AssertionError("短稿不应另做章节规划"))
    service._retrieve_async = AsyncMock(return_value=[])
    service._draft_prompt_async = AsyncMock(return_value="写作规则")
    service._regenerate_if_needed_async = AsyncMock(side_effect=lambda *_args: (_args[-2], None))
    service._finalize_draft = lambda _task, _ctx, content, *_args, **_kwargs: {
        "current_content": content, "reply": "完成"}

    async def collect():
        return [json.loads(event[6:]) async for event in
                service.draft_stream_async("task-a", "user-a")]

    events = asyncio.run(collect())
    assert [event["type"] for event in events] == ["stage", "stage", "delta", "delta", "done"]
    assert events[2]["text"] == "各位来宾，"
    assert "致辞" in service._build_draft_instruction(task.context, False, None)
    service._section_plan_async.assert_not_awaited()


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


def test_slow_writing_rag_returns_empty_sources_without_delaying_model(monkeypatch):
    from app.application.knowledge.rag_service import RagService
    from app.application.writing import async_task_service as module
    from app.core.config import settings
    from app.infrastructure.database import SessionLocal

    monkeypatch.setattr(module, "_rag_degraded_until", 0.0)
    monkeypatch.setattr(settings, "WRITING_RAG_SOFT_TIMEOUT_SECONDS", 0.03)
    calls = []

    def search(worker, **_kwargs):
        calls.append((worker.fast_mode, threading.get_ident()))
        if not worker.fast_mode:
            time.sleep(0.12)
        return [{"doc_id": "allowed", "content": "资料"}]

    monkeypatch.setattr(RagService, "search", search)
    outer = SessionLocal()
    service = AsyncWritingTaskService(
        outer, assistant=None,
        rag=SimpleNamespace(embedder=None, vector_store=None), attachments=None)
    try:
        async def exercise():
            started = time.perf_counter()
            result = await service._retrieve_async({"topic": "普法"}, "u1")
            return result, time.perf_counter() - started

        result, elapsed = asyncio.run(exercise())
        assert result == []
        assert elapsed < 0.11
        assert calls == [(False, calls[0][1])]
        assert not module._rag_degraded()
    finally:
        outer.close()
        monkeypatch.setattr(module, "_rag_degraded_until", 0.0)


def test_rag_circuit_opens_after_three_failures_and_short_circuits(monkeypatch):
    from app.application.knowledge.rag_service import RagService
    from app.application.writing import async_task_service as module
    from app.core.config import settings
    from app.infrastructure.database import SessionLocal

    monkeypatch.setattr(module, "_rag_degraded_until", 0.0)
    monkeypatch.setattr(module, "_rag_failure_count", 0)
    monkeypatch.setattr(settings, "WRITING_RAG_SOFT_TIMEOUT_SECONDS", 0.2)
    calls = []
    def failed_search(worker, **_kwargs):
        calls.append(worker.fast_mode)
        raise RuntimeError("embedding unavailable")
    monkeypatch.setattr(RagService, "search", failed_search)
    outer = SessionLocal()
    service = AsyncWritingTaskService(
        outer, assistant=None,
        rag=SimpleNamespace(embedder=None, vector_store=None), attachments=None)
    try:
        async def exercise():
            return [await service._retrieve_async({"topic": "普法"}, "u1")
                    for _ in range(4)]
        assert asyncio.run(exercise()) == [[], [], [], []]
        assert calls == [False, False, False]
        assert module._rag_degraded()
    finally:
        outer.close()
        monkeypatch.setattr(module, "_rag_degraded_until", 0.0)
        monkeypatch.setattr(module, "_rag_failure_count", 0)


def test_prompt_rag_timeout_keeps_base_rules_and_template(monkeypatch):
    from app.application.writing import async_task_service as module
    from app.core.config import settings
    from app.infrastructure.database import SessionLocal

    monkeypatch.setattr(module, "_rag_degraded_until", 0.0)
    monkeypatch.setattr(module, "_rag_failure_count", 0)
    monkeypatch.setattr(settings, "WRITING_RAG_SOFT_TIMEOUT_SECONDS", 0.03)

    def slow_style(worker, *_args, **_kwargs):
        time.sleep(0.12)
        return "迟到的范文"

    monkeypatch.setattr(AsyncWritingTaskService, "_example_style_block", slow_style)
    monkeypatch.setattr(AsyncWritingTaskService, "_draft_system",
                        lambda _self, _user, template=None:
                        "基础写作规则；" + str((template or {}).get("name") or ""))
    monkeypatch.setattr(AsyncWritingTaskService, "_accepted_style_memory",
                        lambda *_args: "已采纳风格")
    received = {}
    class Assistant:
        async def achat(self, **kwargs):
            received.update(kwargs)
            return "通知正文"

    outer = SessionLocal()
    service = AsyncWritingTaskService(
        outer, assistant=Assistant(),
        rag=SimpleNamespace(embedder=None, vector_store=None), attachments=None)
    # Production may route long drafts through a separate gateway. Keep this
    # unit test on its controllable assistant so it never calls the live model.
    service.long_form_assistant = Assistant()
    try:
        assert asyncio.run(service._llm_draft_async(
            "写通知", [], None, "u1", {"name": "通知模板"}))
        system = received["system_prompt"]
        assert "基础写作规则" in system
        assert "通知模板" in system
        assert "已采纳风格" in system
        assert "迟到的范文" not in system
        assert received["message"] == "写通知"
        assert service._rag_degraded_this_run
    finally:
        outer.close()
        monkeypatch.setattr(module, "_rag_degraded_until", 0.0)
        monkeypatch.setattr(module, "_rag_failure_count", 0)


def test_draft_prompt_reuses_style_and_memory_across_sections(monkeypatch):
    from app.infrastructure.database import SessionLocal
    from app.application.writing import async_task_service as module

    calls = {"style": 0, "memory": 0}
    queries = []
    def style(_worker, _query, _user):
        calls["style"] += 1
        queries.append(_query)
        return "同文种范文"
    def memory(_worker, _user, _doc_type):
        calls["memory"] += 1
        return "采纳习惯"
    monkeypatch.setattr(AsyncWritingTaskService, "_example_style_block", style)
    monkeypatch.setattr(AsyncWritingTaskService, "_accepted_style_memory", memory)
    monkeypatch.setattr(AsyncWritingTaskService, "_draft_system",
                        lambda *_args, **_kwargs: "完整基础规则")
    monkeypatch.setattr(module.prompt_snapshot, "current_task", lambda: "same-task")
    outer = SessionLocal()
    monkeypatch.setattr(outer, "get", lambda *_args: SimpleNamespace(
        user_id="u1", current_content="", context={
            "document_type": "讲话稿", "topic": "法治宣传", "recipient": "基层干部",
            "history": [
                {"role": "user", "content": "写一篇讲话稿"},
                {"role": "user", "content": "重点讲基层普法"},
            ],
        }))
    service = AsyncWritingTaskService(
        outer, assistant=None,
        rag=SimpleNamespace(embedder=None, vector_store=None), attachments=None)
    try:
        async def exercise():
            return [await service._draft_prompt_async(
                f"讲话稿第 {index} 节", [], None, "u1") for index in (1, 2, 3)]
        systems = asyncio.run(exercise())
        assert all("完整基础规则" in item and "同文种范文" in item
                   and "采纳习惯" in item for item in systems)
        assert calls == {"style": 1, "memory": 1}
        assert "文种：讲话稿" in queries[0]
        assert "主题：法治宣传" in queries[0]
        assert "对象：基层干部" in queries[0]
        assert "重点讲基层普法" in queries[0]
    finally:
        outer.close()


def test_retrieval_degradation_is_visible_in_final_result(monkeypatch):
    from app.application.writing.task_service import WritingTaskService

    monkeypatch.setattr(WritingTaskService, "_finalize_draft",
                        lambda *_args, **_kwargs: {"reply": "生成完成", "current_content": "正文"})
    service = AsyncWritingTaskService.__new__(AsyncWritingTaskService)
    service._rag_degraded_this_run = True
    task = SimpleNamespace(current_content="", id="task-a")
    result = service._finalize_draft(task, {}, "正文", [], "u1")
    assert "未取得部分参考资料" in result["retrieval_warning"]
    assert result["retrieval_warning"] in result["reply"]


def test_fast_rag_skips_embedding_and_reranking(monkeypatch):
    from app.application.knowledge.rag_service import RagService
    from app.application.knowledge import rag_service as module

    rag = RagService(None, SimpleNamespace(encode_queries=lambda *_: 1),
                     SimpleNamespace(search=lambda *_a, **_kw: 1), fast_mode=True)
    monkeypatch.setattr(rag, "_dept_code_of", lambda *_: "")
    monkeypatch.setattr(rag, "_is_admin", lambda *_: False)
    monkeypatch.setattr(rag, "resolve_scopes", lambda *_: ["GLOBAL"])
    monkeypatch.setattr(rag, "_get_accessible_kb_ids", lambda *_: ["allowed"])
    monkeypatch.setattr(rag, "_keyword_search", lambda *_: [])
    monkeypatch.setattr(rag, "_feedback_weights", lambda *_: {})
    monkeypatch.setattr(module.reranker, "rerank", lambda *_: 1)
    assert rag.search("查询", "u1", kb_ids=["forbidden"]) == []
    assert rag.search("查询", "u1", kb_ids=["allowed"]) == []


def test_planning_materials_fast_mode_skips_vector_lookup():
    service = AsyncWritingTaskService.__new__(AsyncWritingTaskService)
    service.rag = SimpleNamespace(
        fast_mode=True,
        _get_accessible_kb_ids=lambda *_: ["allowed"],
        embedder=SimpleNamespace(encode_queries=lambda *_: (_ for _ in ()).throw(
            AssertionError("slow embedding must not run"))),
    )
    service._plan_materials_fallback = lambda query, user_id, kb_ids: [
        {"id": kb_ids[0], "label": query, "selected": True}]
    result = service._plan_materials({"topic": "普法"}, "u1", {})
    assert result[0]["id"] == "allowed"


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
    async def first(_ctx, _section, index, *_args, on_delta):
        if index:
            on_delta("第二段")
            return "第二段", []
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
        assert decode(await anext(stream))["type"] == "stage"
        assert decode(await anext(stream))["type"] == "stage"
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
    finish_third = asyncio.Event()
    async def first(_ctx, _section, index, *_args, on_delta):
        if index == 2:
            await finish_third.wait()
        text = "第一段" if index == 0 else f"第{index + 1}段"
        on_delta(text)
        return text, []
    service._section_plan_async = plan
    service._generate_one_section_stream_async = first
    service._merge_sources = lambda _groups: []
    service._finalize_draft = lambda _task, _ctx, content, *_args, **_kwargs: {
        "current_content": content, "reply": "完成"}

    async def exercise():
        stream = service.draft_stream_async("task-a", "user-a")
        assert json.loads((await anext(stream))[6:])["type"] == "stage"
        assert json.loads((await anext(stream))[6:])["type"] == "stage"
        first_event = json.loads((await anext(stream))[6:])
        second_event = await asyncio.wait_for(anext(stream), 1)
        assert first_event["text"] == "第一段"
        assert json.loads(second_event[6:])["text"] == "\n\n第2段"
        finish_third.set()
        return [json.loads(event[6:]) async for event in stream]

    rest = asyncio.run(exercise())
    assert rest[-1]["type"] == "done"
    assert rest[-1]["data"]["current_content"] == "第一段\n\n第2段\n\n第3段"


def test_stream_disconnect_waits_for_section_producer_cleanup():
    import json

    service = AsyncWritingTaskService.__new__(AsyncWritingTaskService)
    task = SimpleNamespace(current_content="", version_no=0, context={}, session_id="")
    service._get_owned = lambda *_: task
    service._prepare_agent_graph = lambda *_: None
    service._load_template = lambda *_: None
    service._attachment_context = lambda *_: None
    service._should_section = lambda *_: True
    async def plan(_ctx):
        return [{"heading": "一、", "focus": "首节"}]
    service._section_plan_async = plan
    cleaned = asyncio.Event()
    async def first(*_args, on_delta):
        try:
            on_delta("首字")
            await asyncio.Event().wait()
        finally:
            cleaned.set()
    service._generate_one_section_stream_async = first

    async def exercise():
        stream = service.draft_stream_async("task-a", "user-a")
        while json.loads((await anext(stream))[6:])["type"] != "delta":
            pass
        await stream.aclose()
        assert cleaned.is_set()

    asyncio.run(exercise())


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
