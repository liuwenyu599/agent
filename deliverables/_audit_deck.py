#!/usr/bin/env python3
"""对单个成品 PPTX 跑与模板体检同一套几何审计。

用法：python deliverables/_audit_deck.py <deck.pptx> [输出目录]
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "deliverables"))
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT / "deploy"))

from pptx import Presentation  # noqa: E402

import _template_audit as ta  # noqa: E402
from render_with_template import SAMPLE_OUTLINE  # noqa: E402


def audit_deck(pptx_path: Path, out_dir: Path) -> int:
    prs = Presentation(str(pptx_path))
    sw, sh = prs.slide_width, prs.slide_height
    pages = []
    for idx, slide in enumerate(prs.slides, 1):
        kind = (SAMPLE_OUTLINE["slides"][idx - 1]["type"]
                if idx <= len(SAMPLE_OUTLINE["slides"]) else "content")
        pages.append(ta.audit_slide(slide, idx, sw, sh, kind))
    bad = [p["index"] for p in pages
           if any(i["level"] == "FAIL" for i in p["issues"])]
    fails = sum(1 for p in pages for i in p["issues"] if i["level"] == "FAIL")
    warns = sum(1 for p in pages for i in p["issues"] if i["level"] == "WARN")
    if bad:
        ta.convert_previews(pptx_path, bad, out_dir)
    print(f"{pptx_path.name}: {len(pages)} 页 FAIL={fails} WARN={warns} "
          f"问题页={bad or '无'}")
    for p in pages:
        for i in p["issues"]:
            if i["level"] in ("FAIL", "WARN"):
                print(f"  第 {p['index']} 页 {i['type']}: {i['detail']} {i['text']}")
    return fails


if __name__ == "__main__":
    deck = Path(sys.argv[1])
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else deck.parent / "deck-previews"
    out.mkdir(parents=True, exist_ok=True)
    sys.exit(1 if audit_deck(deck, out) else 0)
