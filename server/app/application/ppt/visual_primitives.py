"""Relationship-aware page decorations shared by PPTX rendering and SVG preview.

The scene describes *where text goes*; this module describes *what the page looks
like around that text*.  Both renderers consume the same list, so the wireframe
endpoint cannot silently drift away from the exported deck.

All coordinates are fractions of the slide (0..1).  Colours are semantic names;
only the renderers map them to a concrete theme.  Decorations are drawn before
the text layer, which keeps the geometry audit's TEXT_HIDDEN check quiet.
"""
from __future__ import annotations

import math

# 装饰安全区：比 audit() 的文字区略宽，允许贴边色带，但不越出页面。
SAFE_X, SAFE_Y, SAFE_R, SAFE_B = .030, .020, .970, .900

# 16:9 下「同样一份相对坐标」在 x/y 上代表不同物理长度；所有正圆装饰都要换算，
# 否则 PPTX 里是椭圆而 SVG 线框里是正圆，预览与成稿对不上。
ASPECT = 540 / 960

SVG_PALETTE = {
    "primary": "#0F6E8C",
    "accent": "#3FA7B8",
    "light": "#EDF3F5",
    "dark": "#243746",
    "white": "#FFFFFF",
    "line": "#AFC2C9",
}

RELATIONSHIPS = ("none", "comparison", "parallel", "grouped", "takeaway")
MODEL_KINDS = frozenset({"rect", "oval", "chevron", "gradient", "line"})
MODEL_COLORS = frozenset(SVG_PALETTE)


def model_visuals(proposed: object, elements: list[dict]) -> list[dict] | None:
    """Accept a small, text-free page design in theme colors; None means use defaults.

    Decorative shapes are drawn behind text. Dark opaque fills may only be thin
    rules, so a model cannot hide the page's editable wording under a color block.
    """
    if not isinstance(proposed, list) or len(proposed) > 6:
        return None
    result: list[dict] = []
    for raw in proposed:
        if not isinstance(raw, dict) or raw.get("kind") not in MODEL_KINDS:
            return None
        kind = raw["kind"]
        keys = ("x1", "y1", "x2", "y2") if kind == "line" else ("x", "y", "w", "h")
        coords = [raw.get(key) for key in keys]
        if any(type(v) not in (int, float) or not math.isfinite(v) for v in coords):
            return None
        item = {"kind": kind, **{key: float(raw[key]) for key in keys}}
        if kind == "line":
            if (any(not 0 <= item[key] <= 1 for key in keys)
                    or raw.get("stroke") not in MODEL_COLORS):
                return None
            width = raw.get("width", 1.2)
            if type(width) not in (int, float) or not math.isfinite(width) or not .5 <= width <= 3:
                return None
            left, right = sorted((item["x1"], item["x2"]))
            top, bottom = sorted((item["y1"], item["y2"]))
            if any(e.get("ref") != "image" and
                   left <= e["x"] + e["w"] and right >= e["x"] and
                   top <= e["y"] + e["h"] and bottom >= e["y"]
                   for e in elements):
                return None
            item.update(stroke=raw["stroke"], width=float(width))
        else:
            x, y, w, h = (item[key] for key in keys)
            if (x < SAFE_X or y < SAFE_Y or w < .005 or h < .004
                    or x + w > SAFE_R or y + h > SAFE_B):
                return None
            if kind == "gradient":
                if raw.get("from") not in MODEL_COLORS or raw.get("to") not in MODEL_COLORS:
                    return None
                item.update({"from": raw["from"], "to": raw["to"]})
            else:
                if raw.get("fill") not in MODEL_COLORS:
                    return None
                item["fill"] = raw["fill"]
                if kind == "rect":
                    if type(raw.get("radius", False)) is not bool:
                        return None
                    item["radius"] = raw.get("radius", False)
            alpha = raw.get("alpha", 100)
            if type(alpha) not in (int, float) or not math.isfinite(alpha) or not 0 <= alpha <= 100:
                return None
            if kind != "gradient":
                item["alpha"] = float(alpha)
            # A broad saturated shape behind body copy destroys contrast even
            # when the text geometry itself passes audit().
            saturated = (kind == "gradient" and
                         (item["from"] not in ("light", "white") or
                          item["to"] not in ("light", "white"))) or item.get("fill") in (
                              "primary", "accent", "dark")
            if saturated and (kind == "gradient" or alpha > 20) and w > .02 and h > .04:
                if any(e.get("ref") != "image" and
                       min(x+w, e["x"]+e["w"])-max(x, e["x"]) > .002 and
                       min(y+h, e["y"]+e["h"])-max(y, e["y"]) > .002
                       for e in elements):
                    return None
        result.append(item)
    return result


def _clamp(value: float, low: float, high: float) -> float:
    return min(max(value, low), high)


def _box(x, y, w, h, **kwargs) -> dict:
    """Clamp a decoration box into the safe area (never drops it silently)."""
    w = max(.005, min(float(w), SAFE_R - SAFE_X))
    h = max(.004, min(float(h), SAFE_B - SAFE_Y))
    x = _clamp(float(x), SAFE_X, SAFE_R - w)
    y = _clamp(float(y), SAFE_Y, SAFE_B - h)
    return {"kind": kwargs.pop("kind", "rect"), "x": x, "y": y, "w": w, "h": h, **kwargs}


def _line(x1, y1, x2, y2, **kwargs) -> dict:
    return {"kind": "line",
            "x1": _clamp(float(x1), SAFE_X, SAFE_R),
            "y1": _clamp(float(y1), SAFE_Y, SAFE_B),
            "x2": _clamp(float(x2), SAFE_X, SAFE_R),
            "y2": _clamp(float(y2), SAFE_Y, SAFE_B), **kwargs}


def _badge(box: dict, index: int, fill: str) -> dict:
    """Numbered circle in the gutter to the left of a text region."""
    height = .034
    width = height * ASPECT
    return _box(box["x"] - .028, box["y"] + .006, width, height, kind="badge",
                fill=fill, label=str(index + 1))


def _disc(cx: float, cy: float, height: float, **kwargs) -> dict:
    """A visually circular oval in 16:9 relative coordinates."""
    width = height * ASPECT
    return _box(cx - width / 2, cy - height / 2, width, height,
                kind="oval", **kwargs)


def _gradient(box: dict, source: str, target: str, y: float | None = None,
              height: float = .010) -> dict:
    return _box(box["x"], box["y"] if y is None else y, box["w"], height,
                kind="gradient", **{"from": source, "to": target})


def _card(box: dict, fill: str = "light", alpha: int | None = None) -> dict:
    return _box(box["x"], box["y"], box["w"], box["h"],
                kind="rect", fill=fill, radius=True, alpha=alpha)


def _groups(boxes: list[dict]) -> list[list[dict]]:
    """Rows of regions sharing a baseline (tolerance 6% of slide height)."""
    groups: list[list[dict]] = []
    for box in sorted(boxes, key=lambda b: (b["y"], b["x"])):
        if groups and abs(box["y"] - groups[-1][0]["y"]) <= .06:
            groups[-1].append(box)
        else:
            groups.append([box])
    return groups


def _layout_motif(out: list, scene: dict) -> list:
    """按版式补一组骨架形状，让同关系多页不只是「换列数」。

    全部落在标题区或页边空白，不与正文文字框重叠；只使用既有 kind，
    因此 SVG 线框与原生 PPTX 导出共用同一份列表，几何审计不会判 TEXT_HIDDEN。
    """
    layout = str((scene or {}).get("layout") or "")
    boxes = [e for e in (scene or {}).get("elements", [])
             if str(e.get("ref", "")).startswith("point:")]
    # 旧缓存 scene 没有 layout 字段：保持原有视觉语言，不给历史稿件凭空加装饰。
    if not layout or not boxes:
        return out
    variant = layout.rsplit(".", 1)[-1]
    body_top = min(b["y"] for b in boxes)
    rule_y = min(.205, body_top - .035)
    add: list[dict] = []
    if variant in ("two_col", "compare", "symmetric"):
        if not any(item["kind"] == "line" for item in out):
            add.append(_line(.5, rule_y + .02, .5, .845, stroke="line", width=1.0))
        add.append(_box(.055, rule_y, .40, .006, kind="rect", fill="primary", alpha=55))
    elif variant in ("three_cards", "icon_grid", "cards"):
        for i, fill in enumerate(("primary", "accent", "primary")):
            add.append(_box(.055 + i * .30, rule_y, .28, .008,
                            kind="rect", fill=fill, alpha=70))
    elif variant in ("center", "statement", "quote"):
        add.append(_box(.30, rule_y, .40, .008, kind="gradient",
                        **{"from": "primary", "to": "light"}))
        add.append(_box(.455, rule_y + .022, .09, .004, kind="rect", fill="accent"))
    else:  # bullets / image_* / 未知：左侧竖色带，与卡片类明显不同
        add.append(_box(.035, body_top, .008, max(.10, .845 - body_top),
                        kind="rect", fill="primary", alpha=45))
        add.append(_box(.055, rule_y, .11, .006, kind="rect", fill="accent"))
    return out + add


def decorations(scene: dict, slide: dict) -> list[dict]:
    """Build the decoration list for one scene.

    Each ``design.relationship`` gets a recognisably different visual language:
    comparison = centre axis + mirrored cards, parallel = numbered chevrons,
    grouped = colour-banded groups, takeaway = oval emphasis + quote bar,
    none = restrained rules only.  Unknown values degrade to ``none``.
    """
    elements = (scene or {}).get("elements") or []
    boxes = [e for e in elements if str(e.get("ref", "")).startswith("point:")]
    title = next((e for e in elements if e.get("ref") == "title"), None)
    out: list[dict] = []

    # 所有关系共用的标题短横线（原来内联在 r_scene 里）。
    if title:
        out.append(_box(title["x"], title["y"] + title["h"] + .007, .11, .006,
                        kind="rect", fill="accent"))
    if not boxes:
        return out

    design = slide.get("design") if isinstance(slide.get("design"), dict) else {}
    rel = str(design.get("relationship") or "none")
    if rel not in RELATIONSHIPS:
        rel = "none"
    ordered = sorted(boxes, key=lambda b: (b["y"], b["x"]))

    if rel == "takeaway":
        main = max(boxes, key=lambda b: b["w"] * b["h"])
        diameter = min(main["h"], main["w"] / ASPECT) * .86
        out.append(_disc(main["x"] + main["w"] / 2,
                         main["y"] + main["h"] / 2,
                         diameter, fill="accent", alpha=9))
        out.append(_box(main["x"] - .016, main["y"], .010, main["h"],
                        kind="rect", fill="accent"))
        for box in boxes:
            if box is not main:
                out.append(_box(box["x"] - .012, box["y"], .006, box["h"],
                                kind="rect", fill="primary", alpha=55))
        return _layout_motif(out, scene)

    if rel == "comparison":
        top = min(b["y"] for b in boxes)
        bottom = max(b["y"] + b["h"] for b in boxes)
        axis = (min(b["x"] for b in boxes) + max(b["x"] + b["w"] for b in boxes)) / 2
        out.append(_line(axis, top - .012, axis, bottom + .012,
                         stroke="line", width=1.5))
        out.append(_disc(axis, (top + bottom) / 2, .030, fill="primary"))
        for index, box in enumerate(ordered[:2]):
            fill = "primary" if index == 0 else "accent"
            out.append(_card(box, fill=fill, alpha=11))
            out.append(_gradient(box, fill, "accent" if index == 0 else "primary"))
            out.append(_badge(box, index, fill))
        for index, box in enumerate(ordered[2:], 2):
            out.append(_card(box))
            out.append(_gradient(box, "primary", "accent"))
            out.append(_badge(box, index, "primary" if index % 2 == 0 else "accent"))
        return _layout_motif(out, scene)

    if rel == "parallel":
        for index, box in enumerate(ordered):
            fill = "primary" if index % 2 == 0 else "accent"
            out.append(_card(box))
            # 并行步骤用 chevron 顶条代替普通色带，形成明确的推进方向。
            out.append(_box(box["x"], box["y"] - .018, box["w"] * .96, .014,
                            kind="chevron", fill=fill, alpha=85))
            out.append(_badge(box, index, fill))
        return _layout_motif(out, scene)

    if rel == "grouped":
        serial = 0
        for gi, group in enumerate(_groups(ordered)):
            fill = "primary" if gi % 2 == 0 else "accent"
            gx = min(b["x"] for b in group)
            gw = max(b["x"] + b["w"] for b in group) - gx
            out.append(_box(gx, group[0]["y"] - .020, gw, .012,
                            kind="gradient", **{"from": fill, "to": "light"}))
            for box in group:
                out.append(_card(box))
                out.append(_box(box["x"], box["y"], .006, box["h"],
                                kind="rect", fill=fill))
                out.append(_badge(box, serial, fill))
                serial += 1
        return _layout_motif(out, scene)

    # none / 未知：克制版式，只给每条要点一条竖线与顶部渐变细条，避免整页卡片。
    for index, box in enumerate(boxes):
        fill = "primary" if index % 2 == 0 else "accent"
        out.append(_box(box["x"] - .012, box["y"], .006, box["h"],
                        kind="rect", fill=fill, alpha=75))
        out.append(_gradient(box, fill, "light", y=box["y"], height=.008))
    return _layout_motif(out, scene)


def svg_decoration(item: dict, palette: dict | None = None) -> str:
    """One decoration as SVG markup; the preview uses the very same geometry."""
    p = {**SVG_PALETTE, **(palette or {})}

    def col(name):
        return p.get(name, SVG_PALETTE["primary"])

    def opacity():
        alpha = item.get("alpha")
        return "" if alpha is None else f' opacity="{max(0, min(100, alpha)) / 100:.2f}"'

    kind = item["kind"]
    if kind == "line":
        return (f'<line x1="{item["x1"] * 960:.1f}" y1="{item["y1"] * 540:.1f}" '
                f'x2="{item["x2"] * 960:.1f}" y2="{item["y2"] * 540:.1f}" '
                f'stroke="{col(item.get("stroke"))}" '
                f'stroke-width="{item.get("width", 1.2) * 1.3:.1f}"/>')

    x, y = item["x"] * 960, item["y"] * 540
    w, h = item["w"] * 960, item["h"] * 540
    if kind == "gradient":
        gid = f'grad{int(x)}_{int(y)}'
        return (f'<defs><linearGradient id="{gid}" x1="0" y1="0" x2="1" y2="0">'
                f'<stop offset="0" stop-color="{col(item["from"])}"/>'
                f'<stop offset="1" stop-color="{col(item["to"])}"/>'
                f'</linearGradient></defs>'
                f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" '
                f'fill="url(#{gid})"{opacity()}/>')
    if kind == "oval":
        return (f'<ellipse cx="{x + w / 2:.1f}" cy="{y + h / 2:.1f}" '
                f'rx="{w / 2:.1f}" ry="{h / 2:.1f}" fill="{col(item.get("fill"))}"'
                f'{opacity()}/>')
    if kind == "chevron":
        tip = min(9.0, w * .12)
        pts = (f'{x:.1f},{y:.1f} {x + w - tip:.1f},{y:.1f} '
               f'{x + w:.1f},{y + h / 2:.1f} {x + w - tip:.1f},{y + h:.1f} '
               f'{x:.1f},{y + h:.1f} {x + tip:.1f},{y + h / 2:.1f}')
        return f'<polygon points="{pts}" fill="{col(item.get("fill"))}"{opacity()}/>'
    if kind == "badge":
        label = str(item.get("label") or "").replace("&", "&amp;").replace("<", "&lt;")
        return (f'<circle cx="{x + w / 2:.1f}" cy="{y + h / 2:.1f}" r="{min(w, h) / 2:.1f}" '
                f'fill="{col(item.get("fill"))}"/>'
                f'<text x="{x + w / 2:.1f}" y="{y + h / 2 + 4:.1f}" text-anchor="middle" '
                f'font-size="11" fill="{col("white")}">{label}</text>')
    rx = ' rx="7"' if item.get("radius") else ""
    return (f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" '
            f'fill="{col(item.get("fill"))}"{opacity()}{rx}/>')
