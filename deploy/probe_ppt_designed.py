"""Measure the on-site model's page composition: acceptance, latency, reject reasons.

The designed mode asks the model to lay out each page (regions + visuals). Whether
that works depends on the model, and the dev machine cannot reach the intranet
model, so the number has to be produced where the model lives. This probe is the
measurement: one command, one JSON report, one PNG contact sheet.

    python deploy/probe_ppt_designed.py \
        --template-file "/data/ppt/tpl_src/xxx.pptx" \
        --outline-json deploy/samples/probe_outline_11p.json \
        --out /tmp/ppt_probe

What it reports:
  * authoring acceptance  — did the model return regions that pass geometry audit
  * compile acceptance    — of those, how many survive mapping onto the real
                            template body area (this stage used to fail silently)
  * wall clock            — per LLM call, so slow batches are visible
  * reject reasons        — verbatim, so the prompt can be fixed on evidence

It writes nothing to the database and does not touch production data.
"""
from __future__ import annotations

import argparse
import copy
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))


class TimedAssistant:
    """Record every model call: latency, output size, token budget."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.calls: list[dict] = []

    def complete(self, messages, **kwargs):
        started = time.time()
        try:
            output = self.inner.complete(messages, **kwargs)
        except Exception as exc:
            self.calls.append({"seconds": round(time.time() - started, 1),
                               "error": type(exc).__name__,
                               "max_tokens": kwargs.get("max_tokens")})
            raise
        self.calls.append({"seconds": round(time.time() - started, 1),
                           "chars": len(output or ""),
                           "max_tokens": kwargs.get("max_tokens")})
        return output

    def __getattr__(self, name):
        return getattr(self.inner, name)


class ReasonCollector(logging.Handler):
    """Capture the per-page reject reasons page_authoring logs as warnings."""

    PATTERN = re.compile(r"第 (\d+) 页模型构图未采用：(.*)")

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.reasons: dict[int, str] = {}

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = record.getMessage()
        except Exception:
            return
        match = self.PATTERN.search(message)
        if match:
            self.reasons[int(match.group(1))] = match.group(2).strip()


def _load_template(args) -> tuple[dict, bytes]:
    from app.application.ppt import ppt_engine

    if args.template_file:
        source = Path(args.template_file).read_bytes()
    else:
        from sqlalchemy import text
        from app.core.config import settings
        from app.infrastructure.database import SessionLocal
        db = SessionLocal()
        try:
            row = db.execute(text(
                "select id from ppt_templates where name = :name "
                "order by created_at desc limit 1"), {"name": args.template_name}).first()
        finally:
            db.close()
        if not row:
            raise SystemExit(f"模板库里没有名为「{args.template_name}」的模板")
        # 底稿按 id 落盘，与 PPTService._tpl_source_path 同一规则。
        path = Path(settings.ppt_dir) / "tpl_src" / f"{row[0]}.pptx"
        if not path.is_file():
            raise SystemExit(f"模板「{args.template_name}」没有可用的底稿：{path}")
        source = path.read_bytes()

    learned = ppt_engine.analyze_template(source)
    template = {"colors": learned["colors"], "font": learned["font"],
                "layout_library": learned["layouts"]}
    return template, source


def _assistant() -> Any:
    from app.application.shared.writing_assistant import WritingAssistant
    from app.infrastructure.ai import get_llm_gateway, get_ppt_gateway

    gateway = get_ppt_gateway() or get_llm_gateway()
    return WritingAssistant(gateway)


def _drop_missing_images(outline: dict) -> list[str]:
    """Image pages without a file on disk would be rejected as a false negative."""
    dropped = []
    for index, slide in enumerate(outline.get("slides") or [], 1):
        image = slide.get("_image") or {}
        path = image.get("file_path")
        if not path:
            continue
        resolved = Path(str(path))
        if not resolved.is_absolute():
            resolved = ROOT / resolved      # 样例大纲里的相对路径按仓库根解析
        if resolved.is_file():
            image["file_path"] = str(resolved)
            continue
        slide.pop("_image", None)
        slide.pop("image_id", None)
        slide.pop("image_name", None)
        dropped.append(f"p{index}: {Path(str(path)).name}")
    return dropped


def _render_png(pptx_path: Path, out_dir: Path) -> str:
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        return "未找到 LibreOffice，跳过预览渲染"
    profile = out_dir / "lo_profile"
    subprocess.run([soffice, f"-env:UserInstallation={profile.as_uri()}",
                    "--headless", "--convert-to", "pdf",
                    "--outdir", str(out_dir), str(pptx_path)],
                   check=True, capture_output=True)
    pdf = pptx_path.with_suffix(".pdf")
    if not shutil.which("pdftoppm"):
        return "未找到 pdftoppm，跳过预览渲染"
    subprocess.run(["pdftoppm", "-png", "-r", "110", str(pdf),
                    str(out_dir / "pg")], check=True, capture_output=True)
    return ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template-file", help="模板 pptx 路径（与 --template-name 二选一）")
    parser.add_argument("--template-name", help="模板库里的模板名")
    parser.add_argument("--outline-json", required=True, help="大纲 JSON（含 slides）")
    parser.add_argument("--out", default="probe_out", help="输出目录")
    parser.add_argument("--limit", type=int, default=0, help="只测前 N 页（0=全部）")
    parser.add_argument("--no-render", action="store_true", help="跳过 PNG 预览")
    args = parser.parse_args()

    if not args.template_file and not args.template_name:
        parser.error("必须给 --template-file 或 --template-name")

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    collector = ReasonCollector()
    logging.getLogger("app.application.ppt.page_authoring").addHandler(collector)

    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    outline = json.loads(Path(args.outline_json).read_text(encoding="utf-8"))
    if args.limit:
        outline["slides"] = (outline.get("slides") or [])[:args.limit]
    outline.setdefault("template_mode", "designed")
    dropped = _drop_missing_images(outline)

    template, source = _load_template(args)
    from app.application.ppt import page_authoring, ppt_engine

    in_scope = [index for index, slide in enumerate(outline["slides"], 1)
                if slide.get("type") in {"content", "summary"} and slide.get("points")]

    assistant = TimedAssistant(_assistant())
    started = time.time()
    authored = page_authoring.author_pages(outline, template, assistant, warnings=[])
    author_seconds = time.time() - started
    author_calls = list(assistant.calls)

    warnings: list[str] = []
    diagnostics: list[dict] = []
    started = time.time()
    data = ppt_engine.render_pptx(authored, template, base_pptx=source,
                                  warnings=warnings, adaptive=False,
                                  diagnostics=diagnostics)
    render_seconds = time.time() - started
    pptx_path = out_dir / "probe.pptx"
    pptx_path.write_bytes(data)

    rows = []
    for index in in_scope:
        slide = authored["slides"][index - 1]
        has_regions = isinstance((slide.get("design") or {}).get("regions"), list) and \
            bool((slide.get("design") or {}).get("regions"))
        diag = next((item for item in diagnostics if item.get("page") == index), {})
        rows.append({
            "page": index,
            "title": slide.get("title"),
            "type": slide.get("type"),
            "authored": has_regions,
            "author_reason": collector.reasons.get(index, ""),
            "composition": diag.get("composition", ""),
            "compile_skip": diag.get("composition_skip", ""),
        })

    authored_ok = [row for row in rows if row["authored"]]
    compiled_ok = [row for row in rows if row["composition"] == "model"]
    compile_fail = [row for row in authored_ok if row["composition"] != "model"]
    call_seconds = [call["seconds"] for call in author_calls if "seconds" in call]

    report = {
        "template": args.template_file or args.template_name,
        "pages_in_scope": len(in_scope),
        "authoring": {
            "accepted": len(authored_ok),
            "rate": round(len(authored_ok) / max(1, len(in_scope)), 3),
            "calls": len(author_calls),
            "seconds": round(author_seconds, 1),
            "call_seconds": call_seconds,
            "per_call_mean": round(sum(call_seconds) / max(1, len(call_seconds)), 1),
            "per_call_max": max(call_seconds) if call_seconds else 0,
            "errors": [call for call in author_calls if "error" in call],
        },
        "compile": {
            "accepted": len(compiled_ok),
            "rate_of_authored": round(len(compiled_ok) / max(1, len(authored_ok)), 3),
            "seconds": round(render_seconds, 1),
        },
        "rows": rows,
        "compile_failures": [{"page": row["page"], "reason": row["compile_skip"]}
                             for row in compile_fail],
        "dropped_images": dropped,
        "warnings": warnings,
    }
    (out_dir / "probe.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    if not args.no_render:
        try:
            note = _render_png(pptx_path, out_dir)
        except Exception as exc:  # rendering is a convenience, never a failure
            note = f"预览渲染失败：{type(exc).__name__} {exc}"
        if note:
            print(note)

    print()
    print(f"{'页':>3} {'构图':>4} {'编译':>4}  标题 / 原因")
    print("-" * 74)
    for row in rows:
        mark = lambda value: "OK" if value else "—"
        reason = row["author_reason"] or row["compile_skip"]
        print(f"{row['page']:>3} {mark(row['authored']):>4} "
              f"{mark(row['composition'] == 'model'):>4}  "
              f"{str(row['title'])[:22]}" + (f" | {reason[:34]}" if reason else ""))

    print("-" * 74)
    print(f"正文页 {len(in_scope)} 页；模型构图接受 {len(authored_ok)} 页 "
          f"({report['authoring']['rate']:.0%})；"
          f"编译落地 {len(compiled_ok)} 页 ({report['compile']['rate_of_authored']:.0%})")
    print(f"构图调用 {len(author_calls)} 次，共 {author_seconds:.1f}s，"
          f"平均 {report['authoring']['per_call_mean']}s，最长 {report['authoring']['per_call_max']}s；"
          f"渲染 {render_seconds:.1f}s")
    for item in report["compile_failures"]:
        print(f"  编译被拒 p{item['page']}：{item['reason']}")
    for item in dropped:
        print(f"  跳过无图页 {item}")
    print(f"报告 {out_dir / 'probe.json'}")
    print(f"成稿 {pptx_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
