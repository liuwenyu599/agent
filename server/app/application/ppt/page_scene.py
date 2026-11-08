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
    if isinstance(previous, dict) and previous.get("version") == 2 and previous.get("source") == stamp:
        elements = previous.get("elements")
        if audit(elements, slide):
            expected = model_visuals(design.get("visuals"), elements)
            expected = decorations(previous, slide) + (expected or [])
            if previous.get("visuals") == expected:
                return previous

    def scene_from(elements: list) -> dict:
        scene = {"version": 2, "source": stamp, "elements": elements}
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
    columns = 1
    if not image:
        if variant in ("two_col", "compare", "symmetric", "icon_grid"):
            columns = min(2, n)
        elif variant in ("three_cards", "cards"):
            columns = min(3, n)
        if variant == "compare" and any(len(str(p)) > 80 for p in points):
            columns = 1
    rows = math.ceil(n / columns)
    gap = .065 if variant == "symmetric" else .035
    left = .14 if variant == "center" else .055
    span = .72 if variant == "center" else .89
    width = (.48 if image else span - gap*(columns-1)) / columns
    height = (.60 - gap*(rows-1)) / rows
    top = .245
    if (design.get("relationship") == "comparison" and n == 2
            and columns == 2 and not image):
        # 两项短对照不需要占满正文高度；大空卡会让文字悬在页面中间。
        height, top = .40, .32
    for index in range(n):
        column, row = index % columns, index // columns
        elements.append({"ref": f"point:{index}", "x": left+column*(width+gap),
                         "y": top+row*(height+gap), "w": width, "h": height})
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
