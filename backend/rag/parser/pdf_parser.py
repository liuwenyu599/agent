"""PDF 解析器（文本 + 超链接 + 表格 + 扫描件 OCR 回退）。

设计目标（对应对话附件链路的实际需求）：
1. 文本型 PDF：逐页提取正文，保留页码标记（如"【第3页】"），便于 AI 引用来源位置；
2. 超链接：提取 PDF 的 URI 链接注释（page.get_links()），
   同时对正文做 URL 正则兜底（很多公众号链接是直接印在文字里的裸 URL）；
3. 表格：使用 PyMuPDF 的 find_tables() 提取为二维数组；
4. 扫描件检测：当整册提取字符数过少时判定为扫描件，
   在 OCR_ENABLED 开启且系统装有 tesseract 时逐页 OCR 回退；
5. 依赖：优先 PyMuPDF（pip install pymupdf）；未安装时回退 PyPDF2（仅文字，无链接/表格）。

解析结果同时提供两种形态：
- PdfParser.parse()  -> ParsedDocument（接入现有 rag/parser 体系）
- extract_pdf()      -> dict（供 AttachmentService 等对话附件场景直接调用）
"""

import re
from pathlib import Path
from typing import Dict, List

from .base import BaseParser, ParsedDocument

# 裸 URL 兜底（覆盖 http/https，含微信 mp.weixin.qq.com 等）
_URL_RE = re.compile(r'https?://[^\s<>"\'）)】\]]+')

# 判定为扫描件的阈值：整册平均提取字符数低于该值，视为无文本层
_SCANNED_CHAR_THRESHOLD = 20


def _extract_with_pymupdf(file_path: Path) -> Dict:
    import fitz  # PyMuPDF

    doc = fitz.open(str(file_path))
    page_count = doc.page_count

    pages_text: List[str] = []      # 每页正文（带页码标记）
    links: List[Dict] = []          # [{url, page, source}]
    tables: List[Dict] = []         # [{page, rows}]
    total_chars = 0

    for pno in range(page_count):
        page = doc[pno]
        text = page.get_text("text") or ""
        text = text.strip()
        total_chars += len(text)

        # 1) URI 链接注释
        for lk in page.get_links():
            uri = lk.get("uri")
            if uri:
                links.append({"url": uri, "page": pno + 1, "source": "annotation"})

        # 2) 表格
        try:
            for tb in page.find_tables().tables:
                rows = [[(c or "").strip() for c in row] for row in tb.extract()]
                if rows:
                    tables.append({"page": pno + 1, "rows": rows})
        except Exception:
            pass  # 旧版 PyMuPDF 无 find_tables，忽略

        pages_text.append(f"【第{pno + 1}页】\n{text}")

    is_scanned = (total_chars / max(page_count, 1)) < _SCANNED_CHAR_THRESHOLD
    ocr_used = False

    # 3) 扫描件 OCR 回退
    if is_scanned:
        ocr_pages = _ocr_pages(doc)
        if ocr_pages is not None:
            pages_text = ocr_pages
            ocr_used = True
            is_scanned = True

    # 4) 裸 URL 兜底（正文里印出来的链接）
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


def _ocr_pages(doc) -> List[str] | None:
    """扫描件逐页 OCR。环境不满足（未装 pytesseract/tesseract）时返回 None。"""
    try:
        from backend.config.settings import OCR_ENABLED, OCR_LANG
        if not OCR_ENABLED:
            return None
        import pytesseract

        pages = []
        for pno in range(doc.page_count):
            pix = doc[pno].get_pixmap(dpi=200)
            img_bytes = pix.tobytes("png")
            import io
            from PIL import Image
            img = Image.open(io.BytesIO(img_bytes))
            text = pytesseract.image_to_string(img, lang=OCR_LANG)
            pages.append(f"【第{pno + 1}页】\n{text.strip()}")
        return pages
    except Exception as e:
        print(f"[PdfParser] OCR 回退失败（扫描件将无法提取文字）: {e}")
        return None


def _extract_with_pypdf2(file_path: Path) -> Dict:
    """PyMuPDF 不可用时的兜底：仅文字，无链接/表格/OCR。"""
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
    """对外统一入口：返回 {text, links, tables, page_count, is_scanned, ocr_used}。

    AttachmentService 可直接调用本函数，把 text + 链接清单写入 text_content。
    """
    file_path = Path(file_path)
    try:
        return _extract_with_pymupdf(file_path)
    except ImportError:
        print("[PdfParser] 未安装 PyMuPDF，回退 PyPDF2（无链接注释/表格/OCR）。"
              "建议：pip install pymupdf")
        try:
            return _extract_with_pypdf2(file_path)
        except Exception as e:
            print(f"[PdfParser] PyPDF2 解析失败: {e}")
            return {"text": "", "links": [], "tables": [], "page_count": 0,
                    "is_scanned": False, "ocr_used": False}
    except Exception as e:
        print(f"[PdfParser] 解析失败: {e}")
        return {"text": "", "links": [], "tables": [], "page_count": 0,
                "is_scanned": False, "ocr_used": False}


class PdfParser(BaseParser):
    """接入 rag/parser 体系的 PDF 解析器"""

    def supported_extensions(self) -> List[str]:
        return [".pdf"]

    def parse(self, file_path: Path) -> ParsedDocument:
        result = extract_pdf(file_path)

        parsed = ParsedDocument()
        parsed.content = result["text"]
        parsed.metadata = {
            "page_count": result["page_count"],
            "is_scanned": result["is_scanned"],
            "ocr_used": result["ocr_used"],
            "links": result["links"],
        }
        parsed.sections = [
            {"text": block, "style": "page", "level": 0}
            for block in result["text"].split("\n\n") if block.strip()
        ]
        parsed.tables = [t["rows"] for t in result["tables"]]
        # 标题：取第一页第一行非空文本
        first_lines = [l.strip() for l in result["text"].splitlines() if l.strip()]
        parsed.title = first_lines[1] if len(first_lines) > 1 else (
            first_lines[0] if first_lines else "未命名")
        return parsed
