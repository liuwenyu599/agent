"""Bounded page geometry shared by editable PPTX export and rendered previews."""
from __future__ import annotations

import hashlib
import base64
import io
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
    blocks = slide.get("blocks") or {}
    if slide.get("type") in {"data", "chart"}:
        chart = blocks.get("chart") or {}
        if valid_chart_spec(chart):
            values["chart"] = ""
        elif (blocks.get("table") or {}).get("rows"):
            values["table"] = ""
        else:
            from app.application.ppt.outline_gate import PLACEHOLDER_RE
            for index, card in enumerate((blocks.get("cards") or [])[:4]):
                if (isinstance(card, dict)
                        and str(card.get("value") or "").strip()
                        and not PLACEHOLDER_RE.search(str(card.get("value")))):
                    values[f"metric:{index}"] = (f"{card.get('value')} "
                                                  f"{card.get('label') or ''}").strip()
    if (slide.get("_image") or {}).get("file_path"):
        values["image"] = ""
    return values


def valid_chart_spec(chart: object) -> bool:
    """Only let the model place a chart the native PPTX writer can represent."""
    if not isinstance(chart, dict):
        return False
    categories, series = chart.get("categories"), chart.get("series")
    if not isinstance(categories, list) or not categories or not isinstance(series, list) or not series:
        return False
    for item in series:
        if not isinstance(item, dict):
            return False
        values = item.get("values")
        if not isinstance(values, list) or len(values) != len(categories):
            return False
        if any(type(value) not in (int, float) or not math.isfinite(value)
               for value in values):
            return False
    return True


def audit(elements: list, slide: dict) -> bool:
    return explain(elements, slide) == ""


def explain_layered(elements: list, slide: dict) -> str:
    """Validate editable content layers, including the actual photo under white text.

    The dark scrim is a native PPT shape covering the photo. When a text box
    crosses its edge, a second native scrim covers the whole text box.
    """
    issue = explain(elements, slide, layered=True)
    if issue:
        return issue
    layers = {"image": "image", "chart": "chart", "table": "chart"}
    for item in elements:
        expected = layers.get(item["ref"], "text")
        if item.get("layer", expected) != expected:
            return f"区域 {item['ref']} 的 layer 应为 {expected}"
    decorations = (slide.get("design") or {}).get("visuals") or []
    decor_boxes = []
    for visual in decorations:
        if not isinstance(visual, dict) or visual.get("kind") == "line":
            continue
        box = (visual.get("x"), visual.get("y"), visual.get("w"), visual.get("h"))
        if any(type(value) not in (int, float) or not math.isfinite(value)
               for value in box):
            return "装饰层坐标无效"
        if any(_intersection_area(box, other) > .001 for other in decor_boxes):
            return "同层装饰图形重叠，请拆分或移开其中一个"
        decor_boxes.append(box)
    image = next((item for item in elements if item["ref"] == "image"), None)
    if image is None:
        return ""
    image_box = (image["x"], image["y"], image["w"], image["h"])
    overlapping = []
    for item in elements:
        if item["ref"] == "image":
            continue
        area = _intersection_area(image_box, (item["x"], item["y"],
                                              item["w"], item["h"]))
        if area <= .0001:
            continue
        if not item["ref"].startswith("point:"):
            return f"区域 {item['ref']} 不可压在照片上"
        overlapping.append(item)
        if (slide.get("design") or {}).get("image_overlay") != "dark":
            return f"区域 {item['ref']} 压在照片上但没有深色蒙版"
        coverage = area / (item["w"] * item["h"])
        if coverage < .70:
            return f"区域 {item['ref']} 的蒙版只覆盖 {coverage:.0%}，至少需要 70%"
    if not overlapping:
        return ""
    path = (slide.get("_image") or {}).get("file_path")
    if not path:
        return "图片缺失，无法实测叠字对比度"
    try:
        from PIL import Image, ImageOps
        with Image.open(path) as source:
            photo = ImageOps.fit(source.convert("RGB"), (256, 256),
                                 method=Image.Resampling.LANCZOS)
        for item in overlapping:
            area = _intersection_area(image_box, (item["x"], item["y"],
                                                  item["w"], item["h"]))
            left = max(0, int((item["x"] - image["x"]) / image["w"] * 256))
            top = max(0, int((item["y"] - image["y"]) / image["h"] * 256))
            right = min(256, int(math.ceil((item["x"] + item["w"] - image["x"])
                                           / image["w"] * 256)))
            bottom = min(256, int(math.ceil((item["y"] + item["h"] - image["y"])
                                            / image["h"] * 256)))
            raw = photo.crop((left, top, right, bottom)).tobytes()
            pixels = list(zip(raw[0::3], raw[1::3], raw[2::3]))
            if area < item["w"] * item["h"] * .999:
                # The supplemental native scrim also covers the part outside
                # the photograph. White is the worst possible backdrop.
                pixels.append((255, 255, 255))
            # Native scrim: RGB(15,20,25), 62% opacity, white text above it.
            worst = min((_wcag_contrast_white(tuple(round(c * .38 + shade * .62)
                                                     for c, shade in zip(pixel, (15, 20, 25))))
                         for pixel in pixels), default=0.0)
            threshold = 3.0 if item.get("font_pt", 0) >= 24 else 4.5
            if worst < threshold:
                return (f"区域 {item['ref']} 的实测文字对比度 {worst:.2f}:1，"
                        f"需达到 {threshold:.1f}:1")
    except (OSError, ValueError):
        return "图片无法读取，不能验证叠字对比度"
    return ""


def _intersection_area(a: tuple, b: tuple) -> float:
    return max(0.0, min(a[0]+a[2], b[0]+b[2])-max(a[0], b[0])) * max(
        0.0, min(a[1]+a[3], b[1]+b[3])-max(a[1], b[1]))


def _wcag_contrast_white(rgb: tuple[int, int, int]) -> float:
    def channel(value: int) -> float:
        value /= 255
        return value / 12.92 if value <= .04045 else ((value + .055) / 1.055) ** 2.4
    luminance = sum(weight * channel(value) for weight, value in
                    zip((.2126, .7152, .0722), rgb))
    return 1.05 / (luminance + .05)


def svg_text_overlap(png: bytes, elements: list, slide: dict) -> str:
    """An SVG decoration may not paint behind editable ordinary text."""
    from PIL import Image
    with Image.open(io.BytesIO(png)) as source:
        alpha = source.convert("RGBA").getchannel("A")
        width, height = alpha.size
        image = next((item for item in elements if item.get("ref") == "image"), None)
        for item in elements:
            ref = item.get("ref", "")
            if ref == "image":
                continue
            if image and ref.startswith("point:") and (
                    (slide.get("design") or {}).get("image_overlay") == "dark"):
                covered = _intersection_area(
                    (image["x"], image["y"], image["w"], image["h"]),
                    (item["x"], item["y"], item["w"], item["h"]))
                if covered / (item["w"] * item["h"]) >= .70:
                    continue  # Native photo and scrim are above the SVG layer.
            box = (max(0, int(item["x"] * width)),
                   max(0, int(item["y"] * height)),
                   min(width, math.ceil((item["x"] + item["w"]) * width)),
                   min(height, math.ceil((item["y"] + item["h"]) * height)))
            if alpha.crop(box).getbbox():
                return f"SVG 装饰覆盖文字区域 {ref}"
    return ""


def intent_issue(elements: list, slide: dict) -> str:
    """Check whether model geometry carries the page's stated relationship."""
    design = slide.get("design") or {}
    points = {item.get("ref"): item for item in elements
              if isinstance(item, dict) and str(item.get("ref", "")).startswith("point:")}
    if design.get("relationship") == "comparison" and len(points) == 2:
        left, right = sorted(points.values(), key=lambda item: item["x"])
        horizontal_gap = right["x"] - (left["x"] + left["w"])
        vertical_overlap = min(left["y"] + left["h"], right["y"] + right["h"]) - max(
            left["y"], right["y"])
        if horizontal_gap < .015 or vertical_overlap < .25 * min(left["h"], right["h"]):
            return "本页是对比关系，两项须并排形成可直接比较的左右两栏"
    if design.get("relationship") == "takeaway" and len(points) >= 2:
        areas = sorted((item["w"] * item["h"] for item in points.values()), reverse=True)
        if areas[0] < areas[1] * 1.3:
            return "本页有主结论，最大的正文区域须明显大于次要说明区域"
    image = next((item for item in elements if item.get("ref") == "image"), None)
    if image and design.get("image_role") == "evidence":
        if image["w"] * image["h"] < .16:
            return "本页图片承担证据作用，图片区域须足够大以辨认现场细节"
    return ""


def explain(elements: list, slide: dict, *, layered: bool = False) -> str:
    """Return why a composition is rejected, or "" when it passes.

    audit() used to answer only True/False, so the retry prompt could not tell
    the model what was wrong — it always sent the same catch-all sentence back
    and the second attempt failed the same way. The reason has to be specific
    (which region, how far out of bounds, which two regions overlap) to be
    actionable. audit() now delegates here, so both stay in lockstep.
    """
    values = references(slide)
    if not isinstance(elements, list):
        return "regions 不是数组"
    if len(elements) != len(values):
        present = {str(item.get("ref")) for item in elements if isinstance(item, dict)}
        missing = [ref for ref in values if ref not in present]
        extra = sorted(present - set(values) - {"None"})
        parts = []
        if missing:
            parts.append("缺少 " + "、".join(missing))
        if extra:
            parts.append("多出 " + "、".join(extra))
        return (f"regions 有 {len(elements)} 个，应为 {len(values)} 个"
                + ("（" + "；".join(parts) + "）" if parts else ""))
    overlay = (slide.get("design") or {}).get("image_overlay") == "dark"
    found, boxes = set(), []
    for item in elements:
        if not isinstance(item, dict) or not isinstance(item.get("ref"), str):
            return "有区域缺少 ref 字段"
        ref = item["ref"]
        if ref not in values:
            return f"未知区域 {ref}（只允许 {'、'.join(values)}）"
        if ref in found:
            return f"区域 {ref} 重复出现"
        found.add(ref)
        numbers = [item.get(key) for key in ("x", "y", "w", "h")]
        if any(type(value) not in (int, float) or not math.isfinite(value) for value in numbers):
            return f"区域 {ref} 的坐标不是有限数值"
        x, y, w, h = numbers
        if x < .035 or y < .025 or w <= .03 or h <= .02 or x+w > .965 or y+h > .89:
            return (f"区域 {ref} 越界：x={x:.3f} y={y:.3f} 右缘={x + w:.3f} "
                    f"底边={y + h:.3f}，须满足 x≥.035 y≥.025 右缘≤.965 底边≤.89")
        preferred = 28 if ref == "title" else (30 if len(values) == 2 else 20)
        # 大框短句原来恒按 20pt 排，卡片占 60% 页高却只有一两行字，
        # 形成明显空卡；高框放宽到 26pt。
        # ⚠ 但「框高」不等于「字数少」：三卡页的每个卡都占 56% 页高，
        # 塞 51 个字的段落时同样会放宽到 26pt，实测成稿正文 26pt、标题
        # 28pt，层级几乎相同，卡片被字挤满（用户 2026-11-09：字号太大、
        # 不和谐）。所以放宽条件必须同时看字数：只有真正的短句才提号。
        if ref.startswith("point:"):
            chars = sum(len(str(t)) for t in values[ref])
            if h >= .16 and chars <= 24:
                preferred = 26
        inset = 0 if ref == "title" else .04
        if w <= inset or h <= inset:
            return f"区域 {ref} 太小（{w:.2f}×{h:.2f}），扣除内边距后没有可排字的面积"
        size = (20 if ref in {"image", "chart", "table"} else fit_font_size(
            values[ref], w-inset, h-inset, preferred,
            min_pt=18 if ref == "title" else 14))
        if size is None:
            chars = sum(len(str(t)) for t in values[ref])
            return (f"区域 {ref} 只有 {w:.2f}×{h:.2f} 页宽页高，"
                    f"装不下 {chars} 个字（连 14pt 都放不进）；请加宽或加高该区域")
        item["font_pt"] = size
        item["budget_chars"] = (0 if ref in {"image", "chart", "table"} else
                               budget_chars(w-inset, h-inset, size))
        if ref == "chart" and (w < .36 or h < .30):
            return "图表区域至少需要页面宽度的 36% 和高度的 30%，否则类别与数值无法辨认"
        if ref == "table" and (w < .50 or h < .28):
            return "表格区域太小，至少需要页面宽度的 50% 和高度的 28%"
        for other, bx, by, bw, bh in boxes:
            if min(x+w, bx+bw)-max(x, bx) > .002 and min(y+h, by+bh)-max(y, by) > .002:
                if overlay and ((ref == "image" and other.startswith("point:"))
                                or (other == "image" and ref.startswith("point:"))):
                    image_box = (x, y, w, h) if ref == "image" else (bx, by, bw, bh)
                    text_box = (x, y, w, h) if ref.startswith("point:") else (bx, by, bw, bh)
                    ix, iy, iw, ih = image_box
                    tx, ty, tw, th = text_box
                    if layered and _intersection_area(image_box, text_box) / (tw * th) >= .70:
                        continue
                    if (not layered and tx >= ix + .015 and ty >= iy + .015
                            and tx + tw <= ix + iw - .015
                            and ty + th <= iy + ih - .015):
                        continue
                return (f"区域 {ref} 与 {other} 重叠，每个区域必须互不相交；"
                        f"请缩小其中一个或改为上下排列")
        boxes.append((ref, x, y, w, h))
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
    missing = [ref for ref in values if ref not in found]
    if missing:
        return "缺少区域 " + "、".join(missing)
    if overlay and ("image" not in values or not any(
            item["ref"].startswith("point:") and any(
                image["ref"] == "image" and
                ((_intersection_area((image["x"], image["y"], image["w"], image["h"]),
                                     (item["x"], item["y"], item["w"], item["h"]))
                  / (item["w"] * item["h"]) >= .70) if layered else (
                     item["x"] >= image["x"] + .015 and
                     item["y"] >= image["y"] + .015 and
                     item["x"] + item["w"] <= image["x"] + image["w"] - .015 and
                     item["y"] + item["h"] <= image["y"] + image["h"] - .015))
                for image in elements) for item in elements)):
        return "图文叠加须有图片，并把至少一条正文完整放在图片内侧"
    return ""


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
        # 三点对称页不再「上二下一、末条横跨整行」：一张 28 字的句子铺满整行
        # 会变成半页空白，且与 icon_grid 的 2+1 撞脸（用户 2026-11-09 说
        # 「还是同质化」就是这页）。改成三列等宽，靠装饰层的数字水印与卡片
        # 网格区分，不再靠几何硬凑。
        if n == 3:
            gap = .05
            width = (.89 - gap * 2) / 3
            return [{"ref": f"point:{i}", "x": .055 + i * (width + gap),
                     "y": .30, "w": width, "h": .50} for i in range(3)]
        # 多点对称：交错双栏，右列整体下移，避免与 two_col 的规整网格撞脸。
        gap, rows = .045, math.ceil(n / 2)
        w = (.89 - gap) / 2
        h = (.60 - .03 * (rows - 1) - .04) / rows
        boxes = [{"ref": f"point:{i}",
                  "x": .055 + (i % 2) * (w + gap),
                  "y": .245 + (i // 2) * (h + .03) + (i % 2) * .04,
                  "w": w, "h": h} for i in range(n)]
        return boxes
    if family == "statement" and n <= 4:
        # 居中大结论 + 其余要点下方横排；单点时就是整页一句大字。
        if n == 1:
            return [{"ref": "point:0", "x": .14, "y": .30, "w": .72, "h": .38}]
        if n >= 3:
            # 三条以上是并列关系，没有主次可分：排成等级一致的竖卡（不再做
            # 1 大 + n-1 小，那等于凭空造出主次，且字号差违反同级一致）。
            # 起点 .28、宽度 .84 与 three_cards / icon_grid 都不同，仍是自己的
            # 几何指纹，不会在选版时撞回网格族。
            gap = .03
            if n == 3:
                w = (.84 - gap * 2) / 3
                return [{"ref": f"point:{i}", "x": .08 + i * (w + gap),
                         "y": .28, "w": w, "h": .55} for i in range(3)]
            w = (.84 - gap) / 2
            h = (.52 - gap) / 2
            return [{"ref": f"point:{i}", "x": .08 + (i % 2) * (w + gap),
                     "y": .28 + (i // 2) * (h + gap), "w": w, "h": h} for i in range(4)]
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
    # 保留三列：4 条要点时末条通栏，是 three_cards 与 two_col / symmetric
    # 的关键几何差异（选版要能区分它们）。目录页的 2×2 另有 r_toc 处理。
    columns = 3 if variant in ("three_cards", "cards") else min(2, n)
    # 图标网格三条要点本来就该三列并排；落到两列会变成「上二下一」，
    # 和对称页/双栏页看不出区别。
    if variant == "icon_grid" and n == 3:
        columns = 3
    rows = math.ceil(n / columns)
    gap = .035
    width = (.89 - gap * (columns - 1)) / columns
    height = (.60 - gap * (rows - 1)) / rows
    boxes = [{"ref": f"point:{i}", "x": .055 + (i % columns) * (width + gap),
              "y": .245 + (i // columns) * (height + gap),
              "w": width, "h": height} for i in range(n)]
    # 末行不满时让最后一张横跨整行：三点的双列网格原本右下空一格，看着像漏排。
    if n % columns:
        boxes[-1].update({"x": .055, "w": .89})
    return boxes

def plan(slide: dict, layout: str) -> dict | None:
    from app.application.ppt.visual_primitives import decorations, model_visuals

    if slide.get("type") not in ("content", "case", "summary") or slide.get("blocks"):
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
        if audit(elements, slide) and not intent_issue(elements, slide):
            elements, visuals, changed = (
                (elements, design.get("visuals"), False) if design.get("image_overlay") == "dark"
                else compact_regions(elements, slide, design.get("visuals")))
            if changed and (not audit(elements, slide) or intent_issue(elements, slide)):
                # 收紧后反而越界/重叠：保留模型原构图，宁可留白也不压字。
                elements = clamp_regions(copy.deepcopy(suggested))
                visuals, changed = design.get("visuals"), False
            if changed:
                # 收紧结果写回 design：预览、缓存、导出三处必须读到同一份几何，
                # 否则线框里还是「大框短句」，成稿却是收过的。
                design["regions"] = [{key: item[key] for key in
                                      ("ref", "x", "y", "w", "h")} for item in elements]
                if isinstance(visuals, list):
                    design["visuals"] = visuals
                # 几何写回后指纹跟着变：不重算的话第二次 plan 会拿旧指纹去比
                # 缓存，每次都当未命中重排一遍（场景缓存等于失效）。
                stamp = signature(slide, layout)
            return scene_from(elements)
    elements = [{"ref": "title", "x": .055, "y": .05, "w": .89, "h": .12}]
    n = len(points)
    variant = layout.split(".")[-1]
    avg_chars = sum(len(str(p)) for p in points) / max(1, n)
    # 每条都长（>45 字）时竖卡/双列都放不下：三卡会把 60 字挤进 3 英寸宽的
    # 窄框（字号只能压到 12pt），双列则排成「上二下一 + 末条通栏」，那条
    # 又宽又扁、右侧全空。这类页统一走通栏横条带，每行读 30~38 字最舒服。
    long_text = (any(len(str(p)) > 80 for p in points) if variant == "compare"
                 else (n >= 3 and avg_chars > 45))
    elements.extend(_compose_points(
        variant, n, image, long_text,
        comparison=(design.get("relationship") == "comparison")))
    if image:
        elements.append({"ref": "image", "x": .58, "y": .245, "w": .365, "h": .60})
    # 两点对照（窄高框 + 中央留白）与单点大结论（整页一句大字）是专门设计的
    # 几何，不参与"按内容收紧 + 居中"——收紧会把对照页压成两块小框浮在中间，
    # 骨架感就没了。
    is_two_way_compare = (n == 2 and design.get("relationship") == "comparison"
                          and not image)
    is_single_statement = (variant == "statement" and n == 1)
    if not audit(elements, slide):
        return None
    if not (is_two_way_compare or is_single_statement):
        _tighten(elements, slide, points)
    return scene_from(elements)


def _tighten(elements: list, slide: dict, points: list) -> list:
    """按文字实际行数收紧正文块，整组在正文区垂直居中。

    排版器把正文框按格子平分（三卡页每卡占 56% 页高），但一条要点常常只有
    两三行，卡片上下各空一大块，读起来像「框没用完」——这是用户说的
    「同质化」里最刺眼的一层：每页都是几个大空块。收紧只缩小、不放大，
    字号沿用 audit 回填的结果，所以不会把字挤爆。
    """
    rows: list[list[dict]] = []
    for item in elements:
        ref = str(item.get("ref", ""))
        if not ref.startswith("point:"):
            continue
        try:
            text = str(points[int(ref.split(":", 1)[1])])
        except (ValueError, IndexError):
            continue
        size = float(item.get("font_pt") or 18)
        inner = max(.05, item["w"] - .04) * 960          # 内宽（磅）
        per_line = max(4, int(inner / max(1.0, size)))   # 一行约放多少个汉字
        lines = max(1, math.ceil(len(text) / per_line))
        need = min(item["h"], lines * size * 1.34 / 540 + .05)
        # 下限保证卡片有呼吸感，上限避免「一句话一张大卡」；真正的目标是
        # 让框高跟着内容走，而不是每页都撑成同样的几个大块。
        item["_need"] = min(.44, max(.30, need))
        for group in rows:
            if abs(group[0]["y"] - item["y"]) < .02:
                group.append(item)
                break
        else:
            rows.append([item])
    if not rows:
        return elements
    rows.sort(key=lambda g: min(i["y"] for i in g))
    gap = .035
    total = sum(max(i["_need"] for i in g) for g in rows) + gap * (len(rows) - 1)
    # 整组在正文区 .245–.86 内垂直居中：单排顶对齐会在下方空出半页，
    # 上下对称的留白才读作「排完了」。超过可用高度就保持原样（不压字）。
    if total > .86 - .245:
        return elements
    y = .245 + (.86 - .245 - total) / 2
    for group in rows:
        height = max(i["_need"] for i in group)
        for item in group:
            item["y"] = round(y, 4)
            item["h"] = round(height, 4)
        y += height + gap
    return elements


def _needed_height(text: str, width: float, size: float, limit: float) -> float:
    """一段正文排完需要多高（页高比例），口径与 _tighten 一致。"""
    inner = max(.05, width - .04) * 960          # 内宽（磅）
    per_line = max(4, int(inner / max(1.0, size)))
    lines = max(1, math.ceil(len(text) / per_line))
    return min(limit, lines * size * 1.34 / 540 + .045)


def compact_regions(elements: list, slide: dict, visuals: object = None):
    """把模型给的「大框短句」收成文字实际高度，模型画的卡片跟着一起走。

    模型只负责构图（谁在左、谁在右），不管字号和行数：一句十四字的话被分
    进占 46% 页高的框里，成稿就是「卡片顶上挂一行字、底下空一大片」。内置
    版式的网格早就用 _tighten 解决同一个问题，模型构图这条路一直没接——样稿
    里两张半页空的卡就是这么来的。

    收框必须连卡片一起搬：只缩文字框，卡片会留在原地，成稿变成一张空卡加
    一段悬空的字，比不收更糟。所以按「视觉元素包住了哪些区域」把收缩量传导
    过去，保持卡片与文字的上下留白不变。

    返回 (elements, visuals, changed)；视觉层无法解释时不强改，宁可留白也不
    做出压字或错位的构图。
    """
    points = slide.get("points") or []
    boxes = [item for item in elements
             if str(item.get("ref", "")).startswith("point:") and item.get("font_pt")]
    if not boxes:
        return elements, visuals, False
    before = {item["ref"]: {key: item[key] for key in ("x", "y", "w", "h")}
              for item in boxes}
    for item in boxes:
        try:
            text = str(points[int(str(item["ref"]).split(":", 1)[1])])
        except (ValueError, IndexError):
            text = ""
        need = _needed_height(text, item["w"], float(item["font_pt"]), item["h"])
        # 收紧要幂等：第二次进 explain 时字号可能从 26 掉到 25，需求高度跟着变
        # 一两千分之一；不设阈值的话每渲染一次框就再小一点（场景缓存重算、
        # 导出重建都会触发）。留 20% 余量，只收真正「大框短句」的那种。
        item["_need"] = need if need < item["h"] * .8 else item["h"]
    rows: list[list[dict]] = []
    for item in sorted(boxes, key=lambda b: (b["y"], b["x"])):
        if rows and abs(rows[-1][0]["y"] - item["y"]) <= .02:
            rows[-1].append(item)
        else:
            rows.append([item])
    gap = .035
    total = sum(max(entry["_need"] for entry in row) for row in rows)
    total += gap * (len(rows) - 1)
    top = min(entry["y"] for entry in boxes)
    has_image = any(item.get("ref") == "image" for item in elements)
    if total > .86 - .245:
        # 装不下就只收高度、不动起点，绝不压缩行距硬塞。
        for row in rows:
            height = round(max(entry["_need"] for entry in row), 4)
            for entry in row:
                entry["h"] = height
    else:
        # 图文页从正文起点往下排：卡片顶边跟图片顶边齐平，读起来是「左边两段
        # 说明、右边一张现场」，整组下移到页面正中反而比照片低一截。纯文字页
        # 才在正文区居中，上下留白对称。
        y = top if has_image else .245 + (.86 - .245 - total) / 2
        for row in rows:
            height = round(max(entry["_need"] for entry in row), 4)
            for entry in row:
                entry["y"], entry["h"] = round(y, 4), height
            y += height + gap
    for item in elements:
        item.pop("_need", None)
    changed = any(before[item["ref"]] != {key: item[key] for key in
                                          ("x", "y", "w", "h")} for item in boxes)
    adjusted = copy.deepcopy(visuals) if isinstance(visuals, list) else visuals
    if not isinstance(adjusted, list) or not changed:
        return elements, adjusted, changed
    band_top = min(before[item["ref"]]["y"] for item in boxes)
    band_bottom = max(before[item["ref"]]["y"] + before[item["ref"]]["h"]
                      for item in boxes)
    moved: list[tuple[float, float, float, float]] = []   # x, w, old_y, delta
    for visual in adjusted:
        if not isinstance(visual, dict) or visual.get("kind") == "line":
            continue
        if not all(type(visual.get(key)) in (int, float)
                   for key in ("x", "y", "w", "h")) or visual["h"] < .03:
            continue        # 色带/细线不包住区域，第二遍单独跟着区域平移
        inside = [item for item in boxes
                  if item["x"] >= visual["x"] - .006
                  and item["x"] + item["w"] <= visual["x"] + visual["w"] + .006
                  and item["y"] >= visual["y"] - .006
                  and item["y"] + item["h"] <= visual["y"] + visual["h"] + .006]
        if not inside:
            continue
        old_top = min(before[item["ref"]]["y"] for item in inside)
        old_bottom = max(before[item["ref"]]["y"] + before[item["ref"]]["h"]
                         for item in inside)
        new_top = min(item["y"] for item in inside)
        new_bottom = max(item["y"] + item["h"] for item in inside)
        pad_top = max(0.0, old_top - visual["y"])
        pad_bottom = max(0.0, (visual["y"] + visual["h"]) - old_bottom)
        was = visual["y"]
        visual["y"] = round(max(.02, new_top - pad_top), 4)
        visual["h"] = round(max(.03, (new_bottom - new_top) + pad_top + pad_bottom), 4)
        if visual["y"] + visual["h"] > .90:
            visual["h"] = round(max(.03, .90 - visual["y"]), 4)
        moved.append((visual["x"], visual["w"], was, visual["y"] - was))

    def _shift(left: float, width: float, top: float, bottom: float) -> float:
        """色带/细线该跟着谁走：先看正下方最近的那块文字，再看卡片。"""
        best = None
        for item in boxes:
            old = before[item["ref"]]
            overlap = (min(left + width, item["x"] + item["w"])
                       - max(left, item["x"]))
            if overlap <= .4 * min(width, item["w"]):
                continue
            distance = abs(old["y"] - bottom)
            if distance <= .03 and (best is None or distance < best[0]):
                best = (distance, item["y"] - old["y"])
        if best is not None:
            return best[1]
        for card_x, card_w, card_old_y, card_delta in moved:
            overlap = min(left + width, card_x + card_w) - max(left, card_x)
            if overlap <= .4 * min(width, card_w):
                continue
            if abs(card_old_y - top) <= .04:
                return card_delta
        return 0.0

    for visual in adjusted:
        if not isinstance(visual, dict):
            continue
        if visual.get("kind") == "line":
            if not all(type(visual.get(key)) in (int, float)
                       for key in ("x1", "y1", "x2", "y2")):
                continue
            ys = (visual["y1"], visual["y2"])
            if not all(band_top - .03 <= value <= band_bottom + .03 for value in ys):
                continue      # 标题下的分隔线不属于正文组，不动
            shift = _shift(min(visual["x1"], visual["x2"]),
                           abs(visual["x2"] - visual["x1"]), min(ys), max(ys))
            if shift:
                visual["y1"] = round(visual["y1"] + shift, 4)
                visual["y2"] = round(visual["y2"] + shift, 4)
            continue
        if not all(type(visual.get(key)) in (int, float)
                   for key in ("x", "y", "w", "h")) or visual["h"] >= .03:
            continue
        shift = _shift(visual["x"], visual["w"], visual["y"],
                       visual["y"] + visual["h"])
        if shift:
            visual["y"] = round(visual["y"] + shift, 4)
    return elements, adjusted, changed


def wireframe(scene: dict, slide: dict, colors: dict | None = None,
              canvas_height: int = 540) -> str:
    """Preview drawn from the same decoration list as the exported deck.

    Still a line-frame (not a pixel-perfect design proof), but relationship
    primitives, connectors, numbered badges and gradient bands are visible and
    share their geometry with ``r_scene``.
    """
    values = references(slide)
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 {canvas_height}">',
             f'<rect width="960" height="{canvas_height}" fill="white"/>']
    svg = (slide.get("design") or {}).get("svg")
    if svg:
        try:
            from app.application.ppt.svg_layer import to_png
            encoded = base64.b64encode(to_png(svg, scale=1)).decode("ascii")
            parts.append(f'<image href="data:image/png;base64,{encoded}" '
                         f'x="0" y="0" width="960" height="{canvas_height}"/>')
        except Exception:
            pass
    from app.application.ppt import visual_primitives as vp
    if canvas_height != 540:
        parts.append(f'<g transform="scale(1,{canvas_height / 540})">')
    for item in scene.get("visuals") or []:
        parts.append(vp.svg_decoration(item, colors))
    if canvas_height != 540:
        parts.append('</g>')
    for element in scene["elements"]:
        x, y, w, h = (element[k] * scale for k, scale in
                       (("x", 960), ("y", canvas_height),
                        ("w", 960), ("h", canvas_height)))
        label = escape(element["ref"] + " · " + values[element["ref"]][:16])
        parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" '
                     'fill="none" stroke="#304557" stroke-dasharray="4 3"/>')
        parts.append(f'<svg x="{x}" y="{y}" width="{w}" height="{h}" overflow="hidden">'
                     f'<text x="8" y="20" font-size="14">{label}</text></svg>')
    return "".join(parts) + "</svg>"
