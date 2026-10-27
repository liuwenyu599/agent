"""质量门修复决策：规则优先、模型兜底、预算不放大。

背景：主持词用例曾连续 D 级（机械重复 + 偏短）却三次用同一策略，
根因是重试把issue 拼回 prompt 后原样重发。修复决策必须区分问题类型。
"""
import pytest
import asyncio

from app.application.writing.async_task_service import AsyncWritingTaskService
from app.application.writing.quality_retry_service import (
    _MAX_QUALITY_RETRIES,
    QualityRetryWritingTaskService,
)


class _Assistant:
    """记录调用次数的假网关。decisions 依次返回修复计划。"""

    def __init__(self, decisions=None):
        self.calls = 0
        self.decisions = list(decisions or [])

    async def acomplete(self, *args, **kwargs):
        self.calls += 1
        if self.decisions:
            return self.decisions.pop(0)
        return ""


def _quality(*critical: str) -> dict:
    return {
        "level": "D",
        "issues": [{"source": "quality", "severity": "critical", "message": m}
                   for m in critical],
    }


def _svc(assistant=None):
    svc = AsyncWritingTaskService.__new__(AsyncWritingTaskService)
    svc.assistant = assistant
    return svc


def test_repetition_issue_maps_to_rewrite_action_without_model():
    """机械重复必须命中确定性动作，且不额外调模型（延迟不放大）。"""
    svc = _svc()
    decision = asyncio.run(svc._repair_plan_async(_quality("机械重复：同一句最多出现 4 次"), {}))
    assert decision.source == "rule"
    assert "改写" in decision.action


def test_placeholder_and_truncation_each_map_to_specific_action():
    svc = _svc()
    a = asyncio.run(svc._repair_plan_async(_quality("占位符：['XX']"), {}))
    b = asyncio.run(svc._repair_plan_async(_quality("结尾悬空（以'的了'结尾）"), {}))
    assert a.source == b.source == "rule"
    assert a.action != b.action


def test_unknown_issue_falls_back_to_model_decision():
    """规则覆盖不到时才问模型一次。"""
    assistant = _Assistant(["补写缺失的实证段落，不要重复已有表述"])
    svc = _svc(assistant)
    decision = asyncio.run(svc._repair_plan_async(
        _quality("某种尚未归类的新硬伤"), {"document_type": "通知"}))
    assert decision.source == "model"
    assert assistant.calls == 1
    assert "补写" in decision.action


def test_partial_rule_coverage_does_not_half_fix():
    """一条命中一条没命中时不能只修一半，必须走模型。"""
    assistant = _Assistant(["同时处理两类问题"])
    svc = _svc(assistant)
    decision = asyncio.run(svc._repair_plan_async(
        _quality("机械重复：同一句最多出现 4 次", "尚未归类的新硬伤"), {}))
    assert decision.source == "model"


def test_model_failure_does_not_break_repair_chain():
    """模型决策失败必须降级到兜底动作，绝不能让修复链断在这里。"""

    class Boom:
        async def acomplete(self, *args, **kwargs):
            raise RuntimeError("model down")

    svc = _svc(Boom())
    decision = asyncio.run(svc._repair_plan_async(_quality("尚未归类的新硬伤"), {}))
    assert decision.source == "fallback"
    assert decision.action


def test_no_assistant_still_works_offline():
    svc = _svc(None)
    decision = asyncio.run(svc._repair_plan_async(_quality("机械重复：同一句最多出现 4 次"), {}))
    assert decision.source == "rule"


def test_model_plan_strips_list_markers_and_rejects_noise():
    assistant = _Assistant(["好的\n1. 改写重复段落\n- 补充依据\n短"])
    svc = _svc(assistant)
    decision = asyncio.run(svc._repair_plan_async(_quality("未知硬伤"), {}))
    assert "1." not in decision.action
    assert "-" not in decision.action
    assert "改写重复段落" in decision.action
    assert "补充依据" in decision.action
    # 过短/过长的行被丢弃
    assert decision.action.count("；") == 1


def test_step_budget_did_not_grow():
    """受限自主的关键约束：步数预算不变，延迟不因引入决策而放大。"""
    assert _MAX_QUALITY_RETRIES == 2


def test_retry_prompt_carries_the_decided_action():
    prompt = QualityRetryWritingTaskService._retry_prompt(
        "写一篇通知", "候选正文", _quality("机械重复：同一句最多出现 4 次"),
        retry_no=1, action="改写重复最多的两处句子")
    assert "【本次修复动作】" in prompt
    assert "改写重复最多的两处句子" in prompt
    # 原有约束不能丢
    assert "机械重复：同一句最多出现 4 次" in prompt
    assert "候选正文" in prompt
    assert "不得用解释、道歉或占位符代替正文" in prompt


def test_retry_prompt_without_action_still_usable():
    """老调用方不传 action 时退回兜底文案，不会拼出空动作块。"""
    prompt = QualityRetryWritingTaskService._retry_prompt(
        "写一篇通知", "候选正文", _quality("空输出"), retry_no=1)
    assert "【本次修复动作】" in prompt
