import pytest
from fastapi import HTTPException

from app.application.writing.quality_retry_service import QualityRetryWritingTaskService


BAD = "一、工作目标\n此处略去。\n二、工作任务\n此处略去。"
GOOD = (
    "一、工作目标\n围绕社区矫正教育帮扶工作，细化教育、帮扶和衔接措施，提升工作规范性。\n\n"
    "二、主要任务\n结合实际情况开展分类教育，落实困难帮扶和部门协同，及时记录办理情况。\n\n"
    "三、工作要求\n压实责任，加强过程管理，发现问题及时整改，确保各项措施有序落实。"
)


class SequenceAssistant:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = []

    def chat(self, message, **kwargs):
        self.calls.append(message)
        if not self.outputs:
            raise AssertionError("unexpected extra model call")
        return self.outputs.pop(0)


class BareRetryService(QualityRetryWritingTaskService):
    def __init__(self, assistant):
        # Unit test only: _llm_revise needs assistant and no database/RAG activity.
        self.assistant = assistant
        self.rag = None
        self.attachments = None

    def _agent_prompt(self, user_id):
        return ""

    def _example_style_block(self, query, user_id):
        return ""


def test_revise_retries_with_concrete_quality_issues_then_accepts_good_candidate():
    assistant = SequenceAssistant([BAD, GOOD])
    service = BareRetryService(assistant)

    result = service._llm_revise("原始修改要求", [], "", "u1")

    assert result == GOOD
    assert len(assistant.calls) == 2
    retry_prompt = assistant.calls[1]
    assert "QualityGate 第 1 次修复" in retry_prompt
    assert "提纲式退化" in retry_prompt
    assert "此处略去" in retry_prompt
    assert "上一版未通过正文" in retry_prompt


def test_revise_stops_after_two_retries_and_raises_without_returning_d_candidate():
    assistant = SequenceAssistant([BAD, BAD, BAD])
    service = BareRetryService(assistant)

    with pytest.raises(HTTPException) as exc:
        service._llm_revise("原始修改要求", [], "", "u1")

    assert len(assistant.calls) == 3  # initial + retry 1 + retry 2
    assert exc.value.status_code == 422
    assert exc.value.detail["code"] == "WRITING_QUALITY_GATE_D"
    assert exc.value.detail["retry_count"] == 2
    assert exc.value.detail["issues"]


def test_finalizer_rejects_d_before_calling_persistence_parent():
    service = BareRetryService(SequenceAssistant([]))

    with pytest.raises(HTTPException) as exc:
        service._finalize_draft(
            t=object(),
            ctx={"title": "测试通知"},
            text=BAD,
            sources=[],
            user_id="u1",
        )

    assert exc.value.status_code == 422
    assert exc.value.detail["code"] == "WRITING_QUALITY_GATE_D"
