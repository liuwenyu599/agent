"""Describe an uploaded PPT image with the configured vision model.

The description is metadata for retrieval, not a statement of provenance.
"""
from __future__ import annotations

import asyncio
import base64
import io
import os
import time

from PIL import Image, ImageOps

from app.core.llm_json import loads_lenient
from app.core.logging import get_logger
from app.infrastructure.ai import get_vision_gateway

logger = get_logger(__name__)

# 35B 多模态首字延迟常在 10s 以上，早期固定 15s 让识图几乎必然超时；
# caption 为空又会被 _outline_images 过滤（自动配图只收录有描述的图片），
# 最终表现为「图片传上去了，生成时却从不被选用」。上限避免上传请求被
# 单个慢模型长期占住，可由 VISION_CAPTION_TIMEOUT 覆盖。
_CAPTION_TIMEOUT = float(os.getenv("VISION_CAPTION_TIMEOUT", "90"))

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


async def describe_image(data: bytes, timeout: float | None = None) -> str:
    """Return an objective caption, or empty text when vision is unavailable.

    ``timeout`` 只对单次调用生效；默认取 VISION_CAPTION_TIMEOUT（90s），
    而不是网关的 VISION_MODEL_TIMEOUT（180s，那是整轮对话的上限）。
    """
    gateway = get_vision_gateway()
    if gateway is None:
        logger.info("[PPT] 图片视觉识别跳过：未配置 VISION_MODEL_URL")
        return ""
    limit = float(timeout if timeout is not None else _CAPTION_TIMEOUT)
    started = time.monotonic()
    try:
        url = await asyncio.to_thread(_preview_url, data)
        messages = [{"role": "user", "content": [
            {"type": "text", "text": _PROMPT},
            {"type": "image_url", "image_url": {"url": url}},
        ]}]
        raw = await asyncio.wait_for(
            gateway.acomplete(messages, temperature=0.0, max_tokens=200),
            timeout=limit)
        result = loads_lenient(raw)
        if not isinstance(result, dict):
            raise ValueError("vision response is not an object")
        caption = str(result.get("caption") or "").strip()[:160]
        if not caption or caption.lower() in {"null", "none", "未知"}:
            raise ValueError("vision response has no description")
        logger.info("[PPT] 图片视觉识别完成：耗时=%.1fs 字数=%d",
                    time.monotonic() - started, len(caption))
        return caption
    except asyncio.TimeoutError:
        logger.warning("[PPT] 图片视觉识别超时：limit=%.0fs elapsed=%.1fs；"
                       "图片仍已入库，可补写说明后用于自动配图",
                       limit, time.monotonic() - started)
        return ""
    except Exception as exc:  # noqa: BLE001 - image upload must remain available
        logger.warning("[PPT] 图片视觉识别未完成：error=%s detail=%s",
                       type(exc).__name__, exc)
        return ""
