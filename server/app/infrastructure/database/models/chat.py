"""对话模块 ORM 模型（表结构与旧系统一致）。"""
from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, BigInteger, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.database.base import Base, IdMixin


class ChatSessionModel(Base, IdMixin):
    __tablename__ = "chat_sessions"

    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    title: Mapped[Optional[str]] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped[Optional[object]] = relationship("UserModel", lazy="joined")
    messages: Mapped[list] = relationship(
        "ChatMessageModel", back_populates="session", cascade="all, delete-orphan"
    )
    attachments: Mapped[list] = relationship(
        "ChatAttachmentModel", back_populates="session", cascade="all, delete-orphan"
    )


class ChatMessageModel(Base, IdMixin):
    __tablename__ = "chat_messages"

    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("chat_sessions.id"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(50), default="chat")  # chat/template
    sources: Mapped[Optional[list]] = mapped_column(JSON)
    attachments: Mapped[Optional[list]] = mapped_column(JSON)  # [{id, filename, kind}]
    tool_calls: Mapped[Optional[list]] = mapped_column(JSON)
    tokens_used: Mapped[Optional[int]] = mapped_column(Integer)
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    session: Mapped[ChatSessionModel] = relationship(
        "ChatSessionModel", back_populates="messages"
    )


class ChatAttachmentModel(Base, IdMixin):
    """写作对话中用户上传的附件（Word/PDF/TXT/图片等），与知识库完全独立。"""
    __tablename__ = "chat_attachments"

    session_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("chat_sessions.id"), nullable=True
    )
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)  # doc / image
    file_path: Mapped[Optional[str]] = mapped_column(String(500))
    file_size: Mapped[Optional[int]] = mapped_column(BigInteger)
    text_content: Mapped[Optional[str]] = mapped_column(Text)
    parse_status: Mapped[str] = mapped_column(String(20), default="ok")
    parse_note: Mapped[Optional[str]] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    session: Mapped[Optional[ChatSessionModel]] = relationship(
        "ChatSessionModel", back_populates="attachments"
    )


class SessionSummaryModel(Base, IdMixin):
    __tablename__ = "session_summaries"

    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("chat_sessions.id"), nullable=False
    )
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    key_points: Mapped[Optional[list]] = mapped_column(JSON)
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class UserMemoryModel(Base, IdMixin):
    __tablename__ = "user_memories"

    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    memory_type: Mapped[str] = mapped_column(String(50), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    importance: Mapped[float] = mapped_column(Float, default=0.5)
    source: Mapped[Optional[str]] = mapped_column(String(50))
    last_accessed: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    access_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
