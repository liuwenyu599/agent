# -*- coding: utf-8 -*-
"""PPT 模板体检工具（采购验收用）。

把买回来的 .pptx 丢进来，判断它能不能被系统「学习版式 + 克隆填充」：
    python deploy/check_ppt_template.py 模板1.pptx 模板2.pptx
    python deploy/check_ppt_template.py 模板.pptx --preview ./preview

结论三档：
    PASS  可直接入库
    WARN  能用，但有需要人工确认的点
    FAIL  不要用（学习器会拒收或出稿会崩）

检查项对应真实代码：
    analyze_template()          ppt_engine.py:2295  （版式提取 + 去重 + 固定元素识别）
    validate_learned_template() ppt_engine.py:2371  （至少一页可替换标题+正文）
    _iter_shapes / _element_of  ppt_engine.py:2172  （递归展开组合，组内文字可替换）
    _mark_fixed                 ppt_engine.py:2253  （≥60% 页面重复出现判为装饰）
    build_pptx_learned          ppt_engine.py:2758  （克隆填充）
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import subprocess
import sys
import tempfile
import zipfile
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "server"))

try:  # Windows 控制台默认 cp936，中文报告需要 utf-8
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from pptx import Presentation                      # noqa: E402
from pptx.enum.shapes import MSO_SHAPE_TYPE        # noqa: E402

from app.application.ppt import ppt_engine         # noqa: E402

TARGET_W, TARGET_H = 12192000, 6858000             # 16:9 13.333in × 7.5in
SIZE_TOLERANCE = 0.02

SAFE_FONTS = {
    "微软雅黑", "Microsoft YaHei", "等线", "DengXian", "思源黑体",
    "Source Han Sans SC", "Source Han Sans CN", "Noto Sans CJK SC",
    "黑体", "SimHei", "宋体", "SimSun", "方正兰亭黑", "HarmonyOS Sans SC",
}

VERDICT_LABEL = {"pass": "PASS（可直接入库）",
                 "warn": "WARN（能用，需人工确认）",
                 "fail": "FAIL（不要用）"}


def walk_shapes(shapes, depth=0):
    """递归展开组合形状，返回 (shape, depth)。"""
    for shape in shapes:
        yield shape, depth
        try:
            is_group = shape.shape_type == MSO_SHAPE_TYPE.GROUP
        except Exception:
            is_group = False
        if is_group:
            try:
                yield from walk_shapes(shape.shapes, depth + 1)
            except Exception:
                continue


def has_text(shape) -> str:
    try:
        if shape.has_text_frame:
            return (shape.text_frame.text or "").strip()
    except Exception:
        pass
    return ""


def picture_hash(shape) -> str:
    try:
        return hashlib.md5(shape.image.blob).hexdigest()[:12]
    except Exception:
        return ""


def scan_raw(data: bytes) -> dict:
    """按页扫描原始结构，找学习器会误判/出稿会塌的东西。"""
    prs = Presentation(__import__("io").BytesIO(data))
    pages = []
    for slide in prs.slides:
        groups = 0
        group_texts = 0
        group_shapes = 0
        max_depth = 0
        shapes_total = 0
        pics = []
        smartart = 0
        for shape, depth in walk_shapes(slide.shapes):
            shapes_total += 1
            max_depth = max(max_depth, depth)
            if depth > 0:
                groups += 1
                group_shapes += 1
                if has_text(shape):
                    group_texts += 1
            try:
                if shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
                    pics.append(picture_hash(shape))
            except Exception:
                pass
            try:
                xml = shape._element.xml
                if "/diagram" in xml or "dgm" in xml:
                    smartart += 1
            except Exception:
                pass
        pages.append({"shapes": shapes_total, "groups": groups,
                      "group_texts": group_texts, "group_shapes": group_shapes,
                      "max_depth": max_depth, "pics": pics,
                      "smartart": smartart,
                      "slide": slide})
    return {"pages": pages,
            "size": (int(prs.slide_width or 0), int(prs.slide_height or 0))}


def check_one(path: Path, preview_dir: Path | None) -> tuple[str, list[str], list[str]]:
    reasons: list[str] = []
    notes: list[str] = []

    if not path.exists():
        return "fail", [f"文件不存在：{path}"], []
    data = path.read_bytes()
    if not zipfile.is_zipfile(__import__("io").BytesIO(data)):
        return "fail", ["不是有效的 .pptx（zip 结构损坏，可能是改了扩展名的 ppt/图片）"], []

    raw = scan_raw(data)
    total = len(raw["pages"])
    if total == 0:
        return "fail", ["文件里没有任何页面"], []

    # ---------- 1. 页面尺寸 ----------
    w, h = raw["size"]
    ratio = w / h if h else 0
    if abs(w - TARGET_W) / TARGET_W > SIZE_TOLERANCE or abs(h - TARGET_H) / TARGET_H > SIZE_TOLERANCE:
        if abs(ratio - 16 / 9) < 0.02:
            notes.append(f"页面尺寸 {w}×{h} 接近 16:9，但不是标准 13.333×7.5 英寸；"
                         "克隆填充仍可用，但坐标会有轻微缩放")
        else:
            reasons.append(f"页面不是 16:9（当前 {w}×{h}，比例 {ratio:.2f}）；"
                           "系统按 13.333×7.5 英寸排版，4:3 模板会导致版式错位")

    # ---------- 2. 学习版式 ----------
    try:
        learned = ppt_engine.analyze_template(data)
    except Exception as exc:  # noqa: BLE001
        return "fail", reasons + [f"版式解析直接失败：{type(exc).__name__}: {exc}"], notes

    layouts = learned.get("layouts") or []
    content_layouts = []
    for lay in layouts:
        texts = [e for e in (lay.get("element_schema") or [])
                 if e.get("kind") == "text" and e.get("role") != "fixed"]
        if lay.get("detected_type") not in {"cover", "toc", "closing"} and len(texts) >= 2:
            content_layouts.append(lay)

    dropped = total - len(layouts)
    if dropped > 0:
        pct = dropped / total
        msg = f"{total} 页里识别出 {len(layouts)} 个版式，{dropped} 页因结构重复被合并"
        (notes if pct <= 0.4 else reasons).append(
            msg + ("（正常：封面/过渡页常见）" if pct <= 0.4
                   else "（过多：模板可能在用同一套骨架复制页，设计价值有限）"))

    try:
        ppt_engine.validate_learned_template(learned)
    except Exception as exc:  # noqa: BLE001
        reasons.append(f"学习器校验不通过：{exc}")

    if len(content_layouts) < 3:
        reasons.append(f"可用的正文版式只有 {len(content_layouts)} 个（建议 ≥4，"
                       "否则不同内容会挤进同一套版式，出稿仍是模板脸）")

    # Having many text-bearing pages is not enough: a decorative one-line
    # slot can pass the structural check yet overflow on an ordinary slide.
    typical = {"type": "content", "title": "年度重点工作安排",
               "points": ["完善业务办理流程，明确各环节责任与完成时限，并建立跟踪反馈机制。",
                          "加强人员培训和日常督导，及时解决执行中的具体问题，确保措施落实。",
                          "定期汇总各科室工作进展，形成可核查的阶段成果和下一步行动清单。"]}
    if not any(ppt_engine._learned_layout_fits(lay, typical) for lay in layouts):
        reasons.append("没有能容纳常规三要点正文的版式；生成时会大量改用通用可读页，"
                       "无法保留所购模板的页面设计")
    for page_type, sample in (
        ("toc", {"type": "toc", "title": "目录", "points": ["工作背景", "重点任务", "实施安排"]}),
        ("section", {"type": "section", "title": "一、重点任务"}),
    ):
        if not any(ppt_engine._learned_layout_fits(lay, sample) for lay in layouts):
            notes.append(f"缺少可用的{page_type}页版式；此类页面会使用通用可读页")

    # ---------- 3. 组合（已支持递归解析，仍按风险提示） ----------
    # 学习器用 _iter_shapes 递归展开组合并按 chOff/chExt 换算坐标，组内文字能被
    # 识别和替换；剩余风险是组内文本框无法单独调整大小/位置，正文变长时会挤压。
    gtext_pages = [i + 1 for i, p in enumerate(raw["pages"]) if p["group_texts"] > 0]
    if gtext_pages:
        count = sum(p["group_texts"] for p in raw["pages"])
        notes.append(f"第 {gtext_pages[:6]}{'…' if len(gtext_pages) > 6 else ''} 页共有 {count} 处文字"
                     "在组合里；系统会递归解析并正常替换，但组内文本框不能单独调字号/位置，"
                     "正文变长时该页可能挤压，出稿后需预览确认")
    deep = [i + 1 for i, p in enumerate(raw["pages"]) if p["max_depth"] >= 3]
    if deep:
        notes.append(f"第 {deep[:5]} 页组合嵌套 ≥3 层；坐标换算仍能处理，但错位风险随层数上升")
    whole = [i + 1 for i, p in enumerate(raw["pages"])
             if p["group_shapes"] and p["group_shapes"] == p["shapes"]]
    if whole:
        notes.append(f"第 {whole[:5]} 页整页元素都在一个组合里；文字能替换，但版式无法局部调整，"
                     "出稿会沿用模板的固定间距")

    # ---------- 4. 每页重复的示例图（会被判成装饰永久保留） ----------
    pic_counter = Counter()
    for p in raw["pages"]:
        for hsh in set(p["pics"]):
            pic_counter[hsh] += 1
    repeated = [(hsh, c) for hsh, c in pic_counter.items() if c >= max(3, int(total * 0.6))]
    if repeated:
        notes.append(f"有 {len(repeated)} 张示例图出现在 ≥60% 页面（最多 {repeated[0][1]}/{total} 页）；"
                     "它们会被当作固定装饰保留到成品，若那是示意用图，出稿会每页重复")

    # ---------- 5. 版式里的纯图片页 ----------
    pic_only = [lay.get("id") for lay in layouts
                if lay.get("detected_type") not in {"cover", "closing"}
                and not [e for e in (lay.get("element_schema") or [])
                         if e.get("kind") == "text" and e.get("role") != "fixed"]]
    if pic_only:
        notes.append(f"{len(pic_only)} 个版式没有可替换文本框（{', '.join(pic_only[:5])}）；"
                     "这些页会被跳过，出稿时该类内容改用其他版式")

    # ---------- 6. 字体 ----------
    font = learned.get("font") or ""
    if font and not any(f.lower() in font.lower() or font.lower() in f.lower() for f in SAFE_FONTS):
        notes.append(f"字体「{font}」不在常见中文字体清单内；生产容器只有思源黑体，"
                     "预览会回退字体（Windows 打开 pptx 仍按客户机字体显示）")

    # ---------- 7. 页数与形态 ----------
    if total < 6:
        reasons.append(f"只有 {total} 页；一套可复用模板至少需要 8~12 页覆盖主要页型")
    heavy = [i + 1 for i, p in enumerate(raw["pages"]) if p["shapes"] > 80]
    if heavy:
        notes.append(f"第 {heavy[:5]} 页形状数超过 80，克隆填充会变慢且容易错位")
    smart = [i + 1 for i, p in enumerate(raw["pages"]) if p["smartart"]]
    if smart:
        notes.append(f"第 {smart[:5]} 页含 SmartArt/图示对象；python-pptx 无法写入其内部文字，"
                     "该页大概率退化为基础排版")

    # ---------- 8. 可选：生成预览 ----------
    if preview_dir is not None:
        try:
            preview_dir.mkdir(parents=True, exist_ok=True)
            _render_preview(path, preview_dir)
            notes.append(f"预览已生成：{preview_dir}")
        except Exception as exc:  # noqa: BLE001
            notes.append(f"预览生成失败（不影响判断）：{type(exc).__name__}")

    # ---------- 汇总 ----------
    if reasons:
        verdict = "fail"
    elif notes:
        verdict = "warn"
    else:
        verdict = "pass"

    head = (f"页数 {total} | 尺寸 {w}×{h} | 字体 {font or '未知'}")
    head += (f" | 版式 {len(layouts)} 个（可用正文 {len(content_layouts)} 个）")
    notes.insert(0, head)
    return verdict, reasons, notes


def _render_preview(path: Path, out_dir: Path) -> None:
    soffice = None
    for candidate in ("soffice",
                      r"D:\apps\LibreOffice\program\soffice.exe",
                      r"C:\Program Files\LibreOffice\program\soffice.exe"):
        if candidate == "soffice":
            from shutil import which
            soffice = which("soffice")
        elif Path(candidate).exists():
            soffice = candidate
        if soffice:
            break
    if not soffice:
        raise RuntimeError("本机未找到 LibreOffice，跳过预览")

    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "t.pptx"
        src.write_bytes(path.read_bytes())
        subprocess.run([soffice, "--headless", "--convert-to", "pdf",
                        "--outdir", td, str(src)], timeout=180, capture_output=True)
        pdf = Path(td) / "t.pdf"
        if not pdf.exists():
            raise RuntimeError("LibreOffice 转换 PDF 失败")
        out = out_dir / path.stem
        out.mkdir(parents=True, exist_ok=True)
        try:
            subprocess.run(["pdftoppm", "-png", "-r", "60", str(pdf),
                            str(out / "pg")], timeout=120, capture_output=True)
        except FileNotFoundError:
            raise RuntimeError("未找到 pdftoppm（poppler）")


def main() -> int:
    ap = argparse.ArgumentParser(description="PPT 模板采购体检")
    ap.add_argument("files", nargs="+", help="待检查的 .pptx 文件")
    ap.add_argument("--preview", metavar="DIR", default=None,
                    help="同时输出逐页预览 PNG 到该目录（需本机 LibreOffice）")
    args = ap.parse_args()

    worst = 0
    for raw_path in args.files:
        path = Path(raw_path)
        print("=" * 72)
        print(f"检查：{path.name}")
        verdict, reasons, notes = check_one(
            path, Path(args.preview) if args.preview else None)
        for line in notes:
            print(f"  · {line}")
        for line in reasons:
            print(f"  ✗ {line}")
        print(f"结论：{VERDICT_LABEL[verdict]}")
        worst = max(worst, {"pass": 0, "warn": 1, "fail": 2}[verdict])
    print("=" * 72)
    return 1 if worst == 2 else 0


if __name__ == "__main__":
    raise SystemExit(main())
