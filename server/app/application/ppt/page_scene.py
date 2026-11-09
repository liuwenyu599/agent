"""Bounded page geometry shared by editable PPTX export and rendered previews."""
from __future__ import annotations

import hashlib
import json
import math
import copy
from html import escape

from app.application.ppt.adaptive_design import fit_font_size, budget_chars


def signature(slide: dict, layout: str) -> str:
    fields = {key: slide.get(key) for key in ("title", "points", "design", "image_id", "image_name")}
    return hashlib.sha256(json.dumps([fields, layout], sort_keys=True,
                                    ensure_ascii=False).encode()).hexdigest()


def references(slide: dict) -> dict:
    values = {"title": str(slide.get("title") or ""),
              **{f"point:{i}": str(value) for i, value in enumerate(slide.get("points") or [])}}
    if (slide.get("_image") or {}).get("file_path"):
        values["image"] = ""
    return values


def audit(elements: list, slide: dict) -> bool:
    values = references(slide)
    if not isinstance(elements, list) or len(elements) != len(values):
        return False
    found, boxes = set(), []
    for item in elements:
        if not isinstance(item, dict) or not isinstance(item.get("ref"), str):
            return False
        ref = item["ref"]
        if ref not in values or ref in found:
            return False
        found.add(ref)
        numbers = [item.get(key) for key in ("x", "y", "w", "h")]
        if any(type(value) not in (int, float) or not math.isfinite(value) for value in numbers):
            return False
        x, y, w, h = numbers
        if x < .035 or y < .025 or w <= .03 or h <= .02 or x+w > .965 or y+h > .89:
            return False
        preferred = 28 if ref == "title" else (30 if len(values) == 2 else 20)
        # 大框短句原来恒按 20pt 排，卡片占 60% 页高却只有一两行字，
        # 形成明显空卡；高框放宽到 26pt，窄条带保持 20pt 以免挤出多行。
        if ref.startswith("point:") and h >= .16:
            preferred = 26
        inset = 0 if ref == "title" else .04
        if w <= inset or h <= inset:
            return False
        size = (20 if ref == "image" else fit_font_size(
            values[ref], w-inset, h-inset, preferred,
            min_pt=18 if ref == "title" else 14))
        if size is None:
            return False
        item["font_pt"] = size
        item["budget_chars"] = (0 if ref == "image" else
                               budget_chars(w-inset, h-inset, size))
        for bx, by, bw, bh in boxes:
            if min(x+w, bx+bw)-max(x, bx) > .002 and min(y+h, by+bh)-max(y, by) > .002:
                return False
        boxes.append((x, y, w, h))
    # 同页同级模块字号一致：各框先取「装得下的最大字号」，整组再取
    # 最小值（即所有槽共同装得下的最大字号），绝不出现一大三小。
    point_sizes = [item["font_pt"] for item in elements
                   if str(item["ref"]).startswith("point:")]
    if point_sizes:
        common = min(point_sizes)
        for item in elements:
            if not str(item["ref"]).startswith("point:"):
                continue
            item["font_pt"] = common
            item["budget_chars"] = budget_chars(
                item["w"] - .04, item["h"] - .04, common)
    return found == set(values)


def clamp_regions(elements: list) -> list:
    """小幅越界只平移回安全区，保留模型其余构图；非法数值原样留给 audit 拒绝。

    生成路径（plan）与问题页重写路径必须共用这一套修正，否则重写返回的
    regions 会被严格 audit 整页拒绝，而正常生成却能保留同类构图。
    """
    max_shift = .06  # 页面宽高的 6%；更远的坐标留给 audit 拒绝并使用安全版式。
    for item in elements:
        if not isinstance(item, dict):
            continue
        if all(type(item.get(k)) in (int, float) and math.isfinite(item[k])
               for k in ("x", "y", "w", "h")):
            if .03 < item["w"] <= .93 and .02 < item["h"] <= .865:
                x = min(max(item["x"], .035), .965-item["w"])
                y = min(max(item["y"], .025), .89-item["h"])
                if abs(x-item["x"]) <= max_shift and abs(y-item["y"]) <= max_shift:
                    item["x"], item["y"] = x, y
    return elements


# 版式 → 构图族。此前 layout 只影响列数，11 个正文版式共用
# 1/2/3 列等高网格，换版式看不出差别；现在把语义映射到明显不同的骨架。
_LAYOUT_FAMILY: dict[str, str] = {
    "bullets": "bands", "list": "bands",
    "two_col": "grid", "three_cards": "grid", "icon_grid": "grid", "cards": "grid",
    "compare": "split", "symmetric": "mirror",
    "center": "statement", "statement": "statement", "quote": "statement",
}


def _compose_points(variant: str, n: int, image: bool,
                    long_text: bool = False,
                    comparison: bool = False) -> list[dict]:
    """按版式生成真正不同的 point 槽几何；字号由 audit 统一回填。"""
    family = _LAYOUT_FAMILY.get(variant, "bands")
    # 长文本左右对照装不下窄框，退回单列横向条带（旧行为：columns=1）。
    if long_text:
        family = "bands"
    if image:
        gap = .025
        h = (.60 - gap * (n - 1)) / n
        return [{"ref": f"point:{i}", "x": .055, "y": .245 + i * (h + gap),
                 "w": .48, "h": h} for i in range(n)]
    if family == "mirror" and n == 2 and not comparison:
        # 左右对称但上下错落，位置与 split / grid 都不同。
        return [{"ref": f"point:{i}", "x": .065 + i * .50,
                 "y": .245 + i * .075, "w": .40, "h": .48} for i in range(n)]
    if family in ("split", "mirror") and n == 2 and not long_text:
        # 左右对照（含被判为 comparison 的对称页）：两块窄高框 +
        # 中央留白给中轴，不用等高网格。
        return [{"ref": f"point:{i}", "x": .055 + i * .49, "y": .32,
                 "w": .40, "h": .40} for i in range(n)]
    if family == "mirror" and n > 2:
        # 多点对称：交错双栏，右列整体下移，避免与 two_col 的规整网格撞脸。
        gap, rows = .045, math.ceil(n / 2)
        w = (.89 - gap) / 2
        h = (.60 - .03 * (rows - 1) - .04) / rows
        return [{"ref": f"point:{i}",
                 "x": .055 + (i % 2) * (w + gap),
                 "y": .245 + (i // 2) * (h + .03) + (i % 2) * .04,
                 "w": w, "h": h} for i in range(n)]
    if family == "statement" and n <= 4:
        # 居中大结论 + 其余要点下方横排；单点时就是整页一句大字。
        if n == 1:
            return [{"ref": "point:0", "x": .14, "y": .30, "w": .72, "h": .38}]
        rest, gap = n - 1, .03
        w = (.72 - gap * (rest - 1)) / rest
        boxes = [{"ref": "point:0", "x": .14, "y": .27, "w": .72, "h": .28}]
        boxes += [{"ref": f"point:{i+1}", "x": .14 + i * (w + gap),
                   "y": .615, "w": w, "h": .20} for i in range(rest)]
        return boxes
    if family == "bands":
        # 编号要点：横向条带，与竖卡阵列明显不同。
        gap = .022
        h = (.60 - gap * (n - 1)) / n
        return [{"ref": f"point:{i}", "x": .10, "y": .245 + i * (h + gap),
                 "w": .80, "h": h} for i in range(n)]
    # grid：三卡 / 双栏 / 对称多点沿用等宽网格，但列数由版式决定。
    columns = 3 if variant in ("three_cards", "cards") else min(2, n)
    rows = math.ceil(n / columns)
    gap = .035
    width = (.89 - gap * (columns - 1)) / columns
    height = (.60 - gap * (rows - 1)) / rows
    return [{"ref": f"point:{i}", "x": .055 + (i % columns) * (width + gap),
             "y": .245 + (i // columns) * (height + gap),
             "w": width, "h": height} for i in range(n)]


def plan(slide: dict, layout: str) -> dict | None:
    from app.application.ppt.visual_primitives import decorations, model_visuals

    if slide.get("type") not in ("content", "summary"):
        return None
    points = slide.get("points") or []
    if not points:
        return None
    design = slide.get("design") or {}
    image = bool((slide.get("_image") or {}).get("file_path"))
    if image and not design.get("regions") and not slide.get("scene"):
        return None
    stamp = signature(slide, layout)
    previous = slide.get("scene")
    if (isinstance(previous, dict) and previous.get("version") == 2
            and previous.get("source") == stamp
            and previous.get("layout") == layout):
        elements = previous.get("elements")
        if audit(elements, slide):
            expected = model_visuals(design.get("visuals"), elements)
            expected = decorations(previous, slide) + (expected or [])
            if previous.get("visuals") == expected:
                return previous

    def scene_from(elements: list) -> dict:
        scene = {"version": 2, "source": stamp, "layout": layout,
                 "elements": elements}
        visuals = model_visuals(design.get("visuals"), elements)
        scene["visuals"] = decorations(scene, slide) + (visuals or [])
        return scene

    suggested = design.get("regions")
    if isinstance(suggested, list):
        elements = clamp_regions(copy.deepcopy(suggested))
        if audit(elements, slide):
            return scene_from(elements)
    elements = [{"ref": "title", "x": .055, "y": .05, "w": .89, "h": .12}]
    n = len(points)
    variant = layout.split(".")[-1]
    long_text = (variant == "compare"
                 and any(len(str(p)) > 80 for p in points))
    elements.extend(_compose_points(
        variant, n, image, long_text,
        comparison=(design.get("relationship") == "comparison")))
    if image:
        elements.append({"ref": "image", "x": .58, "y": .245, "w": .365, "h": .60})
    if not audit(elements, slide):
        return None
    return scene_from(elements)


def wireframe(scene: dict, slide: dict, colors: dict | None = None) -> str:
    """Preview drawn from the same decoration list as the exported deck.

    Still a line-frame (not a pixel-perfect design proof), but relationship
    primitives, connectors, numbered badges and gradient bands are visible and
    share their geometry with ``r_scene``.
    """
    values = references(slide)
    parts = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 540">',
             '<rect width="960" height="540" fill="white"/>']
    from app.application.ppt import visual_primitives as vp
    for item in scene.get("visuals") or []:
        parts.append(vp.svg_decoration(item, colors))
    for element in scene["elements"]:
        x, y, w, h = (element[k] * scale for k, scale in
                       (("x", 960), ("y", 540), ("w", 960), ("h", 540)))
        label = escape(element["ref"] + " · " + values[element["ref"]][:16])
        parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" '
                     'fill="none" stroke="#304557" stroke-dasharray="4 3"/>')
        parts.append(f'<svg x="{x}" y="{y}" width="{w}" height="{h}" overflow="hidden">'
                     f'<text x="8" y="20" font-size="14">{label}</text></svg>')
    return "".join(parts) + "</svg>"
