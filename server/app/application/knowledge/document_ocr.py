"""OCR / OFD text extraction helpers for knowledge ingestion.

Design goals:
- keep normal text-native documents on the deterministic local parser path;
- use the already configured vision model only when a PDF has too little text or
  the uploaded source is an image;
- support text-native OFD without an external converter by reading TextCode nodes
  from the OFD ZIP package;
- for scan-style OFD, OCR common embedded image resources when available.
"""
from __future__ import annotations

import base64
import mimetypes
import zipfile
from pathlib import Path
from typing import Callable, List, Optional, Sequence, Tuple
from xml.etree import ElementTree as ET

from app.application.ports import LLMGateway
from app.core.config import settings
from app.core.exceptions import AppError
from app.core.logging import get_logger

logger = get_logger(__name__)

_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}
_OFD_IMAGE_EXTS = _IMAGE_EXTS
_OCR_PROMPT = (
    "你正在执行司法行政知识库文档 OCR。请逐字识别图片中的中文、英文、数字、日期、文号和标点。"
    "保持原有阅读顺序与自然段，表格按行转写；不要概括、解释、改写、纠错或补全看不清的内容。"
    "无法辨认的局部用【无法辨认】标记。只输出识别后的正文。"
)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _data_url(data: bytes, mime: str) -> str:
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:{mime};base64,{encoded}"


class KnowledgeDocumentExtractor:
    def __init__(self, vision_gateway: Optional[LLMGateway] = None) -> None:
        if vision_gateway is None:
            # Lazy import avoids coupling the deterministic parser to AI bootstrap
            # and lets production automatically reuse the configured Qwen-VL gateway.
            from app.infrastructure.ai import get_vision_gateway
            vision_gateway = get_vision_gateway()
        self.vision_gateway = vision_gateway

    async def extract(
        self,
        file_path: Path,
        filename: str,
        plain_extractor: Callable[[Path, str], str],
    ) -> Tuple[str, str]:
        """Return ``(text, extraction_method)``.

        ``plain_extractor`` is the existing deterministic parser from
        :class:`DocumentService`; keeping it injected avoids duplicating DOCX/PDF/XLSX logic.
        """
        suffix = Path(filename or "").suffix.lower()

        if suffix == ".ofd":
            text = self._extract_ofd_text(file_path)
            if len(text.strip()) >= settings.OCR_MIN_TEXT_CHARS:
                return text, "ofd_xml"
            ocr_text = await self._ocr_ofd_images(file_path)
            if ocr_text.strip():
                return ocr_text, "ofd_vision_ocr"
            if text.strip():
                return text, "ofd_xml"
            raise AppError(400, self._ocr_unavailable_message("OFD"))

        if suffix in _IMAGE_EXTS:
            text = await self._ocr_image_files([file_path])
            if text.strip():
                return text, "vision_ocr"
            raise AppError(400, self._ocr_unavailable_message("图片"))

        if suffix == ".pdf":
            plain_text = ""
            try:
                plain_text = plain_extractor(file_path, filename)
            except AppError:
                # Existing parser intentionally rejects scan-only PDFs. OCR is the
                # recovery path, so defer the error until OCR has also been tried.
                plain_text = ""
            if len(plain_text.strip()) >= settings.OCR_MIN_TEXT_CHARS:
                return plain_text, "pdf_text"
            ocr_text = await self._ocr_pdf(file_path)
            if ocr_text.strip():
                return ocr_text, "pdf_vision_ocr"
            if plain_text.strip():
                return plain_text, "pdf_text"
            raise AppError(400, self._ocr_unavailable_message("PDF 扫描件"))

        return plain_extractor(file_path, filename), "native_text"

    def _ocr_unavailable_message(self, source: str) -> str:
        if not settings.OCR_ENABLED:
            return f"{source}未能解析出文字；服务器 OCR 功能当前未启用"
        if self.vision_gateway is None:
            return f"{source}未能解析出文字；服务器未配置视觉模型，无法执行 OCR"
        return f"{source}未能识别出有效文字内容"

    def _extract_ofd_text(self, file_path: Path) -> str:
        """Extract text from OFD TextCode nodes in package order.

        OFD files are ZIP containers. TextCode carries the visible string for
        text-native pages; namespace prefixes vary across producers, so matching is
        performed on the local XML tag name rather than a fixed namespace URI.
        """
        try:
            with zipfile.ZipFile(file_path) as archive:
                xml_names = sorted(
                    name for name in archive.namelist()
                    if name.lower().endswith(".xml") and not name.endswith("/")
                )
                blocks: List[str] = []
                for name in xml_names:
                    try:
                        root = ET.fromstring(archive.read(name))
                    except Exception:
                        continue
                    values: List[str] = []
                    for elem in root.iter():
                        if _local_name(elem.tag) != "TextCode":
                            continue
                        value = "".join(elem.itertext()).strip()
                        if value:
                            values.append(value)
                    if values:
                        blocks.append("\n".join(values))
                return "\n\n".join(blocks)
        except zipfile.BadZipFile as exc:
            raise AppError(400, "OFD 文件解析失败，文件可能已损坏") from exc
        except Exception as exc:
            logger.exception("OFD 文本解析失败")
            raise AppError(400, "OFD 文件解析失败") from exc

    async def _ocr_pdf(self, file_path: Path) -> str:
        if not self._ocr_ready():
            return ""
        try:
            import fitz  # PyMuPDF
        except ImportError:
            logger.error("OCR PDF 失败：未安装 PyMuPDF")
            return ""

        images: List[Tuple[bytes, str, str]] = []
        try:
            doc = fitz.open(str(file_path))
            page_count = min(len(doc), settings.OCR_MAX_PAGES)
            for index in range(page_count):
                page = doc.load_page(index)
                # 1.5x renders Chinese body text legibly without exploding memory.
                pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
                images.append((pix.tobytes("png"), "image/png", f"第{index + 1}页"))
            doc.close()
        except Exception:
            logger.exception("PDF 页面渲染失败")
            return ""
        return await self._ocr_images(images)

    async def _ocr_image_files(self, paths: Sequence[Path]) -> str:
        if not self._ocr_ready():
            return ""
        images: List[Tuple[bytes, str, str]] = []
        for path in paths[: settings.OCR_MAX_PAGES]:
            try:
                data = Path(path).read_bytes()
            except Exception:
                continue
            mime = mimetypes.guess_type(path.name)[0] or "image/png"
            images.append((data, mime, path.name))
        return await self._ocr_images(images)

    async def _ocr_ofd_images(self, file_path: Path) -> str:
        if not self._ocr_ready():
            return ""
        images: List[Tuple[bytes, str, str]] = []
        try:
            with zipfile.ZipFile(file_path) as archive:
                for name in sorted(archive.namelist()):
                    suffix = Path(name).suffix.lower()
                    if suffix not in _OFD_IMAGE_EXTS:
                        continue
                    try:
                        data = archive.read(name)
                    except Exception:
                        continue
                    if not data:
                        continue
                    mime = mimetypes.guess_type(name)[0] or "image/png"
                    images.append((data, mime, Path(name).name))
                    if len(images) >= settings.OCR_MAX_PAGES:
                        break
        except zipfile.BadZipFile:
            return ""
        except Exception:
            logger.exception("OFD 图片资源读取失败")
            return ""
        return await self._ocr_images(images)

    def _ocr_ready(self) -> bool:
        return bool(settings.OCR_ENABLED and self.vision_gateway is not None)

    async def _ocr_images(self, images: Sequence[Tuple[bytes, str, str]]) -> str:
        if not self._ocr_ready() or not images:
            return ""

        batch_size = max(1, min(settings.VISION_MAX_IMAGES, 4))
        outputs: List[str] = []
        for start in range(0, min(len(images), settings.OCR_MAX_PAGES), batch_size):
            batch = images[start:start + batch_size]
            content = [{"type": "text", "text": _OCR_PROMPT}]
            for data, mime, label in batch:
                content.append({"type": "text", "text": f"【{label}】"})
                content.append({
                    "type": "image_url",
                    "image_url": {"url": _data_url(data, mime)},
                })
            try:
                text = await self.vision_gateway.acomplete(
                    [{"role": "user", "content": content}],
                    temperature=0.0,
                    max_tokens=settings.OCR_MAX_TOKENS,
                )
            except Exception:
                logger.exception("视觉 OCR 调用失败")
                continue
            text = (text or "").strip()
            if text:
                outputs.append(text)
        return "\n\n".join(outputs)
