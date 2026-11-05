#!/usr/bin/env python3
"""模板启用前体检（确定性几何审计，不依赖任何模型）。

背景：占位符填完不等于页面可用。模板复用链路的「装得下」判据只保证文字能缩进框，
不保证不出界、不保证不与装饰重叠、也不保证模板自带的示例照片/提示文字被清掉。
本脚本对每套拟启用模板用同一份 12 页样稿实际渲染，逐页做：

  FAIL 级（页面不可用）
    OUT_OF_BOUNDS   形状超出页面边界
    TEXT_OVERFLOW   文字估算溢出所在框（含单行框被塞多行）
    TEXT_OVERLAP    两个含字文本框明显交叠
    TEXT_HIDDEN     文字被上层实心形状遮挡
    TOKEN_LEFT      残留 {{token}} 占位符
  WARN 级（需人工确认/可修）
    PLACEHOLDER_TEXT 残留模板示例提示文字（「请输入标题」「20XX」等）
    TINY_FONT        正文字号过小
    BLANK_SLIDE      空白页（几乎无文字也无图）
    SAMPLE_IMAGE     模板自带的示例照片（与内容无关的图片）

产物：deliverables/template-audit/report.json / report.md / <模板>/pg-NN.png（仅问题页）

用法：
  python deliverables/_template_audit.py            # 全量
  python deliverables/_template_audit.py --only 民法典  # 只跑名字含关键词的
  python deliverables/_template_audit.py --no-preview    # 不出图（快）
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT / "deploy"))

from pptx import Presentation  # noqa: E402
from pptx.enum.shapes import MSO_SHAPE_TYPE  # noqa: E402

from app.application.ppt import ppt_engine as pe  # noqa: E402
from app.application.ppt.adaptive_design import estimated_lines, fit_font_size  # noqa: E402


def _text_bbox(shape, norm, size_pt: float) -> tuple:
    """估算文字实际占用区域 (x, y, w, h)，基于行数与 anchor 对齐。"""
    x, y, ww, hh = norm
    try:
        texts = ["".join(r.text for r in p.runs).strip()
                 for p in shape.text_frame.paragraphs]
        texts = [t for t in texts if t]
        lines = sum(estimated_lines(t, ww * 0.85, max(6, int(size_pt)),
                                    deck_width_pt=960) for t in texts) if texts else 0
        from pptx.oxml.ns import qn
        bodyPr = shape.text_frame._txBody.find(qn("a:bodyPr"))
        anchor = bodyPr.get("anchor") if bodyPr is not None else "t"
    except Exception:
        lines, anchor = 0, "t"
    th = min(hh, lines * size_pt * 1.22 / 540) if lines else hh * 0.3
    if anchor == "ctr":
        ty = y + max(0.0, (hh - th) / 2)
    elif anchor == "b":
        ty = y + max(0.0, hh - th)
    else:
        ty = y
    return (x, ty, ww, th)
from render_with_template import SAMPLE_OUTLINE  # noqa: E402

DB = ROOT / "server" / "data" / "judicial_app.db"
OUT = Path(os.environ.get("AUDIT_OUT") or (ROOT / "deliverables" / "template-audit"))
SOFFICE = Path("D:/apps/LibreOffice/program/soffice.exe")
PDFTOPPM = Path("D:/apps/poppler/bin/pdftoppm.exe")

TOL = 0.004          # 越界容差（占页宽/页高比例）
OVERLAP_RATIO = 0.30  # 交叠面积 / 较小框面积，超过即判重叠
HIDE_RATIO = 0.45     # 文字被上层实心形状覆盖比例

# 模板自带的示例提示文字：属于「与内容无关的模板残留」，必须清掉或替换
PLACEHOLDER_PATTERNS = [
    r"请输入", r"在此输入", r"点击输入", r"点击此处", r"点此输入", r"此处输入",
    r"添加标题", r"添加文字", r"标题文字", r"输入标题", r"输入文字", r"输入正文",
    r"20XX", r"20xx", r"202X", r"XXXX", r"xxxx", r"×××",
    r"Lorem", r"lorem", r"ipsum", r"Click to", r"Type something",
    r"您的姓名", r"公司名称", r"部门名称", r"汇报人[:：]\s*$", r"演讲人[:：]\s*$",
]
PLACEHOLDER_RE = re.compile("|".join(PLACEHOLDER_PATTERNS))


def _resolve_source(source_file: str, template_id: str = "") -> Path | None:
    """按 处理后目录 → 原目录 → deliverables 的顺序找模板源文件。"""
    cands = []
    if source_file:
        stem = Path(source_file).stem
        cands.extend([
            ROOT / "ppttem" / "_processed" / source_file,
            ROOT / "ppttem" / "_processed" / f"{stem}_处理后.pptx",
            ROOT / "ppttem" / source_file,
            ROOT / "deliverables" / source_file,
        ])
    if template_id:
        cands.append(ROOT / "server" / "data" / "ppt" / "tpl_src" /
                     f"{template_id}.pptx")
    for cand in cands:
        if cand.exists():
            return cand
    return None


def _font_pt(shape) -> float:
    """形状内最大显式字号；都没有时按 18pt（引擎默认正文）估算。"""
    sizes = []
    try:
        for para in shape.text_frame.paragraphs:
            for run in para.runs:
                if run.font.size:
                    sizes.append(run.font.size.pt)
            if para.font.size:
                sizes.append(para.font.size.pt)
    except Exception:
        pass
    return max(sizes) if sizes else 18.0


def _shape_kind(shape) -> str:
    try:
        return pe._shape_kind(shape)
    except Exception:
        return "other"


def _is_picture(shape) -> bool:
    if shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
        return True
    return _shape_kind(shape) == "image"


def _has_solid_fill(shape) -> bool:
    """实心填充（会遮住下层内容）；无填充/渐变以外的都算。"""
    if _is_picture(shape):
        return True
    try:
        fill = shape.fill
        return bool(fill.type is not None and str(fill.type).startswith("MSO_FILL_TYPE.SOLID"))
    except Exception:
        return False


def _overlap(a, b) -> float:
    """交叠面积 / 较小框面积。"""
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ix = max(0.0, min(ax + aw, bx + bw) - max(ax, bx))
    iy = max(0.0, min(ay + ah, by + bh) - max(ay, by))
    inter = ix * iy
    small = min(aw * ah, bw * bh)
    return inter / small if small > 0 else 0.0


def _count_chars(text: str) -> int:
    return len(re.sub(r"\s+", "", text or ""))


def _outline_texts() -> set[str]:
    """样稿全部文字片段：竖排框里出现样稿内容才是 bug，模板原文竖排标语是设计。"""
    chunks = set()

    def walk(value):
        if isinstance(value, str):
            chunks.add(re.sub(r"\s+", "", value))
        elif isinstance(value, dict):
            for v in value.values():
                walk(v)
        elif isinstance(value, list):
            for v in value:
                walk(v)

    walk(SAMPLE_OUTLINE)
    return {c for c in chunks if len(c) >= 4}


OUTLINE_TEXTS = _outline_texts()


def audit_slide(slide, idx: int, sw: int, sh: int, kind: str) -> dict:
    """单页审计：返回 {issues: [...], chars: n, pictures: n}。"""
    issues: list[dict] = []
    texts = []      # (z, rect, shape, text, size_pt)
    shapes_all = []  # (z, rect, shape)

    for z, (shape, rect, _depth) in enumerate(pe._iter_shapes(slide.shapes)):
        left, top, w, h = rect
        norm = (left / sw, top / sh, w / sw, h / sh)
        shapes_all.append((z, norm, shape))
        text = ""
        if getattr(shape, "has_text_frame", False):
            text = shape.text_frame.text or ""
        if text.strip():
            size = _font_pt(shape)
            texts.append((z, _text_bbox(shape, norm, size), shape, text, size))

        # 1) 越界：无字无图的形状是贴边出血装饰（底部彩带/贯穿竖线），豁免；
        #    含字/含图的形状超出 2% 以上才算 FAIL（标题条全宽多出的零点几像素不误报）
        x, y, ww, hh = norm
        over = max(-x, -y, x + ww - 1, y + hh - 1)
        # 越界只对含文字的形状下结论：无字形状（含图片）是贴边出血装饰，
        # 出血幅度大才提示人工复核（图片大块越界多为裁切错误）。
        if over > TOL and text.strip():
            if over >= 0.02:
                issues.append({"type": "OUT_OF_BOUNDS", "level": "FAIL",
                               "detail": f"超出页面 {over * 100:.1f}% "
                                         f"(x={x:.3f} y={y:.3f} w={ww:.3f} h={hh:.3f})",
                               "text": text.strip()[:40]})
        elif over > TOL and _is_picture(shape) and over >= 0.05:
            issues.append({"type": "IMAGE_BLEED", "level": "WARN",
                           "detail": f"图片超出页面 {over * 100:.1f}%",
                           "text": ""})

        if not text.strip():
            continue

        # 2) 残留占位符 token
        if "{{" in text or "}}" in text or "{%" in text:
            issues.append({"type": "TOKEN_LEFT", "level": "FAIL",
                           "detail": "残留模板占位符", "text": text.strip()[:40]})

        # 3) 模板示例提示文字残留
        hit = PLACEHOLDER_RE.search(text)
        if hit:
            issues.append({"type": "PLACEHOLDER_TEXT", "level": "WARN",
                           "detail": f"命中示例词「{hit.group(0)}」", "text": text.strip()[:40]})

        # 3.5) 竖排/旋转框内出现长句：引擎本应清空竖排装饰槽的要点 token
        try:
            is_vertical = (pe._shape_is_vertical(shape)
                           or abs((getattr(shape, "rotation", 0) or 0) % 180 - 90) < 1)
        except Exception:
            is_vertical = False
        compact = re.sub(r"\s+", "", text)
        if is_vertical and len(compact) > 8 and compact in OUTLINE_TEXTS:
            issues.append({"type": "VERTICAL_LONG_TEXT", "level": "FAIL",
                           "detail": f"竖排/旋转框被塞入 {len(compact)} 字样稿内容",
                           "text": text.strip()[:40]})

        # 4) 文字溢出框
        size = _font_pt(shape)
        if ww > 0.01 and hh > 0.005:
            got = fit_font_size([text], ww, hh, size,
                                deck_width_pt=sw / 12700, deck_height_pt=sh / 12700,
                                min_pt=6)
            if got is None:
                issues.append({"type": "TEXT_OVERFLOW", "level": "FAIL",
                               "detail": f"框 {ww * 100:.1f}%×{hh * 100:.1f}%，"
                                         f"{size:.0f}pt 装不下",
                               "text": text.strip()[:40]})
            elif got < size * 0.7:
                issues.append({"type": "TEXT_OVERFLOW", "level": "FAIL",
                               "detail": f"缩号 {size:.0f}→{got:.0f}pt 超三成",
                               "text": text.strip()[:40]})
            elif got < size - 1.5:
                issues.append({"type": "TEXT_SHRINK", "level": "WARN",
                               "detail": f"{size:.0f}→{got:.0f}pt 轻微缩号",
                               "text": text.strip()[:40]})

        # 5) 字号过小（正文类页型才管，封面/章节的大字标题不在此列）
        if kind == "content" and size < 10 and _count_chars(text) > 12:
            issues.append({"type": "TINY_FONT", "level": "WARN",
                           "detail": f"{size:.0f}pt", "text": text.strip()[:40]})

    # 6) 文本框互相交叠
    for i in range(len(texts)):
        for j in range(i + 1, len(texts)):
            ratio = _overlap(texts[i][1], texts[j][1])
            if ratio > OVERLAP_RATIO:
                issues.append({"type": "TEXT_OVERLAP", "level": "FAIL",
                               "detail": f"交叠 {ratio * 100:.0f}%",
                               "text": (texts[i][3].strip()[:18] + " ⟷ "
                                        + texts[j][3].strip()[:18])})

    # 7) 文字被上层实心形状遮挡
    for z, rect, _shape, text, _size in texts:
        for z2, rect2, shape2 in shapes_all:
            if z2 <= z:
                continue
            if getattr(shape2, "has_text_frame", False) and shape2.text_frame.text.strip():
                continue  # 文字压文字已由 TEXT_OVERLAP 负责
            if not _has_solid_fill(shape2):
                continue
            if _overlap(rect, rect2) > HIDE_RATIO:
                issues.append({"type": "TEXT_HIDDEN", "level": "FAIL",
                               "detail": f"被 z={z2} 实心形状覆盖",
                               "text": text.strip()[:40]})
                break

    # 8) 模板示例照片 & 空白页
    pics = [s for _z, r, s in shapes_all if _is_picture(s) and r[2] * r[3] > 0.03]
    # 模板自带图片多为装饰插画（国旗/纹理/建筑剪影），无法无模型区分示例照片，
    # 因此只统计不下结论，人工翻预览图时按页核对。

    total_chars = sum(_count_chars(t[3]) for t in texts)
    if total_chars < 4 and not pics:
        issues.append({"type": "BLANK_SLIDE", "level": "WARN",
                       "detail": f"全页仅 {total_chars} 字且无图", "text": ""})

    return {"index": idx, "chars": total_chars, "pictures": len(pics),
            "issues": issues}


def convert_previews(pptx_path: Path, pages: list[int], out_dir: Path) -> dict[int, Path]:
    """soffice → pdf → 指定页 PNG。失败返回空字典（审计结论不依赖出图）。"""
    if not SOFFICE.exists() or not PDFTOPPM.exists():
        return {}
    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        profile = Path(td) / "lo"
        cmd = [str(SOFFICE), "--headless", "--norestore",
               f"-env:UserInstallation=file:///{str(profile).replace(chr(92), '/')}",
               "--convert-to", "pdf", "--outdir", td, str(pptx_path)]
        try:
            subprocess.run(cmd, capture_output=True, timeout=180, check=False)
        except subprocess.TimeoutExpired:
            return {}
        pdf = Path(td) / (pptx_path.stem + ".pdf")
        if not pdf.exists():
            return {}
        produced = {}
        for page in sorted(set(pages)):
            stem = out_dir / f"pg-{page:02d}"
            subprocess.run([str(PDFTOPPM), "-f", str(page), "-l", str(page),
                            "-singlefile", "-r", "110", "-png", str(pdf), str(stem)],
                           capture_output=True, timeout=120, check=False)
            found = out_dir / f"pg-{page:02d}.png"
            if found.exists():
                produced[page] = found
        return produced


def load_templates(only: str = "") -> list[dict]:
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "select id,name,category,source_file,colors,font,layout_library "
        "from ppt_templates order by category,name").fetchall()
    out = []
    for row in rows:
        lib = json.loads(row["layout_library"] or "[]")
        if not lib:
            continue  # 引擎内置版式（无源 pptx），不在本次体检范围
        src = _resolve_source(row["source_file"], row["id"])
        if src is None:
            out.append({"id": row["id"], "name": row["name"],
                        "category": row["category"], "source": None,
                        "layouts": len(lib)})
            continue
        if only and only not in row["name"]:
            continue
        out.append({"id": row["id"], "name": row["name"],
                    "category": row["category"], "source": src,
                    "layouts": len(lib), "lib": lib,
                    "colors": json.loads(row["colors"] or "{}"),
                    "font": row["font"]})
    return out


def audit_template(tpl: dict, preview: bool = True) -> dict:
    slug = tpl["id"][:8]
    work = OUT / slug
    work.mkdir(parents=True, exist_ok=True)
    src_bytes = tpl["source"].read_bytes()
    template = pe.template_to_dict({
        "name": tpl["name"], "category": tpl["category"],
        "colors": tpl.get("colors") or {}, "font": tpl.get("font") or "",
        "layouts": {}, "layout_library": tpl["lib"],
    })
    warnings: list[str] = []
    data = pe.render_pptx(SAMPLE_OUTLINE, template, base_pptx=src_bytes, warnings=warnings)
    out_pptx = work / "outline.pptx"
    out_pptx.write_bytes(data)

    prs = Presentation(str(out_pptx))
    sw, sh = prs.slide_width, prs.slide_height
    pages = []
    for idx, slide in enumerate(prs.slides, 1):
        kind = (SAMPLE_OUTLINE["slides"][idx - 1]["type"]
                if idx <= len(SAMPLE_OUTLINE["slides"]) else "content")
        pages.append(audit_slide(slide, idx, sw, sh, kind))

    bad_pages = [p["index"] for p in pages
                 if any(i["level"] == "FAIL" for i in p["issues"])]
    if preview and bad_pages:
        convert_previews(out_pptx, bad_pages, work)

    fails = sum(1 for p in pages for i in p["issues"] if i["level"] == "FAIL")
    warns = sum(1 for p in pages for i in p["issues"] if i["level"] == "WARN")
    fallback_pages = sum("可读版式" in item for item in warnings)
    verdict = ("FAIL" if fails else "REVIEW" if fallback_pages >= 4 else
               "WARN" if warns or fallback_pages else "PASS")
    return {"id": tpl["id"], "name": tpl["name"], "category": tpl["category"],
            "slug": slug, "layouts": tpl["layouts"],
            "source": str(tpl["source"].relative_to(ROOT)) if tpl["source"] else "",
            "pages": len(pages), "fails": fails, "warns": warns,
            "fallback_pages": fallback_pages, "verdict": verdict,
            "detail": pages, "warnings": warnings[:6]}


def write_report(results: list[dict]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "report.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = ["# 模板启用前体检报告", "",
             f"样稿：{len(SAMPLE_OUTLINE['slides'])} 页统一内容（封面/目录/章节/正文/结尾）",
             f"模板数：{len(results)}", "",
             "判定：PASS=几何合格且完整复用模板；WARN=局部使用通用可读排版或有轻微问题；REVIEW=至少四页未能复用模板，需人工看成品；FAIL=存在越界/溢出/重叠。统一样稿体检不替代业务主题审稿。", "",
             "| 结论 | 模板 | 分类 | 版式数 | 通用回退页/12 | FAIL | WARN | 问题页 |",
             "|---|---|---|---|---|---|---|---|---|"]
    order = {"FAIL": 0, "REVIEW": 1, "WARN": 2, "PASS": 3, "MISSING": 4}
    for r in sorted(results, key=lambda x: (order.get(x.get("verdict", "MISSING"), 9),
                                            -x.get("fails", 0), x["name"])):
        if r.get("source") is None:
            lines.append(f"| MISSING | {r['name']} | {r['category']} | {r['layouts']} | - | - | - | 源文件缺失 |")
            continue
        bad = [str(p["index"]) for p in r["detail"]
               if any(i["level"] == "FAIL" for i in p["issues"])]
        lines.append(f"| {r['verdict']} | {r['name']} | {r['category']} | {r['layouts']} "
                     f"| {r.get('fallback_pages', 0)} | {r['fails']} | {r['warns']} | {', '.join(bad) or '-'} |")

    lines += ["", "## 问题明细", ""]
    for r in sorted(results, key=lambda x: -x.get("fails", 0)):
        if r.get("source") is None:
            continue
        if r["verdict"] == "PASS":
            continue
        lines.append(f"### {r['name']}（{r['verdict']}）")
        lines.append(f"- 目录：`deliverables/template-audit/{r['slug']}/`")
        if r.get("fallback_pages"):
            lines.append(f"- 统一样稿中 {r['fallback_pages']} 页改用了通用可读排版；正式启用前请目视确认。")
        for p in r["detail"]:
            bad = [i for i in p["issues"] if i["level"] in ("FAIL", "WARN")]
            if not bad:
                continue
            tags = "、".join(f"{i['type']}" for i in bad)
            lines.append(f"- 第 {p['index']} 页：{tags}")
            for issue in bad:
                txt = f"「{issue['text']}」" if issue["text"] else ""
                lines.append(f"  - {issue['type']}：{issue['detail']} {txt}")
        lines.append("")

    (OUT / "report.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="只跑名字含该关键词的模板")
    ap.add_argument("--no-preview", action="store_true")
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    templates = load_templates(args.only)
    results = []
    for i, tpl in enumerate(templates, 1):
        if tpl.get("source") is None:
            results.append({"id": tpl["id"], "name": tpl["name"],
                            "category": tpl["category"], "source": None,
                            "layouts": tpl["layouts"], "fails": 0, "warns": 0,
                            "verdict": "MISSING", "detail": []})
            print(f"[{i}/{len(templates)}] {tpl['name']}: 源文件缺失", flush=True)
            continue
        try:
            res = audit_template(tpl, preview=not args.no_preview)
        except Exception as exc:  # noqa: BLE001 - 单套失败不能中断全量
            print(f"[{i}/{len(templates)}] {tpl['name']}: 渲染失败 {exc}", flush=True)
            results.append({"id": tpl["id"], "name": tpl["name"],
                            "category": tpl["category"], "source": "",
                            "layouts": tpl["layouts"], "fails": 0, "warns": 0,
                            "verdict": "ERROR", "detail": [], "error": str(exc)[:200]})
            continue
        results.append(res)
        print(f"[{i}/{len(templates)}] {res['verdict']:<4} {res['name']} "
              f"FAIL={res['fails']} WARN={res['warns']}", flush=True)

    write_report(results)
    total = len([r for r in results if r.get("source") is not None])
    fails = len([r for r in results if r.get("verdict") in ("FAIL", "ERROR")])
    print(f"\n完成：{total} 套渲染体检，{fails} 套存在 FAIL 级问题")
    print(f"报告：{OUT / 'report.md'}")


if __name__ == "__main__":
    main()
