"""Check both preview files and stored layout preview pointers before a model probe."""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path


def check(db_path: Path, ppt_dir: Path, template_id: str) -> dict:
    connection = sqlite3.connect(f"file:{db_path.resolve().as_posix()}?mode=ro", uri=True)
    try:
        row = connection.execute(
            "SELECT name, layout_library FROM ppt_templates WHERE id=?",
            (template_id,)).fetchone()
    finally:
        connection.close()
    if row is None:
        raise ValueError(f"模板不存在：{template_id}")
    layouts = json.loads(row[1] or "[]")
    content = [item for item in layouts if item.get("detected_type") not in
               {"cover", "toc", "section", "closing"}]
    records = []
    for item in content:
        layout_id = str(item.get("id") or "")
        preview = ppt_dir / "tpl_prev" / template_id / f"{layout_id}.png"
        records.append({"layout_id": layout_id,
                        "db_preview": bool(item.get("preview") or item.get("source_preview")),
                        "png_exists": preview.is_file()})
    return {"template_id": template_id, "template_name": row[0],
            "content_layouts": len(content), "layouts": records,
            "ready": bool(records) and all(
                item["db_preview"] and item["png_exists"] for item in records)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("template_id")
    parser.add_argument("--db", type=Path, default=Path("server/data/judicial_app.db"))
    parser.add_argument("--ppt-dir", type=Path, default=Path("server/data/ppt"))
    args = parser.parse_args()
    print(json.dumps(check(args.db, args.ppt_dir, args.template_id),
                     ensure_ascii=False, indent=2))
