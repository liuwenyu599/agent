"""导出图库学习模板（DB 行 + 底稿 + 版式预览图），供服务器导入。

用法（开发机 server/ 下）：
    D:/apps/anaconda3/python.exe ../deliverables/_export_library_templates.py \
        --out ../.tmp/library-export

产出结构：
    <out>/templates.jsonl        每行一个模板（id/name/category/colors/font/
                                 layouts/layout_library/license_note/use_count）
    <out>/tpl_src/<id>.pptx      渲染底稿
    <out>/tpl_prev/<id>/*.png    版式预览图
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))

from sqlalchemy import select  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.infrastructure.database import SessionLocal  # noqa: E402
from app.infrastructure.database.models.ppt import PPTTemplateModel  # noqa: E402
from app.application.ppt import ppt_engine  # noqa: E402

# 服务器已有、无需重复导出的模板名（导入端也会按 name 判重，这里只是省体积）
SERVER_ALREADY_HAS = ("公正司法", "消防安全")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="../.tmp/library-export")
    args = ap.parse_args()
    out = Path(args.out)
    (out / "tpl_src").mkdir(parents=True, exist_ok=True)
    (out / "tpl_prev").mkdir(parents=True, exist_ok=True)

    db = SessionLocal()
    rows = db.scalars(select(PPTTemplateModel)).all()
    ppt_dir = settings.ppt_dir

    exported = skipped = 0
    for m in rows:
        lib = m.layout_library or []
        if len(lib) < 8:
            continue  # 内置影子模板/学习不完整的不导
        if any(k in m.name for k in SERVER_ALREADY_HAS):
            skipped += 1
            continue
        base = ppt_dir / "tpl_src" / f"{m.id}.pptx"
        if not base.exists():
            print(f"[警告] 缺底稿，跳过：{m.name}")
            skipped += 1
            continue
        row = {
            "id": m.id, "name": m.name, "category": m.category,
            "description": m.description, "colors": m.colors,
            "font": m.font, "layouts": m.layouts,
            "layout_library": lib, "license_note": m.license_note,
            "use_count": 0,
        }
        (out / "templates.jsonl").open("a", encoding="utf-8").write(
            json.dumps(row, ensure_ascii=False) + "\n")
        shutil.copy2(base, out / "tpl_src" / f"{m.id}.pptx")
        prev_src = ppt_dir / "tpl_prev" / m.id
        if prev_src.exists():
            shutil.copytree(prev_src, out / "tpl_prev" / m.id, dirs_exist_ok=True)
        exported += 1
        print(f"[导出] {m.name}（{len(lib)} 版式）")

    total_mb = sum(f.stat().st_size for f in (out / "tpl_src").iterdir()) / 1048576
    print(f"完成：导出 {exported} 套，跳过 {skipped} 套；底稿合计 {total_mb:.1f} MB → {out}")


if __name__ == "__main__":
    main()
