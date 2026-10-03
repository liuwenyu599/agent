"""Security helpers for knowledge-file ingress.

Never derive a filesystem path from a client-supplied filename. Uploads are streamed
with a hard byte ceiling so a large request cannot be buffered entirely in memory.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, Tuple

from app.core.config import settings
from app.core.exceptions import AppError

_CHUNK_SIZE = 1024 * 1024
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]+")


def safe_client_filename(filename: str, allowed_extensions: Iterable[str] | None = None) -> Tuple[str, str]:
    raw = (filename or "").replace("\\", "/")
    name = raw.rsplit("/", 1)[-1]
    name = _CONTROL_RE.sub("", name).strip().strip(".")
    if not name:
        raise AppError(400, "文件名无效")
    suffix = Path(name).suffix.lower()
    if not suffix:
        raise AppError(400, "文件缺少扩展名")
    if allowed_extensions is not None:
        allowed = {str(ext).lower() for ext in allowed_extensions}
        if suffix not in allowed:
            raise AppError(400, f"暂不支持 {suffix} 格式的文件")
    return name[:255], suffix


async def stream_upload_to_file(upload, destination: Path, max_bytes: int | None = None) -> int:
    limit = int(max_bytes or settings.UPLOAD_MAX_SIZE)
    if limit <= 0:
        raise RuntimeError("UPLOAD_MAX_SIZE 必须大于 0")
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    try:
        with destination.open("wb") as handle:
            while True:
                chunk = await upload.read(_CHUNK_SIZE)
                if not chunk:
                    break
                total += len(chunk)
                if total > limit:
                    raise AppError(413, f"文件超过上传上限 {limit // (1024 * 1024)} MB")
                handle.write(chunk)
        if total == 0:
            raise AppError(400, "上传文件为空")
        return total
    except Exception:
        destination.unlink(missing_ok=True)
        raise
