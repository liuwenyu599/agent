#!/usr/bin/env python3
"""PPT 模板后处理：把下载来的模板改成系统可直接使用的形态。

核心流水线已抽到 server/app/application/ppt/template_prepare.py（上传模板时
服务端会自动执行同一套处理），本脚本只是它的命令行封装，额外提供：
  · 诊断报告（不给 --out 只看不改）
  · 手动微调参数（--image-pages / --drop-pages）

默认行为（只给 --out 时）就完成全部机械处理：
  · 打 token：{{title}}/{{subtitle}}/{{pointN}}/{{image}} 自动写入
  · 统一字体：默认「微软雅黑」（Windows/WPS 端自带，导出显示一致）
  · 去品牌：自动移除版式/母版层的 logo 图与品牌字（--keep-brand 可保留）
  · 自动去空页：处理完仍无任何 token/图片的页（如结束页艺术字）自动删

可选微调（大多数情况不需要）：
  --image-pages 3,5  多图页中强制锚定面积最大的那张（默认不锚定，留人工决策）
  --drop-pages 2,9   额外手动删页（1 起算，支持 2-4 区间），与自动去空页叠加
  --no-title-tokens / --no-point-tokens / --no-image-anchors  关闭对应自动写入
  --no-font          不统一字体（保留模板原字体）
  --no-scrub         不清空残留示例字（封面落款/页脚日期等，默认开启）
  --no-auto-drop     关闭自动去空页

典型流程（一键）：
  python deploy/prepare_ppt_template.py 原.pptx --out 处理.pptx
  python deploy/check_ppt_template.py 处理.pptx

注意：本脚本不会把 4:3 改成 16:9。比例不符必须回 PowerPoint 重设页面并重排，
等比拉伸会把圆形变椭圆、字号比例失真，属于自欺欺人。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))

from app.application.ppt.template_prepare import (  # noqa: E402
    TARGET_RATIO, has_smartart, is_picture, layout_brand, prepare_template_bytes,
    text_size, walk,
)
from pptx import Presentation  # noqa: E402


def parse_pages(spec: str) -> set:
    pages = set()
    for chunk in spec.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "-" in chunk:
            lo, hi = chunk.split("-", 1)
            pages.update(range(int(lo), int(hi) + 1))
        else:
            pages.add(int(chunk))
    return pages


def report(prs) -> None:
    print(f"页数：{len(prs.slides)}")
    ratio = (prs.slide_width or 0) / (prs.slide_height or 1)
    ok = abs(ratio - TARGET_RATIO) <= 0.02
    print(f"页面比例：{ratio:.3f}（{'16:9 ✅' if ok else '不是 16:9 ❌，系统会直接拒收'}）")
    print()
    print("页  文本框  最大字号  图片  组合  形状  提示")
    for i, slide in enumerate(prs.slides, 1):
        texts, pics, groups, shapes, smart = [], 0, 0, 0, 0
        for sh, depth in walk(slide.shapes):
            shapes += 1
            if depth:
                groups += 1
            if is_picture(sh):
                pics += 1
            if getattr(sh, "has_text_frame", False) and sh.text_frame.text.strip():
                texts.append(sh)
            if has_smartart(sh):
                smart += 1
        max_font = max((text_size(s) for s in texts), default=0)
        tips = []
        if smart:
            tips.append(f"SmartArt×{smart} 不解析")
        if not texts:
            tips.append("无可替换文本，整页会被跳过")
        elif len(texts) == 1:
            tips.append("只有 1 个文本框，正文无处安放")
        sample = " ".join(t.text_frame.text.strip().replace("\n", " ")[:8] for t in texts[:2])
        print(f"{i:<3} {len(texts):^7} {max_font:^9.0f} {pics:^5} {groups:^5} {shapes:^5} "
              f"{'；'.join(tips) or sample}")

    items = layout_brand(prs)
    if items:
        print("\n品牌残留（版式/母版层，--out 时默认移除，--keep-brand 可保留）：")
        for where, kind, detail in items:
            print(f"  [{where}] {kind} {detail}")
    else:
        print("\n品牌残留：未检测到版式/母版层的 logo 图片或品牌文字")


def main() -> int:
    ap = argparse.ArgumentParser(description="PPT 模板后处理（自取模板改造成系统可用形态）")
    ap.add_argument("file", help="源 .pptx")
    ap.add_argument("--out", default=None, help="输出路径；不给则只诊断")
    ap.add_argument("--drop-pages", default=None,
                    help="额外手动删页，如 2,9 或 2-4（与自动去空页叠加）")
    ap.add_argument("--no-title-tokens", action="store_true", help="关闭 {{title}}/{{subtitle}} 写入（默认开启）")
    ap.add_argument("--no-point-tokens", action="store_true", help="关闭 {{pointN}} 写入（默认开启）")
    ap.add_argument("--no-image-anchors", action="store_true", help="关闭图片位 {{image}} 锚点（默认开启）")
    ap.add_argument("--image-pages", default=None, help="多图页中强制锚定最大图，如 3,5")
    ap.add_argument("--strip-pictures", action="store_true",
                    help="清除第 2 页起所有未锚定图片（真实旧稿改模板用：照片/截图是旧内容不是装饰）")
    ap.add_argument("--font", default="微软雅黑", help="统一字体名（默认 微软雅黑；--no-font 可跳过）")
    ap.add_argument("--no-font", action="store_true", help="不统一字体，保留模板原字体")
    ap.add_argument("--no-auto-drop", action="store_true",
                    help="关闭自动删除无 token/无图的空页（默认开启）")
    ap.add_argument("--no-scrub", action="store_true",
                    help="关闭清空残留示例字（封面落款/页脚日期等，默认开启）")
    ap.add_argument("--keep-brand", action="store_true",
                    help="保留版式/母版里的 logo 图片与品牌文字（默认会移除）")
    args = ap.parse_args()

    src = Path(args.file)
    prs = Presentation(str(src))
    report(prs)

    if not args.out:
        print("\n（只诊断，未改文件。加 --out 输出处理后的副本）")
        return 0

    try:
        data, notes = prepare_template_bytes(
            src.read_bytes(),
            font=None if args.no_font else args.font,
            keep_brand=args.keep_brand,
            title_tokens=not args.no_title_tokens,
            point_tokens=not args.no_point_tokens,
            image_anchors=not args.no_image_anchors,
            image_pages=parse_pages(args.image_pages) if args.image_pages else frozenset(),
            drop_pages=parse_pages(args.drop_pages) if args.drop_pages else frozenset(),
            auto_drop=not args.no_auto_drop,
            scrub=not args.no_scrub,
            strip_pictures=args.strip_pictures)
    except Exception as e:
        print(f"\n❌ {e}")
        return 2

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    print("\n处理记录：")
    for note in notes:
        print(f"  - {note}")
    print(f"\n已保存：{out}")
    print("下一步：python deploy/check_ppt_template.py " + str(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
