from app.application.writing.intent_interpreter import WritingIntentInterpreter
from app.application.writing.semantic_task_service import SemanticWritingTaskService
from app.application.writing.task_service import WritingTaskService


class BrokenAssistant:
    def __init__(self):
        self.calls = 0

    def complete(self, *args, **kwargs):
        self.calls += 1
        return "这不是合法 JSON"


def test_public_writing_service_routes_to_semantic_service():
    # Existing FastAPI routes import WritingTaskService from task_service. The package-level
    # compatibility binding must therefore expose the semantic implementation.
    assert WritingTaskService is SemanticWritingTaskService


def test_intent_failure_fails_closed_instead_of_regex_fallback():
    assistant = BrokenAssistant()
    result = WritingIntentInterpreter(assistant).interpret(
        "把标题改成关于社区矫正工作的通知",
        context={"title": "旧标题"},
        has_draft=True,
    )
    assert assistant.calls == 2  # initial parse + model repair retry
    assert result["side_effect"] == "none"
    assert result["intent"] == "answer"
    assert "没有改动" in result["reply"]
    # Crucially, no local regex inferred the obvious-looking title command.
    assert result["title"] is None


def test_canonical_body_removes_duplicate_headers_and_signoffs():
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


def test_revision_summary_is_visible_in_conversation():
    before = "第一段保持不变。\n\n第二段原来比较啰嗦，需要处理。"
    after = "第一段保持不变。\n\n第二段已经精简。"
    summary = SemanticWritingTaskService._revision_diff(before, after)
    assert "原：第二段原来比较啰嗦，需要处理。" in summary
    assert "改：第二段已经精简。" in summary
