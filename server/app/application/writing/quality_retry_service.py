"""Compatibility helpers for the centralized quality policy.

A D-level candidate is never allowed to reach snapshot/commit. The exact QualityGate issues are
fed back to the model and regeneration is attempted at most twice.

修复策略本身（修什么、怎么修、修几次）已经收敛到 :mod:`quality_policy`，起草 / 整篇改写 /
局部修改三条支路共用同一套预算与动作选择；本层只保留两件事：

生产链不再继承本类；异步入口直接调用 :mod:`quality_policy`，最终 fail-closed 由
``finalize_pipeline`` 负责。本类只给历史测试/脚本保留无模型 I/O 的纯函数别名。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.application.writing.ops_task_service import OpsWritingTaskService
from app.application.writing.quality_policy import (
    MAX_QUALITY_RETRIES,
    RepairDecision,
    critical_issue_lines,
    quality_result,
    retry_prompt,
    rule_plan,
)

# 兼容旧调用方（测试与外部脚本历史上按这个私有名读取预算）
_MAX_QUALITY_RETRIES = MAX_QUALITY_RETRIES

__all__ = [
    "QualityRetryWritingTaskService",
    "RepairDecision",
    "MAX_QUALITY_RETRIES",
]


class QualityRetryWritingTaskService(OpsWritingTaskService):
    """Block D-level drafts/revisions and retry with a *targeted* repair action."""

    @staticmethod
    def _quality_result(text: str, topic: str = "") -> Dict[str, Any]:
        return quality_result(text, topic)

    @staticmethod
    def _critical_issue_lines(quality: Dict[str, Any]) -> List[str]:
        return critical_issue_lines(quality)

    @classmethod
    def _rule_plan(cls, quality: Dict[str, Any]) -> Optional[str]:
        return rule_plan(quality)

    @classmethod
    def _retry_prompt(cls, original_prompt: str, candidate: str,
                      quality: Dict[str, Any], retry_no: int,
                      action: str = "") -> str:
        return retry_prompt(original_prompt, candidate, quality, retry_no, action)
