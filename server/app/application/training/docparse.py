
"""数据资产文档解析：从 docx / pdf / txt / md 提取正文、识别标题与文种。

全部本地解析，不调用任何云端服务；不复制原始文件，只读取内容。
"""
import os
from pathlib import Path
from typing import Any, Dict, List

SUPPORTED_DOC_EXT = {".docx", ".pdf", ".txt", ".md"}

# 党政机关公文文种（GB/T 9704-2012）
DOC_TYPES = [
    "决议", "决定", "命令", "公报", "公告", "通告",
    "意见", "通知", "通报", "报告", "请示", "批复",
    "议案", "函", "纪要",
]


def extract_text(file_path: str | Path) -> str:
    """按扩展名提取正文文本。"""
    file_path = Path(file_path)
    ext = file_path.suffix.lower()
    try:
        if ext == ".docx":
            return _extract_docx(file_path)
        if ext == ".pdf":
            return _extract_pdf(file_path)
        if ext in (".txt", ".md"):
            for enc in ("utf-8", "gbk", "gb18030"):
                try:
                    return file_path.read_text(encoding=enc)
                except UnicodeDecodeError:
                    continue
            return file_path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""
    return ""


def _extract_docx(path: Path) -> str:
    from docx import Document
    doc = Document(str(path))
    parts = [p.text for p in doc.paragraphs if p.text.strip()]
    for table in doc.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                parts.append("\t".join(cells))
    return "\n".join(parts)


def _extract_pdf(path: Path) -> str:
    import pdfplumber
    parts = []
    with pdfplumber.open(str(path)) as pdf:
        for page in pdf.pages:
            t = page.extract_text() or ""
            if t.strip():
                parts.append(t)
    return "\n".join(parts)


def detect_title(text: str, fallback: str = "") -> str:
    """识别标题：第一个长度适中、非句号收尾的行。"""
    for line in text.splitlines():
        line = line.strip().strip("\u3000")
        if not line:
            continue
        if 4 <= len(line) <= 60 and not line.endswith("。"):
            return line
        if len(line) > 4:
            return line[:60]
    return fallback


def detect_doc_type(title: str, text: str = "") -> str:
    """根据标题/开头识别文种。"""
    for dt in DOC_TYPES:
        if title.rstrip("。 ").endswith(dt):
            return dt
    head = title + "\n" + text[:300]
    for dt in DOC_TYPES:
        if dt in head:
            return dt
    return ""


def parse_document(file_path: str | Path) -> Dict[str, Any]:
    """解析单个文件，返回数据资产字段。"""
    path = Path(file_path)
    text = extract_text(path)
    title = detect_title(text, fallback=path.stem)
    return {
        "name": path.name,
        "file_path": str(path),
        "file_type": path.suffix.lower().lstrip("."),
        "title": title,
        "doc_type": detect_doc_type(title, text),
        "content": text,
        "char_count": len(text),
    }


def scan_directory(dir_path: str | Path, recursive: bool = True) -> List[Path]:
    """扫描目录中受支持的文件（只返回路径，不复制文件）。"""
    root = Path(dir_path)
    if not root.is_dir():
        return []
    pattern = "**/*" if recursive else "*"
    return sorted(
        p for p in root.glob(pattern)
        if p.is_file() and p.suffix.lower() in SUPPORTED_DOC_EXT
    )
