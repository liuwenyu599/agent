"""工作流 ORM 模型（字段与旧系统 workflow_* / node_instances 一致）。"""
from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base, IdMixin


class WorkflowTemplateModel(Base, IdMixin):
    __tablename__ = "workflow_templates"

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    category: Mapped[str] = mapped_column(String(50), default="通用")
    description: Mapped[Optional[str]] = mapped_column(Text)
    icon: Mapped[str] = mapped_column(String(50), default="Share")
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class WorkflowNodeModel(Base, IdMixin):
    __tablename__ = "workflow_nodes"

    template_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workflow_templates.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    stage: Mapped[str] = mapped_column(String(20), default="中期")
    description: Mapped[Optional[str]] = mapped_column(Text)
    write_guide: Mapped[Optional[str]] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    optional: Mapped[bool] = mapped_column(Boolean, default=False)


class WorkflowInstanceModel(Base, IdMixin):
    __tablename__ = "workflow_instances"

    template_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workflow_templates.id"), nullable=False)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="running")
    basic_info: Mapped[Optional[dict]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class NodeInstanceModel(Base, IdMixin):
    __tablename__ = "node_instances"

    instance_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workflow_instances.id"), nullable=False, index=True)
    node_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workflow_nodes.id"), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    content: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
