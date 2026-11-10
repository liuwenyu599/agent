"""Qualify reusable PPT layouts with real replacement content before publication.

The source slide is evidence of a design, not proof that another presentation
will fit it.  Keep the source and its review result together; rendering only
selects layouts whose replacement-content probes passed.
"""
from __future__ import annotations

import io
import tempfile
from collections import defaultdict
from pathlib import Path

from pptx import Presentation

from app.application.ppt import ppt_engine


_SPECIAL = {"cover", "toc", "section", "closing"}
_SAMPLE = "推进司法行政工作提升公共法律服务质效"


def _words(length: int) -> str:
    return (_SAMPLE * (length // len(_SAMPLE) + 1))[:length]


def _content_slots(layout: dict) -> list[dict]:
    return [item for item in layout.get("text_regions") or []
            if item.get("role") not in {"title", "subtitle"}
            and item.get("w", 0) >= .25 and item.get("h", 0) >= .08
            and item.get("y", 1) < .9]


def _slot_contract(layout: dict) -> list[dict]:
    budget = ppt_engine.template_content_budget([layout])
    return budget[0]["slots"] if budget else []


def _source_issues(layout: dict, primary: str = "") -> list[str]:
    """Reject defects that content fitting cannot repair."""
    issues = []
    elements = [item for item in layout.get("element_schema") or []
                if item.get("role") != "fixed"]
    texts = [item for item in elements if item.get("kind") == "text"]
    for item in texts:
        if (item.get("w", 0) <= 0 or item.get("h", 0) <= 0 or
                item.get("x", 0) < -.02 or item.get("y", 0) < -.02 or
                item.get("x", 0) + item.get("w", 0) > 1.02 or
                item.get("y", 0) + item.get("h", 0) > 1.02):
            issues.append("可编辑文字框越出页面")
            break
    if not any("title" in (item.get("placeholder_keys") or []) for item in texts):
        # Legacy decks may have no explicit token.  The existing filler treats
        # the largest text frame as the title, so keep that compatibility.
        if not texts:
            issues.append("缺少标题文字框")
        else:
            guessed = max(texts, key=lambda item: item.get("font_size") or 0)
            if (layout.get("detected_type") != "toc" and
                    guessed.get("y", 1) > .25 and
                    any(item.get("y", 1) < .18 and
                        (item.get("font_size") or 0) >= 18 for item in texts)):
                issues.append("标题槽可能误识别为正文数字或卡片")
    if layout.get("detected_type") not in _SPECIAL and not _content_slots(layout):
        issues.append("缺少可编辑正文区域")
    if primary and not ppt_engine._layout_matches_theme(layout, primary):
        issues.append("版式配色与模板主色不一致")

    # Same-sized peer cards are one visual level.  An enormous first-card font
    # beside three small peers makes the page look broken even when each fits.
    peers = defaultdict(list)
    for item in elements:
        if item.get("kind") != "text" or item.get("font_size", 0) < 13:
            continue
        if "title" in (item.get("placeholder_keys") or []):
            continue
        key = (round(item.get("w", 0) * 10), round(item.get("h", 0) * 10))
        peers[key].append(float(item.get("font_size") or 18))
    if any(len(sizes) >= 3 and max(sizes) / min(sizes) > 1.8
           for sizes in peers.values()):
        issues.append("同级卡片文字字号差异过大")
    return issues


def _probe_slide(layout: dict, density: float) -> dict:
    kind = str(layout.get("detected_type") or "content")
    slots = _slot_contract(layout)
    title_budget = next((int(s["suggested_chars"]) for s in slots
                         if s["role"] == "title"), 16)
    title_length = max(4, min(22, round(title_budget * density)))
    title = ("版式试填" + _words(max(0, title_length - 4)))[:title_length]
    body_slots = _content_slots(layout)
    count = min(6, len(body_slots))
    if kind in _SPECIAL:
        count = 0 if kind in {"cover", "closing"} else min(3, count)
    body_budgets = [int(slot["suggested_chars"])
                    for region, slot in zip(layout.get("text_regions") or [], slots)
                    if region in body_slots]
    points = [_words(max(2, min(36, round(
        (body_budgets[min(index, len(body_budgets) - 1)]
         if body_budgets else 18) * density))))
              for index in range(count)]
    # Repeated test strings make the content-integrity check ambiguous.  Give
    # each point a distinct leading numeral without changing its length.
    points = [f"{index + 1}{value[1:]}" for index, value in enumerate(points)]
    return {"type": kind, "layout": layout["id"], "title": title,
            "subtitle": "司法行政工作汇报" if kind == "cover" else "",
            "points": points}


def _render_probe(source: bytes, learned: dict, layout: dict,
                  density: float) -> str | None:
    """Run the production clone/fill path, then read the produced PPTX back."""
    slide = _probe_slide(layout, density)
    template = {"colors": learned["colors"], "font": learned["font"],
                "layouts": {slide["type"]: layout["id"]}}
    warnings: list[str] = []
    with tempfile.TemporaryDirectory(prefix="ppt-layout-probe-") as td:
        if any(ppt_engine._element_is_image_slot(item)
               for item in layout.get("element_schema") or []):
            from PIL import Image
            image_path = Path(td) / "sample.png"
            Image.new("RGB", (640, 360), (205, 215, 225)).save(image_path)
            slide["_image"] = {"file_path": str(image_path)}
        result = ppt_engine.build_pptx_learned(
            {"slides": [slide]}, template, source, [layout], warnings)
    if any("可读版式" in value or "已省略" in value for value in warnings):
        return "试填后改用基础排版或丢失内容"
    page = Presentation(io.BytesIO(result)).slides[0]
    visible = "\n".join(shape.text_frame.text for shape in page.shapes
                        if getattr(shape, "has_text_frame", False))
    if "{{" in visible or slide["title"] not in visible:
        return "占位符未替换或标题缺失"
    if any(point not in visible for point in slide["points"]):
        return "正文试填后缺失"
    return None


def qualify_template(source: bytes, learned: dict) -> dict:
    """Attach per-layout review results and return counts for the import UI.

    The short and medium probes are mandatory.  The long probe records the
    usable range; a compact card can be a good layout without holding prose.
    """
    qualified = 0
    for layout in learned.get("layouts") or []:
        source_issues = _source_issues(
            layout, (learned.get("colors") or {}).get("primary", ""))
        probe_issues = []
        probes = {}
        if not source_issues:
            for label, density in (("short", .35), ("medium", .65),
                                   ("long", 1.0)):
                try:
                    probes[label] = _render_probe(source, learned, layout, density)
                except Exception as exc:
                    probes[label] = f"试填渲染失败：{type(exc).__name__}"
            for label in ("short", "medium"):
                if probes[label]:
                    probe_issues.append(f"{label}：{probes[label]}")
        issues = source_issues + probe_issues
        passed = not issues
        warnings = ([f"long：{probes['long']}"] if probes.get("long") else [])
        layout["qualification"] = {
            "status": "qualified" if passed else "rejected",
            "issues": issues,
            "source_issues": source_issues,
            "probe_issues": probe_issues,
            "warnings": warnings,
            "probes": {key: "passed" if value is None else value
                       for key, value in probes.items()},
            "slots": _slot_contract(layout),
        }
        qualified += passed
    return {"qualified": qualified,
            "rejected": len(learned.get("layouts") or []) - qualified}


def has_qualified_content(learned: dict) -> bool:
    """A cover/ending-only library is not a usable presentation template."""
    return any(layout.get("detected_type") not in _SPECIAL and
               (layout.get("qualification") or {}).get("status") == "qualified"
               for layout in learned.get("layouts") or [])


def build_probe_deck(source: bytes, learned: dict, image_dir: Path) -> tuple[bytes, list[str]]:
    """Build one medium-density page per accepted layout for visual review."""
    layouts = [item for item in learned.get("layouts") or []
               if (item.get("qualification") or {}).get("status") == "qualified"]
    slides = []
    for layout in layouts:
        slide = _probe_slide(layout, .65)
        if any(ppt_engine._element_is_image_slot(item)
               for item in layout.get("element_schema") or []):
            from PIL import Image
            image_path = image_dir / "sample.png"
            if not image_path.exists():
                Image.new("RGB", (640, 360), (205, 215, 225)).save(image_path)
            slide["_image"] = {"file_path": str(image_path)}
        slides.append(slide)
    template = {"colors": learned["colors"], "font": learned["font"],
                "layouts": {}}
    return (ppt_engine.build_pptx_learned(
        {"slides": slides}, template, source, layouts),
        [item["id"] for item in layouts])
