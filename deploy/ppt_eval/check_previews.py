"""Check both preview files and stored layout preview pointers before a model probe.

Works against the two databases this project actually uses:

* local / dev  -- SQLite file (``--db``)
* production   -- PostgreSQL in the ``justice-db`` container
                  (``--database-url`` or ``PPT_EVAL_DATABASE_URL``; same value
                  the API container has, e.g.
                  ``postgresql+psycopg2://justice:pwd@db:5432/justice``)

The library function only honours an explicit ``database_url`` argument.
It deliberately does not auto-read the application's ``DATABASE_URL``: the
test suite sets that variable for DB isolation, and picking it up here would
silently redirect a local SQLite check to an unrelated database.

Run inside the API container so the ``db`` hostname resolves and so
``--ppt-dir`` points at the mounted volume (``/data/justice/ppt``).
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
from pathlib import Path

_VISION_TYPES = {"content", "case", "summary"}
_NON_CONTENT = {"cover", "toc", "section", "closing"}


def _query_row(db_path: Path, template_id: str, database_url: str | None):
    """Return (name, layout_library) for one template from either backend."""
    if database_url:
        from sqlalchemy import create_engine, text

        engine = create_engine(database_url)
        try:
            with engine.connect() as connection:
                return connection.execute(
                    text("SELECT name, layout_library FROM ppt_templates "
                         "WHERE id=:template_id"),
                    {"template_id": template_id}).fetchone()
        finally:
            engine.dispose()

    connection = sqlite3.connect(
        f"file:{db_path.resolve().as_posix()}?mode=ro", uri=True)
    try:
        return connection.execute(
            "SELECT name, layout_library FROM ppt_templates WHERE id=?",
            (template_id,)).fetchone()
    finally:
        connection.close()


def _as_layouts(raw) -> list:
    """SQLite stores JSON as TEXT; psycopg2 returns json/jsonb already parsed."""
    if not raw:
        return []
    if isinstance(raw, (str, bytes, bytearray)):
        raw = json.loads(raw)
    return raw if isinstance(raw, list) else []


def check(db_path: Path, ppt_dir: Path, template_id: str,
          database_url: str | None = None) -> dict:
    url = database_url or None
    row = _query_row(Path(db_path), template_id, url)
    if row is None:
        raise ValueError(f"模板不存在：{template_id}")
    layouts = _as_layouts(row[1])
    content = [item for item in layouts
               if isinstance(item, dict)
               and item.get("detected_type") not in _NON_CONTENT]
    records = []
    for item in content:
        layout_id = str(item.get("id") or "")
        preview = ppt_dir / "tpl_prev" / template_id / f"{layout_id}.png"
        records.append({
            "layout_id": layout_id,
            "detected_type": item.get("detected_type"),
            "db_preview": bool(item.get("preview") or item.get("source_preview")),
            "png_exists": preview.is_file(),
            "vision_eligible": item.get("detected_type") in _VISION_TYPES,
        })
    ready = bool(records) and all(
        item["db_preview"] and item["png_exists"] for item in records)
    return {
        "template_id": template_id,
        "template_name": row[0],
        "backend": "sqlalchemy" if url else "sqlite3",
        "content_layouts": len(content),
        "layouts": records,
        "ready": ready,
        # ready 只说明「文件齐、字段齐」。模型构图侧 read_template_reference()
        # 只认 content/case/summary；全是 cards 的模板即使 ready=true，
        # 缩略图仍会静默退回文字摘要。这两个结论不能混为一谈。
        "vision_reference_ready": any(
            item["db_preview"] and item["png_exists"] and item["vision_eligible"]
            for item in records),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("template_id")
    parser.add_argument("--db", type=Path,
                        default=Path("server/data/judicial_app.db"),
                        help="本地 SQLite 库路径（未给 --database-url 时使用）")
    parser.add_argument("--database-url",
                        default=os.getenv("PPT_EVAL_DATABASE_URL"),
                        help="PostgreSQL 连接串；也可设 PPT_EVAL_DATABASE_URL。"
                             "不读应用的 DATABASE_URL（测试会设它做隔离）")
    parser.add_argument("--ppt-dir", type=Path, default=Path("server/data/ppt"),
                        help="生产用 /data/justice/ppt")
    args = parser.parse_args()
    print(json.dumps(check(args.db, args.ppt_dir, args.template_id,
                           args.database_url),
                     ensure_ascii=False, indent=2))
