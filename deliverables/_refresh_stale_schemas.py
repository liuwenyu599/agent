#!/usr/bin/env python3
"""库内 schema 保活：逐模板对比库内 layout_library 与 analyze_template 现算结果，
页型/几何不一致（预处理产物被 _reprep 覆盖、分类口径变化等导致）就重新落库。

用法：python deliverables/_refresh_stale_schemas.py [--dry-run]
"""
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))

from app.application.ppt import ppt_engine as pe  # noqa: E402

DB = ROOT / "server/data/judicial_app.db"
PROCESSED = ROOT / "ppttem/_processed"
DRY = "--dry-run" in sys.argv


def sig(lib):
    return {l["id"]: l.get("detected_type") for l in lib}


def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("select id,name,colors,font,layout_library,source_file "
                        "from ppt_templates where source_file is not null").fetchall()
    updated = 0
    for row in rows:
        base = PROCESSED / row["source_file"]
        if not base.exists():
            continue
        fresh = pe.analyze_template(base.read_bytes())
        fresh_lib = fresh.get("layouts") or []
        if not fresh_lib:
            print(f"[跳过] {row['name']} 现分析为空")
            continue
        old_lib = json.loads(row["layout_library"] or "[]")
        # vert（竖排）字段是后来加进 schema 的：老库没有它，fit 闸门判不了
        # 竖排槽，所以除了页型差异，字段缺失也要重算落库。
        def needs_vert(lib):
            return any("vert" not in e
                       for l in lib for e in (l.get("element_schema") or [])
                       if e.get("kind") == "text")
        if sig(old_lib) == sig(fresh_lib) and not needs_vert(old_lib) and not needs_vert(fresh_lib):
            continue
        diff = {k: (sig(old_lib).get(k), sig(fresh_lib).get(k))
                for k in sig(fresh_lib)
                if sig(old_lib).get(k) != sig(fresh_lib).get(k)}
        print(f"[差异] {row['name']}: {diff or '补 vert 字段'}")
        if DRY:
            continue
        conn.execute(
            "update ppt_templates set layout_library=?, colors=?, font=?, updated_at="
            "datetime('now') where id=?",
            (json.dumps(fresh_lib, ensure_ascii=False),
             json.dumps(fresh.get("colors") or json.loads(row["colors"] or "{}"),
                        ensure_ascii=False),
             fresh.get("font") or row["font"], row["id"]))
        updated += 1
    if not DRY:
        conn.commit()
    conn.close()
    print(f"完成：更新 {updated} 个模板" + ("（dry-run 未落库）" if DRY else ""))


if __name__ == "__main__":
    main()
