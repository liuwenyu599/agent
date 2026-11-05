#!/usr/bin/env python3
"""验证：从数据库读取（seed 刷新后的）schema 直接渲染，统计模板版式复用率与兜底页数。

不走 analyze_template，纯用 ppt_templates.layout_library + source_file，
等价于生产环境 `render_pptx` 的学习渲染路径。
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
    row = conn.execute(
        "select name,category,colors,font,layouts,layout_library,source_file "
        "from ppt_templates where name=?", (name,)).fetchone()
    conn.close()
    if not row:
        raise SystemExit(f"模板不存在: {name}")
    d = dict(row)
    for key, empty in (("colors", {}), ("layouts", {})):
        d[key] = json.loads(d[key]) if d[key] else empty
    d["layout_library"] = json.loads(d["layout_library"]) if d["layout_library"] else []
    return d


def main():
    picked = []
    fallbacks = []

    orig_pick = pe._pick_layout
    orig_fill = pe._fill_readable_template_page

    def spy_pick(library, slide_type, used, preferred=None, slide=None):
        lay = orig_pick(library, slide_type, used, preferred, slide=slide)
        picked.append((slide_type, lay.get("id"), lay.get("detected_type")) if lay
                      else (slide_type, None, "MISS"))
        return lay

    def spy_fill(*args, **kwargs):
        fallbacks.append(1)
        return orig_fill(*args, **kwargs)

    for name in TARGETS:
        picked.clear()
        fallbacks.clear()
        pe._pick_layout = spy_pick
        pe._fill_readable_template_page = spy_fill
        t = load_row(name)
        base = PROCESSED / (t["source_file"] or "")
        if not base.exists():
            print(f"[跳过] {name} 底版缺失: {base}")
            continue
        warnings = []
        data = pe.render_pptx(SAMPLE_OUTLINE, pe.template_to_dict(t),
                              base_pptx=base.read_bytes(), warnings=warnings)
        pe._pick_layout = orig_pick
        pe._fill_readable_template_page = orig_fill
        out = ROOT / f"deliverables/_db_render_{name}.pptx"
        out.write_bytes(data)
        total = len(SAMPLE_OUTLINE["slides"])
        hits = sum(1 for p in picked if p[1])
        token_left = b"{{" in data
        print(f"\n=== {name} | 版式 {len(t['layout_library'])} | 页数 {total} ===")
        print(f"命中模板版式 {hits}/{total}｜兜底页 {len(fallbacks)}｜残留 token {token_left}")
        for st, lid, dt in picked:
            print(f"  {st:<8} -> {lid} ({dt})")
        if warnings:
            for w in warnings[:4]:
                print("  ! ", w)


if __name__ == "__main__":
    main()
