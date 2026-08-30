"""知识库仓储 SQLAlchemy 实现。"""
from datetime import datetime
from typing import List, Optional

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.domain.knowledge.entities import DocumentChunk, KnowledgeBase, KnowledgeDocument
from app.domain.knowledge.repositories import (
    ChunkRepository,
    DocumentRepository,
    KnowledgeBaseRepository,
)
from app.infrastructure.database.models.identity import UserModel
from app.infrastructure.database.models.knowledge import (
    ChunkModel,
    DocumentModel,
    KnowledgeBaseModel,
)


def _kb_to_entity(m: KnowledgeBaseModel) -> KnowledgeBase:
    return KnowledgeBase(
        id=m.id, name=m.name, description=m.description or "", kb_type=m.kb_type,
        owner_id=m.owner_id, is_active=bool(m.is_active),
        created_at=m.created_at, updated_at=m.updated_at,
    )


def _doc_to_entity(m: DocumentModel) -> KnowledgeDocument:
    return KnowledgeDocument(
        id=m.id, kb_id=m.kb_id, title=m.title, doc_type=m.doc_type,
        department=m.department, issue_date=m.issue_date, doc_number=m.doc_number,
        file_path=m.file_path, file_size=m.file_size, page_count=m.page_count,
        content=m.content, status=m.status, uploaded_by=m.uploaded_by,
        created_by=m.created_by, reviewed_by=m.reviewed_by, reviewed_at=m.reviewed_at,
        review_comment=m.review_comment, version=m.version or 1,
        doc_metadata=m.doc_metadata or {}, created_at=m.created_at, updated_at=m.updated_at,
    )


def _chunk_to_entity(m: ChunkModel) -> DocumentChunk:
    return DocumentChunk(
        id=m.id, doc_id=m.doc_id, chunk_index=m.chunk_index, content=m.content,
        chunk_type=m.chunk_type, title=m.title, char_count=m.char_count or 0,
        word_count=m.word_count or 0, embedding_model=m.embedding_model,
        chunk_metadata=m.chunk_metadata or {}, created_at=m.created_at,
    )


class SqlAlchemyKnowledgeBaseRepository(KnowledgeBaseRepository):
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, id: str) -> Optional[KnowledgeBase]:
        m = self.db.get(KnowledgeBaseModel, id)
        return _kb_to_entity(m) if m else None

    def get_model(self, id: str) -> Optional[KnowledgeBaseModel]:
        return self.db.get(KnowledgeBaseModel, id)

    def list_accessible(self, user_id: str, user_role: str) -> List[KnowledgeBase]:
        q = select(KnowledgeBaseModel)
        if user_role != "admin":
            q = q.where(or_(
                KnowledgeBaseModel.kb_type == "public",
                (KnowledgeBaseModel.kb_type == "personal") & (KnowledgeBaseModel.owner_id == user_id),
            ))
        return [_kb_to_entity(m) for m in self.db.scalars(q).all()]

    def get_personal_kb(self, user_id: str) -> Optional[KnowledgeBase]:
        m = self.db.scalar(select(KnowledgeBaseModel).where(
            KnowledgeBaseModel.kb_type == "personal",
            KnowledgeBaseModel.owner_id == user_id,
        ))
        return _kb_to_entity(m) if m else None

    def count_active(self) -> int:
        return len(self.db.scalars(
            select(KnowledgeBaseModel.id).where(KnowledgeBaseModel.is_active == True)  # noqa: E712
        ).all())

    def add(self, kb: KnowledgeBase) -> KnowledgeBase:
        m = KnowledgeBaseModel(
            name=kb.name, description=kb.description,
            kb_type=kb.kb_type, owner_id=kb.owner_id, is_active=kb.is_active,
        )
        self.db.add(m)
        self.db.commit()
        self.db.refresh(m)
        return _kb_to_entity(m)

    def update(self, kb: KnowledgeBase) -> KnowledgeBase:
        m = self.db.get(KnowledgeBaseModel, kb.id)
        if m:
            m.name = kb.name
            m.description = kb.description
            m.is_active = kb.is_active
            self.db.commit()
            self.db.refresh(m)
            return _kb_to_entity(m)
        return kb

    def delete(self, kb: KnowledgeBase) -> None:
        m = self.db.get(KnowledgeBaseModel, kb.id)
        if m:
            m.is_active = False
            self.db.commit()

    def published_doc_count(self, kb_id: str) -> int:
        return len(self.db.scalars(select(DocumentModel.id).where(
            DocumentModel.kb_id == kb_id, DocumentModel.status == "published"
        )).all())


class SqlAlchemyDocumentRepository(DocumentRepository):
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, id: str) -> Optional[KnowledgeDocument]:
        m = self.db.get(DocumentModel, id)
        return _doc_to_entity(m) if m else None

    def get_model(self, id: str) -> Optional[DocumentModel]:
        return self.db.get(DocumentModel, id)

    def add(self, doc: KnowledgeDocument) -> KnowledgeDocument:
        m = DocumentModel(
            id=doc.id, kb_id=doc.kb_id, title=doc.title, doc_type=doc.doc_type,
            department=doc.department, doc_number=doc.doc_number,
            file_path=doc.file_path, file_size=doc.file_size, content=doc.content,
            status=doc.status, uploaded_by=doc.uploaded_by, created_by=doc.created_by,
            doc_metadata=doc.doc_metadata,
        )
        self.db.add(m)
        return doc

    def update(self, doc: KnowledgeDocument) -> KnowledgeDocument:
        m = self.db.get(DocumentModel, doc.id)
        if not m:
            return doc
        m.title = doc.title
        m.doc_type = doc.doc_type
        m.status = doc.status
        m.department = doc.department
        m.doc_number = doc.doc_number
        m.reviewed_by = doc.reviewed_by
        m.reviewed_at = doc.reviewed_at
        m.review_comment = doc.review_comment
        self.db.commit()
        self.db.refresh(m)
        return _doc_to_entity(m)

    def delete(self, doc: KnowledgeDocument) -> None:
        m = self.db.get(DocumentModel, doc.id)
        if m:
            m.status = "archived"
            self.db.commit()

    def list_by_kb(self, kb_id: str, status: Optional[str] = None,
                   page: int = 1, page_size: int = 20) -> tuple:
        q = select(DocumentModel).where(DocumentModel.kb_id == kb_id)
        if status:
            q = q.where(DocumentModel.status == status)
        total = len(self.db.scalars(q).all())
        items = self.db.scalars(q.offset((page - 1) * page_size).limit(page_size)).all()
        return total, [_doc_to_entity(m) for m in items]

    def list_by_status(self, status: str) -> List[KnowledgeDocument]:
        items = self.db.scalars(
            select(DocumentModel).where(DocumentModel.status == status)
        ).all()
        return [_doc_to_entity(m) for m in items]

    def list_all(self, status: Optional[str] = None, page: int = 1, page_size: int = 20) -> tuple:
        q = select(DocumentModel)
        if status:
            q = q.where(DocumentModel.status == status)
        q = q.order_by(DocumentModel.created_at.desc())
        total = len(self.db.scalars(q).all())
        items = self.db.scalars(q.offset((page - 1) * page_size).limit(page_size)).all()
        return total, [_doc_to_entity(m) for m in items]

    def find_by_source_url(self, source_url: str) -> Optional[KnowledgeDocument]:
        try:
            m = self.db.scalar(select(DocumentModel).where(
                DocumentModel.doc_metadata["source_url"].as_string() == source_url
            ))
            return _doc_to_entity(m) if m else None
        except Exception:
            docs = self.db.scalars(
                select(DocumentModel).where(DocumentModel.doc_metadata.isnot(None))
            ).all()
            for d in docs:
                if (d.doc_metadata or {}).get("source_url") == source_url:
                    return _doc_to_entity(d)
            return None

    def count(self, status: Optional[str] = None) -> int:
        q = select(DocumentModel.id)
        if status:
            q = q.where(DocumentModel.status == status)
        return len(self.db.scalars(q).all())

    # ---- 列表展示专用：携带上传人/审核人姓名与知识库名 ----
    def list_with_display(self, kb_id: Optional[str] = None, status: Optional[str] = None,
                          page: int = 1, page_size: int = 20,
                          order_desc: bool = False) -> tuple:
        q = select(DocumentModel)
        if kb_id:
            q = q.where(DocumentModel.kb_id == kb_id)
        if status:
            q = q.where(DocumentModel.status == status)
        if order_desc:
            q = q.order_by(DocumentModel.created_at.desc())
        total = len(self.db.scalars(q).all())
        items = self.db.scalars(q.offset((page - 1) * page_size).limit(page_size)).all()
        return total, [self._display_dict(m) for m in items]

    def _display_dict(self, m: DocumentModel) -> dict:
        return {
            "id": m.id, "title": m.title, "doc_type": m.doc_type, "status": m.status,
            "department": m.department, "doc_number": m.doc_number,
            "kb_name": m.knowledge_base.name if m.knowledge_base else "",
            "uploader_name": m.uploader.real_name if m.uploader else None,
            "reviewer_name": m.reviewer.real_name if m.reviewer else None,
            "review_comment": m.review_comment, "reviewed_at": m.reviewed_at,
            "created_at": m.created_at,
        }


class SqlAlchemyChunkRepository(ChunkRepository):
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, id: str) -> Optional[DocumentChunk]:
        m = self.db.get(ChunkModel, id)
        return _chunk_to_entity(m) if m else None

    def list_by_document(self, doc_id: str) -> List[DocumentChunk]:
        items = self.db.scalars(
            select(ChunkModel).where(ChunkModel.doc_id == doc_id)
            .order_by(ChunkModel.chunk_index)
        ).all()
        return [_chunk_to_entity(m) for m in items]

    def add(self, chunk: DocumentChunk) -> DocumentChunk:
        m = ChunkModel(
            id=chunk.id, doc_id=chunk.doc_id, chunk_index=chunk.chunk_index,
            chunk_type=chunk.chunk_type, title=chunk.title, content=chunk.content,
            char_count=chunk.char_count, word_count=chunk.word_count,
            chunk_metadata=chunk.chunk_metadata,
        )
        self.db.add(m)
        return chunk

    def add_many(self, chunks: List[DocumentChunk]) -> None:
        for c in chunks:
            self.add(c)

    def delete(self, chunk: DocumentChunk) -> None:
        m = self.db.get(ChunkModel, chunk.id)
        if m:
            self.db.delete(m)
