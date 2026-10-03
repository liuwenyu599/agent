"""Prompt-budget helpers for writing/reference injection.

Style examples must teach structure and phrasing without dumping whole historical
articles into the model context. The extractor is deliberately deterministic: it
keeps first-level headings, a small set of recurring official-writing phrases, and
short opening/closing sentence patterns. Concrete numbers are masked.
"""
from __future__ import annotations

import re
from typing import Dict, Iterable, List

_STYLE_TOTAL_CHAR_BUDGET = 1100  # <= 1.5K tokens under the gateway's conservative estimator
_EXAMPLE_SCAN_BUDGET = 1200
_HEADING_RE = re.compile(
    r"^(?:[一二三四五六七八九十]+[、.]|（[一二三四五六七八九十]+）|\d+[、.．])\s*(.+)$"
)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？；])\s*")
_NUMBER_RE = re.compile(r"(?<![\u4e00-\u9fff])[+-]?\d+(?:\.\d+)?%?")
_DATE_RE = re.compile(r"\d{4}\s*年(?:\d{1,2}\s*月)?(?:\d{1,2}\s*日)?")
_PHRASE_HINTS = (
    "现将", "根据", "按照", "为深入", "为进一步", "坚持", "围绕", "聚焦",
    "一是", "二是", "三是", "四是", "下一步", "下一阶段", "特此报告",
    "妥否，请批示", "以上请示", "请予批复",
)


def _mask_facts(text: str) -> str:
    text = _DATE_RE.sub("××年××月××日", text)
    return _NUMBER_RE.sub("××", text)


def _clean(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", (text or "")).strip()
    text = _mask_facts(text)
    return text[:limit]


def _paragraphs(content: str) -> List[str]:
    return [re.sub(r"\s+", " ", p).strip()
            for p in re.split(r"[\r\n]+", content or "") if p.strip()]


def _bounded_scan(content: str) -> str:
    """Keep a 1200-char scan window while preserving the real opening and closing."""
    content = content or ""
    if len(content) <= _EXAMPLE_SCAN_BUDGET:
        return content
    return content[:900] + "\n" + content[-300:]


def compact_style_example(title: str, content: str, max_chars: int = _STYLE_TOTAL_CHAR_BUDGET) -> str:
    """Convert one historical article into a compact, structured few-shot style card."""
    paragraphs = _paragraphs(content)
    if not paragraphs:
        return ""

    headings: List[str] = []
    for p in paragraphs:
        match = _HEADING_RE.match(p)
        if match:
            value = _clean(match.group(1), 60)
            if value and value not in headings:
                headings.append(value)
        if len(headings) >= 8:
            break

    sentences = [s.strip() for s in _SENTENCE_SPLIT_RE.split(content or "") if s.strip()]
    phrases: List[str] = []
    for sentence in sentences:
        if any(hint in sentence for hint in _PHRASE_HINTS):
            value = _clean(sentence, 90)
            if value and value not in phrases:
                phrases.append(value)
        if len(phrases) >= 6:
            break

    body_paragraphs = [p for p in paragraphs if not _HEADING_RE.match(p)] or paragraphs
    opening = _clean(body_paragraphs[0], 140)
    closing = _clean(body_paragraphs[-1], 140)

    parts = [f"【风格卡：{_clean(title or '范文', 50)}】"]
    if headings:
        parts.append("一级结构骨架：" + " → ".join(headings))
    if phrases:
        parts.append("固定用语/过渡句式：" + "；".join(phrases))
    if opening:
        parts.append("开头模式（只学句式）：" + opening)
    if closing and closing != opening:
        parts.append("结尾模式（只学句式）：" + closing)
    parts.append("使用边界：只模仿结构、套语和语气；其中实体、事实、时间、数字不得迁移到新稿。")
    return "\n".join(parts)[:max_chars]


def compact_style_examples(examples: Iterable[Dict],
                           max_chars: int = _STYLE_TOTAL_CHAR_BUDGET) -> str:
    """Build one structured few-shot card under one shared total budget (top_k=1)."""
    example_list = list(examples or [])[:1]
    if not example_list:
        return ""
    example = example_list[0]
    return compact_style_example(
        str(example.get("title") or "范文"),
        _bounded_scan(str(example.get("content") or "")),
        max_chars=max_chars,
    )[:max_chars]
