#!/usr/bin/env python3
"""把预处理好的本地模板批量注册进系统（PPT 模板库种子脚本）。

对 ppttem/_processed/*_处理后.pptx（外加 deliverables 的蓝色渐变模板）逐份：
  · analyze_template 提取 colors/font/layout_library
  · 落库 ppt_templates（is_official=True，按名字去重，已存在则更新）
  · 源文件存 DATA_DIR/ppt/tpl_src/<id>.pptx（渲染底版）
  · soffice 渲染逐页预览，按版式源页截取 tpl_prev/<id>/<Lx>.png

用法：
  cd server && D:/apps/anaconda3/python.exe ../deploy/seed_ppt_library.py [--dry-run]
"""
from __future__ import annotations

import argparse
import glob
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))

from app.application.ppt import ppt_engine, template_prepare  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.infrastructure.database.models.ppt import PPTTemplateModel  # noqa: E402
from app.infrastructure.database.session import SessionLocal  # noqa: E402

# 模板名 → 分类
CATEGORY = {
    "党务党建工作汇报": "党建党政", "精美党建党政通用": "党建党政",
    "党委党支部工作汇报": "党建党政", "党课党建工作汇报": "党建党政",
    "我是党员我奉献党课": "党建党政",
    "中国首部民法典解读": "法律法规", "公职人员政务处分法": "法律法规",
    "食品安全法实施条例": "法律法规",
    "简洁年中工作总结计划": "工作总结", "大气部门年终工作总结": "工作总结",
    "大气公司企业简介": "企业介绍", "简约黑白大气商务": "企业介绍",
    "简洁创意点线设计": "通用", "清新绿色简约通用": "通用",
    "简约淡雅文艺清新绿植": "通用", "时尚精美欧美杂志风": "通用",
    "蓝色渐变商务通用": "通用",
}

SOURCES = sorted(glob.glob(str(ROOT / "ppttem" / "_processed" / "*_处理后.pptx"))) + [
    str(ROOT / "deliverables" / "tpl_gradient_blue_24p.pptx")]


SPECIAL_NAMES = {"tpl_gradient_blue_24p": "蓝色渐变商务通用"}


def display_name(stem: str) -> str:
    stem = re.sub(r"_处理后$", "", stem)
    if stem in SPECIAL_NAMES:
        return SPECIAL_NAMES[stem]
    return stem[: -len("PPT模板")] if stem.endswith("PPT模板") else stem


def gen_previews(ppt_dir: Path, template_id: str, data: bytes, layouts: list) -> None:
    """与 service._gen_tpl_previews 同逻辑：soffice→pdf→png→按源页截取。"""
    d = ppt_dir / "tpl_prev" / template_id
    d.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        src = os.path.join(td, "tpl.pptx")
        with open(src, "wb") as f:
            f.write(data)
        profile = (Path(td) / "lo-profile").as_uri()
        subprocess.run(["soffice", f"-env:UserInstallation={profile}",
                        "--headless", "--convert-to", "pdf", "--outdir", td, src],
                       timeout=180, capture_output=True)
        pdf = os.path.join(td, "tpl.pdf")
        if not os.path.exists(pdf):
            print("    预览生成失败（soffice 无输出），跳过")
            return
        subprocess.run(["pdftoppm", "-png", "-r", "60", pdf, os.path.join(td, "pg")],
                       timeout=120, capture_output=True)
        pages = sorted(glob.glob(os.path.join(td, "pg-*.png")))
        for lay in layouts:
            i = lay.get("source_slide_index", 0)
            if i < len(pages):
                shutil.copy(pages[i], str(d / f"{lay['id']}.png"))
                lay["preview"] = f"{lay['id']}.png"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只解析不落库")
    args = ap.parse_args()

    tpl_dir = settings.ppt_dir
    src_dir = tpl_dir / "tpl_src"
    db = SessionLocal()
    created = updated = skipped = 0
    try:
        for path in SOURCES:
            p = Path(path)
            display = display_name(p.stem)
            category = CATEGORY.get(display, "通用")
            try:
                data = p.read_bytes()
                learned = ppt_engine.analyze_template(data)
                ppt_engine.validate_learned_template(learned)
            except Exception as e:
                print(f"[跳过] {display}: 解析失败 {e}")
                skipped += 1
                continue
            library = learned.get("layouts") or []
            row = db.query(PPTTemplateModel).filter(
                PPTTemplateModel.name == display,
                PPTTemplateModel.builtin_id.is_(None)).first()
            if args.dry_run:
                print(f"[试算] {display} [{category}] 版式 {len(library)} "
                      f"主色 {learned['colors'].get('primary')}")
                continue
            if row is None:
                row = PPTTemplateModel(
                    name=display, category=category,
                    description=f"本地导入模板，自动识别 {len(library)} 种版式"
                                f"（来源：{p.name}）",
                    is_official=True, created_by=None,
                    license_note="自取免费模板，允许系统内重复使用和改编",
                    colors=learned["colors"], font=learned["font"],
                    layouts=dict(ppt_engine.DEFAULT_LAYOUTS),
                    source_file=p.name)
                db.add(row)
                db.flush()
                created += 1
                action = "新建"
            else:
                row.colors, row.font = learned["colors"], learned["font"]
                row.category = category
                updated += 1
                action = "更新"
            src_dir.mkdir(parents=True, exist_ok=True)
            (src_dir / f"{row.id}.pptx").write_bytes(data)
            gen_previews(tpl_dir, row.id, data, library)
            row.layout_library = library
            db.commit()
            print(f"[{action}] {display} [{category}] 版式 {len(library)} "
                  f"主色 {learned['colors'].get('primary')} id={row.id}")
        print(f"\n完成：新建 {created}、更新 {updated}、跳过 {skipped}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
