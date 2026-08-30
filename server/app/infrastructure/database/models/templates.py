"""写作模板 ORM 模型（字段与旧系统 writing_templates / template_categories 一致）。"""
from datetime import datetime
from typing import List, Optional

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base, IdMixin


class WritingTemplateModel(Base, IdMixin):
    __tablename__ = "writing_templates"

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    icon: Mapped[str] = mapped_column(String(50), default="Document")
    params_schema: Mapped[Optional[list]] = mapped_column(JSON, default=list)
    content_template: Mapped[str] = mapped_column(Text, nullable=False)
    system_prompt: Mapped[Optional[str]] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    use_count: Mapped[int] = mapped_column(Integer, default=0)
    base_type: Mapped[str] = mapped_column(String(50), default="公文")
    writing_style: Mapped[str] = mapped_column(String(50), default="正式公文")
    word_count: Mapped[int] = mapped_column(Integer, default=1000)
    need_red_header: Mapped[bool] = mapped_column(Boolean, default=False)
    need_signature: Mapped[bool] = mapped_column(Boolean, default=True)
    need_date: Mapped[bool] = mapped_column(Boolean, default=True)
    need_doc_number: Mapped[bool] = mapped_column(Boolean, default=False)
    keywords: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # 新版字段
    template_kind: Mapped[str] = mapped_column(String(20), default="official_doc")
    tags: Mapped[Optional[list]] = mapped_column(JSON, default=list)
    scene: Mapped[Optional[str]] = mapped_column(String(300))
    writing_guide: Mapped[Optional[str]] = mapped_column(Text)
    structure: Mapped[Optional[list]] = mapped_column(JSON, default=list)
    kb_ids: Mapped[Optional[list]] = mapped_column(JSON, default=list)
    visibility: Mapped[str] = mapped_column(String(20), default="official")
    share_scope: Mapped[str] = mapped_column(String(20), default="all")
    share_departments: Mapped[Optional[list]] = mapped_column(JSON, default=list)
    share_roles: Mapped[Optional[list]] = mapped_column(JSON, default=list)
    is_draft: Mapped[bool] = mapped_column(Boolean, default=False)


class TemplateCategoryModel(Base, IdMixin):
    __tablename__ = "template_categories"

    name: Mapped[str] = mapped_column(String(50), nullable=False)
    code: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    description: Mapped[Optional[str]] = mapped_column(Text)
    icon: Mapped[str] = mapped_column(String(50), default="Folder")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
