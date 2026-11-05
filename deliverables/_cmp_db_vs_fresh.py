#!/usr/bin/env python3
"""对比：库内存储 schema 与「现渲染时重新分析」的复用率差异。

同一份 _processed 底版，两条路径各渲一遍：
  A. 用 ppt_templates.layout_library（seed 落库结果）
  B. 用 analyze_template(bytes) 现场分析
差异大 → 说明库里 schema 是旧代码产物，需要重新落库。
"""
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))

from app.application.ppt import ppt_engine as pe  # noqa: E402
sys.path.insert(0, str(ROOT / "deploy"))
from render_with_template import SAMPLE_OUTLINE  # noqa: E402

DB = ROOT / "server/data/judicial_app.db"
PROCESSED = ROOT / "ppttem/_processed"
TARGETS = ["党委党支部工作汇报", "中国首部民法典解读", "简约黑白大气商务", "简洁年中工作总结计划"]


def load_row(name):
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    row = conn.execute("select name,category,colors,font,layouts,layout_library,source_file "
                       "from ppt_templates where name=?", (name,)).fetchone()
    conn.close()
    d = dict(row)
    for key in ("colors", "layouts", "layout_library"):
        if isinstance(d.get(key), str):
            d[key] = json.loads(d[key]) if d[key] else ([] if key == "layout_library" else {})
    return d


def render_with(library, template, base_bytes):
    picked, fallbacks = [], []
    orig_pick, orig_fill = pe._pick_layout, pe._fill_readable_template_page

    def spy_pick(library_, slide_type, used, preferred=None, slide=None):
        lay = orig_pick(library_, slide_type, used, preferred, slide=slide)
        picked.append((slide_type, lay.get("id") if lay else None,
                       lay.get("detected_type") if lay else "MISS"))
        return lay

    def spy_fill(*a, **k):
        fallbacks.append(1)
        return orig_fill(*a, **k)

    pe._pick_layout, pe._fill_readable_template_page = spy_pick, spy_fill
    try:
        tpl = {**template, "layout_library": library}
        warnings = []
        data = pe.render_pptx(SAMPLE_OUTLINE, tpl, base_pptx=base_bytes, warnings=warnings)
    finally:
        pe._pick_layout, pe._fill_readable_template_page = orig_pick, orig_fill
    return data, picked, fallbacks, warnings


def tokens_left(data):
    """统计 p:txBody 里残留的 {{token}}（只算可见文字）。"""
    import io
    import re
    from pptx import Presentation
    prs = Presentation(io.BytesIO(data))
    found = []
    for i, slide in enumerate(prs.slides):
        for shape in slide.shapes:
            if not shape.has_text_frame:
                continue
            m = re.findall(r"\{\{[a-zA-Z][a-zA-Z0-9_]*\}\}", shape.text_frame.text or "")
            if m:
                found.append((i, shape.name, m))
    return found


def main():
    for name in TARGETS:
        t = load_row(name)
        base = PROCESSED / (t["source_file"] or "")
        if not base.exists():
            print(f"[跳过] {name} 底版缺失")
            continue
        raw = base.read_bytes()
        db_lib = t["layout_library"]
        fresh = pe.analyze_template(raw)
        fresh_lib = fresh.get("layouts") or []

        data_a, pick_a, fb_a, warn_a = render_with(db_lib, pe.template_to_dict(t), raw)
        tpl_b = pe.template_to_dict(t)
        tpl_b["colors"] = fresh.get("colors") or tpl_b["colors"]
        data_b, pick_b, fb_b, _ = render_with(fresh_lib, tpl_b, raw)

        print(f"\n=== {name} ===")
        print(f"库内版式 {len(db_lib)}｜现分析版式 {len(fresh_lib)}")
        for tag, pick, fb, data in (("库内", pick_a, fb_a, data_a), ("现分析", pick_b, fb_b, data_b)):
            hit = sum(1 for p in pick if p[1])
            print(f"  {tag}: 命中 {hit}/12 兜底 {len(fb)}｜"
                  f"页型 {[p[2] for p in pick]}")
        left_a, left_b = tokens_left(data_a), tokens_left(data_b)
        print(f"  残留token 库内={len(left_a)} 现分析={len(left_b)}")
        if left_a:
            print("   库内样例:", left_a[:3])
        (ROOT / f"deliverables/_cmp_db_{name}.pptx").write_bytes(data_a)
        (ROOT / f"deliverables/_cmp_fresh_{name}.pptx").write_bytes(data_b)


if __name__ == "__main__":
    main()
