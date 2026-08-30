"""PDF 解析器（移植自旧 rag/parser/pdf_parser.py）。

逐页正文（带【第N页】标记）+ URI 超链接 + 裸 URL 兜底 + 表格 + 扫描件 OCR 回退。
优先 PyMuPDF（fitz），未安装时回退 PyPDF2（仅文字）。
"""
import re
from pathlib import Path
from typing import Dict, List, Optional

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_URL_RE = re.compile(r'https?://[^\s<>"\'）)】\]]+')

# 整册平均提取字符数低于该值视为扫描件（无文本层）
_SCANNED_CHAR_THRESHOLD = 20


def _ocr_pages(doc) -> Optional[List[str]]:
    """扫描件逐页 OCR。环境不满足时返回 None。"""
    try:
        if not settings.OCR_ENABLED:
            return None
        import io

        import pytesseract
        from PIL import Image

        pages = []
        for pno in range(doc.page_count):
            pix = doc[pno].get_pixmap(dpi=200)
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            text = pytesseract.image_to_string(img, lang=settings.OCR_LANG)
            pages.append(f"【第{pno + 1}页】\n{text.strip()}")
        return pages
    except Exception as e:
        logger.warning("[PdfParser] OCR 回退失败（扫描件将无法提取文字）: %s", e)
        return None


def _extract_with_pymupdf(file_path: Path) -> Dict:
    import fitz  # PyMuPDF

    doc = fitz.open(str(file_path))
    page_count = doc.page_count

    pages_text: List[str] = []
    links: List[Dict] = []
    tables: List[Dict] = []
    total_chars = 0

    for pno in range(page_count):
        page = doc[pno]
        text = (page.get_text("text") or "").strip()
        total_chars += len(text)

        for lk in page.get_links():
            uri = lk.get("uri")
            if uri:
                links.append({"url": uri, "page": pno + 1, "source": "annotation"})

        try:
            for tb in page.find_tables().tables:
                rows = [[(c or "").strip() for c in row] for row in tb.extract()]
                if rows:
                    tables.append({"page": pno + 1, "rows": rows})
        except Exception:
            pass  # 旧版 PyMuPDF 无 find_tables

        pages_text.append(f"【第{pno + 1}页】\n{text}")

    is_scanned = (total_chars / max(page_count, 1)) < _SCANNED_CHAR_THRESHOLD
    ocr_used = False

    if is_scanned:
        ocr_pages = _ocr_pages(doc)
        if ocr_pages is not None:
            pages_text = ocr_pages
            ocr_used = True

    full_text = "\n\n".join(pages_text)
    seen = {l["url"] for l in links}
    for pno, ptext in enumerate(pages_text):
        for u in _URL_RE.findall(ptext):
            u = u.rstrip("。，、；")
            if u not in seen:
                seen.add(u)
                links.append({"url": u, "page": pno + 1, "source": "text"})

    doc.close()
    return {
        "text": full_text,
        "links": links,
        "tables": tables,
        "page_count": page_count,
        "is_scanned": is_scanned,
        "ocr_used": ocr_used,
    }


def _extract_with_pypdf2(file_path: Path) -> Dict:
    """PyMuPDF 不可用时的兜底：仅文字，无链接注释/表格/OCR。"""
    from PyPDF2 import PdfReader
    reader = PdfReader(str(file_path))
    pages = []
    for i, page in enumerate(reader.pages):
        try:
            pages.append(f"【第{i + 1}页】\n{(page.extract_text() or '').strip()}")
        except Exception:
            pages.append(f"【第{i + 1}页】\n")
    full_text = "\n\n".join(pages)
    links = [{"url": u.rstrip("。，、；"), "page": None, "source": "text"}
             for u in dict.fromkeys(_URL_RE.findall(full_text))]
    return {
        "text": full_text,
        "links": links,
        "tables": [],
        "page_count": len(reader.pages),
        "is_scanned": len(full_text.strip()) < _SCANNED_CHAR_THRESHOLD,
        "ocr_used": False,
    }


def extract_pdf(file_path) -> Dict:
    """统一入口：返回 {text, links, tables, page_count, is_scanned, ocr_used}。"""
    file_path = Path(file_path)
    try:
        return _extract_with_pymupdf(file_path)
    except ImportError:
        logger.warning("[PdfParser] 未安装 PyMuPDF，回退 PyPDF2（无链接注释/表格/OCR）")
        try:
            return _extract_with_pypdf2(file_path)
        except Exception as e:
            logger.error("[PdfParser] PyPDF2 解析失败: %s", e)
            return {"text": "", "links": [], "tables": [], "page_count": 0,
                    "is_scanned": False, "ocr_used": False}
    except Exception as e:
        logger.error("[PdfParser] 解析失败: %s", e)
        return {"text": "", "links": [], "tables": [], "page_count": 0,
                "is_scanned": False, "ocr_used": False}
