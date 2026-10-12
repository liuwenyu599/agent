"""Per-user paragraph suggestions and immutable action history."""
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.timeutil import now_local
from app.infrastructure.database.base import Base, IdMixin


class WritingSuggestionModel(Base, IdMixin):
    __tablename__ = "writing_suggestions"
    __table_args__ = (Index("ix_writing_suggestions_lookup",
                            "user_id", "task_id", "status", "line_index", "created_at"),)

    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    task_id: Mapped[str] = mapped_column(String(36), ForeignKey("writing_tasks.id"), nullable=False, index=True)
    paragraph_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    line_index: Mapped[int] = mapped_column(Integer, nullable=False)
    document_type: Mapped[str] = mapped_column(String(100), default="")
    base_version: Mapped[int] = mapped_column(Integer, nullable=False)
    base_content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    original_content: Mapped[str] = mapped_column(Text, nullable=False)
    proposed_content: Mapped[str] = mapped_column(Text, nullable=False)
    final_content: Mapped[Optional[str]] = mapped_column(Text)
    instruction: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_local)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_local, onupdate=now_local)


class WritingSuggestionEventModel(Base, IdMixin):
    __tablename__ = "writing_suggestion_events"

    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    task_id: Mapped[str] = mapped_column(String(36), ForeignKey("writing_tasks.id"), nullable=False, index=True)
    suggestion_id: Mapped[str] = mapped_column(String(36), ForeignKey("writing_suggestions.id"), nullable=False, index=True)
    paragraph_id: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    original_content: Mapped[str] = mapped_column(Text, nullable=False)
    final_content: Mapped[Optional[str]] = mapped_column(Text)
    diff_text: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_local)
