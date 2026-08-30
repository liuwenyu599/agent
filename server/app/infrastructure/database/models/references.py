"""参考材料 ORM 模型（表结构与旧 models_reference.py 一致）。"""
from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base, IdMixin


class TemplateReferenceModel(Base, IdMixin):
    __tablename__ = "template_references"

    template_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("writing_templates.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    ref_type: Mapped[str] = mapped_column(String(20), nullable=False)  # file / text / url
    file_path: Mapped[Optional[str]] = mapped_column(String(500))
    file_size: Mapped[Optional[int]] = mapped_column(BigInteger)
    source_url: Mapped[Optional[str]] = mapped_column(String(1000))
    text_content: Mapped[Optional[str]] = mapped_column(Text)
    char_count: Mapped[int] = mapped_column(BigInteger, default=0)
    parse_status: Mapped[str] = mapped_column(String(20), default="ok")
    parse_note: Mapped[Optional[str]] = mapped_column(String(500))
    created_by: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class TaskReferenceModel(Base, IdMixin):
    __tablename__ = "task_references"

    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    template_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("writing_templates.id"), nullable=True, index=True
    )
    session_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("chat_sessions.id"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    ref_type: Mapped[str] = mapped_column(String(20), nullable=False)
    file_path: Mapped[Optional[str]] = mapped_column(String(500))
    file_size: Mapped[Optional[int]] = mapped_column(BigInteger)
    source_url: Mapped[Optional[str]] = mapped_column(String(1000))
    text_content: Mapped[Optional[str]] = mapped_column(Text)
    char_count: Mapped[int] = mapped_column(BigInteger, default=0)
    parse_status: Mapped[str] = mapped_column(String(20), default="ok")
    parse_note: Mapped[Optional[str]] = mapped_column(String(500))
    promoted_doc_id: Mapped[Optional[str]] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
