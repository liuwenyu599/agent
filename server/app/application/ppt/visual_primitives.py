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


def _band_covered(out: list, x: float, y: float) -> bool:
    """该列顶端是否已经有一条色带（避免同一位置叠两条，成稿看着像双线）。

    ``grouped`` 分组自带顶端色带，motif 再按列补一条就会错位重叠：一条比卡片
    略窄、一条略宽，投影上是「一条线旁边挂了一小截」的廉价感。
    """
    for item in out:
        if item.get("kind") not in ("rect", "gradient", "chevron"):
            continue
        if float(item.get("h", 1)) >= .02:      # 卡片本体不算色带
            continue
        if abs(float(item.get("y", 0)) - y) > .03:
            continue
        left, right = float(item["x"]), float(item["x"]) + float(item["w"])
        if left <= x + .012 and right >= x + .012:
            return True
    return False


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
    # 色条必须对齐真实列，且跟着该列的实际顶部走：mirror（上下错落）布局里
    # 两列起点相差 4%，统一钉在 rule_y 会让右列色条悬空在卡片外 0.08 处。
    columns = sorted({round(b["x"], 3) for b in boxes})[:4]
    if variant in ("two_col", "compare", "three_cards", "cards"):
        for i, x in enumerate(columns):
            column_boxes = [b for b in boxes if abs(b["x"] - x) <= .01]
            width = min(b["w"] for b in column_boxes)
            band_y = max(.02, min(b["y"] for b in column_boxes) - .018)
            if _band_covered(out, x, band_y):
                continue
            add.append(_box(x, band_y, width, .006, kind="rect",
                            fill=("primary", "accent", "primary", "accent")[i % 4],
                            alpha=70))
        # 只有真正左右对照（split/compare）才画中轴；mirror 是上下错落的镜像，
        # 中轴穿过两列间隙没有任何语义，成稿里像一条无来由的竖线。
        if (variant in ("two_col", "compare")
                and not any(item["kind"] == "line" for item in out)):
            add.append(_line(.5, rule_y + .02, .5, .845, stroke="line", width=1.0))
    elif variant in ("center", "statement", "quote"):
        # 这里原本再画一条 0.40 宽渐变条 + 一小截金色短线，读作「居中大结论」
        # 的引线。但页头已有统一的标题短线，两条叠在标题下方就是用户反复说的
        # 「双线」；多要点时（scene 是 1 大 + 3 小）更是悬在空白处、不贴任何
        # 卡片的两条无主横杠。装饰语义已由构图本身表达，不再补线。
        pass
    # else: bullets / image_* / 未知 —— 标题下方已有统一短线（见 decorations
    # 开头），正文块不再逐条补线，避免条带页出现「一排来历不明的横杠」。
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
        # 中轴只有在「左右两栏之间有缝」时才是对照线。整页竖排的三条要点也被
        # 归为 comparison，旧逻辑会在正中间拉一条竖线 + 一个圆点，正好压在正文
        # 上（用户 2026-11-09 第三次反馈「线穿过文字」就是这么来的）。
        columns = {round(b["x"], 3) for b in boxes}
        gutter = len(columns) >= 2 and not any(
            b["x"] + .012 < axis < b["x"] + b["w"] - .012 for b in boxes)
        if gutter:
            out.append(_line(axis, top - .012, axis, bottom + .012,
                             stroke="line", width=1.5))
            out.append(_disc(axis, (top + bottom) / 2, .030, fill="primary"))
        # 双色卡片只属于「真的左右对照」（两条）。三点并列被归为 comparison
        # 时，前两张一绿一棕、第三张又是浅底，读起来像三种不同的卡（用户
        # 2026-11-09 截图第 4 页就是这个）。并列一律同一种浅底卡。
        dual = len(boxes) == 2
        for index, box in enumerate(ordered[:2]):
            if dual:
                fill = "primary" if index == 0 else "accent"
                out.append(_card(box, fill=fill, alpha=11))
            else:
                fill = "primary"
                out.append(_card(box))
            out.append(_badge(box, index, fill))
        for index, box in enumerate(ordered[2:], 2):
            out.append(_card(box))
            out.append(_badge(box, index, "primary" if index % 2 == 0 else "accent"))
        return _layout_motif(out, scene)

    # 同一关系下不同版式必须长成不同的东西，否则「换版式」只是换列数，
    # 读者看到的还是一排浅底块（用户 2026-11-09「现在还是同质化」）。
    # icon_grid / symmetric 单独一套无卡片语言：白底文字 + 只留序号或题头。
    variant = str((scene or {}).get("layout") or "").rsplit(".", 1)[-1]
    if variant == "icon_grid":
        # 极简三栏：不铺卡片、不放序号，只留三列文字本身。卡片页已经很多了，
        # 这一页的作用就是"什么都不加"，让整稿有呼吸。
        return _layout_motif(out, scene)

    if variant == "symmetric":
        # 引用块：左侧一条竖色线，不封口（早先"顶横线 + 左竖线"读作画了一半
        # 的边框，像没渲染完）。线长取框高的六成并居中，否则竖线上下各伸出
        # 一大截，比文字还高，看着像栏线而不是引用符。
        for index, box in enumerate(ordered):
            fill = "primary" if index % 2 == 0 else "accent"
            bar = box["h"] * .60
            out.append(_box(box["x"] - .014, box["y"] + (box["h"] - bar) / 2,
                            .006, bar, kind="rect", fill=fill, alpha=85))
        return _layout_motif(out, scene)

    if variant in ("center", "statement", "quote"):
        # 结论式版式：一段段并列的结论，不铺卡片；每块只留一条短题头。
        for index, box in enumerate(ordered):
            fill = "primary" if index % 2 == 0 else "accent"
            out.append(_box(box["x"], box["y"], .045, .007, kind="rect",
                            fill=fill, alpha=90))
        return _layout_motif(out, scene)

    if rel == "parallel":
        for index, box in enumerate(ordered):
            fill = "primary" if index % 2 == 0 else "accent"
            out.append(_card(box))
            # 并行步骤用 chevron 顶条代替普通色带，形成明确的推进方向。
            # 宽度与卡片同宽：留 4% 缩进会让色带右端比卡片短一截，看着像没对齐。
            out.append(_box(box["x"], box["y"] - .018, box["w"], .014,
                            kind="chevron", fill=fill, alpha=85))
            out.append(_badge(box, index, fill))
        return _layout_motif(out, scene)

    if rel == "grouped":
        serial = 0
        for gi, group in enumerate(_groups(ordered)):
            fill = "primary" if gi % 2 == 0 else "accent"
            # 一条横贯整行的色带会让三列卡片像挂在同一根晾衣绳上（用户看到的是
            # 「一条多余的横线」）；改成每张卡片顶端各一条自己的色带。
            for box in group:
                out.append(_card(box))
                # 色带贴着卡片顶边，不再悬在卡外 .020 处：三张并排的卡各自
                # 一条悬空色带时，间隙只有 20px，投影上连成一条横贯整页的线，
                # 三个序号圆点正好挂在线上（用户看到的就是「一条莫名其妙的
                # 横线穿过圆点」）。贴边后读作卡片自己的顶盖，互不相连。
                out.append(_box(box["x"], box["y"], box["w"], .008,
                                kind="rect", fill=fill, alpha=80))
                out.append(_box(box["x"], box["y"], .006, box["h"],
                                kind="rect", fill=fill))
                out.append(_badge(box, serial, fill))
                serial += 1
        return _layout_motif(out, scene)

    # none / 未知：克制版式，只给每条要点一条竖线作为项目符号。
    # 原本每条要点上方还压一条 primary→light 的渐变细条，右侧渐隐在浅底上
    # 像一层灰影，三条叠起来就是用户说的「下面一些莫名其妙的线条」；删掉，
    # 页头已有统一的标题短线，正文块不需要再各挂一条。
    # 多列网格（槽宽 < 50% 页宽）仍铺浅底卡片，否则三列页只剩几根孤线；
    # 横条带页（槽宽 80%）不铺卡，保持整页留白。
    for index, box in enumerate(boxes):
        fill = "primary" if index % 2 == 0 else "accent"
        if box["w"] < .50:
            out.append(_card(box))
        out.append(_box(box["x"] - .012, box["y"], .006, box["h"],
                        kind="rect", fill=fill, alpha=75))
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
