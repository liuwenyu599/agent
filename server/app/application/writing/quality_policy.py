"""D 级硬伤的修复策略与失败策略（单一来源）。

一处定义「修什么、怎么修、修几次、仍不合格怎么报」，供起草、整篇改写、局部修改
三条支路共用。此前这套策略在同步与异步两条链上各写一份，重试预算的计数规则还不
一致（一处把结构性重写折算成 1 次，另一处从 0 开始数），同一条请求走哪条链会得到
不同的修复次数。现在预算、规则表、prompt 拼装、拒收响应都只在这里。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException

from app.application.writing.quality_gate import QualityGate

# 单次产出最多修复 2 次；仍为 D 级则拒绝落库。
MAX_QUALITY_RETRIES = 2

QUALITY_GATE_CODE = "WRITING_QUALITY_GATE_D"

# issue 文本 → 针对性修复动作。键是 detect_* 产出的稳定前缀，不是易变的中文全句。
# 「机械重复」尤其不能靠原样重试解决：同一句被复用 4 次说明分段产出塌缩，
# 必须要求模型改写重复段落而不是再抽一次签。
RULES: Tuple[Tuple[str, str], ...] = (
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

FALLBACK_ACTION = "逐项消除下列硬伤后重新输出完整正文"

MODEL_PLAN_SYSTEM = (
    "你是公文生成质量修复规划器。只输出可执行的动作指令，"
    "每行一条，不超过 120 字，不输出正文。"
)


class RepairDecision(dict):
    """一次修复决策：动作文本 + 决策来源。来源用于日志与测试断言。"""

    @property
    def action(self) -> str:
        return str(self.get("action") or FALLBACK_ACTION)

    @property
    def source(self) -> str:
        return str(self.get("source") or "rule")


def quality_result(text: str, topic: str = "", *, document_type: str = "",
                   word_count_target: Optional[int] = None) -> Dict[str, Any]:
    """Evaluate one candidate through the shared gate with all task-level constraints."""
    return QualityGate().evaluate(
        text or "", topic=topic or "", body_only=True,
        document_type=document_type or "", word_count_target=word_count_target,
    )


def critical_issue_lines(quality: Dict[str, Any]) -> List[str]:
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


def rule_plan(quality: Dict[str, Any]) -> Optional[str]:
    """按 issue 前缀命中确定性动作；全部命中才返回，避免只修一半。"""
    issues = critical_issue_lines(quality)
    if not issues:
        return None
    actions: List[str] = []
    for message in issues:
        for prefix, action in RULES:
            if prefix in message:
                actions.append(action)
                break
    if not actions or len(actions) != len(issues):
        return None
    return "；".join(dict.fromkeys(actions))


def model_plan_prompt(quality: Dict[str, Any], ctx: Dict[str, Any]) -> Optional[str]:
    """规则覆盖不到时，请模型读 issue 决定怎么改。"""
    issues = critical_issue_lines(quality)
    if not issues:
        return None
    doc_type = str(ctx.get("document_type") or "").strip()
    return (
        "下面是自动质检判定出的硬伤，以及一份被拒绝的稿件。"
        "请只回答一件事：针对每条硬伤，下一次重写应该采取什么具体动作。"
        "直接输出动作清单，每行一条，不要重写稿件、不要解释、不要客套。\n\n"
        f"文种：{doc_type or '未指定'}\n"
        + "\n".join(f"- {item}" for item in issues)
    )


def parse_model_plan(text: str, issue_count: int) -> Optional[str]:
    """把模型输出的动作清单收敛成一行动作串；可用行不足则放弃。"""
    import re

    lines = [
        re.sub(r"^\s*(?:\d+[.、)]|[-*])\s*", "", ln).strip()
        for ln in (text or "").splitlines()
    ]
    actions = [ln for ln in lines if 4 <= len(ln) <= 120]
    if not actions:
        return None
    return "；".join(actions[:issue_count + 2])


def repair_decision(quality: Dict[str, Any], model_action: Optional[str]) -> RepairDecision:
    """规则优先；规则无法全覆盖时采用模型给出的动作；都没有则用兜底动作。"""
    ruled = rule_plan(quality)
    if ruled:
        return RepairDecision(action=ruled, source="rule")
    if model_action:
        return RepairDecision(action=model_action, source="model")
    return RepairDecision(action=FALLBACK_ACTION, source="fallback")


def retry_prompt(original_prompt: str, candidate: str, quality: Dict[str, Any],
                 retry_no: int, action: str = "") -> str:
    issues = critical_issue_lines(quality)
    issue_block = "\n".join(f"- {item}" for item in issues) or "- QualityGate 判定为 D 级"
    action_block = action or FALLBACK_ACTION
    # 保留足够长的被拒稿，让模型能精确修掉重复句/截断句，同时不让异常输出吃满上下文。
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


def raise_quality_gate(quality: Dict[str, Any], message: str) -> None:
    """D 级产出拒绝落库：统一的 422 响应，供三条支路复用。"""
    raise HTTPException(
        status_code=422,
        detail={
            "code": QUALITY_GATE_CODE,
            "message": message,
            "issues": quality.get("issues") or [],
            "retry_count": MAX_QUALITY_RETRIES,
        },
    )


def assert_acceptable(quality: Dict[str, Any],
                      message: str = "生成结果连续两次修复后仍存在硬伤，未保存该版本。") -> None:
    if quality.get("level") == "D":
        raise_quality_gate(quality, message)
