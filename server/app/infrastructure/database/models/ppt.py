"""PPT 助手 ORM 模型（字段与旧系统 models_ppt 一致，materials 补 mime_type 列）。"""
from datetime import datetime
from typing import Optional

from sqlalchemy import (JSON, BigInteger, Boolean, DateTime, ForeignKey,
                        Integer, String, Text, func)
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base, IdMixin


class PPTTemplateModel(Base, IdMixin):
    __tablename__ = "ppt_templates"

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    builtin_id: Mapped[Optional[str]] = mapped_column(String(50), unique=True, nullable=True)
    category: Mapped[str] = mapped_column(String(50), default="工作汇报")
    description: Mapped[Optional[str]] = mapped_column(String(300))
    is_official: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id"))
    colors: Mapped[Optional[dict]] = mapped_column(JSON)
    font: Mapped[str] = mapped_column(String(50), default="微软雅黑")
    layouts: Mapped[Optional[dict]] = mapped_column(JSON)
    layout_library: Mapped[Optional[list]] = mapped_column(JSON)
    source_file: Mapped[Optional[str]] = mapped_column(String(500))
    use_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class PPTTemplateFavoriteModel(Base, IdMixin):
    __tablename__ = "ppt_template_favorites"

    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    template_id: Mapped[str] = mapped_column(String(36), ForeignKey("ppt_templates.id"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class PPTMaterialModel(Base, IdMixin):
    __tablename__ = "ppt_materials"

    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    caption: Mapped[Optional[str]] = mapped_column(String(500))
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    file_size: Mapped[Optional[int]] = mapped_column(BigInteger)
    width: Mapped[Optional[int]] = mapped_column(Integer)
    height: Mapped[Optional[int]] = mapped_column(Integer)
    mime_type: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class PPTDocumentModel(Base, IdMixin):
    __tablename__ = "ppt_documents"

    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    subtitle: Mapped[str] = mapped_column(String(300), default="")
    source_content: Mapped[Optional[str]] = mapped_column(Text)
    template_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("ppt_templates.id"))
    theme_id: Mapped[str] = mapped_column(String(50), default="gov_report_red")
    source_type: Mapped[str] = mapped_column(String(20), default="topic")
    status: Mapped[str] = mapped_column(String(20), default="draft")
    is_favorite: Mapped[bool] = mapped_column(Boolean, default=False)
    outline: Mapped[Optional[dict]] = mapped_column(JSON)
    file_path: Mapped[Optional[str]] = mapped_column(String(500))
    slide_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
