"""知识库 ORM 模型：knowledge_bases / documents / chunks。"""
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.database.base import Base, IdMixin, TimestampMixin


class KnowledgeBaseModel(Base, IdMixin, TimestampMixin):
    __tablename__ = "knowledge_bases"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    kb_type: Mapped[str] = mapped_column(String(20), default="public")
    owner_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    documents: Mapped[list] = relationship("DocumentModel", back_populates="knowledge_base")


class DocumentModel(Base, IdMixin, TimestampMixin):
    __tablename__ = "documents"

    kb_id: Mapped[str] = mapped_column(String(36), ForeignKey("knowledge_bases.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    doc_type: Mapped[Optional[str]] = mapped_column(String(50))
    department: Mapped[Optional[str]] = mapped_column(String(100))
    issue_date: Mapped[Optional[datetime]] = mapped_column(DateTime)
    doc_number: Mapped[Optional[str]] = mapped_column(String(100))
    file_path: Mapped[Optional[str]] = mapped_column(String(500))
    file_size: Mapped[Optional[int]] = mapped_column(BigInteger)
    page_count: Mapped[Optional[int]] = mapped_column(Integer)
    content: Mapped[Optional[str]] = mapped_column(Text)

    status: Mapped[str] = mapped_column(String(20), default="pending")
    uploaded_by: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id"))
    created_by: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id"))
    reviewed_by: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id"))
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    review_comment: Mapped[Optional[str]] = mapped_column(Text)

    version: Mapped[int] = mapped_column(Integer, default=1)
    doc_metadata: Mapped[Optional[dict]] = mapped_column(JSON)

    knowledge_base: Mapped[KnowledgeBaseModel] = relationship(
        "KnowledgeBaseModel", back_populates="documents"
    )
    uploader: Mapped[Optional[Any]] = relationship(
        "UserModel", foreign_keys=[uploaded_by], lazy="joined"
    )
    reviewer: Mapped[Optional[Any]] = relationship(
        "UserModel", foreign_keys=[reviewed_by], lazy="joined"
    )
    chunks: Mapped[list] = relationship(
        "ChunkModel", back_populates="document", cascade="all, delete-orphan"
    )


class ChunkModel(Base, IdMixin):
    __tablename__ = "chunks"

    doc_id: Mapped[str] = mapped_column(String(36), ForeignKey("documents.id"), nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_type: Mapped[Optional[str]] = mapped_column(String(50))
    title: Mapped[Optional[str]] = mapped_column(String(500))
    content: Mapped[str] = mapped_column(Text, nullable=False)
    char_count: Mapped[Optional[int]] = mapped_column(Integer)
    word_count: Mapped[Optional[int]] = mapped_column(Integer)
    embedding_model: Mapped[Optional[str]] = mapped_column(String(50))
    chunk_metadata: Mapped[Optional[dict]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    document: Mapped[DocumentModel] = relationship("DocumentModel", back_populates="chunks")
