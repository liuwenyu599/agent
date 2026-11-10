"""Safe, text-free SVG artwork behind editable PowerPoint carriers.

The authoring source remains SVG. Export rasterizes only this decorative layer;
all slide wording and selected photos remain separate PowerPoint objects.
"""
from __future__ import annotations

import io
import math
import re
from functools import lru_cache

from defusedxml import ElementTree

_DRAWABLE = {"path", "rect", "circle", "ellipse", "line",
         "polyline", "polygon"}
_TAGS = {"svg", "g"} | _DRAWABLE
_SOLID_COLOR = re.compile(r"(?:none|#[0-9a-fA-F]{3}|#[0-9a-fA-F]{6})\Z")
_MAX_RENDER_PIXELS = 2400 * 1800
_MAX_SCALE = 2.5  # 960 design units across a 10-inch page: 240 DPI.


def viewbox_height(width: int, height: int) -> int:
    """Use 960 horizontal design units at the actual slide aspect ratio."""
    return round(960 * height / width)


def validate(svg: object, *, width: int | None = None,
             height: int | None = None) -> str:
    """Return a concrete rejection reason, or an empty string for safe artwork."""
    if not isinstance(svg, str) or not svg.strip():
        return "SVG 为空"
    if len(svg) > 60_000:
        return "SVG 超过 60000 字符"
    if "<!doctype" in svg.lower():
        return "SVG 不允许文档类型声明"
    try:
        root = ElementTree.fromstring(svg)
    except Exception:
        return "SVG 不是有效 XML"
    if root.tag.rsplit("}", 1)[-1] != "svg":
        return "根元素须为 svg"
    viewbox = root.get("viewBox") or ""
    if width and height:
        expected = f"0 0 960 {viewbox_height(width, height)}"
        if viewbox != expected:
            return f"SVG viewBox 须为 {expected}，以匹配页面画幅"
    else:
        match = re.fullmatch(r"0 0 960 ([1-9]\d{2})", viewbox)
        if not match or not 360 <= int(match.group(1)) <= 900:
            return "SVG viewBox 须为 0 0 960 高度（360～900）"
    nodes = list(root.iter())
    if len(nodes) > 300:
        return "SVG 元素过多"
    if sum(node.tag.rsplit("}", 1)[-1] in _DRAWABLE for node in nodes) > 128:
        return "SVG 可绘制图形超过 128 个，无法逐形状验收"
    for node in nodes:
        kind = node.tag.rsplit("}", 1)[-1]
        if kind not in _TAGS:
            return f"SVG 不允许 {kind} 元素；文字和图片须走可编辑图文层"
        if (node.text or "").strip() or (node.tail or "").strip():
            return "SVG 不允许文字内容；文字须走可编辑文本框"
        for key, value in node.attrib.items():
            attr = key.rsplit("}", 1)[-1].lower()
            low = value.lower()
            if attr.startswith("on") or attr in {"href", "src"}:
                return f"SVG 不允许 {attr} 属性"
            if attr == "style":
                return "SVG 请使用独立的填色和描边属性，不支持 style 属性"
            if attr in {"fill", "stroke"} and not _SOLID_COLOR.fullmatch(value):
                return f"SVG 不支持 {attr}={value[:32]}；请使用纯色十六进制值或 none"
            if "url(" in low:
                return "SVG 当前不支持引用式填充或渐变；请使用纯色路径"
            if ("javascript:" in low or "data:" in low
                    or "@import" in low or "expression(" in low):
                return "SVG 不允许外部资源或脚本"
    return ""


@lru_cache(maxsize=128)
def _visibility_issue(svg: str) -> str:
    """A shape must change final pixels; this also detects full occlusion.

    Rendering each minus-one variant at half resolution avoids false failures
    for long thin curves, whose bbox can be mostly empty by design.
    """
    from PIL import Image, ImageChops
    import pymupdf

    def sample(source: str) -> Image.Image:
        with pymupdf.open(stream=source.encode("utf-8"), filetype="svg") as doc:
            pixmap = doc[0].get_pixmap(matrix=pymupdf.Matrix(.5, .5),
                                      alpha=True)
            with Image.open(io.BytesIO(pixmap.tobytes("png"))) as image:
                return image.convert("RGBA")

    root = ElementTree.fromstring(svg)
    parents = {child: parent for parent in root.iter() for child in parent}
    drawables = [node for node in root.iter()
                 if node.tag.rsplit("}", 1)[-1] in _DRAWABLE]
    if not drawables:
        return "SVG 没有可见图形"
    baseline = sample(svg)
    for index, node in enumerate(drawables, 1):
        parent = parents[node]
        position = list(parent).index(node)
        parent.remove(node)
        try:
            without = sample(ElementTree.tostring(root, encoding="unicode"))
        except Exception:
            return f"SVG 第{index}个图形无法验证"
        finally:
            parent.insert(position, node)
        if without.size != baseline.size:
            return f"SVG 第{index}个图形导致画布尺寸变化"
        difference = ImageChops.difference(baseline, without)
        if not any(channel.getbbox() for channel in difference.split()):
            return f"SVG 第{index}个图形未出现在最终画面（渲染失败或完全遮挡）"
        paints = [node.get(key) for key in ("fill", "stroke")
                  if node.get(key) and node.get(key) != "none"]
        if not paints:
            continue
        expected = []
        for paint in paints:
            hex_color = paint.lstrip("#")
            if len(hex_color) == 3:
                hex_color = "".join(value * 2 for value in hex_color)
            expected.append(tuple(int(hex_color[offset:offset + 2], 16)
                                  for offset in (0, 2, 4)))
        isolated_root = ElementTree.fromstring(svg)
        isolated_nodes = [item for item in isolated_root.iter()
                          if item.tag.rsplit("}", 1)[-1] in _DRAWABLE]
        isolated_parents = {child: owner for owner in isolated_root.iter()
                            for child in owner}
        for other_index, other in enumerate(isolated_nodes, 1):
            if other_index != index:
                isolated_parents[other].remove(other)
        isolated = sample(ElementTree.tostring(isolated_root, encoding="unicode"))
        colored = (pixel[:3] for pixel in isolated.get_flattened_data()
                   if pixel[3] > 32)
        if not any(all(abs(actual - target) <= 12
                       for actual, target in zip(pixel, color))
                   for pixel in colored for color in expected):
            return f"SVG 第{index}个图形的填色或描边未按指定颜色渲染"
    return ""


def to_png(svg: str, scale: float = _MAX_SCALE, *, width: int | None = None,
           height: int | None = None) -> bytes:
    issue = validate(svg, width=width, height=height)
    if issue:
        raise ValueError(issue)
    issue = _visibility_issue(svg)
    if issue:
        raise ValueError(issue)
    if not isinstance(scale, (int, float)) or not math.isfinite(scale) or scale <= 0:
        raise ValueError("SVG 渲染倍率须为正数")
    import pymupdf

    with pymupdf.open(stream=svg.encode("utf-8"), filetype="svg") as doc:
        if doc.page_count != 1:
            raise ValueError("SVG 须为单页")
        page = doc[0]
        area = page.rect.width * page.rect.height
        if area <= 0:
            raise ValueError("SVG 画布尺寸无效")
        actual_scale = min(scale, _MAX_SCALE,
                           math.sqrt(_MAX_RENDER_PIXELS / area))
        for _ in range(3):
            pixmap = page.get_pixmap(
                matrix=pymupdf.Matrix(actual_scale, actual_scale), alpha=True)
            if pixmap.width * pixmap.height <= _MAX_RENDER_PIXELS:
                opaque = pixmap.samples[3::4].count(255)
                if opaque > pixmap.width * pixmap.height * .60:
                    raise ValueError("SVG 不透明像素覆盖超过 60%，请改用页面背景层")
                return pixmap.tobytes("png")
            # Integer rounding can add a few pixels; retry at a slightly
            # smaller scale instead of silently dropping the visual layer.
            actual_scale *= math.sqrt(
                _MAX_RENDER_PIXELS / (pixmap.width * pixmap.height)) * .995
        raise ValueError("SVG 渲染尺寸无法收敛到像素预算")


def add_to_slide(slide, svg: str, width: int, height: int) -> None:
    """Add arbitrary path artwork as one transparent visual layer."""
    slide.shapes.add_picture(io.BytesIO(to_png(svg, width=width, height=height)),
                             0, 0, width, height)


def fixed_decoration_overlap(png: bytes, slide, width: int, height: int) -> bool:
    """Check painted SVG pixels against retained edge artwork and master marks."""
    from PIL import Image

    ancestors = [slide, slide.slide_layout]
    try:
        ancestors.append(slide.slide_layout.slide_master)
    except AttributeError:
        pass
    with Image.open(io.BytesIO(png)) as artwork:
        alpha = artwork.getchannel("A")
        for owner in ancestors:
            for shape in owner.shapes:
                if getattr(shape, "is_placeholder", False):
                    continue
                try:
                    x, y = shape.left / width, shape.top / height
                    w, h = shape.width / width, shape.height / height
                except (AttributeError, TypeError, ZeroDivisionError):
                    continue
                if (w <= 0 or h <= 0 or w * h > .15 or
                        not (x < .18 or x + w > .82 or
                             y < .18 or y + h > .82)):
                    continue
                box = (max(0, round(x * alpha.width)),
                       max(0, round(y * alpha.height)),
                       min(alpha.width, round((x + w) * alpha.width)),
                       min(alpha.height, round((y + h) * alpha.height)))
                if box[2] <= box[0] or box[3] <= box[1]:
                    continue
                if alpha.crop(box).point(lambda value: 255 if value > 12 else 0).getbbox():
                    return True
    return False
