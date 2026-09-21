"""审核流转 ORM 模型（v3.0）

approval_instances 与 my_documents 双向外键且**均可空**：
- 存量公文从未走过审批流，document_id 关联后 approval_instance_id 仍可为 NULL，
  保证已有 10 篇文档零改动。
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base, IdMixin


class ApprovalInstanceModel(Base, IdMixin):
    __tablename__ = "approval_instances"

    document_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("my_documents.id"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    submitter_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True)
    submitter_name: Mapped[str] = mapped_column(String(100), default="")
    department: Mapped[str] = mapped_column(String(100), default="")
    current_status: Mapped[str] = mapped_column(String(30), default="PENDING_DEPT")
    current_step: Mapped[str] = mapped_column(String(30), default="dept")
    flow: Mapped[Optional[dict]] = mapped_column(JSON)
    doc_number: Mapped[Optional[str]] = mapped_column(String(80))
    urgency: Mapped[str] = mapped_column(String(10), default="normal")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now())


class ApprovalActionModel(Base, IdMixin):
    __tablename__ = "approval_actions"

    instance_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("approval_instances.id"), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(30), nullable=False)
    from_status: Mapped[str] = mapped_column(String(30), default="")
    to_status: Mapped[str] = mapped_column(String(30), default="")
    comment: Mapped[Optional[str]] = mapped_column(Text)
    actor_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id"))
    actor_name: Mapped[str] = mapped_column(String(100), default="")
    actor_role: Mapped[str] = mapped_column(String(30), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
