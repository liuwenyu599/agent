"""对话模块 ORM 模型。"""
from app.core.timeutil import now_local
from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, BigInteger, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.database.base import Base, IdMixin


class ChatSessionModel(Base, IdMixin):
    __tablename__ = "chat_sessions"

    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    title: Mapped[Optional[str]] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_local)

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
    source: Mapped[str] = mapped_column(String(50), default="chat")
    sources: Mapped[Optional[list]] = mapped_column(JSON)
    attachments: Mapped[Optional[list]] = mapped_column(JSON)
    tool_calls: Mapped[Optional[list]] = mapped_column(JSON)
    tokens_used: Mapped[Optional[int]] = mapped_column(Integer)
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_local)

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
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    file_path: Mapped[Optional[str]] = mapped_column(String(500))
    file_size: Mapped[Optional[int]] = mapped_column(BigInteger)
    text_content: Mapped[Optional[str]] = mapped_column(Text)
    parse_status: Mapped[str] = mapped_column(String(20), default="ok")
    parse_note: Mapped[Optional[str]] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_local)

    session: Mapped[Optional[ChatSessionModel]] = relationship(
        "ChatSessionModel", back_populates="attachments"
    )


class AIResponseFeedbackModel(Base, IdMixin):
    """用户对 AI 回复或文本版本的显式反馈。

    rating 只允许 1（赞）或 -1（踩）。source_chunk_ids 是提交反馈时该 AI 回复实际引用的
    chunk 快照，用于之后对该用户做轻量 rerank；不把单个用户反馈传播给其他用户。
    """
    __tablename__ = "ai_response_feedback"
    __table_args__ = (
        UniqueConstraint("user_id", "target_type", "target_id", name="uq_ai_feedback_user_target"),
    )

    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    target_type: Mapped[str] = mapped_column(String(32), nullable=False)  # chat_message/document_version
    target_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    message_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("chat_messages.id", ondelete="CASCADE"), nullable=True, index=True
    )
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    detail: Mapped[Optional[str]] = mapped_column(Text)
    source_chunk_ids: Mapped[Optional[list]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_local)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_local, onupdate=now_local)


class SessionSummaryModel(Base, IdMixin):
    __tablename__ = "session_summaries"

    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("chat_sessions.id"), nullable=False
    )
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    key_points: Mapped[Optional[list]] = mapped_column(JSON)
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_local)


class UserMemoryModel(Base, IdMixin):
    __tablename__ = "user_memories"

    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    memory_type: Mapped[str] = mapped_column(String(50), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    importance: Mapped[float] = mapped_column(Float, default=0.5)
    source: Mapped[Optional[str]] = mapped_column(String(50))
    last_accessed: Mapped[datetime] = mapped_column(DateTime, default=now_local)
    access_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_local)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=now_local, onupdate=now_local
    )