"""Quality-gated production writing service.

A D-level candidate is never allowed to reach snapshot/commit. The exact QualityGate issues are
fed back to the model and regeneration is attempted at most twice.

修复策略本身（修什么、怎么修、修几次）已经收敛到 :mod:`quality_policy`，起草 / 整篇改写 /
局部修改三条支路共用同一套预算与动作选择；本层只保留两件事：

1. 把策略包装成服务上的可覆写钩子（``_repair_plan`` / ``_retry_prompt``），
   让同步与异步两种模型调用方式共用同一决策；
2. 在正文离开服务之前做 fail-closed 守卫（``_postprocess`` / ``_finalize_draft``），
   D 级一律 422，不落库。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from app.application.writing import quality_policy
from app.application.writing.ops_task_service import OpsWritingTaskService
from app.application.writing.quality_policy import (
    MAX_QUALITY_RETRIES,
    RepairDecision,
    assert_acceptable,
    critical_issue_lines,
    model_plan_prompt,
    parse_model_plan,
    quality_result,
    repair_decision,
    retry_prompt,
    rule_plan,
)

logger = logging.getLogger(__name__)

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

    def _model_plan(self, quality: Dict[str, Any], ctx: Dict[str, Any]) -> Optional[str]:
        """规则覆盖不到时，让模型读 issue 自己决定怎么改。只调用一次，且失败即放弃。"""
        if not self.assistant:
            return None
        prompt = model_plan_prompt(quality, ctx)
        if not prompt:
            return None
        try:
            text = self.assistant.chat(
                message=prompt, history=[], sources=None, user_role="user",
                system_prompt=quality_policy.MODEL_PLAN_SYSTEM,
            ) or ""
        except Exception as exc:  # 模型不可用时退回规则/兜底，绝不让修复链断在这里
            logger.warning("[质量门修复] 模型决策失败，回退兜底动作: %s", exc)
            return None
        return parse_model_plan(text, len(critical_issue_lines(quality)))

    def _repair_plan(self, quality: Dict[str, Any], ctx: Dict[str, Any]) -> RepairDecision:
        """决定这一轮怎么修：规则优先，规则不覆盖才问模型。"""
        return repair_decision(quality, self._model_plan(quality, ctx))

    @classmethod
    def _retry_prompt(cls, original_prompt: str, candidate: str,
                      quality: Dict[str, Any], retry_no: int,
                      action: str = "") -> str:
        return retry_prompt(original_prompt, candidate, quality, retry_no, action)

    # ------------------------------------------------------------- fail-closed
    def _finalize_draft(self, t, ctx: Dict[str, Any], text: str,
                        sources: List[Dict], user_id: str) -> Dict[str, Any]:
        """Final fail-closed guard: a D candidate cannot enter the task/version tables."""
        quality = self._quality_result(
            text, topic=str(ctx.get("title") or ctx.get("topic") or ""))
        assert_acceptable(quality)
        return super()._finalize_draft(t, ctx, text, sources, user_id)

    def _postprocess(self, text: str, ctx: Dict[str, Any]):
        """Guard the exact postprocessed candidate immediately before callers can persist it."""
        processed, events, doc_number, doc_date = super()._postprocess(text, ctx)
        quality = self._quality_result(
            processed, topic=str(ctx.get("title") or ctx.get("topic") or ""))
        assert_acceptable(quality, "后处理后的结果仍存在硬伤，未保存该版本。")
        return processed, events, doc_number, doc_date
