"""Small, reusable visual grammar distilled from imported PPTX layouts.

The sample slide's words and photographs are never included. Only repeatable
typography and shape motifs are exposed to the page designer and compiler.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path
from statistics import median


def summarize_template_style(template: dict) -> dict:
    layouts = [item for item in (template.get("layout_library") or [])
               if item.get("detected_type") in {"content", "summary", "case"}
               and (item.get("qualification") or {}).get("status") != "rejected"][:12]
    title_sizes: list[float] = []
    body_sizes: list[float] = []
    motifs: Counter[str] = Counter()
    for layout in layouts:
        for region in layout.get("text_regions") or []:
            try:
                size = float(region.get("font_size") or 0)
            except (TypeError, ValueError):
                continue
            if not 12 <= size <= 48:
                continue
            if region.get("role") == "title":
                title_sizes.append(size)
            elif region.get("role") == "body" and not region.get("bold"):
                body_sizes.append(size)
        for shape in layout.get("element_schema") or []:
            if shape.get("kind") != "shape":
                continue
            kind = str(shape.get("shape_type") or "").upper()
            if "ROUNDED_RECTANGLE" in kind:
                motifs["rounded_cards"] += 1
            elif "OVAL" in kind:
                motifs["circles"] += 1
            elif "CHEVRON" in kind:
                motifs["chevrons"] += 1
    result = {"motifs": [name for name, _ in motifs.most_common(3)]}
    if title_sizes:
        result["title_font_pt"] = int(median(title_sizes))
    if body_sizes:
        result["body_font_pt"] = int(median(body_sizes))
    return result


_NON_BODY_TYPES = {"cover", "toc", "section", "closing"}


def read_template_reference(template: dict, preview_dir: Path) -> bytes | None:
    """Read one original content-page preview for optional visual grounding.

    排除法而不是「只认 content/case/summary」：采购模板的正文版式常被识别成
    ``cards`` / ``content_image`` / ``two_col`` 等结构名，旧白名单会把整套模板
    的预览都跳过，模型于是静默退回文字摘要——勾掉保底真跑时，这一步决定
    「模型是否真的看过模板」。与 deploy/ppt_eval/check_previews.py 的正文判据一致。
    """
    for layout in template.get("layout_library") or []:
        if (layout.get("detected_type") in _NON_BODY_TYPES
                or (layout.get("qualification") or {}).get("status") == "rejected"):
            continue
        for name in (layout.get("source_preview"), layout.get("preview")):
            if not isinstance(name, str) or not name.endswith(".png"):
                continue
            # A database-supplied preview name must never escape the template folder.
            if Path(name).name != name:
                continue
            path = preview_dir / name
            try:
                if path.is_file() and path.stat().st_size <= 5_000_000:
                    return path.read_bytes()
            except OSError:
                continue
    return None
