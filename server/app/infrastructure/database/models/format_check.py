"""格式校验 ORM 模型（字段与旧系统 format_rules / format_check_records 一致）。"""
from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base, IdMixin


class FormatRuleModel(Base, IdMixin):
    __tablename__ = "format_rules"

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    target: Mapped[str] = mapped_column(String(30), nullable=False)
    checks: Mapped[dict] = mapped_column(JSON, nullable=False)
    severity: Mapped[str] = mapped_column(String(10), default="error")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    remark: Mapped[Optional[str]] = mapped_column(Text)
    created_by: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class FormatCheckRecordModel(Base, IdMixin):
    __tablename__ = "format_check_records"

    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    file_type: Mapped[Optional[str]] = mapped_column(String(20))
    rule_snapshot: Mapped[Optional[list]] = mapped_column(JSON)
    issues: Mapped[Optional[list]] = mapped_column(JSON)
    issue_count: Mapped[int] = mapped_column(Integer, default=0)
    rule_issue_count: Mapped[int] = mapped_column(Integer, default=0)
    ai_issue_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
