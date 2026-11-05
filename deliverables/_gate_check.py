#!/usr/bin/env python3
"""保存前视觉闸门的实弹测试：对每套模板渲一份 12 页样稿，跑
PPTService.review_pptx_visuals，统计 error 级问题（会阻止保存或强制兜底）。

用法：python deliverables/_gate_check.py [模板名关键字]
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT / "deploy"))

from app.application.ppt import ppt_engine as pe  # noqa: E402
from app.application.ppt.service import PPTService  # noqa: E402
from render_with_template import SAMPLE_OUTLINE  # noqa: E402

DB = ROOT / "server/data/judicial_app.db"
PROCESSED = ROOT / "ppttem/_processed"


def rows():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    out = conn.execute(
        "select name,category,colors,font,layouts,layout_library,source_file "
        "from ppt_templates order by category,name").fetchall()
    conn.close()
    return [dict(r) for r in out]


def main() -> int:
    keyword = sys.argv[1] if len(sys.argv) > 1 else ""
    summary = []
    for raw in rows():
        name = raw["name"]
        if keyword and keyword not in name:
            continue
        base = PROCESSED / (raw["source_file"] or "")
        if not raw["source_file"] or not base.is_file():
            summary.append((name, "缺源", 0, []))
            continue
        d = dict(raw)
        for key in ("colors", "layouts", "layout_library"):
            if isinstance(d.get(key), str):
                d[key] = json.loads(d[key]) if d[key] else (
                    [] if key == "layout_library" else {})
        tpl = pe.template_to_dict(d)
        warnings: list = []
        data = pe.render_pptx(SAMPLE_OUTLINE, tpl, base_pptx=base.read_bytes(),
                              warnings=warnings)
        review = PPTService.review_pptx_visuals(data)
        errors = [i for i in review["issues"] if i["severity"] == "error"]
        warns = [i for i in review["issues"] if i["severity"] == "warning"]
        summary.append((name, "BLOCK" if errors else "PASS", len(warns), errors))
        if errors:
            print(f"\n### {name}")
            for e in errors:
                print(f"  P{e['page']} {e['code']}: {e['message']}")
            if warns:
                print(f"  (另有 {len(warns)} 条 warning)")

    print("\n===== 汇总 =====")
    blocked = [s for s in summary if s[1] == "BLOCK"]
    print(f"模板 {len(summary)}｜会阻止/强制兜底 {len(blocked)}｜"
          f"缺源 {sum(1 for s in summary if s[1] == '缺源')}")
    for name, status, warns, _ in summary:
        print(f"  {status:<5} warn={warns:<2} {name}")
    return 1 if blocked else 0


if __name__ == "__main__":
    sys.exit(main())
