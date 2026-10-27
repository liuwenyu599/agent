import asyncio

import pytest
from fastapi import HTTPException

from app.application.writing.async_task_service import AsyncWritingTaskService
from app.application.writing.finalize_pipeline import finalize_text


class BareRetryService(AsyncWritingTaskService):
    def __init__(self, assistant):
        # Unit test only: the async revise chain needs assistant and no DB/RAG activity.
        self.assistant = assistant
        self.long_form_assistant = None
        self.rag = None
        self.attachments = None
        self._draft_memory_cache = {}
        self._draft_style_cache = {}

    def _agent_prompt(self, user_id):
        return ""

    def _example_style_block(self, query, user_id):
        return ""


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

    async def achat(self, message, **kwargs):
        return self.chat(message, **kwargs)


def test_revise_retries_with_concrete_quality_issues_then_accepts_good_candidate():
    assistant = SequenceAssistant([BAD, GOOD])
    service = BareRetryService(assistant)

    result = asyncio.run(service._llm_revise_async("原始修改要求", [], "", "u1"))

    assert result == GOOD
    assert len(assistant.calls) == 2
    retry_prompt = assistant.calls[1]
    assert "QualityGate 第 1 次修复" in retry_prompt
    assert "提纲式退化" in retry_prompt
    assert "此处略去" in retry_prompt
    assert "上一版未通过正文" in retry_prompt
    # 修复动作来自 quality_policy 的规则表，而不是原样重试
    assert "本次修复动作" in retry_prompt
    assert "补回被" in retry_prompt


def test_revise_stops_after_two_retries_and_raises_without_returning_d_candidate():
    assistant = SequenceAssistant([BAD, BAD, BAD])
    service = BareRetryService(assistant)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(service._llm_revise_async("原始修改要求", [], "", "u1"))

    assert len(assistant.calls) == 3  # initial + retry 1 + retry 2
    assert exc.value.status_code == 422
    assert exc.value.detail["code"] == "WRITING_QUALITY_GATE_D"
    assert exc.value.detail["retry_count"] == 2
    assert exc.value.detail["issues"]


def test_finalizer_rejects_d_before_persistence():
    class FinalizeStub:
        @staticmethod
        def _postprocess(text, _ctx):
            return text, [], None, None

        @staticmethod
        def _strip_leading_structural_fields(text, _ctx):
            return text

        @staticmethod
        def _guard_external_document_numbers(text, _sources, _ctx):
            return text, []

        @staticmethod
        def _reference_labels(_sources):
            return []

        @staticmethod
        def _reference_items(_sources):
            return []

    with pytest.raises(HTTPException) as exc:
        finalize_text(FinalizeStub(), BAD, {"title": "测试通知"}, [])

    assert exc.value.status_code == 422
    assert exc.value.detail["code"] == "WRITING_QUALITY_GATE_D"
