"""Hardened production wrapper for knowledge document ingestion.

Adds delivery guarantees without rewriting the legacy parser/chunker stack:
- streamed, size-bounded uploads with trusted server-side paths;
- OCR/OFD extraction for scan-style knowledge material;
- visible vector-indexing status stored in document metadata;
- explicit reindex retry for already-persisted published documents.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.application.knowledge.access import scope_of_doc
from app.application.knowledge.document_ocr import KnowledgeDocumentExtractor
from app.application.knowledge.document_service import DocumentService, new_doc_id
from app.application.knowledge.upload_security import safe_client_filename, stream_upload_to_file
from app.core.config import settings
from app.core.exceptions import AppError
from app.core.logging import get_logger
from app.domain.organization.departments import SCOPE_GLOBAL
from app.infrastructure.database.models.knowledge import ChunkModel, DocumentModel

logger = get_logger(__name__)


class HardenedDocumentService(DocumentService):
    def __init__(self, embedder=None, vector_store=None, vision_gateway=None) -> None:
        super().__init__(embedder=embedder, vector_store=vector_store)
        self.extractor = KnowledgeDocumentExtractor(vision_gateway=vision_gateway)
        self._last_vector_error = ""
        self._last_vector_count = 0

    def _vectorize(self, chunk_records, scope: str = SCOPE_GLOBAL) -> int:
        self._last_vector_error = ""
        self._last_vector_count = 0
        if not chunk_records:
            return 0
        if not self.embedder or not self.vector_store:
            self._last_vector_error = "向量服务未配置"
            logger.error("[RAG] 向量化失败: %s", self._last_vector_error)
            return 0
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
            self._last_vector_count = len(faiss_chunks)
            logger.info("[FAISS] 已索引 %d 个 chunk", self._last_vector_count)
            return self._last_vector_count
        except Exception as exc:
            self._last_vector_error = str(exc)[:1000]
            logger.exception("向量化失败")
            return 0

    @staticmethod
    def _set_index_metadata(db: Session, doc: DocumentModel, status: str,
                            error: str = "", count: int = 0) -> None:
        meta = dict(doc.doc_metadata or {})
        meta["indexing_status"] = status
        meta["indexed_chunks"] = int(count or 0)
        if error:
            meta["indexing_error"] = error[:1000]
        else:
            meta.pop("indexing_error", None)
        doc.doc_metadata = meta
        db.commit()

    def _persist_document(self, db: Session, kb_id: str, title: str, text: str,
                          user_id: str, user_role: str,
                          doc_type: Optional[str] = None,
                          file_path: Optional[str] = None,
                          file_size: int = 0,
                          doc_metadata: Optional[dict] = None,
                          department: Optional[str] = None,
                          doc_number: Optional[str] = None) -> Dict:
        self._last_vector_error = ""
        self._last_vector_count = 0
        result = super()._persist_document(
            db=db, kb_id=kb_id, title=title, text=text,
            user_id=user_id, user_role=user_role, doc_type=doc_type,
            file_path=file_path, file_size=file_size, doc_metadata=doc_metadata,
            department=department, doc_number=doc_number,
        )
        doc = db.get(DocumentModel, result["doc_id"])
        if doc is not None:
            if result.get("status") == "published":
                index_status = "failed" if self._last_vector_error else "indexed"
                self._set_index_metadata(
                    db, doc, index_status, self._last_vector_error, self._last_vector_count
                )
            else:
                index_status = "pending_review"
                self._set_index_metadata(db, doc, index_status)
            result["indexing_status"] = index_status
            if self._last_vector_error:
                result["indexing_error"] = self._last_vector_error
                result["message"] += "；正文已保存，但向量索引失败，可稍后重试"
        return result

    async def process_upload(self, file, kb_id: str, user_id: str, user_role: str,
                             db: Session, title=None, doc_type=None,
                             department=None, doc_number=None) -> Dict:
        original_name, suffix = safe_client_filename(
            getattr(file, "filename", ""), settings.SUPPORTED_DOC_TYPES
        )
        doc_id = new_doc_id()
        upload_dir = settings.knowledge_base_dir / "uploads"
        upload_dir.mkdir(parents=True, exist_ok=True)
        # Trusted path: never contains client-controlled path components.
        stored_path = upload_dir / f"{doc_id}{suffix}"
        file_size = await stream_upload_to_file(file, stored_path, settings.UPLOAD_MAX_SIZE)
        try:
            text, extraction_method = await self.extractor.extract(
                stored_path, original_name, self.extract_text
            )
            if not text.strip():
                raise AppError(400, "未能从文件中解析或识别出文字内容")
            stem = Path(original_name).stem.strip() or "未命名文档"
            result = self._persist_document(
                db=db, kb_id=kb_id,
                title=title if title else stem,
                text=text, user_id=user_id, user_role=user_role,
                doc_type=doc_type, file_path=str(stored_path), file_size=file_size,
                doc_metadata={
                    "source_type": "file",
                    "original_filename": original_name,
                    "extraction_method": extraction_method,
                },
                department=department, doc_number=doc_number,
            )
            result["extraction_method"] = extraction_method
            return result
        except Exception:
            # Parsing/persistence failure must not leave an orphaned uploaded file.
            stored_path.unlink(missing_ok=True)
            raise

    def update_content(self, db: Session, doc_id: str, text: str) -> Dict:
        self._last_vector_error = ""
        self._last_vector_count = 0
        result = super().update_content(db, doc_id, text)
        doc = db.get(DocumentModel, doc_id)
        if doc and doc.status == "published":
            status = "failed" if self._last_vector_error else "indexed"
            self._set_index_metadata(db, doc, status, self._last_vector_error,
                                     self._last_vector_count)
            result["indexing_status"] = status
            if self._last_vector_error:
                result["indexing_error"] = self._last_vector_error
                result["message"] = "正文已更新，但向量索引失败，可稍后重试"
        return result

    def review_document(self, doc_id: str, action: str, comment: str,
                        reviewer_id: str, db: Session) -> Dict:
        self._last_vector_error = ""
        self._last_vector_count = 0
        result = super().review_document(doc_id, action, comment, reviewer_id, db)
        doc = db.get(DocumentModel, doc_id)
        if doc and doc.status == "published":
            status = "failed" if self._last_vector_error else "indexed"
            self._set_index_metadata(db, doc, status, self._last_vector_error,
                                     self._last_vector_count)
            result["indexing_status"] = status
            if self._last_vector_error:
                result["indexing_error"] = self._last_vector_error
        return result

    def retry_index(self, db: Session, doc_id: str) -> Dict:
        doc = db.get(DocumentModel, doc_id)
        if not doc:
            raise AppError(404, "文档不存在")
        if doc.status != "published":
            raise AppError(409, "仅已发布文档可以重建向量索引")
        chunks = db.scalars(
            select(ChunkModel).where(ChunkModel.doc_id == doc_id).order_by(ChunkModel.chunk_index)
        ).all()
        if not chunks:
            raise AppError(409, "文档没有可索引的正文分块")
        if self.vector_store:
            self.vector_store.delete_by_document(doc_id)
        records = [{
            "chunk_id": c.id,
            "doc_id": doc_id,
            "kb_id": doc.kb_id,
            "content": c.content,
            "title": c.title or "",
        } for c in chunks]
        count = self._vectorize(records, scope=scope_of_doc(db, doc))
        status = "failed" if self._last_vector_error else "indexed"
        self._set_index_metadata(db, doc, status, self._last_vector_error, count)
        result = {"doc_id": doc_id, "indexing_status": status, "indexed_chunks": count}
        if self._last_vector_error:
            result["indexing_error"] = self._last_vector_error
        return result
