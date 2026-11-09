#!/usr/bin/env python3
"""把已有 .pptx 剥成「干净母版」：删掉全部内容页，保留母版/版式/主题/页面尺寸。

背景
----
`build_pptx_learned` 用用户模板生成新稿时是「清空原页重绘」，母版、版式和主题
没有被当作底板继承下来。本脚本产出一份 **slides=0、其余模板体系完整** 的
`.pptx`，可作为后续「以母版为底板新建页」的底座。

⚠ 边界
------
* 这是**离线预处理工具**，只产出新文件；**不接入线上生成链路**，不被 server/ 导入，
  不修改任何现有模块，原文件绝不改动。
* 只删「内容页」本身。母版、版式、主题、页面尺寸、备注母版、母版引用的图片全部保留；
  只被内容页引用的图片/备注页会随关系图一起被丢弃。
* 输出不能喂给 `analyze_template()`（它靠遍历已有页面学版式）；本工具的用途是
  作为新建页的底板，不是作为版式学习样本。

用法
----
    python deploy/strip_ppt_template.py 模板.pptx [-o 底板.pptx]
    python deploy/strip_ppt_template.py --dir ppttem/ --out-dir out/base/
    python deploy/strip_ppt_template.py 模板.pptx --dry-run

退出码：全部成功 0，任一失败 1。
"""
from __future__ import annotations

import argparse
import io
import json
import re
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from pptx import Presentation

_A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
_SLIDE_PART = re.compile(r"ppt/slides/slide\d+\.xml$")
_NOTE_PART = re.compile(r"ppt/notesSlides/notesSlide\d+\.xml$")
_THEME_PART = re.compile(r"ppt/theme/theme\d+\.xml$")


class StripError(RuntimeError):
    """输入不是可处理的 pptx，或剥离结果校验不通过。"""


def _accent1(blob: bytes) -> str:
    """读主题强调色 1，用来确认主题没有被重写。"""
    try:
        with zipfile.ZipFile(io.BytesIO(blob)) as zf:
            names = sorted(n for n in zf.namelist() if _THEME_PART.fullmatch(n))
            if not names:
                return ""
            root = ET.fromstring(zf.read(names[0]))
    except (zipfile.BadZipFile, ET.ParseError):
        return ""
    scheme = root.find(f".//{{{_A_NS}}}clrScheme")
    if scheme is None:
        return ""
    accent = scheme.find(f"{{{_A_NS}}}accent1")
    if accent is None or not list(accent):
        return ""
    color = list(accent)[0]
    return str(color.get("val") or color.get("lastClr") or "").upper()


def _facts(blob: bytes) -> dict:
    """从 pptx 字节里读可比对的结构事实。"""
    prs = Presentation(io.BytesIO(blob))
    facts = {
        "slides": len(prs.slides),
        "masters": len(prs.slide_masters),
        "layouts": len(prs.slide_layouts),
        "width": prs.slide_width,
        "height": prs.slide_height,
        "accent1": _accent1(blob),
    }
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        names = zf.namelist()
    facts["slide_parts"] = sum(1 for n in names if _SLIDE_PART.search(n))
    facts["note_parts"] = sum(1 for n in names if _NOTE_PART.search(n))
    facts["media_parts"] = sum(1 for n in names if n.startswith("ppt/media/"))
    return facts


def strip_template_bytes(data: bytes) -> bytes:
    """删掉全部内容页，返回新 pptx 字节；输入不做任何修改。"""
    prs = Presentation(io.BytesIO(data))
    sld_ids = prs.slides._sldIdLst  # noqa: SLF001 - python-pptx 未提供删除页的公开 API
    for sld_id in list(sld_ids):
        r_id = sld_id.rId
        sld_ids.remove(sld_id)
        # 先移除引用元素再 drop_rel，保证关系引用计数为 0，一定被删除；
        # 孤立的内容页 part 在保存时不会被 package 遍历写出。
        prs.part.drop_rel(r_id)
    out = io.BytesIO()
    prs.save(out)
    return out.getvalue()


def verify_strip(original: bytes, base: bytes) -> dict:
    """校验剥离结果，并确认输出仍可作为新建页的底板。不通过则抛 StripError。"""
    src, dst = _facts(original), _facts(base)
    if dst["slides"] != 0:
        raise StripError(f"输出仍有 {dst['slides']} 页内容页")
    for key in ("masters", "layouts", "width", "height", "accent1"):
        if src[key] != dst[key]:
            raise StripError(f"{key} 被改变：{src[key]!r} -> {dst[key]!r}")
    if dst["slide_parts"] or dst["note_parts"]:
        raise StripError("输出包内仍残留内容页或备注页 XML（原文可能外泄）")
    # 底座可用性：用第一个可用版式新建一页并能正常保存。
    try:
        probe = Presentation(io.BytesIO(base))
        layout = probe.slide_layouts[0]
        probe.slides.add_slide(layout)
        probe.save(io.BytesIO())
    except Exception as exc:  # noqa: BLE001 - 统一转成可读的工具错误
        raise StripError(f"底板无法新建页：{type(exc).__name__}: {exc}") from exc
    return {"source": src, "base": dst,
            "src_bytes": len(original), "base_bytes": len(base)}


def strip_file(path: Path, output: Path, *, dry_run: bool = False,
               force: bool = False) -> dict:
    """处理单个文件；dry_run 只校验不写盘。"""
    original = path.read_bytes()
    base = strip_template_bytes(original)
    report = verify_strip(original, base)
    report["file"] = str(path)
    report["output"] = str(output)
    report["dry_run"] = dry_run
    if not dry_run:
        if output.exists() and not force:
            raise StripError(f"输出已存在：{output}（加 --force 覆盖）")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(base)
    return report


def _collect(sources: list[Path], out_dir: Path | None) -> list[tuple[Path, Path]]:
    jobs: list[tuple[Path, Path]] = []
    for item in sources:
        files = sorted(item.glob("*.pptx")) if item.is_dir() else [item]
        for file in files:
            if file.name.startswith("~$"):
                continue
            target = ((out_dir / f"{file.stem}.base.pptx") if out_dir
                      else file.with_name(f"{file.stem}.base.pptx"))
            jobs.append((file, target))
    return jobs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="把 pptx 剥成零内容页的干净母版")
    parser.add_argument("sources", nargs="*", type=Path, help="pptx 文件或目录")
    parser.add_argument("--dir", type=Path, default=None, help="批量处理该目录下的 pptx")
    parser.add_argument("--out-dir", type=Path, default=None, help="批量输出目录")
    parser.add_argument("-o", "--output", type=Path, default=None, help="单文件输出路径")
    parser.add_argument("--dry-run", action="store_true", help="只校验并报告，不写文件")
    parser.add_argument("--force", action="store_true", help="覆盖已存在的输出")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出报告")
    args = parser.parse_args(argv)

    sources = list(args.sources)
    if args.dir:
        sources.insert(0, args.dir)
    if not sources:
        parser.error("至少给一个 pptx 文件或 --dir 目录")
    if args.output and len(sources) != 1:
        parser.error("-o/--output 只能与单个输入文件搭配；批量请用 --out-dir")

    jobs = _collect(sources, args.out_dir)
    if args.output:
        jobs = [(jobs[0][0], args.output)]
    if not jobs:
        parser.error("没有找到 .pptx 文件")

    reports, errors = [], []
    for source, output in jobs:
        try:
            reports.append(strip_file(source, output, dry_run=args.dry_run,
                                     force=args.force))
        except Exception as exc:  # noqa: BLE001 - 批量时单份失败不阻断其余
            errors.append(f"{source}: {type(exc).__name__}: {exc}")

    if args.json:
        print(json.dumps({"reports": reports, "errors": errors},
                         ensure_ascii=False, indent=2))
    else:
        prefix = "预演：" if args.dry_run else ""
        for r in reports:
            s, b = r["source"], r["base"]
            print(f"{prefix}OK  {Path(r['file']).name[:38]:38s} "
                  f"页 {s['slides']}→{b['slides']} | "
                  f"母版 {s['masters']}→{b['masters']} "
                  f"版式 {s['layouts']}→{b['layouts']} | "
                  f"色 {s['accent1'] or '-'}→{b['accent1'] or '-'} | "
                  f"{r['src_bytes'] // 1024}KB→{r['base_bytes'] // 1024}KB | "
                  f"{r['output']}")
        for line in errors:
            print(f"[错误] {line}")
        print(f"\n{prefix}完成 {len(reports)} 份，失败 {len(errors)} 份")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
