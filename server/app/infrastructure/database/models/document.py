"""文档与版本管理 ORM 模型。

- documents：一篇成文文档的元信息（文号、成文日期、当前版本号）
- document_versions：每次保存产生一个不可变版本快照，支持回溯
"""
from datetime import datetime
from typing import List, Optional

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.database.base import Base, IdMixin


class MyDocumentModel(Base, IdMixin):
    __tablename__ = "my_documents"

    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False, default="未命名文档")
    doc_type: Mapped[Optional[str]] = mapped_column(String(50))          # 通知/请示/报告…
    document_number: Mapped[Optional[str]] = mapped_column(String(100))  # 程序生成文号
    document_date: Mapped[Optional[str]] = mapped_column(String(50))     # 成文日期（程序注入）
    current_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="draft")     # draft/final
    session_id: Mapped[Optional[str]] = mapped_column(String(36))        # 来源对话
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    versions: Mapped[List["MyDocumentVersionModel"]] = relationship(
        "MyDocumentVersionModel", back_populates="document",
        cascade="all, delete-orphan", order_by="MyDocumentVersionModel.version_no",
    )


class MyDocumentVersionModel(Base, IdMixin):
    __tablename__ = "my_document_versions"

    document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("my_documents.id"), nullable=False, index=True
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    quality: Mapped[Optional[dict]] = mapped_column(JSON)         # 保存时的质检快照
    content_check: Mapped[Optional[dict]] = mapped_column(JSON)   # 内容核查快照
    note: Mapped[Optional[str]] = mapped_column(String(500))      # 版本备注
    created_by: Mapped[Optional[str]] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    document: Mapped[MyDocumentModel] = relationship(
        "MyDocumentModel", back_populates="versions"
    )
