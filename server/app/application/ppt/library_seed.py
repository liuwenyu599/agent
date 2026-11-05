"""公共图库种子导入：manifest.json → 图片文件 + 缩略图 + 入库。

设计要点（政务内网场景）：
- **离线预置**：图片包与 manifest.json 随仓库/镜像分发，不依赖任何在线图源；
- **幂等**：按 `name` 定位已有条目；文件内容 sha256 相同且元数据未变 → 跳过，
  文件换了 → 覆盖原文件并更新元数据，绝不再插一条重复图；
- **合规前置**：`source` 与 `license_note` 必填（可写在 manifest.defaults 里统一给），
  缺一项该图不入库，直接记错误；
- **坏图不阻断**：单条失败只记错误继续，整批导入不会因为一张图废掉。

manifest 结构见 `templates/library/manifest.json` 与同目录 README。
"""
from __future__ import annotations

import hashlib
import io
import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from PIL import Image, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infrastructure.database.models.ppt import PPTLibraryImageModel

MAX_BYTES = 10 * 1024 * 1024
MIN_EDGE = 128
MAX_PIXELS = 40_000_000
MAX_NAME = 200
MAX_CATEGORY = 50
MAX_CAPTION = 500
MAX_SOURCE = 200
MAX_LICENSE = 500
MAX_TAGS = 12

ID_NAMESPACE = uuid.UUID("5d0f3c1e-8f5a-4b3c-9a7e-2b6d4c8e1f03")


@dataclass
class ImportResult:
    created: int = 0
    updated: int = 0
    skipped: int = 0
    errors: List[str] = field(default_factory=list)
    details: List[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.created + self.updated + self.skipped


class ManifestError(ValueError):
    """manifest 本身不合法（结构/必填项缺失），与单张图片的失败区分开。"""


def load_manifest(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ManifestError(f"manifest 不存在：{path}")
    except json.JSONDecodeError as exc:
        raise ManifestError(f"manifest 不是合法 JSON：{exc}")
    if not isinstance(data, dict):
        raise ManifestError("manifest 根节点必须是对象")
    images = data.get("images")
    if not isinstance(images, list):
        raise ManifestError("manifest 缺少 images 数组")
    defaults = data.get("defaults") or {}
    if not isinstance(defaults, dict):
        raise ManifestError("manifest.defaults 必须是对象")
    return data


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_relative(value: str, base_dir: Path) -> Path:
    """拒绝越出图片包目录的路径，避免 manifest 写到系统任意位置。"""
    candidate = (base_dir / value).resolve()
    root = base_dir.resolve()
    if root != candidate and root not in candidate.parents:
        raise ValueError(f"文件路径越出图片包目录：{value}")
    return candidate


def _prepare_image(data: bytes) -> tuple[int, int, str, str, bytes]:
    """校验图片并生成缩略图，返回 (宽, 高, mime, 扩展名, 缩略图字节)。"""
    if not data:
        raise ValueError("图片为空")
    if len(data) > MAX_BYTES:
        raise ValueError(f"图片超过 {MAX_BYTES // (1024 * 1024)}MB")
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format not in {"JPEG", "PNG", "WEBP"}:
                raise ValueError(f"不支持的图片格式：{image.format}")
            width, height = image.size
            if width < MIN_EDGE or height < MIN_EDGE:
                raise ValueError(f"图片边长不足 {MIN_EDGE}px")
            if width * height > MAX_PIXELS:
                raise ValueError("图片像素数过大")
            image.load()
            thumb = image.convert("RGB")
            thumb.thumbnail((480, 480))
            output = io.BytesIO()
            thumb.save(output, format="JPEG", quality=82)
            mime = {"JPEG": "image/jpeg", "PNG": "image/png",
                    "WEBP": "image/webp"}[image.format]
            extension = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}[image.format]
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError(f"不是有效图片：{exc}") from exc
    return width, height, mime, extension, output.getvalue()


def _normalize_tags(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        parts = value.replace("，", ",").split(",")
    elif isinstance(value, (list, tuple)):
        parts = [str(item) for item in value]
    else:
        raise ValueError("tags 必须是数组或逗号分隔字符串")
    return [part.strip() for part in parts if part.strip()][:MAX_TAGS]


def _entry_meta(entry: Dict[str, Any], defaults: Dict[str, Any]) -> Dict[str, Any]:
    def pick(key: str, limit: int, required: bool = False) -> str:
        value = entry.get(key)
        if value in (None, ""):
            value = defaults.get(key, "")
        text = str(value).strip() if value is not None else ""
        if required and not text:
            raise ValueError(f"缺少必填字段 {key}")
        return text[:limit]

    name = pick("name", MAX_NAME, required=True)
    return {
        "name": name,
        "caption": pick("caption", MAX_CAPTION) or name,
        "category": pick("category", MAX_CATEGORY, required=True),
        "tags": _normalize_tags(entry.get("tags")),
        "source": pick("source", MAX_SOURCE, required=True),
        "license_note": pick("license_note", MAX_LICENSE, required=True),
        "enabled": bool(entry.get("enabled", True)),
    }


def _find_by_name(db: Session, name: str) -> Optional[PPTLibraryImageModel]:
    return db.scalars(
        select(PPTLibraryImageModel).where(PPTLibraryImageModel.name == name)
    ).first()


def import_library_images(db: Session, manifest_path: Path, *,
                          base_dir: Optional[Path] = None,
                          ppt_dir: Optional[Path] = None,
                          dry_run: bool = False) -> ImportResult:
    """按 manifest 导入公共图库。返回新增/更新/跳过计数与逐条说明。

    base_dir: 图片包根目录（默认 manifest 所在目录）
    ppt_dir: 图库文件落盘根目录（默认 settings.ppt_dir）
    """
    manifest_path = Path(manifest_path)
    data = load_manifest(manifest_path)
    base_dir = Path(base_dir) if base_dir else manifest_path.parent
    if ppt_dir is None:
        from app.core.config import settings
        ppt_dir = settings.ppt_dir
    library_dir = Path(ppt_dir) / "library"
    result = ImportResult()
    defaults = data.get("defaults") or {}

    for index, entry in enumerate(data.get("images") or [], 1):
        label = f"第{index}条"
        if not isinstance(entry, dict):
            result.errors.append(f"{label}：条目必须是对象")
            continue
        try:
            relative = str(entry.get("file") or "").strip()
            if not relative:
                raise ValueError("缺少 file")
            source_path = _safe_relative(relative, base_dir)
            if not source_path.is_file():
                raise ValueError(f"图片文件不存在：{relative}")
            meta = _entry_meta(entry, defaults)
            label = f"{meta['name']}（{relative}）"
            payload = source_path.read_bytes()
            width, height, mime, extension, thumb = _prepare_image(payload)
        except (ValueError, ManifestError) as exc:
            result.errors.append(f"{label}：{exc}")
            continue

        digest = _sha256(payload)
        existing = _find_by_name(db, meta["name"])
        if existing is None:
            stable_id = uuid.uuid5(ID_NAMESPACE, f"{meta['name']}|{digest}").hex
            target = library_dir / f"{stable_id}{extension}"
            target_thumb = library_dir / f"{target.stem}-thumb.jpg"
            if not dry_run:
                library_dir.mkdir(parents=True, exist_ok=True)
                target.write_bytes(payload)
                target_thumb.write_bytes(thumb)
                db.add(PPTLibraryImageModel(
                    id=target.stem, file_path=str(target), thumb_path=str(target_thumb),
                    file_size=len(payload), width=width, height=height,
                    mime_type=mime, **meta))
                db.commit()
            result.created += 1
            result.details.append(f"[新建] {label}")
            continue

        same_file = False
        try:
            stored = Path(existing.file_path)
            same_file = (stored.is_file() and len(payload) == existing.file_size
                         and _sha256(stored.read_bytes()) == digest)
        except OSError:
            same_file = False
        meta_changed = False
        for key, value in meta.items():
            current = getattr(existing, key)
            if key == "tags":
                current = current or []
            if current != value:
                meta_changed = True
                break
        if same_file and not meta_changed:
            result.skipped += 1
            result.details.append(f"[跳过] {label}（无变化）")
            continue
        if not dry_run:
            if not same_file:
                library_dir.mkdir(parents=True, exist_ok=True)
                target = Path(existing.file_path)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(payload)
                Path(existing.thumb_path).write_bytes(thumb)
                existing.file_size = len(payload)
                existing.width = width
                existing.height = height
                existing.mime_type = mime
            for key, value in meta.items():
                setattr(existing, key, value)
            db.commit()
        result.updated += 1
        result.details.append(f"[更新] {label}")
    return result
