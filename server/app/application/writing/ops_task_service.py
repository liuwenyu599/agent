"""Executable writing operations on top of the grounded writing service.

The semantic interpreter decides *what* the user wants; this layer provides the deterministic
primitives for *how* an operation mutates the document. Local edits never send the whole document
to the model: ``_local_span`` resolves exactly one span, the model is asked only for the
replacement fragment, and ``_splice_local`` puts it back into the authoritative document. If a
target is ambiguous the operation fails closed instead of silently escalating to a full rewrite.

这些原语由异步生产入口（``AsyncWritingTaskService.patch_section_async``）调用；本层不再保留
同步的 patch/chat/revise 副本。
"""
from __future__ import annotations

import re
from typing import List, Optional, Tuple

from app.application.writing.grounded_task_service import GroundedWritingTaskService


_PARAGRAPH_TARGET_RE = re.compile(
    r"第\s*([0-9０-９一二三四五六七八九十百零〇两]+)\s*段"
)
_TOP_HEADING_RE = re.compile(r"^\s*[一二三四五六七八九十百]+、")
_SUB_HEADING_RE = re.compile(r"^\s*[（(][一二三四五六七八九十百]+[）)]")
_NUM_HEADING_RE = re.compile(r"^\s*\d+[\.、．]")
LOCAL_OPERATIONS = ("patch_section", "append_to_section", "insert_paragraph", "delete_range")

_CN_DIGITS = {
    "零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
}


def _cn_number(value: str) -> Optional[int]:
    value = value.strip().translate(str.maketrans("０１２３４５６７８９", "0123456789"))
    if value.isdigit():
        n = int(value)
        return n if n > 0 else None
    if value == "十":
        return 10
    if "百" in value:
        left, _, right = value.partition("百")
        hundreds = _CN_DIGITS.get(left, 1) if left else 1
        tail = _cn_number(right) if right else 0
        return hundreds * 100 + (tail or 0)
    if "十" in value:
        left, _, right = value.partition("十")
        tens = _CN_DIGITS.get(left, 1) if left else 1
        ones = _CN_DIGITS.get(right, 0) if right else 0
        return tens * 10 + ones
    if len(value) == 1:
        return _CN_DIGITS.get(value)
    return None


class OpsWritingTaskService(GroundedWritingTaskService):
    """Production writing service that executes structured writing operations."""

    # ----------------------------------------------------------- target resolve
    @staticmethod
    def _paragraph_spans(text: str) -> List[Tuple[int, int]]:
        """Return non-empty paragraph spans while preserving blank-line separators outside them."""
        spans: List[Tuple[int, int]] = []
        start = 0
        for sep in re.finditer(r"\n[ \t]*\n+", text):
            raw_start, raw_end = start, sep.start()
            while raw_start < raw_end and text[raw_start].isspace():
                raw_start += 1
            while raw_end > raw_start and text[raw_end - 1].isspace():
                raw_end -= 1
            if raw_start < raw_end:
                spans.append((raw_start, raw_end))
            start = sep.end()
        raw_start, raw_end = start, len(text)
        while raw_start < raw_end and text[raw_start].isspace():
            raw_start += 1
        while raw_end > raw_start and text[raw_end - 1].isspace():
            raw_end -= 1
        if raw_start < raw_end:
            spans.append((raw_start, raw_end))
        return spans

    @staticmethod
    def _line_records(text: str) -> List[Tuple[int, int, str]]:
        records: List[Tuple[int, int, str]] = []
        pos = 0
        for raw in text.splitlines(keepends=True):
            end = pos + len(raw)
            records.append((pos, end, raw.rstrip("\r\n")))
            pos = end
        if pos < len(text):
            records.append((pos, len(text), text[pos:]))
        return records

    @classmethod
    def _section_span(cls, text: str, target: str) -> Optional[Tuple[int, int]]:
        target = target.strip()
        records = cls._line_records(text)
        def heading_name(line):
            return re.sub(r"^(?:[一二三四五六七八九十百]+、|[（(][一二三四五六七八九十百]+[）)]|\d+[\.、．])\s*", "", line.strip()).strip()
        matches = [i for i, (_, _, line) in enumerate(records)
                   if (_TOP_HEADING_RE.match(line) or _SUB_HEADING_RE.match(line) or _NUM_HEADING_RE.match(line))
                   and (line.strip() == target or heading_name(line) == target)]
        if len(matches) != 1:
            return None
        idx = matches[0]
        line = records[idx][2]
        if _TOP_HEADING_RE.match(line):
            heading_re = _TOP_HEADING_RE
        elif _SUB_HEADING_RE.match(line):
            heading_re = _SUB_HEADING_RE
        elif _NUM_HEADING_RE.match(line):
            heading_re = _NUM_HEADING_RE
        else:
            return None
        start = records[idx][0]
        end = len(text)
        for j in range(idx + 1, len(records)):
            candidate = records[j][2]
            # Nested sections end at the next sibling or any parent heading.
            if (heading_re.match(candidate)
                    or (heading_re is not _TOP_HEADING_RE and _TOP_HEADING_RE.match(candidate))
                    or (heading_re is _NUM_HEADING_RE and _SUB_HEADING_RE.match(candidate))):
                end = records[j][0]
                while end > start and text[end - 1].isspace():
                    end -= 1
                break
        return (start, end) if start < end else None

    @classmethod
    def _local_span(cls, text, target, operation, position="after", end_target=None):
        if operation == "append_to_section":
            section = cls._section_span(text, target.strip().strip("“”\"'《》"))
            return (section[1], section[1], text[section[0]:section[1]]) if section else None
        resolved = cls._resolve_patch_target(text, target)
        if not resolved:
            return None
        start, end, fragment = resolved
        if operation == "insert_paragraph":
            anchor = start if position == "before" else end
            return anchor, anchor, fragment
        if operation == "delete_range" and end_target:
            last = cls._resolve_patch_target(text, end_target)
            if not last or last[0] < start:
                return None
            end = last[1]
            fragment = text[start:end]
        return start, end, fragment

    @staticmethod
    def _splice_local(current, start, end, replacement, operation):
        if operation in ("append_to_section", "insert_paragraph"):
            left, right = current[:start], current[end:]
            prefix = "\n\n" if left and not left.endswith("\n\n") else ""
            suffix = "\n\n" if right and not right.startswith("\n\n") else ""
            return left + prefix + replacement + suffix + right
        return current[:start] + replacement + current[end:]

    @classmethod
    def _local_prompt(cls, fragment, instruction, mode_desc, operation):
        if operation in ("append_to_section", "insert_paragraph"):
            return (f"请根据用户要求：{instruction}\n参考定位片段：\n{fragment}\n"
                    "只返回要新增的文字，不要重复参考片段，不要改写原文，不要解释或 Markdown 包裹。")
        return cls._build_patch_prompt(fragment, instruction, mode_desc)

    @classmethod
    def _resolve_patch_target(cls, text: str, target: str) -> Optional[Tuple[int, int, str]]:
        """Resolve a tool target to exactly one deterministic span.

        Resolution order is conservative: ordinal paragraph -> exact section heading -> unique
        literal excerpt. Ambiguity returns None and must be clarified; it never becomes a full
        rewrite implicitly.
        """
        target = (target or "").strip().strip("“”\"'《》")
        if not target:
            return None

        m = _PARAGRAPH_TARGET_RE.fullmatch(target)
        if m:
            index = _cn_number(m.group(1))
            spans = cls._paragraph_spans(text)
            if index and index <= len(spans):
                start, end = spans[index - 1]
                return start, end, text[start:end]
            return None

        section = cls._section_span(text, target)
        if section:
            start, end = section
            return start, end, text[start:end]

        # Literal excerpts are useful when the UI sends the user's selected text. Require one and
        # only one occurrence so a repeated sentence can never mutate an arbitrary location.
        if len(target) >= 4 and text.count(target) == 1:
            start = text.index(target)
            end = start + len(target)
            return start, end, text[start:end]
        return None

    @staticmethod
    def _build_patch_prompt(fragment: str, instruction: str, mode_desc: str) -> str:
        return (
            "这是【局部正文修改】操作，不是全文重写。\n"
            f"修改模式：{mode_desc}\n"
            f"用户要求：{instruction}\n\n"
            "【目标片段】\n"
            f"{fragment}\n"
            "【目标片段结束】\n\n"
            "只返回修改后的目标片段本身。禁止返回目标片段之外的正文；禁止补标题、主送机关、"
            "文号、落款或日期；未要求改变的事实必须保留。不要解释，不要 Markdown 包裹。"
        )
