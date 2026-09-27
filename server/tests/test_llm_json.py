# -*- coding: utf-8 -*-
"""app.core.llm_json 的单元测试：覆盖模型常见的 7 类畸形输出。

回归目标：
1. 正常 JSON 必须 100% 原样解析成功（不能被任何"清洗"逻辑破坏）；
2. 尾随逗号 / 字符串内裸换行 / JSON 后追加说明 / markdown 围栏 / 截断 /
   中文引号 等真实畸形必须能被抢救回来。
"""
import json

import pytest

from app.core.llm_json import (
    LLMJsonError,
    extract_json_array,
    extract_json_block,
    extract_json_object,
    loads_lenient,
    loads_llm_object,
    truncate_for_log,
)

# --- 正常基线：合法 JSON（含嵌套、转义、Unicode、格式化换行） ---
VALID_OUTLINE = {
    "title": "白云区司法局年度工作汇报",
    "subtitle": "2025 年度",
    "slides": [
        {"type": "cover", "title": "封面", "subtitle": "副标题"},
        {"type": "content", "title": "第一页",
         "points": ["含\"引号\"与\\反斜杠的要点", "第二条"], "blocks": {"a": 1}},
    ],
}


def test_valid_json_parsed_verbatim():
    """正常 JSON 原样解析，且嵌套/转义/Unicode 完全不被改写。"""
    text = json.dumps(VALID_OUTLINE, ensure_ascii=False)
    assert loads_lenient(text) == VALID_OUTLINE

    pretty = json.dumps(VALID_OUTLINE, ensure_ascii=False, indent=2)
    assert loads_lenient(pretty) == VALID_OUTLINE


def test_valid_json_with_real_newline_outside_string():
    """格式化换行（位于字符串之外）不得被误转义。"""
    text = '{\n  "a": 1,\n  "b": [1, 2]\n}'
    assert loads_lenient(text) == {"a": 1, "b": [1, 2]}


# --- 畸形 1：尾随逗号 ---
def test_trailing_comma():
    text = '{"slides":[{"title":"a","points":["x",],}]}'
    assert loads_lenient(text) == {"slides": [{"title": "a", "points": ["x"]}]}


def test_trailing_comma_after_comment():
    """逗号后紧跟注释再闭合，也应去掉。"""
    text = '{"a":1, // 末尾注释\n}'
    assert loads_lenient(text) == {"a": 1}


# --- 畸形 2：字符串内裸换行 / 制表符 ---
def test_raw_newline_inside_string():
    text = '{"title":"第一行\n第二行","points":[]}'
    assert loads_lenient(text) == {"title": "第一行\n第二行", "points": []}


def test_raw_tab_inside_string():
    text = '{"title":"a\tb","points":[]}'
    assert loads_lenient(text) == {"title": "a\tb", "points": []}


# --- 畸形 3：JSON 后追加说明文字（旧贪婪正则的典型炸点） ---
def test_trailing_prose():
    text = '{"slides":[]} 以上就是本次大纲，请查收。'
    assert loads_lenient(text) == {"slides": []}


def test_leading_prose_and_trailing_prose():
    text = '好的，大纲如下：\n{"slides":[{"title":"a"}]}\n希望对你有帮助！'
    assert loads_lenient(text) == {"slides": [{"title": "a"}]}


def test_trailing_prose_containing_brace():
    """JSON 后的说明文字里带 } —— 旧贪婪正则会把这段一起吞掉导致失败。"""
    text = '{"slides":[]} 说明：本页 {图} 见附件'
    assert loads_lenient(text) == {"slides": []}


# --- 畸形 4：markdown 围栏 ---
def test_markdown_fence():
    text = '```json\n{"slides":[]}\n```'
    assert loads_lenient(text) == {"slides": []}


def test_markdown_fence_no_lang_and_unclosed():
    assert loads_lenient('```\n{"a":1}\n```') == {"a": 1}
    assert loads_lenient('```json\n{"a":1}') == {"a": 1}


# --- 畸形 5：被 max_tokens 截断 ---
def test_truncated_object():
    text = '{"slides":[{"title":"a","points":["x"]'
    result = loads_lenient(text)
    assert isinstance(result, dict)
    assert result["slides"][0]["title"] == "a"
    assert result["slides"][0]["points"] == ["x"]


def test_truncated_mid_value():
    """截在半截字符串上：回退一个成员后仍应救回前面的完整内容。"""
    text = '{"title":"汇报","slides":[{"title":"a"},{"title":"半截'
    result = loads_lenient(text)
    assert isinstance(result, dict)
    assert result["slides"][0]["title"] == "a"


# --- 畸形 6：中文/全角引号 ---
def test_curly_double_quotes():
    text = '{“slides”:[]}'
    assert loads_lenient(text) == {"slides": []}


def test_curly_quotes_with_content():
    text = '{“title”:“第一行\n第二行”,“points”:[“甲”,“乙”]}'
    assert loads_lenient(text) == {"title": "第一行\n第二行", "points": ["甲", "乙"]}


def test_curly_quote_inside_string_is_preserved():
    """正文里的中文引号属于内容，不得被改成 ASCII 引号。"""
    text = '{"title":"他说“你好”","points":[]}'
    assert loads_lenient(text) == {"title": "他说“你好”", "points": []}


def test_url_slashes_inside_string_are_preserved():
    """字符串内的 //（URL）不能被当成注释删掉。"""
    text = '{"url":"http://example.com/a","points":[]}'
    assert loads_lenient(text) == {"url": "http://example.com/a", "points": []}


# --- 组合畸形（真实场景往往是叠加的） ---
def test_fence_plus_prose_plus_trailing_comma():
    text = '```json\n{"slides":[{"title":"a","points":["x",],},]}\n```\n以上，请查收。'
    assert loads_lenient(text) == {"slides": [{"title": "a", "points": ["x"]}]}


def test_block_comment_outside_string():
    text = '{"a":1 /* 说明 */, "b":2}'
    assert loads_lenient(text) == {"a": 1, "b": 2}


# --- 提取函数 ---
def test_extract_json_object_and_array():
    assert extract_json_object('废话 {"a":{"b":1}} 尾') == '{"a":{"b":1}}'
    assert extract_json_object('没有 JSON') is None
    assert extract_json_object('{"a":1 缺闭合') is None
    assert extract_json_array('结果：[{"a":1},{"b":2}] 完') == '[{"a":1},{"b":2}]'
    assert extract_json_block('x {"a":1} y [2]') == '{"a":1}'


def test_extract_respects_braces_in_string():
    """字符串内的花括号不得被当作结构括号。"""
    assert extract_json_object('{"t":"a{b}c"}') == '{"t":"a{b}c"}'


# --- 降级与异常 ---
def test_loads_llm_object_returns_default_on_failure():
    assert loads_llm_object('完全没有 JSON', default={"ok": True}) == {"ok": True}
    assert loads_llm_object('[1,2]', default=None) is None
    assert loads_llm_object('{"a":1}') == {"a": 1}


def test_error_is_diagnosable():
    """不可救药的输入必须抛出带原始片段的可诊断异常。"""
    bad = "完全不是 JSON 的一段话" * 60
    with pytest.raises(LLMJsonError) as exc:
        loads_lenient(bad)
    assert "无法解析为 JSON" in str(exc.value)
    assert exc.value.raw_preview  # 带上了原始输出片段供排查


def test_empty_input_raises():
    with pytest.raises(LLMJsonError):
        loads_lenient("")


def test_truncate_for_log():
    assert truncate_for_log(None) == ""
    assert truncate_for_log("  a\n b ") == "a b"
    long_text = "x" * 1000
    out = truncate_for_log(long_text, limit=800)
    assert len(out) < 900 and out.startswith("xxx")
