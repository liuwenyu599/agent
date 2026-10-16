"""Deterministic admission rules for the expensive writing-agent graph."""
from __future__ import annotations

import hashlib
import re
from typing import Any, Mapping


_GROUNDING_CUES = (
    "依据", "根据", "结合", "引用", "法规", "政策", "案例", "数据", "文号",
    "统计", "材料", "范文", "知识库", "附件",
)
_CONSTRAINT_CUES = (
    "面向", "主送", "落款", "口径", "不得", "必须", "不少于", "不超过",
    "重点", "同时", "并且", "分别",
)


def _original_request(context: Mapping[str, Any]) -> str:
    for item in context.get("history") or []:
        if isinstance(item, Mapping) and item.get("role") == "user" and item.get("content"):
            return str(item["content"])
    return str(context.get("requirements") or "")


def classify_writing_route(
    context: Mapping[str, Any],
    outline_only: bool = False,
    has_attachments: bool = False,
) -> str:
    """Return ``agent`` only when the task benefits from extra planning/tool calls."""
    if outline_only:
        return "fast"
    try:
        target = int(context.get("word_count_target") or 0)
    except (TypeError, ValueError):
        target = 0
    if target >= 1800 or bool(context.get("kb_ids")) or bool(context.get("template_id")):
        return "agent"
    if has_attachments:
        return "agent"
    request = _original_request(context)
    if any(cue in request for cue in _GROUNDING_CUES):
        return "agent"
    constraint_hits = sum(1 for cue in _CONSTRAINT_CUES if cue in request)
    numeric_constraints = len(re.findall(r"\d+(?:\.\d+)?(?:%|字|页|项|个|万元|元)?", request))
    return "agent" if constraint_hits >= 3 or numeric_constraints >= 3 else "fast"


def graph_enabled_for_user(settings: Any, user_id: str) -> bool:
    """Apply the feature flag and stable per-user rollout without storing a cohort."""
    if not bool(getattr(settings, "WRITING_AGENT_GRAPH_ENABLED", False)):
        return False
    percent = max(0, min(100, int(getattr(settings, "WRITING_AGENT_ROLLOUT_PERCENT", 0))))
    if percent >= 100:
        return True
    if percent <= 0:
        return False
    bucket = int(hashlib.sha256(user_id.encode("utf-8")).hexdigest()[:8], 16) % 100
    return bucket < percent
