# -*- coding: utf-8 -*-
"""大模型输出的「宽容 JSON 解析」工具。

背景
----
大模型的 JSON 输出并不可靠，常见的畸形包括：

- 前后带 markdown 代码围栏（```json ... ```）或客套话（"好的，结果如下："）；
- JSON 之后又追加说明文字（"以上就是本次大纲，请查收。"）；
- 尾随逗号（``["x",]`` / ``{"a":1,}``）；
- 字符串内部出现**未转义的裸换行 / 制表符**；
- 使用中文/全角引号 “ ” ‘ ’ 充当 JSON 分隔符；
- 被 ``max_tokens`` 截断，末尾缺少闭合括号；
- 夹杂 ``//`` 行注释或 ``/* */`` 块注释。

旧代码普遍使用 ``re.search(r"\\{.*\\}", raw, re.S) + json.loads()``：
正则**贪婪**匹配会一路吃到最后一个 ``}``（把 JSON 后面的说明文字一起吞进来），
而 ``json.loads`` 对上述任何一种畸形都是**零容错**，直接抛
``json.JSONDecodeError``，最终变成用户看到的
"Expecting property name enclosed in double quotes: line 1 column N (char M)"。

本模块提供：

- :func:`extract_json_object` / :func:`extract_json_array` / :func:`extract_json_block`
  基于**括号配平扫描**（正确处理字符串内的花括号与转义）提取完整 JSON 片段；
- :func:`loads_lenient` 按「原样 → 轻度清洗 → 控制字符转义 → 截断修复」的顺序
  逐级抢救，全部失败抛 :class:`LLMJsonError`（携带原始输出首尾片段，便于排查）；
- :func:`truncate_for_log` 用于把原始模型输出安全地写进日志。

用法约定：**原始模型输出只进日志，不回传客户端**。调用方应捕获异常后给出
用户可读的提示文案。

Author: Alex (Engineer)
"""
from __future__ import annotations

import json
import re
from typing import Any, Iterator, List, Optional

__all__ = [
    "LLMJsonError",
    "extract_json_object",
    "extract_json_array",
    "extract_json_block",
    "loads_lenient",
    "loads_llm_object",
    "truncate_for_log",
]

# 代码围栏：```json / ```JSON / ``` 均可，允许围栏后有语言标记与换行
_FENCE_RE = re.compile(r"```[ \t]*[A-Za-z0-9_+-]*[ \t]*\r?\n?(?P<body>.*?)(?:```|\Z)", re.S)
# 只出现开头、没有闭合的围栏（输出被截断时常见）
_FENCE_HEAD_RE = re.compile(r"^[ \t]*```[ \t]*[A-Za-z0-9_+-]*[ \t]*\r?\n?")

# 中文/全角引号
_LDQUO = "\u201c"  # “
_RDQUO = "\u201d"  # ”
_LSQUO = "\u2018"  # ‘
_RSQUO = "\u2019"  # ’

# 截断回退的最大次数（每次回退 = 砍掉最后一个不完整的成员）
_MAX_TRUNCATION_REWIND = 5


class LLMJsonError(ValueError):
    """模型输出无法解析为 JSON（已尝试全部抢救策略）。

    Attributes:
        message: 面向排查的简短说明（含 json 原始错误）。
        raw_preview: 原始输出的首尾片段（头 400 字 + 尾 200 字）。
    """

    def __init__(self, message: str, raw_preview: str = "") -> None:
        self.raw_preview = raw_preview or ""
        full = message
        if self.raw_preview:
            full = f"{message} | 原始输出片段：{self.raw_preview}"
        super().__init__(full)
        self.message = message


def truncate_for_log(text: Optional[str], limit: int = 800) -> str:
    """把可能很长的模型输出安全地截断，供日志使用。

    Args:
        text: 原始文本，可为 None。
        limit: 最大保留字符数。

    Returns:
        截断后的单行文本；None 返回空串。
    """
    if not text:
        return ""
    flat = " ".join(str(text).split())
    if len(flat) <= limit:
        return flat
    return f"{flat[:limit]}…(已截断，共 {len(flat)} 字)"


def _strip_bom(text: str) -> str:
    """去掉 BOM 与首尾空白。"""
    return (text or "").lstrip("\ufeff").strip()


def _strip_fences(text: str) -> str:
    """剥掉 markdown 代码围栏，返回围栏内的正文。

    支持：完整围栏、只有开头没有结尾的围栏（截断场景）、围栏内还有多余空行。
    没有围栏时原样返回。
    """
    if not text:
        return ""
    match = _FENCE_RE.search(text)
    if match:
        body = (match.group("body") or "").strip()
        if body:
            return body
    # 未闭合围栏（或围栏标记本身无内容）→ 只去掉开头的围栏行
    return _FENCE_HEAD_RE.sub("", text).strip()


def _scan_balanced(text: str, open_ch: str, close_ch: str) -> Optional[str]:
    """扫描出第一个**完整闭合**的括号片段（正确处理字符串与转义）。

    Args:
        text: 待扫描文本。
        open_ch: 开括号，``{`` 或 ``[``。
        close_ch: 闭括号，``}`` 或 ``]``。

    Returns:
        包含首尾括号的完整片段；找不到完整闭合片段时返回 None。
    """
    start = -1
    depth = 0
    in_string = False
    escape = False
    for i, ch in enumerate(text):
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            continue
        if ch == open_ch:
            if depth == 0:
                start = i
            depth += 1
        elif ch == close_ch:
            if depth > 0:
                depth -= 1
                if depth == 0 and start >= 0:
                    return text[start:i + 1]
    return None


def extract_json_object(text: str) -> Optional[str]:
    """提取第一个完整闭合的 JSON 对象片段（含最外层 ``{}``）。

    Args:
        text: 模型原始输出（可含围栏 / 前后废话）。

    Returns:
        形如 ``{"a":1}`` 的原始字符串；没有完整对象时返回 None。
        调用方需自行 :func:`json.loads` 或 :func:`loads_lenient`。
    """
    return _scan_balanced(_strip_fences(_strip_bom(text) or ""), "{", "}")


def extract_json_array(text: str) -> Optional[str]:
    """提取第一个完整闭合的 JSON 数组片段（含最外层 ``[]``）。"""
    return _scan_balanced(_strip_fences(_strip_bom(text) or ""), "[", "]")


def extract_json_block(text: str) -> Optional[str]:
    """提取第一个完整闭合的 JSON 片段（对象或数组，取先出现者）。"""
    cleaned = _strip_fences(_strip_bom(text) or "")
    if not cleaned:
        return None
    obj = _scan_balanced(cleaned, "{", "}")
    arr = _scan_balanced(cleaned, "[", "]")
    if obj and arr:
        return obj if cleaned.find("{") <= cleaned.find("[") else arr
    return obj or arr


def _basic_clean(text: str) -> str:
    """轻度清洗：注释、尾随逗号、中文引号。

    全程维护「是否在字符串内」状态，因此**不会**误伤字符串内部的
    ``//``（如 URL）、``“ ”``（如正文引用）等字符。
    """
    if not text:
        return ""
    out: List[str] = []
    i = 0
    n = len(text)
    in_string = False
    escape = False
    closing = '"'
    while i < n:
        ch = text[i]
        if in_string:
            out.append(ch)
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == closing:
                out[-1] = '"'  # 全角闭引号统一写成 ASCII 引号
                in_string = False
            i += 1
            continue

        # ---- 不在字符串内 ----
        if ch == '"':
            out.append('"')
            in_string = True
            closing = '"'
            i += 1
            continue
        if ch == _LDQUO:                      # “ 充当字符串开头
            out.append('"')
            in_string = True
            closing = _RDQUO
            i += 1
            continue
        if ch in (_LSQUO, _RSQUO):            # ‘ ’ 充当字符串定界
            out.append('"')
            in_string = True
            closing = _RSQUO
            i += 1
            continue
        if text.startswith("//", i):          # 行注释
            nl = text.find("\n", i)
            i = n if nl < 0 else nl           # 保留换行符本身
            continue
        if text.startswith("/*", i):          # 块注释
            end = text.find("*/", i + 2)
            i = n if end < 0 else end + 2
            continue
        if ch == ",":                         # 尾随逗号
            if _next_meaningful_is_close(text, i + 1):
                i += 1
                continue
            out.append(ch)
            i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _next_meaningful_is_close(text: str, pos: int) -> bool:
    """判断 ``pos`` 之后（跳过空白与注释）是否为 ``}`` 或 ``]``。"""
    n = len(text)
    while pos < n:
        ch = text[pos]
        if ch in " \t\r\n":
            pos += 1
            continue
        if text.startswith("//", pos):
            nl = text.find("\n", pos)
            pos = n if nl < 0 else nl + 1
            continue
        if text.startswith("/*", pos):
            end = text.find("*/", pos + 2)
            pos = n if end < 0 else end + 2
            continue
        return ch in "}]"
    return False


def _escape_control_chars(text: str) -> str:
    """把**字符串内部**的裸控制字符转成合法转义。

    仅处理处于字符串内部的 ``\\n`` / ``\\r`` / ``\\t`` 及其他 < 0x20 的字符；
    合法 JSON 里作为缩进的换行位于字符串之外，不受影响。
    """
    if not text:
        return ""
    out: List[str] = []
    in_string = False
    escape = False
    for ch in text:
        if in_string:
            if escape:
                out.append(ch)
                escape = False
                continue
            if ch == "\\":
                out.append(ch)
                escape = True
                continue
            if ch == '"':
                in_string = False
                out.append(ch)
                continue
            if ch == "\n":
                out.append("\\n")
                continue
            if ch == "\r":
                out.append("\\r")
                continue
            if ch == "\t":
                out.append("\\t")
                continue
            if ord(ch) < 0x20:
                out.append("\\u%04x" % ord(ch))
                continue
            out.append(ch)
            continue
        if ch == '"':
            in_string = True
        out.append(ch)
    return "".join(out)


def _close_open_brackets(text: str) -> Optional[str]:
    """为被截断的文本补齐缺失的闭合括号。

    Args:
        text: 截断后的文本。

    Returns:
        补齐闭合括号后的文本；若结尾停在**未闭合的字符串内部**返回 None。
    """
    stack: List[str] = []
    in_string = False
    escape = False
    for ch in text:
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch in "{[":
            stack.append(ch)
        elif ch in "}]":
            if stack:
                stack.pop()
    if in_string or not stack:
        return None
    closers = "".join("}" if c == "{" else "]" for c in reversed(stack))
    return text + closers


def _last_safe_cut(text: str) -> Optional[int]:
    """返回最后一个「安全回退点」的下标（该位置之前的文本可独立成结构）。

    候选位置：字符串外的 ``,``、字符串外的 ``{`` / ``[``、以及开启字符串的 ``"``。
    用于在截断修复时砍掉最后一个不完整的成员。
    """
    positions: List[int] = []
    in_string = False
    escape = False
    depth = 0
    for i, ch in enumerate(text):
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            positions.append(i)
            continue
        if ch in "{[":
            depth += 1
            positions.append(i)
        elif ch in "}]":
            depth = max(0, depth - 1)
        elif ch == "," and depth >= 1:
            positions.append(i)
    return positions[-1] if positions else None


def _truncation_candidates(text: str) -> Iterator[str]:
    """生成「被 max_tokens 截断」场景下的修复候选（由优到劣）。

    每一轮先尝试直接补齐缺失的右括号；失败则从后往前砍掉最后一个不完整的
    成员再补，最多回退 :data:`_MAX_TRUNCATION_REWIND` 次。
    """
    if not text:
        return
    current = text.rstrip()
    for _ in range(_MAX_TRUNCATION_REWIND + 1):
        closed = _close_open_brackets(current)
        if closed is not None and ":" in closed:
            yield closed
        cut = _last_safe_cut(current)
        if cut is None or cut <= 0:
            return
        current = current[:cut].rstrip().rstrip(",").rstrip()
        if not current:
            return


def _candidate_bases(text: str) -> List[str]:
    """按优先级生成待解析的「基础文本」：原样 → 去围栏 → 配平提取片段。"""
    raw = _strip_bom(text or "")
    if not raw:
        return []
    fenced = _strip_fences(raw)
    block = extract_json_block(fenced) or ""
    bases: List[str] = [raw]
    for candidate in (fenced, block):
        if candidate and candidate not in bases:
            bases.append(candidate)
    return bases


def _repair_variants(base: str) -> List[str]:
    """对一个基础文本生成逐级加码的修复变体（保持顺序，去重）。"""
    variants: List[str] = []
    cleaned = _basic_clean(base)
    for variant in (base, cleaned, _escape_control_chars(cleaned), _escape_control_chars(base)):
        if variant and variant not in variants:
            variants.append(variant)
    return variants


def loads_lenient(text: str) -> Any:
    """宽容解析模型输出的 JSON。

    按以下顺序尝试，任一步成功即返回：
      1. 原样 ``json.loads``（保证正常 JSON 100% 原样解析，不受任何清洗影响）；
      2. 剥掉 markdown 代码围栏后重试；
      3. 括号配平提取出第一个完整 JSON 片段后重试；
      4. 轻度清洗（去注释、去尾随逗号、中文引号转 ASCII）后重试；
      5. 转义字符串内部的裸换行 / 制表符等控制字符后重试；
      6. 截断修复：补齐缺失的右括号，必要时从后往前砍掉不完整的成员
         （最多回退 5 次）。

    Args:
        text: 模型返回的原始文本。

    Returns:
        解析出的 Python 对象（dict / list / 标量）。

    Raises:
        LLMJsonError: 全部策略均失败。异常信息含 json 原始错误与原始输出的
            首尾片段，便于定位模型到底吐了什么。
    """
    bases = _candidate_bases(text)
    if not bases:
        raise LLMJsonError("模型返回内容为空，无法解析", "")

    last_error: Optional[BaseException] = None
    seen: set = set()

    def _try(candidate: str) -> Optional[Any]:
        nonlocal last_error
        if not candidate or candidate in seen:
            return None
        seen.add(candidate)
        try:
            return json.loads(candidate)
        except ValueError as err:      # 只捕获解析类错误，其它异常照常抛出
            last_error = err
            return None

    for base in bases:
        for variant in _repair_variants(base):
            parsed = _try(variant)
            if parsed is not None:
                return parsed

    # 截断修复（放在最后，避免把本可正常解析的内容误判为截断）
    for base in bases:
        repaired = _basic_clean(base)
        for candidate in _truncation_candidates(repaired):
            parsed = _try(candidate)
            if parsed is not None:
                return parsed

    raw_original = _strip_bom(text or "")
    if len(raw_original) > 600:
        preview = f"{raw_original[:400]} …(略)… {raw_original[-200:]}"
    else:
        preview = raw_original
    raise LLMJsonError(f"模型返回的内容无法解析为 JSON：{last_error}", preview)


def loads_llm_object(text: str, default: Optional[dict] = None) -> Optional[dict]:
    """宽容解析并取得一个 dict；解析失败或不是对象时返回 ``default``。

    适用于「解析不出来就降级放行」的场景（如生成前预检、意图判断）。

    Args:
        text: 模型返回的原始文本。
        default: 解析失败时的返回值，默认 None。

    Returns:
        解析出的 dict，或 ``default``。
    """
    if not text or not text.strip():
        return default
    try:
        parsed = loads_lenient(text)
    except LLMJsonError:
        return default
    return parsed if isinstance(parsed, dict) else default
