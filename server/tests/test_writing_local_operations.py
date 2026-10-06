import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.application.writing.async_task_service import AsyncWritingTaskService
from app.application.writing.intent_interpreter import _sanitize_tool_args, _sanitize_legacy_args
from app.application.writing.ops_task_service import OpsWritingTaskService
from app.application.writing.semantic_task_service import SemanticWritingTaskService


BODY = "一、补贴标准\n每人每月补贴100元。\n\n二、申报流程\n向属地司法所申报。"


@pytest.mark.parametrize("operation", ["append_to_section", "insert_paragraph", "delete_range"])
def test_tool_accepts_new_local_operations(operation):
    parsed = _sanitize_tool_args({"operation": operation, "field_updates": {},
                                 "target": "补贴标准", "instruction": "补充按月发放。",
                                 "position": "before", "end_target": "申报流程", "reply": ""})
    assert parsed["operation"] == operation
    assert parsed["patch_target"] == "补贴标准"
    assert parsed["position"] == "before"
    assert parsed["end_target"] == "申报流程"


def test_legacy_json_supports_local_operations_without_full_rewrite():
    parsed = _sanitize_legacy_args({"operation": "append_to_section", "intent": "revise_content",
                                   "target": "补贴标准", "revision_instruction": "补充按月发放。"})
    assert parsed["operation"] == "append_to_section"
    assert parsed["routing"] == "json_fallback"
    assert parsed["revision_instruction"] == "补充按月发放。"
    assert _sanitize_legacy_args({"operation": "append_to_section", "target": "补贴标准"}) is None
    unsafe = _sanitize_legacy_args({"intent": "revise_content", "revision_instruction": "补充一句话"})
    assert unsafe["operation"] == "clarify"
    assert unsafe["side_effect"] == "none"


def test_named_section_append_preserves_every_existing_character():
    start, end, fragment = OpsWritingTaskService._local_span(BODY, "补贴标准", "append_to_section")
    result = OpsWritingTaskService._splice_local(BODY, start, end, "补贴按月发放。", "append_to_section")
    assert result == "一、补贴标准\n每人每月补贴100元。\n\n补贴按月发放。\n\n二、申报流程\n向属地司法所申报。"
    assert fragment == "一、补贴标准\n每人每月补贴100元。"


def test_duplicate_section_names_cannot_append_arbitrary_section():
    duplicated = BODY + "\n\n三、补贴标准\n另一类标准。"
    assert OpsWritingTaskService._local_span(duplicated, "补贴标准", "append_to_section") is None
    assert OpsWritingTaskService._local_span(BODY, "每人每月", "append_to_section") is None


def test_nested_section_stops_at_parent_heading():
    text = "一、工作安排\n（一）补贴标准\n标准正文。\n\n二、申报流程\n流程正文。"
    _, _, fragment = OpsWritingTaskService._resolve_patch_target(text, "补贴标准")
    assert fragment == "（一）补贴标准\n标准正文。"


def test_insert_before_and_delete_inclusive_range():
    start, end, _ = OpsWritingTaskService._local_span(BODY, "申报流程", "insert_paragraph", "before")
    inserted = OpsWritingTaskService._splice_local(BODY, start, end, "请准备身份证明。", "insert_paragraph")
    assert inserted.endswith("请准备身份证明。\n\n二、申报流程\n向属地司法所申报。")
    assert OpsWritingTaskService._local_span(BODY, "申报流程", "delete_range", end_target="补贴标准") is None
    start, end, _ = OpsWritingTaskService._local_span(BODY, "补贴标准", "delete_range", end_target="申报流程")
    assert OpsWritingTaskService._splice_local(BODY, start, end, "", "delete_range") == ""


def service_stub(cls):
    svc = object.__new__(cls)
    task = SimpleNamespace(context={}, current_content=BODY, version_no=1)
    svc.db = Mock()
    svc._get_owned = lambda *_: task
    svc._canonicalize_body = lambda text, ctx: text
    svc._retrieve = lambda *_args, **_kwargs: []
    svc._attachment_context = lambda *_: None
    svc._postprocess = lambda text, ctx: (text, [], None, None)
    svc._guard_external_document_numbers = lambda text, sources, ctx: (text, [])
    svc._reference_labels = lambda *_: []
    svc._snapshot = lambda *_args, **_kwargs: (None, 2)
    svc._to_dict = lambda task: {"current_content": task.current_content}
    svc._llm_revise = Mock(return_value="补贴按月发放。")
    async def revise(*_args):
        return svc._llm_revise(*_args)
    svc._llm_revise_async = revise
    return svc, task


@pytest.mark.parametrize("cls", [OpsWritingTaskService, AsyncWritingTaskService])
@pytest.mark.parametrize("operation", ["append_to_section", "insert_paragraph", "delete_range"])
def test_sync_async_execution_saves_local_changes(cls, operation):
    svc, task = service_stub(cls)
    kwargs = dict(target="补贴标准", instruction="补充按月发放。", operation=operation)
    if cls is AsyncWritingTaskService:
        result = asyncio.run(svc.patch_section_async("task", "user", **kwargs))
    else:
        result = svc.patch_section("task", "user", **kwargs)
    assert result["content_changed"] is True
    assert result["operation"] == operation
    assert "二、申报流程\n向属地司法所申报。" in task.current_content
    assert "本次实际变化" not in result["reply"]
    assert "v2" in result["reply"]
    assert any(word in result["reply"] for word in ("补进了", "删掉了"))
    if operation == "delete_range":
        svc._llm_revise.assert_not_called()
        assert "每人每月补贴100元。" not in task.current_content
    else:
        assert "每人每月补贴100元。" in task.current_content
        assert "补贴按月发放。" in task.current_content


@pytest.mark.parametrize("cls", [OpsWritingTaskService, AsyncWritingTaskService, SemanticWritingTaskService])
@pytest.mark.parametrize("routing_failed", [True, False])
def test_question_answers_without_mutating_document(cls, routing_failed):
    """纯问答不得改动正文，也不得升版本。

    两条路径的回复来源不同，都属正确行为：

    - ``routing_failed=True`` —— 意图路由拿不到结果，回退 ``_answer_only``
      直接问模型，用模型的实际回答。
    - ``routing_failed=False`` —— 路由返回了 ``reply``（它已读过上下文），
      实现按 ``it.get("reply") or self._answer_only(...)`` 短路，不再二次调用
      模型。这是刻意设计：避免同一问题问两遍模型、白白多花一次推理。

    早先这里两种情形都断言 ``answer.assert_called_once()`` 且要求回复等于
    模型输出，等于要求"已经有reply 时仍要再问一次模型"，与实现语义冲突。
    """
    svc, task = service_stub(cls)
    interpreted = None if routing_failed else _sanitize_tool_args({
        "operation": "answer", "field_updates": {}, "reply": "我来解释补贴标准。"})
    svc._interpret = lambda *_args, **_kwargs: interpreted
    async def interpret(*_args, **_kwargs):
        return interpreted
    svc._interpret_async = interpret
    answer = Mock(return_value="补贴标准通常需要明确对象、金额和发放周期。")
    async def complete(*args, **kwargs):
        return answer(*args, **kwargs)
    svc.assistant = SimpleNamespace(complete=answer, acomplete=complete)
    if cls is AsyncWritingTaskService:
        result = asyncio.run(svc.chat_async("task", "user", "这节还缺什么？"))
    else:
        result = svc.chat("task", "user", "这节还缺什么？")

    expected = ("补贴标准通常需要明确对象、金额和发放周期。"
                if routing_failed else "我来解释补贴标准。")
    assert result["reply"] == expected
    assert result["content_changed"] is False
    assert task.current_content == BODY
    assert task.version_no == 1
    # 只有回退路径才需要再问一次模型
    assert answer.called is routing_failed


@pytest.mark.parametrize("cls", [OpsWritingTaskService, AsyncWritingTaskService])
@pytest.mark.parametrize("operation", ["append_to_section", "insert_paragraph", "delete_range"])
def test_chat_routes_local_operations_to_execution(cls, operation):
    svc, task = service_stub(cls)
    parsed = _sanitize_tool_args({"operation": operation, "field_updates": {},
                                 "target": "补贴标准", "instruction": "补充按月发放。"})
    svc._interpret = lambda *_args, **_kwargs: parsed
    async def interpret(*_args, **_kwargs):
        return parsed
    svc._interpret_async = interpret
    if cls is AsyncWritingTaskService:
        result = asyncio.run(svc.chat_async("task", "user", "在补贴标准那节加一句话"))
    else:
        result = svc.chat("task", "user", "在补贴标准那节加一句话")
    assert result["operation"] == operation
    assert result["content_changed"] is True
    assert task.version_no == 2
    assert task.context["history"][-1]["content"] == result["reply"]


@pytest.mark.parametrize("cls", [OpsWritingTaskService, AsyncWritingTaskService])
def test_chat_local_edit_without_draft_reports_missing_draft(cls):
    svc, task = service_stub(cls)
    task.current_content = ""
    parsed = _sanitize_tool_args({"operation": "patch_section", "field_updates": {},
                                  "target": "第二段", "instruction": "补充经费依据。"})
    svc._interpret = lambda *_args, **_kwargs: parsed

    async def interpret(*_args, **_kwargs):
        return parsed

    svc._interpret_async = interpret
    if cls is AsyncWritingTaskService:
        result = asyncio.run(svc.chat_async("task", "user", "第二段补充经费依据"))
    else:
        result = svc.chat("task", "user", "第二段补充经费依据")
    assert "还没有草稿" in result["reply"]
    assert result["content_changed"] is False
    assert task.version_no == 1
