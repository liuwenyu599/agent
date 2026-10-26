"""用户版式覆盖层：正文仍是纯文本，样式与同一版本一起保存。"""
import hashlib
from difflib import SequenceMatcher
from typing import Any

from fastapi import HTTPException

from app.domain.official_document_format import format_checks

FONTS = {
    "方正小标宋简体", "仿宋_GB2312", "黑体", "楷体_GB2312", "宋体",
    "微软雅黑", "思源宋体", "思源黑体", "Arial",
}
ALIGNMENTS = {"left", "center", "right", "justify"}
STYLE_KEYS = {"font_name", "font_size_pt", "bold", "alignment"}
OFFICIAL_TYPES = {"通知", "请示", "报告", "通报", "批复", "函", "纪要", "决定", "决议", "意见", "公告", "通告", "命令", "公报", "议案"}


def text_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _style(value: Any) -> dict:
    if not isinstance(value, dict) or set(value) - STYLE_KEYS:
        raise HTTPException(422, "文档格式参数无效")
    result = {}
    if "font_name" in value:
        if value["font_name"] not in FONTS:
            raise HTTPException(422, "不支持该字体")
        result["font_name"] = value["font_name"]
    if "font_size_pt" in value:
        size = value["font_size_pt"]
        if isinstance(size, bool) or not isinstance(size, (int, float)) or not 8 <= size <= 36:
            raise HTTPException(422, "字号须在 8–36 磅之间")
        result["font_size_pt"] = float(size)
    if "bold" in value:
        if not isinstance(value["bold"], bool):
            raise HTTPException(422, "加粗参数无效")
        result["bold"] = value["bold"]
    if "alignment" in value:
        if value["alignment"] not in ALIGNMENTS:
            raise HTTPException(422, "对齐方式无效")
        result["alignment"] = value["alignment"]
    return result


def normalize_formatting(content: str, raw: dict | None) -> dict | None:
    if raw is None:
        return None
    if not isinstance(raw, dict) or set(raw) - {"title", "paragraphs"}:
        raise HTTPException(422, "文档格式结构无效")
    lines = content.split("\n")
    paragraphs = raw.get("paragraphs") or {}
    if not isinstance(paragraphs, dict) or len(paragraphs) > min(len(lines), 10000):
        raise HTTPException(422, "段落格式结构无效")
    normalized = {}
    for key, style in paragraphs.items():
        if (not isinstance(key, str) or not key.isdecimal() or
                key != str(int(key)) or int(key) >= len(lines)):
            raise HTTPException(422, "段落序号无效")
        normalized[key] = {**_style(style), "text_hash": text_hash(lines[int(key)])}
    return {
        "base_content_hash": text_hash(content),
        "title": _style(raw.get("title") or {}),
        "paragraphs": normalized,
    }


def effective_formatting(content: str, stored: dict | None) -> dict:
    if not isinstance(stored, dict) or stored.get("base_content_hash") != text_hash(content):
        return {"title": {}, "paragraphs": {}}
    lines = content.split("\n")
    paragraphs = {}
    for key, value in (stored.get("paragraphs") or {}).items():
        if (isinstance(value, dict) and str(key).isdecimal() and int(key) < len(lines)
                and value.get("text_hash") == text_hash(lines[int(key)])):
            paragraphs[str(key)] = {k: v for k, v in value.items() if k in STYLE_KEYS}
    return {"title": stored.get("title") or {}, "paragraphs": paragraphs}


def remap_formatting(before: str, after: str, formatting: dict) -> dict:
    """结构字段去重后仅把完全相同的正文行样式带到导出稿。"""
    before_lines, after_lines = before.split("\n"), after.split("\n")
    paragraphs = {}
    for op, i1, i2, j1, _j2 in SequenceMatcher(
            None, before_lines, after_lines, autojunk=False).get_opcodes():
        if op == "equal":
            for offset in range(i2 - i1):
                style = (formatting.get("paragraphs") or {}).get(str(i1 + offset))
                if style:
                    paragraphs[str(j1 + offset)] = style
    return {"title": formatting.get("title") or {}, "paragraphs": paragraphs}


def format_warnings(content: str, stored: dict | None, document_type: str) -> list[str]:
    if document_type not in OFFICIAL_TYPES:
        return []
    formatting = effective_formatting(content, stored)
    warnings = []
    field_names = {"font_name": "字体", "font_size_pt": "字号", "alignment": "对齐方式"}
    for key, style in [("title", formatting["title"]), *formatting["paragraphs"].items()]:
        role = "title" if key == "title" else "body"
        expected = format_checks(role)
        for field in ("font_name", "font_size_pt", "alignment"):
            if field in style and field in expected and style[field] != expected[field]:
                label = "标题" if key == "title" else f"第{int(key) + 1}段"
                warnings.append(f"{label}的{field_names[field]}与公文预设不一致")
    return warnings
