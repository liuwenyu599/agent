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


def read_template_reference(template: dict, preview_dir: Path) -> bytes | None:
    """Read one original content-page preview for optional visual grounding."""
    for layout in template.get("layout_library") or []:
        if (layout.get("detected_type") not in {"content", "case", "summary"}
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
