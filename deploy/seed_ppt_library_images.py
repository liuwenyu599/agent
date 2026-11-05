#!/usr/bin/env python3
"""公共图库离线图片包导入（幂等）。

按 manifest.json 把预置图片导入 `ppt_library_images`：
  · 图片文件落 DATA_DIR/ppt/library/<id>.<ext>，缩略图 <id>-thumb.jpg（480px）
  · 按 name 幂等：内容与元数据都没变 → 跳过；文件换了 → 覆盖并更新
  · source / license_note 必填（政务合规），缺一项该条记错误，不阻断整批

用法：
  python deploy/seed_ppt_library_images.py [--manifest PATH] [--base-dir DIR]
                                           [--ppt-dir DIR] [--dry-run]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))

DEFAULT_MANIFEST = (ROOT / "server" / "app" / "application" / "ppt"
                    / "templates" / "library" / "manifest.json")


def main() -> int:
    parser = argparse.ArgumentParser(description="导入公共图库离线图片包")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST),
                        help="manifest.json 路径（默认随仓库的图库清单）")
    parser.add_argument("--base-dir", default="",
                        help="图片包根目录（默认 manifest 所在目录）")
    parser.add_argument("--ppt-dir", default="",
                        help="图库文件落盘根目录（默认 settings.ppt_dir）")
    parser.add_argument("--dry-run", action="store_true",
                        help="只报告将新增/更新多少条，不写文件不入库")
    args = parser.parse_args()

    from app.application.ppt.library_seed import (
        ManifestError, import_library_images)
    from app.infrastructure.database.session import SessionLocal

    manifest = Path(args.manifest)
    if not manifest.is_file():
        print(f"manifest 不存在：{manifest}")
        return 2
    base_dir = Path(args.base_dir) if args.base_dir else None
    ppt_dir = Path(args.ppt_dir) if args.ppt_dir else None

    db = SessionLocal()
    try:
        result = import_library_images(
            db, manifest, base_dir=base_dir, ppt_dir=ppt_dir,
            dry_run=args.dry_run)
    except ManifestError as exc:
        print(f"manifest 不合法：{exc}")
        return 2
    finally:
        db.close()

    for line in result.details:
        print(line)
    for line in result.errors:
        print(f"[错误] {line}")
    prefix = "预演：" if args.dry_run else ""
    print(f"\n{prefix}完成：新建 {result.created}、更新 {result.updated}、"
          f"跳过 {result.skipped}、错误 {len(result.errors)}")
    if args.dry_run and result.total:
        print("（--dry-run 未写文件、未入库；去掉该参数再执行一次生效）")
    return 1 if result.errors and not result.total else 0


if __name__ == "__main__":
    raise SystemExit(main())
