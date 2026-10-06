"""Quality-gated production writing service.

A D-level candidate is never allowed to reach snapshot/commit. The exact QualityGate issues are
fed back to the model and regeneration is attempted at most twice. This layer deliberately sits
above executable ops so draft, full rewrite and local patch all share the same failure policy.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException

from app.application.writing.ops_task_service import OpsWritingTaskService
from app.application.writing.quality_gate import QualityGate

logger = logging.getLogger(__name__)

_MAX_QUALITY_RETRIES = 2


class QualityRetryWritingTaskService(OpsWritingTaskService):
    """Block D-level drafts/revisions and retry with the actual issue list."""

    @staticmethod
    def _quality_result(text: str, topic: str = "") -> Dict[str, Any]:
        return QualityGate().evaluate(text or "", topic=topic or "", body_only=True)

    @staticmethod
    def _critical_issue_lines(quality: Dict[str, Any]) -> List[str]:
        lines: List[str] = []
        for issue in quality.get("issues") or []:
            if not isinstance(issue, dict):
                continue
            if issue.get("severity") != "critical":
                continue
            message = str(issue.get("message") or "").strip()
            if message:
                lines.append(message)
        return lines

    @classmethod
    def _retry_prompt(cls, original_prompt: str, candidate: str,
                      quality: Dict[str, Any], retry_no: int) -> str:
        issues = cls._critical_issue_lines(quality)
        issue_block = "\n".join(f"- {item}" for item in issues) or "- QualityGate 判定为 D 级"
        # Keep enough of the rejected candidate for the model to repair exact repetition/truncation
        # while preventing a pathological output from consuming the whole model context.
        rejected = (candidate or "")[:12000]
        return (
            original_prompt
            + f"\n\n【QualityGate 第 {retry_no} 次修复】\n"
            + "上一版禁止落库，检测到以下硬伤：\n"
            + issue_block
            + "\n必须逐项消除这些问题后重新生成。不得用解释、道歉或占位符代替正文；"
              "不得删除已有事实来规避检查。\n"
            + "【上一版未通过正文】\n"
            + rejected
            + "\n【上一版结束】"
        )

    # -------------------------------------------------------- full/local revise
    def _llm_revise(self, prompt: str, sources, attachment_ctx, user_id) -> str:
        """Generate a revision candidate; D-level output gets at most two issue-driven retries."""
        candidate = super()._llm_revise(prompt, sources, attachment_ctx, user_id)
        quality = self._quality_result(candidate)
        retry_no = 0
        while quality.get("level") == "D" and retry_no < _MAX_QUALITY_RETRIES:
            retry_no += 1
            issues = self._critical_issue_lines(quality)
            logger.warning(
                "[写作质量门] revise D 级，第 %d/%d 次回灌重试：%s",
                retry_no, _MAX_QUALITY_RETRIES, issues,
            )
            retry_prompt = self._retry_prompt(prompt, candidate, quality, retry_no)
            candidate = super()._llm_revise(
                retry_prompt, sources, attachment_ctx, user_id)
            quality = self._quality_result(candidate)

        if quality.get("level") == "D":
            issues = quality.get("issues") or []
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "WRITING_QUALITY_GATE_D",
                    "message": "生成结果连续两次修复后仍存在硬伤，未保存该版本。",
                    "issues": issues,
                    "retry_count": _MAX_QUALITY_RETRIES,
                },
            )
        return candidate

    # -------------------------------------------------------------- draft path
    def _regenerate_if_needed(self, instruction: str, sources,
                              attachment_ctx, user_id,
                              template: Optional[Dict[str, Any]],
                              text: str, ctx: Dict[str, Any]) -> Tuple[str, Optional[str]]:
        """Preserve legacy structural retry, then spend the remaining budget on D-level issues."""
        candidate, legacy_reason = super()._regenerate_if_needed(
            instruction, sources, attachment_ctx, user_id, template, text, ctx)
        retries_used = 1 if legacy_reason else 0
        quality = self._quality_result(
            candidate, topic=str(ctx.get("title") or ctx.get("topic") or ""))
        reasons: List[str] = [legacy_reason] if legacy_reason else []

        while quality.get("level") == "D" and retries_used < _MAX_QUALITY_RETRIES:
            retries_used += 1
            issues = self._critical_issue_lines(quality)
            logger.warning(
                "[写作质量门] draft D 级，第 %d/%d 次回灌重试：%s",
                retries_used, _MAX_QUALITY_RETRIES, issues,
            )
            retry_instruction = self._retry_prompt(
                instruction, candidate, quality, retries_used)
            try:
                candidate = self._llm_draft(
                    retry_instruction,
                    sources,
                    attachment_ctx,
                    user_id,
                    template=template,
                )
                candidate = self._clean_markdown(candidate)
            except Exception as exc:
                logger.warning("[写作质量门] D 级回灌重试调用失败: %s", exc)
                break
            quality = self._quality_result(
                candidate, topic=str(ctx.get("title") or ctx.get("topic") or ""))
            reasons.append(
                f"QualityGate 检测到硬伤，已按具体问题自动修复第 {retries_used} 次。")

        return candidate, ("".join(reasons) if reasons else None)

    def _finalize_draft(self, t, ctx: Dict[str, Any], text: str,
                        sources: List[Dict], user_id: str) -> Dict[str, Any]:
        """Final fail-closed guard: a D candidate cannot enter the task/version tables."""
        quality = self._quality_result(
            text, topic=str(ctx.get("title") or ctx.get("topic") or ""))
        if quality.get("level") == "D":
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "WRITING_QUALITY_GATE_D",
                    "message": "生成结果连续两次修复后仍存在硬伤，未保存该版本。",
                    "issues": quality.get("issues") or [],
                    "retry_count": _MAX_QUALITY_RETRIES,
                },
            )
        return super()._finalize_draft(t, ctx, text, sources, user_id)

    def _postprocess(self, text: str, ctx: Dict[str, Any]):
        """Guard the exact postprocessed candidate immediately before callers can persist it."""
        processed, events, doc_number, doc_date = super()._postprocess(text, ctx)
        quality = self._quality_result(
            processed, topic=str(ctx.get("title") or ctx.get("topic") or ""))
        if quality.get("level") == "D":
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "WRITING_QUALITY_GATE_D",
                    "message": "后处理后的结果仍存在硬伤，未保存该版本。",
                    "issues": quality.get("issues") or [],
                    "retry_count": _MAX_QUALITY_RETRIES,
                },
            )
        return processed, events, doc_number, doc_date
