"""Quality-gated production writing service.

A D-level candidate is never allowed to reach snapshot/commit. The exact QualityGate issues are
fed back to the model and regeneration is attempted at most twice. This layer deliberately sits
above executable ops so draft, full rewrite and local patch all share the same failure policy.

修复策略不再是「把issue 拼回 prompt 再原样重试」。此前主持词用例反复D 级
（机械重复 + 偏短）却三次用同一策略，是因为重试没有区分问题类型。
现在由 ``_repair_plan`` 依据 issue 文本选定针对性动作：能规则判定的不调模型，
规则不覆盖时才让模型自己读 issue 决定改什么。**步数预算不变（≤2）**，
延迟与改动前同一量级，但重试不再原地打转。
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException

from app.application.writing.ops_task_service import OpsWritingTaskService
from app.application.writing.quality_gate import QualityGate

logger = logging.getLogger(__name__)

_MAX_QUALITY_RETRIES = 2

# issue 文本 → 针对性修复动作。键是 detect_* 产出的稳定前缀，不是易变的中文全句。
# 「机械重复」尤其不能靠原样重试解决：同一句被复用4 次说明分段产出塌缩，
# 必须要求模型改写重复段落而不是再抽一次签。
_RULES: Tuple[Tuple[str, str], ...] = (
    ("机械重复", "定位重复次数最多的句子，改写其中至少两处使表述互不相同；"
                 "禁止仅靠调整段落顺序规避"),
    ("占位符", "把每一处占位符替换为依据检索资料的真实内容；"
               "资料确实不足时删除该句，不要留下任何形式的待填标记"),
    ("提纲式退化", "补回被「略」「同上」顶替的正文，按事项逐条写出具体做法与内容"),
    ("结尾悬空", "补完被截断的末句，使其语义完整且不以虚词或序号收尾"),
    ("乱码", "重新输出含乱码的整段，不要在乱码字符上做局部替换"),
    ("书名号未闭合", "补齐缺失的书名号，或移除不成对的单个书名号"),
    ("空输出", "重新完整生成正文，不要输出空内容或仅含标题"),
)

_FALLBACK = "逐项消除下列硬伤后重新输出完整正文"


class RepairDecision(dict):
    """一次修复决策：动作文本 + 决策来源。来源用于日志与测试断言。"""

    @property
    def action(self) -> str:
        return str(self.get("action") or _FALLBACK)

    @property
    def source(self) -> str:
        return str(self.get("source") or "rule")


class QualityRetryWritingTaskService(OpsWritingTaskService):
    """Block D-level drafts/revisions and retry with a *targeted* repair action."""

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
    def _rule_plan(cls, quality: Dict[str, Any]) -> Optional[str]:
        """按 issue 前缀命中确定性动作；全部命中才返回，避免只修一半。"""
        issues = cls._critical_issue_lines(quality)
        if not issues:
            return None
        actions: List[str] = []
        for message in issues:
            for prefix, action in _RULES:
                if prefix in message:
                    actions.append(action)
                    break
        if not actions or len(actions) != len(issues):
            return None
        return "；".join(dict.fromkeys(actions))

    def _model_plan(self, quality: Dict[str, Any], ctx: Dict[str, Any]) -> Optional[str]:
        """规则覆盖不到时，让模型读 issue 自己决定怎么改。只调用一次，且失败即放弃。"""
        if not self.assistant:
            return None
        issues = self._critical_issue_lines(quality)
        if not issues:
            return None
        doc_type = str(ctx.get("document_type") or "").strip()
        prompt = (
            "下面是自动质检判定出的硬伤，以及一份被拒绝的稿件。"
            "请只回答一件事：针对每条硬伤，下一次重写应该采取什么具体动作。"
            "直接输出动作清单，每行一条，不要重写稿件、不要解释、不要客套。\n\n"
            f"文种：{doc_type or '未指定'}\n"
            + "\n".join(f"- {item}" for item in issues)
        )
        try:
            text = self.assistant.chat(
                message=prompt, history=[], sources=None,
                user_role="user",
                system_prompt=(
                    "你是公文生成质量修复规划器。只输出可执行的动作指令，"
                    "每行一条，不超过 120 字，不输出正文。"
                ),
            ) or ""
        except Exception as exc:  # 模型不可用时退回规则/兜底，绝不让修复链断在这里
            logger.warning("[质量门修复] 模型决策失败，回退兜底动作: %s", exc)
            return None
        lines = [
            re.sub(r"^\s*(?:\d+[.、)]|[-*])\s*", "", ln).strip()
            for ln in text.splitlines()
        ]
        actions = [ln for ln in lines if 4 <= len(ln) <= 120]
        if not actions:
            return None
        return "；".join(actions[:len(issues) + 2])

    def _repair_plan(self, quality: Dict[str, Any], ctx: Dict[str, Any]) -> RepairDecision:
        """决定这一轮怎么修：规则优先，规则不覆盖才问模型。"""
        ruled = self._rule_plan(quality)
        if ruled:
            return RepairDecision(action=ruled, source="rule")
        modeled = self._model_plan(quality, ctx)
        if modeled:
            return RepairDecision(action=modeled, source="model")
        return RepairDecision(action=_FALLBACK, source="fallback")

    @classmethod
    def _retry_prompt(cls, original_prompt: str, candidate: str,
                      quality: Dict[str, Any], retry_no: int,
                      action: str = "") -> str:
        issues = cls._critical_issue_lines(quality)
        issue_block = "\n".join(f"- {item}" for item in issues) or "- QualityGate 判定为 D 级"
        action_block = action or _FALLBACK
        # Keep enough of the rejected candidate for the model to repair exact repetition/truncation
        # while preventing a pathological output from consuming the whole model context.
        rejected = (candidate or "")[:12000]
        return (
            original_prompt
            + f"\n\n【QualityGate 第 {retry_no} 次修复】\n"
            + "上一版禁止落库，检测到以下硬伤：\n"
            + issue_block
            + "\n【本次修复动作】\n"
            + action_block
            + "\n必须逐项消除这些问题后重新生成。不得用解释、道歉或占位符代替正文；"
              "不得删除已有事实来规避检查。\n"
            + "【上一版未通过正文】\n"
            + rejected
            + "\n【上一版结束】"
        )

    # -------------------------------------------------------- full/local revise
    def _llm_revise(self, prompt: str, sources, attachment_ctx, user_id) -> str:
        """Generate a revision candidate; D-level output gets at most two targeted retries."""
        ctx = {"document_type": ""}
        candidate = super()._llm_revise(prompt, sources, attachment_ctx, user_id)
        quality = self._quality_result(candidate)
        retry_no = 0
        while quality.get("level") == "D" and retry_no < _MAX_QUALITY_RETRIES:
            retry_no += 1
            issues = self._critical_issue_lines(quality)
            decision = self._repair_plan(quality, ctx)
            logger.warning(
                "[写作质量门] revise D 级，第 %d/%d 次修复（%s 决策）: %s -> %s",
                retry_no, _MAX_QUALITY_RETRIES, decision.source,
                issues, decision.action,
            )
            retry_prompt = self._retry_prompt(
                prompt, candidate, quality, retry_no, decision.action)
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
            decision = self._repair_plan(quality, ctx)
            logger.warning(
                "[写作质量门] draft D 级，第 %d/%d 次修复（%s 决策）: %s -> %s",
                retries_used, _MAX_QUALITY_RETRIES, decision.source,
                issues, decision.action,
            )
            retry_instruction = self._retry_prompt(
                instruction, candidate, quality, retries_used, decision.action)
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
                logger.warning("[写作质量门] D 级修复重试调用失败: %s", exc)
                break
            quality = self._quality_result(
                candidate, topic=str(ctx.get("title") or ctx.get("topic") or ""))
            reasons.append(
                f"QualityGate 检测到硬伤，已按针对性策略自动修复第 {retries_used} 次"
                f"（{decision.source} 决策）。")

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
