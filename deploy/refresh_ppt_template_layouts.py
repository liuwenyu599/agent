#!/usr/bin/env python3
"""Rebuild stored PPT layout metadata after the analyzer gains new fields.

Dry run by default. Run with --apply after backing up the database. Source
PPTX files are read from DATA_DIR/ppt/tpl_src/<template id>.pptx. The user's
layout choices, colors and fonts are left untouched; only layout_library is
replaced when the source still produces the same layout IDs.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))

from sqlalchemy import select  # noqa: E402

from app.application.ppt.ppt_engine import analyze_template  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.infrastructure.database.models.ppt import PPTTemplateModel  # noqa: E402
from app.infrastructure.database.session import SessionLocal  # noqa: E402


def missing_rotation(layouts: list) -> bool:
    return any("rot" not in element for layout in layouts
               for element in layout.get("element_schema") or []
               if element.get("kind") == "text")


def main() -> int:
    parser = argparse.ArgumentParser(description="补齐已入库 PPT 版式的旋转元数据")
    parser.add_argument("--apply", action="store_true", help="确认后写入数据库")
    parser.add_argument("--template-id", default="", help="只处理指定模板")
    args = parser.parse_args()

    root = settings.ppt_dir / "tpl_src"
    changed = missing = incompatible = 0
    with SessionLocal() as db:
        query = select(PPTTemplateModel).order_by(PPTTemplateModel.name)
        if args.template_id:
            query = query.where(PPTTemplateModel.id == args.template_id)
        for row in db.scalars(query):
            old = row.layout_library or []
            if not old or not missing_rotation(old):
                continue
            source = root / f"{row.id}.pptx"
            if not source.is_file():
                print(f"[缺源文件] {row.name}: {source}")
                missing += 1
                continue
            try:
                fresh = analyze_template(source.read_bytes()).get("layouts") or []
            except Exception as exc:
                print(f"[解析失败] {row.name}: {type(exc).__name__}: {exc}")
                incompatible += 1
                continue
            old_ids = {item.get("id") for item in old}
            fresh_ids = {item.get("id") for item in fresh}
            if old_ids != fresh_ids or missing_rotation(fresh):
                print(f"[版式不一致] {row.name}: 旧 {len(old)} 页，新 {len(fresh)} 页，未修改")
                incompatible += 1
                continue
            print(f"[待更新] {row.name}: {len(fresh)} 页")
            changed += 1
            if args.apply:
                row.layout_library = fresh
        if args.apply:
            if missing or incompatible:
                db.rollback()
                print("存在未能重刷的模板，本次数据库修改已回滚")
            else:
                db.commit()

    applied = args.apply and not (missing or incompatible)
    print(f"完成：{'更新' if applied else '待更新'} {changed} 套，"
          f"缺源文件 {missing} 套，版式不一致 {incompatible} 套")
    return 1 if missing or incompatible else 0


if __name__ == "__main__":
    raise SystemExit(main())
