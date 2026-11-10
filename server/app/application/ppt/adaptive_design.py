"""Content-aware geometry for free-form slides; coordinates are page fractions."""
from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from typing import Sequence


@dataclass(frozen=True)
class DesignTokens:
    margin: float = 0.055
    content_top: float = 0.235
    content_bottom: float = 0.88
    gutter: float = 0.025
    title_pt: int = 28
    body_pt: int = 20
    compact_pt: int = 14
    caption_pt: int = 11


TOKENS = DesignTokens()


def budget_chars(width: float, height: float, font_pt: float,
                 deck_width_pt: float = 960, deck_height_pt: float = 540) -> int:
    """Conservative CJK writing budget shared by template and scene planning."""
    columns = max(1, int(width * deck_width_pt * .85 / font_pt))
    lines = max(1, int(height * deck_height_pt * .8 / (font_pt * 1.35)))
    return columns * lines


def text_units(value: str) -> float:
    """Approximate rendered width without relying on a specific installed font."""
    return sum(1.0 if ord(char) > 0x2E80 else 0.56 for char in str(value))


def estimated_lines(value: str, width: float, font_pt: int,
                    deck_width_pt: float = 960.0) -> int:
    # Standard deck: 13.333 inches wide, 72 points per inch. 非标准宽度（如 10in）
    # 必须传 deck_width_pt，否则会把容量高估、判定为"装得下"。
    capacity = max(1.0, deck_width_pt * width / font_pt)
    return max(1, sum(ceil(text_units(line) / capacity)
                      for line in str(value).splitlines() or [""]))


def fit_font_size(texts, width: float, height: float, preferred_pt: float, *,
                  deck_width_pt: float = 960.0, deck_height_pt: float = 540.0,
                  min_pt: float = 13.0) -> float | None:
    """装下 texts 的最大字号（≤ preferred_pt）；缩到 min_pt 仍装不下返回 None。

    width / height 是相对页宽 / 页高的比例。度量与引擎 `_shrink_text_to_fit`
    保持一致（宽度打 0.85 折、行高 1.22、高度容差 1.15），因此「判定放行」等价于
    「填充时一定缩得进框」——容量闸门不该比实际缩号能力更严，否则模板里明明能
    用的版式会被大面积误拒，只能退回通用排版。
    """
    values = [texts] if isinstance(texts, str) else [str(t) for t in (texts or [])]
    values = [t for t in values if t.strip()]
    if not values:
        return float(preferred_pt)
    usable_w = max(0.02, width) * 0.85
    budget = max(1.0, height * deck_height_pt * 1.15)
    # 框高只装得下单行的槽（红条/标题条），按单行判定：容差再宽也不能把
    # 两行字塞进一行框，第二行必然溢出到框外。判定用原始框高（不带容差），
    # 否则 29pt 的红条配 18pt 字（1.6 倍）会差一点漏判成多行框。
    one_line_only = height * deck_height_pt < max(6.0, float(preferred_pt)) * 1.8
    size = max(6.0, float(preferred_pt))
    while size >= min_pt:
        lines = sum(estimated_lines(t, usable_w, int(round(size)),
                                    deck_width_pt=deck_width_pt) for t in values)
        if lines * size * 1.22 <= budget and (lines <= 1 or not one_line_only):
            return size
        size -= 1
    return None


def point_rows(points: Sequence[str], width: float,
               *, top: float = TOKENS.content_top,
               bottom: float = TOKENS.content_bottom,
               preferred_pt: int = TOKENS.body_pt) -> tuple[int, list[tuple[float, float]]]:
    """Allocate more vertical room to points that wrap onto multiple lines."""
    if not points:
        return preferred_pt, []
    available = bottom - top
    font_pt = preferred_pt
    while font_pt > TOKENS.compact_pt:
        lines = [estimated_lines(point, width, font_pt) for point in points]
        minimum = [max(0.09, count * font_pt * 1.35 / 540 + 0.028)
                   for count in lines]
        if sum(minimum) <= available:
            break
        font_pt -= 1
    else:
        lines = [estimated_lines(point, width, font_pt) for point in points]
        minimum = [max(0.09, count * font_pt * 1.35 / 540 + 0.028)
                   for count in lines]
    if sum(minimum) > available:
        # Keep every row within the page; visual review reports any remaining
        # text-density problem instead of silently discarding a point.
        heights = [value * available / sum(minimum) for value in minimum]
    else:
        spare = (available - sum(minimum)) / len(minimum)
        heights = [value + spare for value in minimum]
    result = []
    y = top
    for height in heights:
        result.append((y, height))
        y += height
    return font_pt, result


def compare_geometry(points: Sequence[str]) -> tuple[str, list[tuple[float, float, float, float]]]:
    """Use wide stacked bands when side-by-side reading would make text cramped."""
    values = [str(point) for point in points[:2]]
    if any(estimated_lines(value, 0.33, TOKENS.body_pt) > 5 for value in values):
        return "stacked", [(0.06, 0.245, 0.88, 0.29),
                           (0.06, 0.555, 0.88, 0.29)]
    first = text_units(values[0]) if values else 1.0
    second = text_units(values[1]) if len(values) > 1 else 1.0
    left_width = max(0.39, min(0.46, 0.855 * first / max(first + second, 1)))
    right_width = 0.855 - left_width
    return "side", [(0.055, 0.265, left_width, 0.53),
                    (0.09 + left_width, 0.265, right_width, 0.53)]


def plan_image_composition(points: Sequence[str], image_ratio: float, *,
                           left: float, right: float, top: float, bottom: float,
                           side: str = "right") -> dict:
    """Choose the image/text relationship before either region is drawn.

    Coordinates are page fractions. A selected image is content, so template
    placeholders do not determine its size or whether it appears at all.
    """
    count = len(points)
    units = sum(text_units(point) for point in points)
    width, height = right - left, bottom - top
    gap = min(.035, width * .045)
    if image_ratio >= 2.1 and count == 1 and units <= 55:
        image_h = height * .62
        return {"mode": "banner",
                "image": (left, top, width, image_h),
                "text": (left + .02, top + image_h + .07,
                         width - .04, height - image_h - .07),
                "preferred_pt": 20}
    if count >= 4 or units > 150:
        share = .31
        preferred_pt = 15
    elif image_ratio < .9:
        share = .35
        preferred_pt = 17
    elif count <= 2 and units <= 80:
        share = .56
        preferred_pt = 20
    else:
        share = .44
        preferred_pt = 17
    if image_ratio >= 1.6 and count <= 3 and units <= 115:
        side = "left"
    image_w = width * share
    text_w = width - image_w - gap
    if side == "left":
        image_x, text_x = left, left + image_w + gap
    else:
        image_x, text_x = right - image_w, left
    return {"mode": "side", "image": (image_x, top, image_w, height),
            "text": (text_x, top, text_w, height),
            "preferred_pt": preferred_pt}
