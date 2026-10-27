"""写作链路单一化护栏。

生产只保留一条内容生成路径：异步服务。历史上同一份逻辑（起草 / 整篇改写 / 局部修改 /
任务内对话 / 质量重试）在同步与异步两条链上各写一遍，改一处忘一处就会分叉——日期注入
误伤讲话稿、修复动作只在同步链生效都是这么来的。

这里锁住四条不变量：
1. 生产服务上不存在同步内容入口（重新加回来会直接失败）；
2. 三条支路共用同一套收尾与落库管线；
3. 质量门的重试预算只有一处定义；
4. 讲话类文种判断只有一处定义。
"""
import inspect

import pytest

from app.application.writing import quality_policy, section_policy
from app.application.writing.async_task_service import AsyncWritingTaskService

SYNC_ENTRY_POINTS = ("draft", "draft_stream", "revise", "patch_section", "chat")


@pytest.mark.parametrize("name", SYNC_ENTRY_POINTS)
def test_production_service_has_no_sync_content_entry_point(name):
    assert not hasattr(AsyncWritingTaskService, name), (
        f"同步入口 {name} 不应存在：生产只走 async，第二套实现必然与生产漂移"
    )


@pytest.mark.parametrize("method", ["revise_async", "patch_section_async"])
def test_revision_paths_share_finalize_and_persist_pipeline(method):
    source = inspect.getsource(getattr(AsyncWritingTaskService, method))
    assert "finalize_text(" in source
    assert "persist_revision(" in source


def test_draft_finalizer_uses_the_same_pipeline():
    # 基类 ``WritingTaskService`` 在包初始化时被重绑到异步实现，取 MRO 里的基类本体。
    base = next(cls for cls in AsyncWritingTaskService.__mro__
                if cls.__name__ == "WritingTaskService")
    source = inspect.getsource(base._finalize_draft)
    assert "finalize_text(" in source
    assert "persist_revision(" in source


def test_quality_retry_budget_is_defined_once():
    from app.application.writing import quality_retry_service

    assert quality_policy.MAX_QUALITY_RETRIES == 2
    # 兼容别名必须指向同一个值，而不是另抄一个常量
    assert quality_retry_service._MAX_QUALITY_RETRIES == quality_policy.MAX_QUALITY_RETRIES


def test_retry_actions_come_from_the_rule_table():
    quality = {"level": "D", "issues": [
        {"source": "quality", "severity": "critical", "message": "机械重复：同一句最多出现 4 次"}
    ]}
    decision = quality_policy.repair_decision(quality, model_action=None)
    assert decision.source == "rule"
    assert "改写" in decision.action


def test_speech_kinds_have_a_single_source():
    """quality_gate / task_service / 分节规则都按同一份讲话类文种判断。"""
    from app.application.writing.quality_gate import QualityGate

    speech = section_policy.SPEECH_KINDS
    assert speech == ("致辞", "讲话", "发言", "主持词")
    assert section_policy.is_speech_type("致辞稿")
    assert section_policy.is_speech_type("会议主持词")
    assert not section_policy.is_speech_type("通知")

    # 质量门不再自持一份文种元组，而是调用同一个判断
    assert "is_speech_type" in inspect.getsource(QualityGate.evaluate)


def test_section_policy_fallback_plan_matches_document_type():
    plan = section_policy.default_section_plan("讲话稿", 900)
    assert plan and all(item["heading"] == "" for item in plan)
    assert len(plan) == 3  # 短讲话不硬拆 4 节
    assert section_policy.default_section_plan("通知", 1200) == []
    assert section_policy.needs_sectioning("工作报告", 2000) is True
    assert section_policy.needs_sectioning("工作报告", 900) is False
