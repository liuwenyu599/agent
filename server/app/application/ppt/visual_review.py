"""Review actual rendered PPT pages with the configured local vision model."""
from __future__ import annotations

import base64
import asyncio
import io
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from pptx import Presentation

from app.core.config import settings
from app.core.llm_json import loads_lenient
from app.core.logging import get_logger

logger = get_logger(__name__)

_CODES = {"visual_overlap", "clipped_text", "unreadable_text", "poor_contrast",
          "unbalanced_layout", "irrelevant_image"}
_PROMPT = (
    "你是演示文稿排版复检员。下面按顺序给出实际渲染页面截图。只判断肉眼可见的"
    "遮挡、文字裁切、字太小难读、对比度不足、版面明显失衡、配图与主题明显无关。"
    "不要评论文案事实、政治口径或未显示的元素；不要把正常留白报成问题。"
    "只返回 JSON：{\"issues\":[{\"page\":页码,\"code\":问题代码,\"message\":简短中文说明}]}。"
    "问题代码只能是 visual_overlap/clipped_text/unreadable_text/poor_contrast/"
    "unbalanced_layout/irrelevant_image。无问题返回空数组。"
)


def render_slide_images(data: bytes) -> list[bytes]:
    """Render to PNG in a private temporary directory; never cache user pages globally."""
    soffice, pdftoppm = shutil.which("soffice"), shutil.which("pdftoppm")
    if not soffice or not pdftoppm:
        raise RuntimeError("服务器缺少 PPT 页面渲染组件")
    temp_root = settings.DATA_DIR / "ppt" / "tmp"
    temp_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ppt-vision-", dir=temp_root) as tmp:
        root = Path(tmp)
        source = root / "slides.pptx"
        source.write_bytes(data)
        profile = root / "lo-profile"
        subprocess.run([soffice, f"-env:UserInstallation={profile.as_uri()}",
                        "--headless", "--convert-to", "pdf",
                        "--outdir", str(root), str(source)],
                       timeout=120, capture_output=True, check=True)
        pdf = root / "slides.pdf"
        if not pdf.is_file():
            raise RuntimeError("演示文稿未能渲染为页面")
        subprocess.run([pdftoppm, "-png", "-r", "72", str(pdf), str(root / "pg")],
                       timeout=120, capture_output=True, check=True)
        pages = list(root.glob("pg-*.png"))
        pages.sort(key=lambda path: int(path.stem.split("-")[-1]))
        if len(pages) != len(Presentation(io.BytesIO(data)).slides):
            raise RuntimeError("演示文稿页面截图数量不完整")
        return [page.read_bytes() for page in pages]


def review_rendered_pages(data: bytes, gateway: Any, batch_size: int = 4) -> dict:
    """Return validated page findings; model output cannot alter the document."""
    if gateway is None:
        return {"status": "unavailable", "pages_checked": 0, "issues": [],
                "reason": "未配置视觉模型"}
    try:
        pages = render_slide_images(data)
    except Exception as exc:  # noqa: BLE001 - visual QA must never block export
        logger.warning("PPT 页面视觉复检未运行：%s", type(exc).__name__)
        return {"status": "unavailable", "pages_checked": 0, "issues": [],
                "reason": "页面渲染不可用"}

    issues: list[dict] = []
    checked = 0
    batch_size = max(1, min(batch_size, 4))
    deadline = time.monotonic() + 90
    for start in range(0, len(pages), batch_size):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        batch = pages[start:start + batch_size]
        content: list[dict] = [{"type": "text", "text": _PROMPT +
                               f" 本批页面编号为 {list(range(start + 1, start + len(batch) + 1))}。"}]
        for page_no, png in enumerate(batch, start + 1):
            content.append({"type": "text", "text": f"第 {page_no} 页"})
            content.append({"type": "image_url", "image_url": {
                "url": "data:image/png;base64," + base64.b64encode(png).decode("ascii")}})
        try:
            messages = [{"role": "user", "content": content}]
            if hasattr(gateway, "acomplete"):
                raw = asyncio.run(asyncio.wait_for(
                    gateway.acomplete(messages, temperature=0.0, max_tokens=700),
                    timeout=min(30, remaining)))
            else:
                raw = gateway.complete(messages, temperature=0.0, max_tokens=700)
            parsed = loads_lenient(raw)
            if not isinstance(parsed, dict) or not isinstance(parsed.get("issues"), list):
                raise ValueError("视觉模型返回格式不正确")
        except Exception as exc:  # noqa: BLE001 - visual QA must not block PPT export
            logger.warning("PPT 页面视觉复检失败：batch=%d error=%s",
                           start // batch_size + 1, type(exc).__name__)
            continue
        checked += len(batch)
        for item in parsed["issues"][:12]:
            if not isinstance(item, dict):
                continue
            try:
                page = int(item.get("page"))
            except (TypeError, ValueError):
                continue
            code = str(item.get("code") or "")
            message = str(item.get("message") or "").strip()[:120]
            if start < page <= start + len(batch) and code in _CODES and message:
                issues.append({"page": page, "code": code, "severity": "warning",
                               "message": message})
    status = ("unavailable" if not checked else "partial" if checked < len(pages)
              else "review" if issues else "passed")
    return {"status": status,
            "pages_checked": checked, "issues": issues,
            "reason": "" if checked == len(pages) else "部分页面未能完成视觉复检"}
