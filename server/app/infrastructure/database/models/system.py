"""系统配置 ORM 模型。"""
from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, Boolean, DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base, IdMixin


class ModelVersionModel(Base, IdMixin):
    __tablename__ = "model_versions"

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    version: Mapped[str] = mapped_column(String(50), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), default="qwen")
    endpoint: Mapped[Optional[str]] = mapped_column(String(500))
    capabilities: Mapped[Optional[dict]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="active")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    activated_at: Mapped[Optional[datetime]] = mapped_column(DateTime)


class SystemConfigModel(Base, IdMixin):
    __tablename__ = "system_configs"

    key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    value: Mapped[Optional[str]] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(50), default="general")
    description: Mapped[Optional[str]] = mapped_column(Text)
    updated_by: Mapped[Optional[str]] = mapped_column(String(36))
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
