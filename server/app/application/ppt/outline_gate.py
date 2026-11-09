"""确定性大纲质量闸：只诊断 + 安全修复，绝不编造内容。

背景：``_OUTLINE_PROMPT`` 已经要求页型/版式多样、要点写实、有数据就出图表页，
但 35B 不保证照做；``normalize_outline`` 只做字段规范化，``sanitize_outline``
只做净化，``_audit_and_repair_outline`` 是同一个模型自查且失败时静默放行。
本模块补上「规则层」：无论模型表现如何，都能给出可观测的结构诊断，并把
明显不合法的 ``layout`` 清掉，交回 ``choose_layout`` 自动选版。

设计约束（重要）：
- 不新增/改写任何标题、要点、数字、来源；不删页、不擅自改页型。
- 唯一的自动修复是清除与内容形态不符的显式 layout（等价于引擎原本的
  ``_layout_usable`` 降级，只是提前到大纲阶段并留下问题记录）。
- 其余问题只进 ``issues``，交给模型定点修或管理员目检。
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

# 与 _OUTLINE_PROMPT 第 5 条「内容要实」一致的空话/补位话术。
_BOILERPLATE = (
    "加强领导", "高度重视", "切实推进", "狠抓落实", "全面提升",
    "认真贯彻落实", "本页内容待根据已确认材料补充", "待补充",
    "略", "同上", "（略）",
)
_NUMBER_HINT = re.compile(
    r"(20\d{2}\s*年|\d+(?:\.\d+)?\s*%|\d+\s*(?:件|人|人次|户|家|个|项|次|万元|亿元)"
    r"|同比增长|同比下降|环比|占比|截至|覆盖率|办结率)")
_TIME_HINT = re.compile(
    r"(20\d{2}\s*年\s*\d{1,2}\s*月|第[一二三四五六七八九十]+\s*阶段"
    r"|\d{1,2}\s*月(?:启动|推进|完成|验收|前|底|份)?"
    r"|时间节点|下一步安排|分阶段)")

_CHROME_TYPES = {"cover", "toc", "section", "closing"}
_STRUCTURE_TYPES = {"data", "chart", "timeline", "process", "case"}

# 与 _OUTLINE_PROMPT「版式选择」契约一致的最低要求；只用于判定显式 layout
# 是否明显不合法，不参与自动选版。
_LAYOUT_MIN_POINTS = {
    "three_cards": 3, "compare": 2, "statement": 1, "quote": 1,
    "icon_grid": 3, "two_col": 4, "center": 2, "symmetric": 2,
}
_LAYOUT_MAX_POINTS = {
    "three_cards": 3, "compare": 2, "statement": 1, "quote": 2,
    "icon_grid": 4, "center": 4, "symmetric": 4,
}


def _points(slide: Dict[str, Any]) -> List[str]:
    return [str(p).strip() for p in (slide.get("points") or []) if str(p).strip()]


def _shape(slide: Dict[str, Any]) -> Tuple:
    """一页的「内容形态」指纹，用于检测连续同构页。"""
    blocks = slide.get("blocks") if isinstance(slide.get("blocks"), dict) else {}
    pts = _points(slide)
    return (
        str(slide.get("type") or "content"),
        min(len(pts), 5),
        bool(blocks.get("chart")),
        bool(blocks.get("cards")),
        bool(blocks.get("timeline")),
        bool(blocks.get("process")),
        bool(slide.get("image_id")),
    )


def _layout_key(raw: Any) -> str:
    key = str(raw or "").strip()
    return key.rsplit(".", 1)[-1] if "." in key else key


def _layout_conflict(slide: Dict[str, Any]) -> str:
    """返回显式 layout 与内容冲突的原因；无冲突返回空串。"""
    if slide.get("layout_locked"):
        return ""  # 用户在编辑器里锁定的版式，规则层不擅自改写
    key = _layout_key(slide.get("layout"))
    if not key or key not in _LAYOUT_MIN_POINTS:
        return ""
    if str(slide.get("type") or "content") != "content":
        return ""
    pts = _points(slide)
    n = len(pts)
    lo, hi = _LAYOUT_MIN_POINTS[key], _LAYOUT_MAX_POINTS.get(key, 99)
    if not lo <= n <= hi:
        return f"{key} 需要 {lo}~{hi} 条要点，实际 {n} 条"
    if key == "statement" and len(pts[0]) > 30:
        return "statement 只容纳 30 字以内的单句结论"
    if key == "icon_grid" and any(len(p) > 20 for p in pts):
        return "icon_grid 要求每条不超过 20 字"
    if key == "quote" and not any(p[:1] in "“\"「" for p in pts):
        return "quote 要求第 1 条为原文引用"
    return ""


def audit_outline(outline: Dict[str, Any],
                  content: str = "") -> Dict[str, Any]:
    """检查大纲结构，返回 ``{issues, stats, outline}``。

    ``outline`` 为浅拷贝后的新对象；只有 ``layout`` 字段可能被清空。
    ``content`` 是原始材料文本，仅用于判断「材料里有数据却没出数据页」。
    """
    source = outline if isinstance(outline, dict) else {}
    slides_in = list(source.get("slides") or [])
    slides: List[Dict[str, Any]] = [dict(s) for s in slides_in if isinstance(s, dict)]
    result: Dict[str, Any] = dict(source)
    issues: List[Dict[str, Any]] = []

    def add(code: str, page: int, message: str) -> None:
        issues.append({"code": code, "page": page, "message": message,
                       "severity": "warn"})

    seen_titles: Dict[str, int] = {}
    for index, slide in enumerate(slides):
        page = index + 1
        title = re.sub(r"\s+", "", str(slide.get("title") or ""))
        if len(title) > 4 and title in seen_titles:
            add("duplicate_title", page,
                f"标题与第 {seen_titles[title]} 页重复：{title[:20]}")
        elif title:
            seen_titles.setdefault(title, page)

        pts = _points(slide)
        if str(slide.get("type") or "") not in _CHROME_TYPES:
            if not pts and not (slide.get("blocks") if isinstance(
                    slide.get("blocks"), dict) else {}):
                add("empty_body", page, "本页既无要点也无结构数据")
            if sum(len(p) for p in pts) > 450:
                add("page_density", page,
                    f"本页要点约 {sum(len(p) for p in pts)} 字，阅读密度偏高")
            for p in pts:
                if any(word in p for word in _BOILERPLATE):
                    add("boilerplate", page, f"要点含空话或补位话术：{p[:24]}")
                    break

        reason = _layout_conflict(slide)
        if reason:
            add("unsupported_layout_cleared", page,
                f"已清除不匹配的版式 {slide.get('layout')}（{reason}），改由系统自动选版")
            slide["layout"] = None

    # 连续同构页：直接对应「12 页全是标题+3 条要点」导致的版式重复。
    shapes = [_shape(s) for s in slides]
    longest_run, run, run_end = (0, 0, 0)
    for i, shape in enumerate(shapes):
        run = run + 1 if i and shape == shapes[i - 1] else 1
        if run > longest_run:
            longest_run, run_end = run, i + 1
    if longest_run >= 3:
        add("repeated_shape_run", max(1, run_end - longest_run + 1),
            f"连续 {longest_run} 页内容形态相同，建议至少一页改用数据/图表/时间轴/案例结构")

    body_pages = [s for s in slides
                  if str(s.get("type") or "content") not in _CHROME_TYPES]
    content_pages = [s for s in body_pages
                     if str(s.get("type") or "content") == "content"]
    ratio = (len(content_pages) / len(body_pages)) if body_pages else 0.0
    if len(body_pages) >= 6 and ratio > 0.7:
        add("content_ratio_high", 0,
            f"正文页中 content 占 {ratio:.0%}，页型过于单一；"
            "材料里有数据/时间线/案例时应改用对应结构页")

    type_counts: Dict[str, int] = {}
    for s in slides:
        key = str(s.get("type") or "content")
        type_counts[key] = type_counts.get(key, 0) + 1
    has_structure = bool(_STRUCTURE_TYPES.intersection(type_counts))
    material = content or ""
    number_hits = len(_NUMBER_HINT.findall(material))
    time_hits = len(_TIME_HINT.findall(material))
    if material and number_hits >= 3 and not ({"data", "chart"} & set(type_counts)):
        add("missing_data_page", 0,
            f"材料中约 {number_hits} 处数值，但大纲没有 data/chart 页")
    if material and time_hits >= 2 and not ({"timeline", "process"} & set(type_counts)):
        add("missing_timeline_page", 0,
            f"材料中约 {time_hits} 处时间/阶段线索，但大纲没有 timeline/process 页")
    if slides and slides[0].get("type") != "cover":
        add("no_cover", 0, "大纲没有封面页（自由结构下不强制补齐，请确认是否有意）")
    if slides and slides[-1].get("type") != "closing":
        add("no_closing", 0, "大纲没有结束页（自由结构下不强制补齐，请确认是否有意）")

    result["slides"] = slides
    return {
        "issues": issues,
        "stats": {
            "pages": len(slides),
            "type_counts": type_counts,
            "content_ratio": round(ratio, 3),
            "longest_shape_run": longest_run,
            "has_structure_page": has_structure,
            "material_number_hits": number_hits,
            "material_time_hits": time_hits,
        },
        "outline": result,
    }


def summary_for_prompt(report: Dict[str, Any], limit: int = 10) -> str:
    """把规则诊断压成一段中文，注入大纲审查 prompt。"""
    issues = report.get("issues") or []
    if not issues:
        return ""
    lines = ["【确定性结构检查（规则层，优先处理）】"]
    for item in issues[:limit]:
        page = int(item.get("page") or 0)
        where = "整稿" if page == 0 else f"第 {page} 页"
        lines.append(f"- {where}：{item.get('message')}")
    if len(issues) > limit:
        lines.append(f"- 另有 {len(issues) - limit} 条同类问题")
    lines.append(
        "只修正被点名的页，不得新增材料中没有的事实或数据，不得改动其他页；"
        "「已清除版式」「无封面/结束页」属于已按自由结构处理，无需反向补回。")
    return "\n".join(lines)
