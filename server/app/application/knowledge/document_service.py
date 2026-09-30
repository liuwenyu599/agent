"""文档入库服务（移植自旧 services/document_service.py）。

分块 → 建 Document/Chunk → 向量化。文件上传与网页导入共用同一流程。
分块时把文档标题传入，块内容自动带「《标题》」面包屑，检索可区分不同文档的雷同章节。
支持正文在线编辑：编辑后重新分块并重建该文档的向量索引。
文件解析支持 docx / doc / pdf / wps / rtf / txt / md / xlsx；解析失败明确报错，不入库垃圾内容。
"""
from app.core.timeutil import now_local
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.application.knowledge.chunkers import LegalChunker, OfficialChunker
from app.application.ports import Embedder, VectorStore
from app.application.knowledge.access import scope_of_doc, scope_of_kb
from app.core.config import settings
from app.core.exceptions import AppError
from app.core.logging import get_logger
from app.domain.identity.authorization import is_privileged
from app.domain.organization.departments import SCOPE_GLOBAL
from app.infrastructure.database.models.knowledge import ChunkModel, DocumentModel, KnowledgeBaseModel

logger = get_logger(__name__)


def new_doc_id() -> str:
    return str(uuid.uuid4())[:8]


class DocumentService:
    def __init__(self, embedder: Embedder = None, vector_store: VectorStore = None) -> None:
        self.embedder = embedder
        self.vector_store = vector_store
        self.legal_chunker = LegalChunker()
        self.official_chunker = OfficialChunker()

    def _detect_doc_type(self, text: str) -> str:
        sample = text[:10000]
        if re.search(r'第[一二三四五六七八九十百千零\d]+条[、\.\s]', sample):
            if any(k in sample for k in ["办法", "规定", "条例", "细则", "章程", "通则", "规则"]):
                return "法规"
        if any(k in sample for k in ["笔录", "告知书", "决定书", "执法", "行政处罚", "责令改正"]):
            return "执法文书"
        official_keywords = ["通知", "通报", "报告", "请示", "批复", "函", "纪要", "决定", "意见",
                             "工作总结", "工作计划", "实施方案", "工作要点", "年度总结", "述职报告",
                             "会议纪要", "会议记录", "领导讲话", "调研报告", "情况汇报"]
        if any(k in sample for k in official_keywords):
            return "公文"
        return "公文"

    # ========== 公共入库流程（文件 / 网页共用） ==========

    def _persist_document(self, db: Session, kb_id: str, title: str, text: str,
                          user_id: str, user_role: str,
                          doc_type: Optional[str] = None,
                          file_path: Optional[str] = None,
                          file_size: int = 0,
                          doc_metadata: Optional[dict] = None,
                          department: Optional[str] = None,
                          doc_number: Optional[str] = None) -> Dict:
        doc_id = new_doc_id()

        auto_doc_type = self._detect_doc_type(text)
        final_doc_type = doc_type if doc_type else auto_doc_type

        if final_doc_type == "法规":
            chunks = self.legal_chunker.chunk(text, doc_id, title=title)
        else:
            chunks = self.official_chunker.chunk(text, doc_id, title=title)

        kb = db.get(KnowledgeBaseModel, kb_id)
        if is_privileged(user_role):
            initial_status = "published"
        else:
            if kb and kb.kb_type == "personal" and kb.owner_id == user_id:
                initial_status = "published"
            else:
                initial_status = "pending"

        scope = scope_of_kb(kb)
        dept_code = getattr(kb, "department_code", "") or ""

        doc = DocumentModel(
            id=doc_id,
            kb_id=kb_id,
            title=title,
            doc_type=final_doc_type,
            department=department,
            department_code=dept_code,
            doc_number=doc_number,
            file_path=file_path,
            file_size=file_size,
            status=initial_status,
            uploaded_by=user_id,
            created_by=user_id,
            content=text[:500000],
            doc_metadata=doc_metadata or {},
        )
        db.add(doc)

        chunk_records = []
        for i, chunk_data in enumerate(chunks):
            chunk_id = f"{doc_id}_{i}"
            chunk = ChunkModel(
                id=chunk_id,
                doc_id=doc_id,
                chunk_index=chunk_data["chunk_index"],
                chunk_type=chunk_data["chunk_type"],
                title=chunk_data.get("title", ""),
                content=chunk_data["content"],
                char_count=chunk_data["metadata"].get("char_count", 0),
                word_count=chunk_data["metadata"].get("word_count", 0),
                chunk_metadata=chunk_data["metadata"],
            )
            db.add(chunk)
            chunk_records.append({
                "chunk_id": chunk_id,
                "doc_id": doc_id,
                "kb_id": kb_id,
                "content": chunk_data["content"],
                "title": chunk_data.get("title", ""),
            })

        db.commit()

        if initial_status == "published":
            self._vectorize(chunk_records, scope=scope)

        return {
            "doc_id": doc_id,
            "chunks": len(chunks),
            "status": initial_status,
            "message": "已直接发布" if initial_status == "published" else "已提交审核，等待管理员审批",
        }

    def _vectorize(self, chunk_records, scope: str = SCOPE_GLOBAL) -> None:
        if not (self.embedder and self.vector_store and chunk_records):
            return
        try:
            texts = [c["content"] for c in chunk_records]
            vectors = self.embedder.encode(texts)
            faiss_chunks = [{
                "chunk_id": c["chunk_id"],
                "doc_id": c["doc_id"],
                "kb_id": c["kb_id"],
                "embedding": vectors[i],
                "content": c["content"],
                "title": c["title"],
                "scope": scope,
            } for i, c in enumerate(chunk_records)]
            self.vector_store.add_chunks(faiss_chunks)
            logger.info("[FAISS] 已索引 %d 个 chunk", len(faiss_chunks))
        except Exception as e:
            logger.error("向量化失败: %s", e)

    # ========== 正文在线编辑 ==========

    def update_content(self, db: Session, doc_id: str, text: str) -> Dict:
        doc = db.get(DocumentModel, doc_id)
        if not doc:
            return {"doc_id": doc_id, "chunks": 0, "message": "文档不存在"}

        text = text or ""
        doc.content = text[:500000]
        db.query(ChunkModel).filter(ChunkModel.doc_id == doc_id).delete(synchronize_session=False)
        if doc.doc_type == "法规":
            chunks = self.legal_chunker.chunk(text, doc_id, title=doc.title or "")
        else:
            chunks = self.official_chunker.chunk(text, doc_id, title=doc.title or "")

        records = []
        for i, chunk_data in enumerate(chunks):
            chunk_id = f"{doc_id}_{i}"
            db.add(ChunkModel(
                id=chunk_id,
                doc_id=doc_id,
                chunk_index=chunk_data["chunk_index"],
                chunk_type=chunk_data["chunk_type"],
                title=chunk_data.get("title", ""),
                content=chunk_data["content"],
                char_count=chunk_data["metadata"].get("char_count", 0),
                word_count=chunk_data["metadata"].get("word_count", 0),
                chunk_metadata=chunk_data["metadata"],
            ))
            records.append({
                "chunk_id": chunk_id,
                "doc_id": doc_id,
                "kb_id": doc.kb_id,
                "content": chunk_data["content"],
                "title": chunk_data.get("title", ""),
            })
        db.commit()

        if self.vector_store:
            try:
                self.vector_store.delete_by_document(doc_id)
            except Exception as e:
                logger.error("[FAISS] 删除旧向量失败: %s", e)
        if doc.status == "published":
            self._vectorize(records, scope=scope_of_doc(db, doc))

        return {"doc_id": doc_id, "chunks": len(chunks), "message": "正文已更新，检索内容已同步"}

    # ========== 网页入库 ==========

    def process_web_document(self, db: Session, kb_id: str, user_id: str, user_role: str,
                             url: str, fetched: Dict,
                             title: Optional[str] = None,
                             source_name: Optional[str] = None,
                             publish_time: Optional[str] = None) -> Dict:
        text = (fetched.get("content") or "").strip()
        final_title = (title or fetched.get("title") or url).strip()[:500]
        header = f"【来源网页】{url}"
        src = source_name or fetched.get("source_name") or ""
        if src:
            header += f"（{src}）"
        full_text = header + "\n\n" + text
        meta = {
            "source_type": "web",
            "source_url": url,
            "source_name": src,
            "publish_time": publish_time or fetched.get("publish_time") or "",
        }
        result = self._persist_document(
            db=db, kb_id=kb_id, title=final_title, text=full_text,
            user_id=user_id, user_role=user_role,
            doc_type="网页", file_path=None, file_size=len(text),
            doc_metadata=meta,
        )
        result["title"] = final_title
        result["source_url"] = url
        return result

    def find_by_source_url(self, db: Session, source_url: str) -> Optional[DocumentModel]:
        try:
            return db.scalar(select(DocumentModel).where(
                DocumentModel.doc_metadata["source_url"].as_string() == source_url
            ))
        except Exception:
            docs = db.scalars(select(DocumentModel).where(DocumentModel.doc_metadata.isnot(None))).all()
            for d in docs:
                if (d.doc_metadata or {}).get("source_url") == source_url:
                    return d
            return None

    # ========== 文件上传 ==========

    async def process_upload(self, file, kb_id: str, user_id: str, user_role: str,
                             db: Session, title=None, doc_type=None,
                             department=None, doc_number=None) -> Dict:
        doc_id = new_doc_id()
        tmp_dir = settings.DATA_DIR / "tmp" / "knowledge-upload"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = tmp_dir / f"{doc_id}_{file.filename}"
        content = await file.read()
        with open(tmp_path, "wb") as f:
            f.write(content)

        text = self.extract_text(tmp_path, file.filename)
        if not text.strip():
            raise AppError(400, "未能从文件中解析出文字内容（扫描件 PDF 请先做 OCR 再上传）")

        stem = Path(file.filename or "").stem.strip() or "未命名文档"
        result = self._persist_document(
            db=db, kb_id=kb_id,
            title=title if title else stem,
            text=text, user_id=user_id, user_role=user_role,
            doc_type=doc_type, file_path=str(tmp_path), file_size=len(content),
            doc_metadata={"source_type": "file", "original_filename": file.filename},
            department=department, doc_number=doc_number,
        )
        return result

    def review_document(self, doc_id: str, action: str, comment: str,
                        reviewer_id: str, db: Session) -> Dict:
        doc = db.get(DocumentModel, doc_id)
        if not doc:
            return {"error": "Document not found"}

        if action in ["approve", "approved"]:
            doc.status = "published"
            doc.reviewed_by = reviewer_id
            doc.reviewed_at = now_local()
            doc.review_comment = comment or "审核通过"
            db.commit()
            doc_scope = scope_of_doc(db, doc)
            chunks = db.scalars(select(ChunkModel).where(ChunkModel.doc_id == doc_id)).all()
            self._vectorize([{
                "chunk_id": c.id, "doc_id": doc_id, "kb_id": doc.kb_id,
                "content": c.content, "title": c.title or "",
            } for c in chunks], scope=doc_scope)
        elif action in ["reject", "rejected"]:
            doc.status = "rejected"
            doc.reviewed_by = reviewer_id
            doc.reviewed_at = now_local()
            doc.review_comment = comment or "审核未通过"
            db.commit()

        return {"doc_id": doc_id, "status": doc.status, "message": "审核完成"}

    # ========== 文件解析 ==========

    _SOFFICE_EXTS = ("doc", "wps", "rtf")

    def extract_text(self, file_path: Path, filename: str) -> str:
        """提取文件纯文本。支持 docx / doc / pdf / wps / rtf / txt / md / xlsx。"""
        suffix = filename.lower().rsplit('.', 1)[-1] if '.' in (filename or "") else ""

        if suffix == 'docx':
            try:
                from docx import Document as DocxDocument
                doc = DocxDocument(str(file_path))
                paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
                text = "\n\n".join(paragraphs)
            except AppError:
                raise
            except Exception as e:
                logger.error("DOCX 解析失败: %s", e)
                raise AppError(400, "docx 文件解析失败，文件可能已损坏")
            if not text.strip():
                raise AppError(400, "docx 文件中没有可读取的文字内容")
            return text

        if suffix in self._SOFFICE_EXTS:
            text = self._extract_via_soffice(file_path)
            if not text.strip() and suffix == 'doc':
                text = self._extract_doc_legacy(file_path)
            if not text.strip():
                raise AppError(400, f".{suffix} 文件解析失败，请另存为 .docx 后上传")
            return text

        if suffix == 'pdf':
            text = self._extract_pdf(file_path)
            if not text.strip():
                raise AppError(400, "PDF 解析失败或不含可复制文字（扫描件请先做 OCR 再上传）")
            return text

        if suffix == 'xlsx':
            try:
                from openpyxl import load_workbook
                wb = load_workbook(str(file_path), read_only=True, data_only=True)
                parts = []
                for ws in wb.worksheets:
                    rows = []
                    for row in ws.iter_rows(values_only=True):
                        values = ["" if v is None else str(v).strip() for v in row]
                        while values and not values[-1]:
                            values.pop()
                        if any(values):
                            rows.append("\t".join(values))
                    if rows:
                        parts.append(f"【工作表：{ws.title}】\n" + "\n".join(rows))
                text = "\n\n".join(parts)
            except Exception as e:
                logger.error("XLSX 解析失败: %s", e)
                raise AppError(400, "xlsx 文件解析失败，文件可能已损坏或加密")
            if not text.strip():
                raise AppError(400, "xlsx 文件中没有可读取的单元格内容")
            return text

        if suffix in ('txt', 'md'):
            return self._read_text_file(file_path)

        raise AppError(
            400, f"暂不支持 .{suffix or '未知'} 格式的文件，"
                 "请上传 doc / docx / pdf / wps / rtf / txt / md / xlsx 格式的文档")

    @staticmethod
    def _read_text_file(file_path: Path) -> str:
        """文本文件：UTF-8 优先，兼容 Windows 中文环境常见的 GBK 编码。"""
        for enc in ("utf-8", "gb18030"):
            try:
                return Path(file_path).read_text(encoding=enc)
            except UnicodeDecodeError:
                continue
            except Exception:
                break
        return ""

    @staticmethod
    def _extract_pdf(file_path: Path) -> str:
        try:
            from pypdf import PdfReader
            reader = PdfReader(str(file_path))
            return "\n\n".join((page.extract_text() or "").strip() for page in reader.pages).strip()
        except Exception as e:
            logger.error("PDF 解析失败: %s", e)
            return ""

    @staticmethod
    def _extract_via_soffice(file_path: Path) -> str:
        import shutil
        import subprocess
        import tempfile
        soffice = shutil.which("libreoffice") or shutil.which("soffice")
        if not soffice:
            return ""
        with tempfile.TemporaryDirectory() as td:
            try:
                subprocess.run([
                    soffice, "--headless", "--convert-to", "txt:Text",
                    "--outdir", td, str(file_path)
                ], check=False, timeout=60, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                txt = Path(td) / (Path(file_path).stem + ".txt")
                if txt.exists():
                    return DocumentService._read_text_file(txt)
            except Exception as e:
                logger.warning("LibreOffice 文本转换失败: %s", e)
        return ""

    @staticmethod
    def _extract_doc_legacy(file_path: Path) -> str:
        try:
            import subprocess
            result = subprocess.run(["antiword", str(file_path)], check=False, timeout=30,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            for enc in ("utf-8", "gb18030"):
                try:
                    return result.stdout.decode(enc)
                except UnicodeDecodeError:
                    continue
        except Exception:
            pass
        return ""
