"""Prepare selected photographs for the size they actually occupy in PPTX."""
from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageOps

_EMU_PER_INCH = 914400
_TARGET_DPI = 220


def prepared_picture(path: str | Path, width: int, height: int) -> tuple[str | io.BytesIO, int, int]:
    """Return an image source while retaining enough pixels for crop regions."""
    path = str(path)
    with Image.open(path) as source:
        orientation = source.getexif().get(274, 1)
        oriented = (ImageOps.exif_transpose(source)
                    if orientation not in (None, 1) else source)
        source_width, source_height = oriented.size
        if source_width <= 0 or source_height <= 0:
            raise ValueError("配图尺寸无效")
        target_width = max(1, round(width / _EMU_PER_INCH * _TARGET_DPI))
        target_height = max(1, round(height / _EMU_PER_INCH * _TARGET_DPI))
        scale = min(1.0, max(target_width / source_width,
                             target_height / source_height))
        output_width = max(1, round(source_width * scale))
        output_height = max(1, round(source_height * scale))
        has_alpha = ("A" in oriented.getbands() or
                     (oriented.mode == "P" and "transparency" in oriented.info))
        fmt = (source.format or "").upper()
        if scale >= .999 and oriented is source and (
                (has_alpha and fmt == "PNG") or
                (not has_alpha and fmt == "JPEG")):
            return path, source_width, source_height
        if scale < .999:
            oriented = oriented.resize((output_width, output_height),
                                       Image.Resampling.LANCZOS)
        result = io.BytesIO()
        if has_alpha:
            oriented.convert("RGBA").save(result, format="PNG", optimize=True)
        else:
            oriented.convert("RGB").save(result, format="JPEG", quality=85,
                                          optimize=True)
        result.seek(0)
        return result, output_width, output_height
