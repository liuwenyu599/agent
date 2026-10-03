import json

from app.application.writing.eval_capture_service import EvalCaptureWritingTaskService
from app.application.writing.intent_interpreter import WritingIntentInterpreter
from app.application.writing.ops_task_service import OpsWritingTaskService
from app.application.writing.quality_retry_service import QualityRetryWritingTaskService
from app.application.writing.semantic_task_service import SemanticWritingTaskService
from app.application.writing.structured_field_service import StructuredFieldWritingTaskService
from app.application.writing.task_service import WritingTaskService


class BrokenAssistant:
    def __init__(self):
        self.calls = 0

    def complete(self, *args, **kwargs):
        self.calls += 1
        return "这不是合法 JSON"


class ToolAssistant:
    def __init__(self, arguments):
        self.arguments = arguments
        self.tool_calls = 0
        self.complete_calls = 0

    def complete_with_tools(self, messages, tools, **kwargs):
        self.tool_calls += 1
        assert tools[0]["function"]["name"] == "route_writing_ops"
        return {
            "role": "assistant",
            "content": "",
            "tool_calls": [{
                "id": "call_1",
                "type": "function",
                "function": {
                    "name": "route_writing_ops",
                    "arguments": json.dumps(self.arguments, ensure_ascii=False),
                },
            }],
        }

    def complete(self, *args, **kwargs):
        self.complete_calls += 1
        raise AssertionError("valid tool call must not fall back to JSON completion")


def test_public_writing_service_routes_to_structured_field_service():
    assert WritingTaskService is StructuredFieldWritingTaskService


def test_structured_field_service_preserves_eval_capture_quality_retry_and_ops_layers():
    assert issubclass(StructuredFieldWritingTaskService, EvalCaptureWritingTaskService)
    assert issubclass(EvalCaptureWritingTaskService, QualityRetryWritingTaskService)
    assert issubclass(QualityRetryWritingTaskService, OpsWritingTaskService)


def test_intent_failure_fails_closed_instead_of_regex_fallback():
    assistant = BrokenAssistant()
    result = WritingIntentInterpreter(assistant).interpret(
        "把标题改成关于社区矫正工作的通知",
        context={"title": "旧标题"},
        has_draft=True,
    )
    assert assistant.calls == 2
    assert result is None


def test_tool_call_routes_local_edit_to_patch_section():
    assistant = ToolAssistant({
        "operation": "patch_section",
        "field_updates": {},
        "target": "第二段",
        "instruction": "把这一段精简一半，事实不变",
        "revision_mode": "condense",
        "reply": "将只精简第二段。",
    })
    result = WritingIntentInterpreter(assistant).interpret(
        "第二段太长了，精简一半",
        context={"title": "测试通知"},
        has_draft=True,
    )
    assert result["operation"] == "patch_section"
    assert result["patch_target"] == "第二段"
    assert result["revision_instruction"] == "把这一段精简一半，事实不变"
    assert result["routing"] == "tool_call"
    assert assistant.tool_calls == 1
    assert assistant.complete_calls == 0


def test_tool_call_keeps_field_updates_separate_from_body_operation():
    assistant = ToolAssistant({
        "operation": "patch_section",
        "field_updates": {"title": "新标题", "document_date": "2026年10月2日"},
        "target": "三、工作措施",
        "instruction": "把措施写得更具体",
        "revision_mode": "expand",
        "reply": "更新标题和日期，并扩写工作措施。",
    })
    result = WritingIntentInterpreter(assistant).interpret(
        "标题改成新标题，日期改成2026年10月2日，第三部分措施写具体",
        context={"title": "旧标题"},
        has_draft=True,
    )
    assert result["title"] == "新标题"
    assert result["document_date"] == "2026年10月2日"
    assert result["operation"] == "patch_section"
    assert "标题" not in result["revision_instruction"]


def test_patch_target_resolves_ordinal_paragraph_without_touching_neighbors():
    text = "第一段保持不变。\n\n第二段需要修改，内容较长。\n\n第三段也保持不变。"
    resolved = OpsWritingTaskService._resolve_patch_target(text, "第二段")
    assert resolved is not None
    start, end, fragment = resolved
    assert fragment == "第二段需要修改，内容较长。"
    replaced = text[:start] + "第二段已精简。" + text[end:]
    assert replaced == "第一段保持不变。\n\n第二段已精简。\n\n第三段也保持不变。"


def test_patch_target_resolves_one_section_until_next_same_level_heading():
    text = (
        "开头。\n\n"
        "一、基本情况\n基本情况正文。\n\n"
        "二、工作措施\n第一项措施。\n第二项措施。\n\n"
        "三、下一步计划\n下一步正文。"
    )
    resolved = OpsWritingTaskService._resolve_patch_target(text, "二、工作措施")
    assert resolved is not None
    _, _, fragment = resolved
    assert fragment.startswith("二、工作措施")
    assert "第二项措施。" in fragment
    assert "三、下一步计划" not in fragment


def test_patch_target_rejects_ambiguous_literal_excerpt():
    text = "有关事项通知如下。\n\n第一项。\n\n有关事项通知如下。"
    assert OpsWritingTaskService._resolve_patch_target(text, "有关事项通知如下。") is None


def test_legacy_semantic_body_still_canonicalizes_one_signoff_for_compatibility():
    ctx = {
        "title": "关于开展专项工作的通知",
        "recipient": "广州市白云区财政局",
        "document_number": "云司发〔2026〕12号",
        "authority": "广州市白云区司法局",
        "document_date": "2026年9月30日",
    }
    raw = """关于开展专项工作的通知
关于开展专项工作的通知
广州市白云区财政局：
云司发〔2026〕12号

现将有关事项通知如下。

广州市白云区司法局
2026年9月29日
广州市白云区司法局
2026年9月30日
"""
    body = SemanticWritingTaskService._canonicalize_body(raw, ctx)

    assert "关于开展专项工作的通知" not in body
    assert "广州市白云区财政局" not in body
    assert "云司发〔2026〕12号" not in body
    assert body.count("广州市白云区司法局") == 1
    assert body.count("2026年9月30日") == 1
    assert "2026年9月29日" not in body
    assert "现将有关事项通知如下。" in body


def test_production_body_contains_no_structured_chrome_at_all():
    ctx = {
        "title": "关于开展专项工作的通知",
        "recipient": "广州市白云区财政局",
        "document_number": "云司发〔2026〕12号",
        "authority": "广州市白云区司法局",
        "document_date": "2026年9月30日",
    }
    raw = """关于开展专项工作的通知
广州市白云区财政局：
云司发〔2026〕12号

现将有关事项通知如下。

广州市白云区司法局
2026年9月30日
"""
    body = StructuredFieldWritingTaskService._canonicalize_body(raw, ctx)
    assert body == "现将有关事项通知如下。"
    assert all(value not in body for value in ctx.values())


def test_revision_summary_is_visible_in_conversation():
    before = "第一段保持不变。\n\n第二段原来比较啰嗦，需要处理。"
    after = "第一段保持不变。\n\n第二段已经精简。"
    summary = SemanticWritingTaskService._revision_diff(before, after)
    assert "原：第二段原来比较啰嗦，需要处理。" in summary
    assert "改：第二段已经精简。" in summary