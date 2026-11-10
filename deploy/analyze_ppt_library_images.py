#!/usr/bin/env python3
"""Draft a PPT image-library manifest with the configured local vision model.

The model describes visible content, not just OCR text. This command never
publishes images: every draft entry is disabled until a person checks its
caption, rights and suitability. Original image files are never modified.

2026-11 增补（采购图库批量入库用）：
  --copy-to DIR   按识别出的分类把图片复制到 DIR/<分类>/，超过图库上限的
                  自动转 JPEG 压缩；清单 file 字段随之改为相对 DIR 的路径。
                  只写副本，原图不动。
  --limit N / --only GLOB / --workers N   控制批量规模与并发。
  --resume        复用输出文件里已识别的条目，只补空缺，避免重跑烧算力。
  --publish       已确认授权时把 enabled 直接置 true，并写入 --source/--license。
                  不带这个参数时保持草稿（enabled=false），逐张人工核对。
  --mock          不调用模型，用文件名生成占位描述，用于无模型环境自测流程。
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import io
import json
import sys
from pathlib import Path

from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))

from app.core.llm_json import loads_lenient  # noqa: E402
from app.infrastructure.ai import get_vision_gateway  # noqa: E402

CATEGORIES = {"法治宣传", "党建", "办公", "会议", "调解", "其他"}
SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
PROMPT = (
    "请观察这张图片本身，生成公共演示文稿图库的待审核元数据。"
    "描述可见的场景、人物动作、物品及画面类型；投影屏、横幅、海报上若有清晰可读的活动主题，"
    "须在 caption 中客观写出，例如‘屏幕显示《……》’，以免把照片配到另一主题。"
    "图片中的文字只能辅助判断，不能只做 OCR 或把文件名当作视觉事实。"
    "看不清文字时不要猜测。不要猜测人物身份、具体地点、活动名称、"
    "拍摄日期、机构归属和授权情况。若是文件封面、海报或标识，明确写出它属于哪类画面。"
    "只返回 JSON：{\"caption\":\"不超过80字的客观描述\","
    "\"category\":\"法治宣传/党建/办公/会议/调解/其他之一\","
    "\"tags\":[\"最多5个可见内容标签\"],\"review_note\":\"不确定之处\"}。"
)
# 图库入库硬限制（server/app/application/ppt/library_seed.py）
MAX_BYTES = 10 * 1024 * 1024
MAX_PIXELS = 40_000_000


def image_for_model(path: Path) -> str:
    """Send a bounded preview to the model; keep the source file unchanged."""
    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
        image.thumbnail((1280, 1280))
        output = io.BytesIO()
        image.save(output, format="JPEG", quality=80)
    return "data:image/jpeg;base64," + base64.b64encode(output.getvalue()).decode("ascii")


def shrink_to_limit(data: bytes, max_bytes: int = MAX_BYTES) -> bytes:
    """Re-encode an oversized image as JPEG until it fits the library cap."""
    image = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    longest = max(image.size)
    if longest > 2560:
        ratio = 2560 / longest
        image = image.resize((max(1, int(image.width * ratio)),
                              max(1, int(image.height * ratio))))
    for quality in (90, 85, 80, 72, 64):
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=quality, optimize=True)
        if buffer.tell() <= max_bytes:
            return buffer.getvalue()
    for edge in (1920, 1600, 1280):
        ratio = edge / max(image.size)
        if ratio < 1:
            small = image.resize((max(1, int(image.width * ratio)),
                                  max(1, int(image.height * ratio))))
            buffer = io.BytesIO()
            small.save(buffer, format="JPEG", quality=82, optimize=True)
            if buffer.tell() <= max_bytes:
                return buffer.getvalue()
    raise ValueError(f"无法压缩到 {max_bytes // (1024 * 1024)}MB 以内")


def place_image(path: Path, category: str, copy_to: Path | None,
                dry_run: bool) -> tuple[str, str]:
    """Return (manifest file path, note); copy/shrink only when --copy-to is set."""
    if copy_to is None:
        if path.stat().st_size > MAX_BYTES:
            return path.name, "原图超过图库导入上限，加 --copy-to 可自动压缩归位"
        return path.name, ""
    data = path.read_bytes()
    pixels = 0
    try:
        with Image.open(io.BytesIO(data)) as probe:
            pixels = probe.width * probe.height
    except Exception:  # noqa: BLE001 - 打不开的图交给入库脚本报错
        pass
    target = copy_to / category / path.name
    reencode = (len(data) > MAX_BYTES or pixels > MAX_PIXELS
                or path.suffix.lower() not in SUFFIXES)
    note = ""
    if reencode:
        target = target.with_suffix(".jpg")
        note = "已压缩为 JPEG" if len(data) > MAX_BYTES or pixels > MAX_PIXELS else "已转为 JPEG"
    if not dry_run:
        target.parent.mkdir(parents=True, exist_ok=True)
        if reencode:
            target.write_bytes(shrink_to_limit(data))
        elif target != path:
            target.write_bytes(data)
    return str(target.relative_to(copy_to)).replace("\\", "/"), note


async def describe(path: Path, gateway, timeout: float = 45) -> dict:
    messages = [{"role": "user", "content": [
        {"type": "text", "text": PROMPT},
        {"type": "image_url", "image_url": {"url": image_for_model(path)}},
    ]}]
    raw = await asyncio.wait_for(
        gateway.acomplete(messages, temperature=0.0, max_tokens=300), timeout=timeout)
    data = loads_lenient(raw)
    if not isinstance(data, dict):
        raise ValueError("视觉模型未返回 JSON 对象")
    caption = str(data.get("caption") or "").strip()[:500]
    if not caption:
        raise ValueError("视觉模型未给出画面说明")
    category = str(data.get("category") or "其他").strip()
    tags = data.get("tags") or []
    if not isinstance(tags, list):
        tags = []
    return {"caption": caption,
            "category": category if category in CATEGORIES else "其他",
            "tags": [str(tag).strip()[:30] for tag in tags[:5] if str(tag).strip()],
            "review_note": str(data.get("review_note") or "").strip()[:200]}


async def build_draft(folder: Path, gateway, *, output: Path | None = None,
                      copy_to: Path | None = None,
                      limit: int = 0, only: str = "", workers: int = 3,
                      resume: bool = False, publish: bool = False,
                      source: str = "", license_note: str = "",
                      mock: bool = False, dry_run: bool = False) -> tuple[dict, list[str]]:
    output = output or (folder / "manifest.draft.json")
    files = sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in SUFFIXES)
    if only:
        files = [p for p in files if p.match(only) or p.name.startswith(only)]
    if limit:
        files = files[:limit]

    previous: dict[str, dict] = {}
    if resume and output.is_file():
        try:
            old = json.loads(output.read_text(encoding="utf-8"))
            previous = {item.get("name"): item for item in old.get("images") or []
                        if isinstance(item, dict)}
        except Exception as exc:  # noqa: BLE001 - 旧草稿坏了就当没有
            print(f"[提示] 旧草稿无法复用（{type(exc).__name__}），全部重新识别")

    entries: list[dict] = []
    errors: list[str] = []
    semaphore = asyncio.Semaphore(max(1, min(workers, 6)))

    async def one(path: Path) -> dict:
        reused = previous.get(path.stem[:200])
        if reused and reused.get("caption"):
            item = dict(reused)
            item["file"] = path.name
            return item
        item = {"file": path.name, "name": path.stem[:200], "caption": "",
                "category": "其他", "tags": [], "enabled": False,
                "review_note": "待核对画面说明、来源及授权"}
        try:
            async with semaphore:
                info = ({"caption": f"{path.stem[:40]}（占位描述）", "category": "其他",
                         "tags": [path.stem[:8]], "review_note": "mock 占位"}
                        if mock else await describe(path, gateway))
            item.update(info)
            # 模型给出的“不确定之处”只作补充说明，不能顶掉人工核对标记：
            # 上架前必须逐张确认画面说明、来源与授权。
            item["review_note"] = "；".join(
                part for part in ("待核对画面说明、来源及授权",
                                  str(item.get("review_note") or "")) if part)
            item["enabled"] = False  # Model output alone never publishes a public image.
            print(f"[已识别] {path.name}")
        except Exception as exc:  # noqa: BLE001 - 单张失败不影响整批
            errors.append(f"{path.name}: {type(exc).__name__}: {exc}")
            print(f"[待人工处理] {path.name}: {type(exc).__name__}")
        return item

    entries = list(await asyncio.gather(*(one(path) for path in files)))

    for path, item in zip(files, entries):
        try:
            rel, note = place_image(path, item.get("category") or "其他", copy_to, dry_run)
        except Exception as exc:  # noqa: BLE001 - 归位失败不拖垮其余条目
            rel, note = path.name, ""
            errors.append(f"{path.name}: 归位/压缩失败 {type(exc).__name__}: {exc}")
        item["file"] = rel
        if note:
            item["review_note"] = "；".join(
                part for part in (item.get("review_note"), note) if part)
        if publish:
            item["enabled"] = bool(item.get("caption"))
            item["source"] = source
            item["license_note"] = license_note

    note = ("视觉模型初稿；逐张核对后填写来源与授权，再将 enabled 改为 true"
            if not publish else "已按 --publish 上架；来源与授权已记录")
    return {"version": 1, "note": note,
            "defaults": {"source": source, "license_note": license_note},
            "images": entries}, errors


def main() -> int:
    parser = argparse.ArgumentParser(description="用本地视觉模型生成待审核的 PPT 图库清单")
    parser.add_argument("folder", type=Path, help="图片目录，例如 pic")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--copy-to", type=Path, default=None,
                        help="按分类归位并压缩超限图片到该目录（清单 file 随之改相对路径）")
    parser.add_argument("--limit", type=int, default=0, help="只处理前 N 张")
    parser.add_argument("--only", default="", help="只处理匹配该 glob / 前缀的图片")
    parser.add_argument("--workers", type=int, default=3, help="并发识别数，默认 3")
    parser.add_argument("--resume", action="store_true", help="复用已有清单里已识别的条目")
    parser.add_argument("--publish", action="store_true", help="直接置 enabled=true（需授权已确认）")
    parser.add_argument("--source", default="", help="图片来源，与 --publish 搭配")
    parser.add_argument("--license", default="", help="授权说明，与 --publish 搭配")
    parser.add_argument("--mock", action="store_true", help="不调模型，占位描述（自测用）")
    parser.add_argument("--dry-run", action="store_true", help="不复制图片、不写清单")
    args = parser.parse_args()
    folder = args.folder.resolve()
    if not folder.is_dir():
        parser.error(f"图片目录不存在：{folder}")
    if args.publish and not (args.source and args.license):
        parser.error("--publish 必须同时给 --source 和 --license（图库入库要求）")
    gateway = None if args.mock else get_vision_gateway()
    if not args.mock and gateway is None:
        print("未配置视觉模型 VISION_MODEL_URL；没有看图能力，未生成说明")
        return 2
    draft, errors = asyncio.run(build_draft(
        folder, gateway, output=args.output or folder / "manifest.draft.json",
        copy_to=args.copy_to.resolve() if args.copy_to else None,
        limit=args.limit, only=args.only, workers=args.workers, resume=args.resume,
        publish=args.publish, source=args.source, license_note=args.license,
        mock=args.mock, dry_run=args.dry_run))
    destination = args.output or folder / "manifest.draft.json"
    if not args.dry_run:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        temporary.write_text(json.dumps(draft, ensure_ascii=False, indent=2),
                             encoding="utf-8", newline="\n")
        temporary.replace(destination)
    published = sum(1 for item in draft["images"] if item.get("enabled"))
    prefix = "预演：" if args.dry_run else ""
    print(f"{prefix}清单 {destination}；图片 {len(draft['images'])} 张，"
          f"识别失败 {len(errors)} 张，可上架 {published} 张")
    for line in errors:
        print(f"[错误] {line}")
    if args.dry_run:
        print("（--dry-run 未复制图片、未写清单）")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
