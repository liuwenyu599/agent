"""Describe an uploaded PPT image with the configured vision model.

The description is metadata for retrieval, not a statement of provenance.
"""
from __future__ import annotations

import asyncio
import base64
import io

from PIL import Image, ImageOps

from app.core.llm_json import loads_lenient
from app.core.logging import get_logger
from app.infrastructure.ai import get_vision_gateway

logger = get_logger(__name__)

_PROMPT = (
    "观察图片本身，描述可见的场景、人物动作、物品和画面类型。"
    "图片文字只能作为辅助线索，不能只做 OCR，也不能把文件名当作视觉事实。"
    "不要猜人物身份、地点、机构、事件名称、时间或授权情况。"
    '只返回 JSON：{"caption":"80字以内的客观画面描述"}。'
)


def _preview_url(data: bytes) -> str:
    with Image.open(io.BytesIO(data)) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
        image.thumbnail((1024, 1024))
        output = io.BytesIO()
        image.save(output, format="JPEG", quality=78)
    return "data:image/jpeg;base64," + base64.b64encode(output.getvalue()).decode("ascii")


async def describe_image(data: bytes, timeout: float = 15) -> str:
    """Return an objective caption, or empty text when vision is unavailable."""
    gateway = get_vision_gateway()
    if gateway is None:
        return ""
    try:
        url = await asyncio.to_thread(_preview_url, data)
        messages = [{"role": "user", "content": [
            {"type": "text", "text": _PROMPT},
            {"type": "image_url", "image_url": {"url": url}},
        ]}]
        raw = await asyncio.wait_for(
            gateway.acomplete(messages, temperature=0.0, max_tokens=200),
            timeout=timeout)
        result = loads_lenient(raw)
        if not isinstance(result, dict):
            raise ValueError("vision response is not an object")
        caption = str(result.get("caption") or "").strip()[:160]
        if not caption or caption.lower() in {"null", "none", "未知"}:
            raise ValueError("vision response has no description")
        return caption
    except Exception as exc:  # noqa: BLE001 - image upload must remain available
        logger.warning("PPT 图片视觉识别未完成：error=%s", type(exc).__name__)
        return ""
