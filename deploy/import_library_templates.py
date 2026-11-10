"""把导出的图库学习模板导入服务器（JSONL + 底稿 + 版式预览图）。

服务器用法（justice-api 容器内，导出包已 scp 到容器可读路径）：
    docker cp <导出目录> justice-api:/tmp/library-export
    docker exec justice-api python /app/deploy/import_library_templates.py \
        --dir /tmp/library-export            # 默认 dry-run，只打印计划
    docker exec justice-api python /app/deploy/import_library_templates.py \
        --dir /tmp/library-export --apply    # 真正写入

幂等：按模板名判重（已存在即跳过）；id 与库内现有行冲突也跳过。
导入统一置 is_official=True、created_by=NULL（官方模板全员可见）。
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, "/app")  # 容器内
_here = Path(__file__).resolve().parent.parent / "server"
if _here.exists():
    sys.path.insert(0, str(_here))  # 开发机直接跑（验证用）

from sqlalchemy import select  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.infrastructure.database import SessionLocal  # noqa: E402
from app.infrastructure.database.models.ppt import PPTTemplateModel  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True, help="导出目录（含 templates.jsonl）")
    ap.add_argument("--apply", action="store_true", help="真正写入（默认 dry-run）")
    args = ap.parse_args()
    export = Path(args.dir)
    jsonl = export / "templates.jsonl"
    if not jsonl.exists():
        sys.exit(f"找不到 {jsonl}，确认导出目录")

    rows = [json.loads(line) for line in
            jsonl.read_text(encoding="utf-8").splitlines() if line.strip()]
    db = SessionLocal()
    existing = {m.name: m.id for m in db.scalars(select(PPTTemplateModel)).all()}
    existing_ids = set(existing.values())
    ppt_dir = settings.ppt_dir

    added = skipped_dup = skipped_id = 0
    for row in rows:
        name = row["name"]
        if name in existing:
            print(f"[跳过] 已存在同名模板：{name}")
            skipped_dup += 1
            continue
        if row["id"] in existing_ids:
            print(f"[跳过] id 冲突：{name} ({row['id']})")
            skipped_id += 1
            continue
        base = export / "tpl_src" / f"{row['id']}.pptx"
        if not base.exists():
            print(f"[警告] 缺底稿，跳过：{name}")
            continue
        print(f"[{'写入' if args.apply else '计划'}] {name}"
              f"（{len(row.get('layout_library') or [])} 版式）")
        if not args.apply:
            added += 1
            continue
        m = PPTTemplateModel(
            id=row["id"], name=name, category=row.get("category") or "工作汇报",
            description=row.get("description"), is_official=True,
            created_by=None, colors=row.get("colors"), font=row.get("font") or
            "SimHei", layouts=row.get("layouts"),
            layout_library=row.get("layout_library"),
            source_file=base.name, license_note=row.get("license_note") or "",
            use_count=row.get("use_count") or 0,
        )
        db.add(m)
        # 空环境（新装服务、独立卷）里这两个目录可能还不存在；不先建目录会
        # 在 db.add 之后抛 FileNotFoundError，事务虽回滚但导入整体失败。
        (ppt_dir / "tpl_src").mkdir(parents=True, exist_ok=True)
        (ppt_dir / "tpl_prev").mkdir(parents=True, exist_ok=True)
        shutil.copy2(base, ppt_dir / "tpl_src" / f"{row['id']}.pptx")
        prev_src = export / "tpl_prev" / row["id"]
        if prev_src.exists():
            shutil.copytree(prev_src, ppt_dir / "tpl_prev" / row["id"],
                            dirs_exist_ok=True)
        added += 1

    if args.apply:
        db.commit()
    mode = "已写入" if args.apply else "dry-run 计划"
    print(f"完成（{mode}）：新增 {added}，同名跳过 {skipped_dup}，id 冲突 {skipped_id}")
    if not args.apply:
        print("确认无误后加 --apply 执行。")


if __name__ == "__main__":
    main()
