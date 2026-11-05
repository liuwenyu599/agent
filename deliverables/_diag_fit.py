#!/usr/bin/env python3
"""诊断：某模板对内容页为何全拒——逐版式打印判定细节。"""
import json
import logging
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))
from app.application.ppt import ppt_engine as pe  # noqa: E402
sys.path.insert(0, str(ROOT / "deploy"))
from render_with_template import SAMPLE_OUTLINE  # noqa: E402

logging.basicConfig(level=logging.DEBUG, format="    %(message)s")
name = sys.argv[1] if len(sys.argv) > 1 else "简约黑白大气商务"
slide = next(s for s in SAMPLE_OUTLINE["slides"] if s["type"] == "content")

conn = sqlite3.connect(ROOT / "server/data/judicial_app.db")
row = conn.execute("select layout_library from ppt_templates where name=?", (name,)).fetchone()
lib = json.loads(row[0])
print(f"模板 {name}｜版式 {len(lib)}｜测试页要点 {len(slide['points'])} 条，标题 {len(slide['title'])} 字")

for lay in lib:
    texts = [e for e in lay.get("element_schema") or []
             if e.get("kind") == "text" and e.get("role") != "fixed"]
    keys = sorted({k for e in texts for k in (e.get("placeholder_keys") or [])})
    score = pe._layout_fit_score(lay, slide)
    body = [e for e in texts if e["w"] >= .35 and e["h"] >= .09]
    print(f"{lay['id']:<4} {lay.get('detected_type'):<14} 槽{len(texts):<3} "
          f"大字槽{len(body):<2} keys={keys[:4]} -> {'OK %.2f' % score if score else 'REJECT'}")
