"""格式校验 ORM 模型（字段与旧系统 format_rules / format_check_records 一致）。"""
from app.core.timeutil import now_local
from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base, IdMixin


class FormatRuleModel(Base, IdMixin):
    __tablename__ = "format_rules"

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    target: Mapped[str] = mapped_column(String(30), nullable=False)
    # 规则集标识：由 004 upgrade 建列（String(30) nullable server_default='gb9704'），
    # ORM 必须有映射，否则 seed_v3 传 ruleset= 会 AttributeError 并被 run_all 静默吞掉。
    ruleset: Mapped[Optional[str]] = mapped_column(String(30), server_default="gb9704")
    checks: Mapped[dict] = mapped_column(JSON, nullable=False)
    severity: Mapped[str] = mapped_column(String(10), default="error")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    remark: Mapped[Optional[str]] = mapped_column(Text)
    created_by: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_local)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_local, onupdate=now_local)


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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_local)
    # 审校工作台状态（迁移 009 新增 TEXT 列，内容存 JSON 整数数组，如 "[1,3]"）
    applied_ids: Mapped[Optional[str]] = mapped_column(Text)
    resolved_ids: Mapped[Optional[str]] = mapped_column(Text)
