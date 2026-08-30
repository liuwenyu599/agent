"""文档入库服务（移植自旧 services/document_service.py）。

分块 → 建 Document/Chunk → 向量化。文件上传与网页导入共用同一流程。
"""
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.application.knowledge.chunkers import LegalChunker, OfficialChunker
from app.application.ports import Embedder, VectorStore
from app.core.config import settings
from app.core.logging import get_logger
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
            chunks = self.legal_chunker.chunk(text, doc_id)
        else:
            chunks = self.official_chunker.chunk(text, doc_id)

        # 初始状态：管理员/知识管理员直接发布；个人库直接发布；公共库待审核
        if user_role in ["knowledge_admin", "developer"]:
            initial_status = "published"
        else:
            kb = db.get(KnowledgeBaseModel, kb_id)
            if kb and kb.kb_type == "personal" and kb.owner_id == user_id:
                initial_status = "published"
            else:
                initial_status = "pending"

        doc = DocumentModel(
            id=doc_id,
            kb_id=kb_id,
            title=title,
            doc_type=final_doc_type,
            department=department,
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
            chunk_id = f"{doc_id}_{i}"  # 数据库 ID 和向量库一致
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

        # 向量化（仅对已发布文档）
        if initial_status == "published":
            self._vectorize(chunk_records)

        return {
            "doc_id": doc_id,
            "chunks": len(chunks),
            "status": initial_status,
            "message": "已直接发布" if initial_status == "published" else "已提交审核，等待管理员审批",
        }

    def _vectorize(self, chunk_records) -> None:
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
            } for i, c in enumerate(chunk_records)]
            self.vector_store.add_chunks(faiss_chunks)
            logger.info("[FAISS] 已索引 %d 个 chunk", len(faiss_chunks))
        except Exception as e:
            logger.error("向量化失败: %s", e)

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
        """按 source_url 查重（archived 的也算已存在）。"""
        from sqlalchemy import select
        try:
            return db.scalar(select(DocumentModel).where(
                DocumentModel.doc_metadata["source_url"].as_string() == source_url
            ))
        except Exception:
            docs = db.scalars(
                select(DocumentModel).where(DocumentModel.doc_metadata.isnot(None))
            ).all()
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

        result = self._persist_document(
            db=db, kb_id=kb_id,
            title=title if title else file.filename.replace(".docx", "").replace(".txt", "").replace(".pdf", "").replace(".md", ""),
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
            doc.reviewed_at = datetime.utcnow()
            doc.review_comment = comment or "审核通过"
            db.commit()

            chunks = db.scalars(
                select(ChunkModel).where(ChunkModel.doc_id == doc_id)
            ).all()
            self._vectorize([{
                "chunk_id": c.id, "doc_id": doc_id, "kb_id": doc.kb_id,
                "content": c.content, "title": c.title or "",
            } for c in chunks])

        elif action in ["reject", "rejected"]:
            doc.status = "rejected"
            doc.reviewed_by = reviewer_id
            doc.reviewed_at = datetime.utcnow()
            doc.review_comment = comment or "审核未通过"
            db.commit()

        return {"doc_id": doc_id, "status": doc.status, "message": "审核完成"}

    def extract_text(self, file_path: Path, filename: str) -> str:
        suffix = filename.lower().split('.')[-1]

        if suffix == 'docx':
            from docx import Document as DocxDocument
            doc = DocxDocument(str(file_path))
            paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
            return "\n\n".join(paragraphs)
        elif suffix == 'doc':
            try:
                import subprocess
                result = subprocess.run(['antiword', str(file_path)], capture_output=True, text=True)
                if result.returncode == 0:
                    return result.stdout
            except Exception:
                pass
            try:
                import docx2txt
                return docx2txt.process(str(file_path))
            except Exception:
                pass
            return "[.doc 格式解析失败，请转换为 .docx 后上传]"
        elif suffix == 'pdf':
            try:
                from PyPDF2 import PdfReader
                reader = PdfReader(str(file_path))
                text = ""
                for page in reader.pages:
                    text += page.extract_text() + "\n"
                return text
            except Exception as e:
                logger.error("PDF 解析失败: %s", e)
                return "[PDF 解析失败]"
        elif suffix in ['txt', 'md']:
            with open(file_path, 'r', encoding='utf-8') as f:
                return f.read()
        else:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    return f.read()
            except Exception:
                return ""
