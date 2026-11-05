"""用户明确说出的写法约束（不分段、精简）的单一解析处。

模型会把「不要分段」当成泛泛的建议忽略，所以这里做三件事：
1. 把自由表述解析成结构化指令（可撤销，例如「还是要分段」）；
2. 生成可进提示词的硬性约束块，起草与修改共用同一份措辞；
3. 提供确定性收尾：模型仍然输出「一、二、三」小标题时，把编号标题并入
   相邻自然段，保证用户看到的要求真的落到正文上。

这里只处理「怎么写」，不碰「写什么」：事实、数字、对象一律不参与。
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Tuple

# 明显在要求重新出一版时，不要把它误判成对现有稿件的修改。
DRAFT_REQUEST_RE = re.compile(
    r"(?:重新|再|另|从新)(?:生成|写|做|来|起草)|继续生成|再生成|重写一份|重做一份|"
    r"换个版本|换一版|再来一版|另起一版|按(?:这些|当前)?参数(?:重新)?生成|开始写|写吧")

_NO_SECTION_RE = re.compile(
    r"(?:不要|不用|不必|别|无需|不需要|禁止|勿)(?:再)?(?:分段|分节|分点|分层|划分段落|"
    r"加小标题|写小标题|列小标题|用[一二三四五六七八九十]、)|"
    r"一段到底|通篇一段|合成一段|全文一段|只写一段|不要另起段")
_SECTION_RESTORE_RE = re.compile(
    r"(?:还是|可以|需要|恢复|继续)(?:分段|分节|分点|用小标题)|"
    r"按[一二三四五六七八九十]、|分条(?:写|列|来)")

_CONCISE_RE = re.compile(r"(?:精简|简洁|精炼|简练|压缩|缩短|简短|篇幅短|写短)")
_EXPAND_RE = re.compile(r"(?:详细|展开|写长|加长|具体一点|具体一些|再充实)")

# 行首编号：一、 （一） (1) 1. 1、 ①
_SECTION_LINE_RE = re.compile(
    r"^[ \t　]*(?:[一二三四五六七八九十]+[、．.]|[（(][一二三四五六七八九十]+[）)]|"
    r"\d+[、．.]|[①-⑳])[ \t　]*(?P<label>.*)$")


def parse_directives(text: str) -> Dict[str, bool]:
    """解析一句话里明确表达的写法约束；未提及的键不出现。"""
    utterance = re.sub(r"\s+", "", text or "")
    flags: Dict[str, bool] = {}
    if _NO_SECTION_RE.search(utterance):
        flags["no_section"] = True
    elif _SECTION_RESTORE_RE.search(utterance):
        flags["no_section"] = False
    if _CONCISE_RE.search(utterance):
        flags["concise"] = True
    elif _EXPAND_RE.search(utterance):
        flags["concise"] = False
    return flags


def merge_directives(current: Any, update: Dict[str, bool]) -> Dict[str, bool]:
    """把新指令叠加到任务上已有的约束；显式撤销优先于沿用。"""
    merged = dict(current) if isinstance(current, dict) else {}
    for key, value in (update or {}).items():
        merged[key] = bool(value)
    return {key: value for key, value in merged.items() if value}


def constraint_lines(flags: Any) -> List[str]:
    """转成提示词里的硬性约束；没有约束时返回空列表。"""
    if not isinstance(flags, dict):
        return []
    lines: List[str] = []
    if flags.get("no_section"):
        lines.append(
            "【硬性约束·不分段】全文只写连续的自然段，禁止出现「一、」「（一）」「1.」"
            "等编号小标题，也不要用单独一行充当小标题；原文已有的编号标题必须并入"
            "相邻自然段，不得保留。")
    if flags.get("concise"):
        lines.append(
            "【硬性约束·精简】在不删事实、不减少必要信息的前提下压缩表述："
            "删掉套话、重复和铺垫，句子能短则短。")
    return lines


def looks_like_draft_request(text: str) -> bool:
    """这句话是不是在要求重新出一版（而不是改现在这版）。"""
    return bool(DRAFT_REQUEST_RE.search(re.sub(r"\s+", "", text or "")))


def _join_label(label: str, paragraph: str) -> str:
    label = label.strip().rstrip("：:。；;，,")
    paragraph = paragraph.strip()
    if not label:
        return paragraph
    if not paragraph:
        return label
    return f"{label}，{paragraph}"


def merge_section_labels(text: str, max_label: int = 14) -> Tuple[str, int]:
    """把编号小标题并入下一自然段，返回 (新正文, 合并处数)。

    只在用户明确要求不分段时调用。短标题（≤14 字、无句末标点）作为话题并入下段；
    过长或本身成句的标题只去掉编号，避免把正常段落塞进别的段落。
    """
    if not text:
        return text, 0
    lines = text.splitlines()
    output: List[str] = []
    merged = 0
    index = 0
    while index < len(lines):
        line = lines[index]
        match = _SECTION_LINE_RE.match(line)
        if not match:
            output.append(line)
            index += 1
            continue
        label = match.group("label").strip()
        if label and len(label) <= max_label and label[-1] not in "。；！？，,":
            cursor = index + 1
            while cursor < len(lines) and not lines[cursor].strip():
                cursor += 1
            if cursor < len(lines):
                output.append(_join_label(label, lines[cursor]))
                merged += 1
                index = cursor + 1
                continue
        output.append(label)
        index += 1
    return "\n".join(output), merged


def unnumber_headings(text: str) -> str:
    """兜底：标题没有可并入的下一段时，至少去掉编号，不再像分节。"""
    merged, _count = merge_section_labels(text)
    return merged


__all__ = [
    "constraint_lines",
    "looks_like_draft_request",
    "merge_directives",
    "merge_section_labels",
    "parse_directives",
    "unnumber_headings",
]
