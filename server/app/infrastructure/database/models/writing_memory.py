"""Curated writing habits, separated from factual knowledge and chat summaries."""
from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base, IdMixin, TimestampMixin


class WritingMemoryModel(Base, IdMixin, TimestampMixin):
    __tablename__ = "writing_memories"
    __table_args__ = (
        CheckConstraint("scope IN ('public', 'department', 'personal')",
                        name="ck_writing_memories_scope"),
        Index("ix_writing_memories_scope_owner", "scope", "owner_user_id"),
        Index("ix_writing_memories_scope_dept", "scope", "department_code"),
    )

    scope: Mapped[str] = mapped_column(String(12), nullable=False)
    owner_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=True)
    department_code: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    created_by: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    document_type: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    content: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
