"""组织架构 ORM 模型（v3.1）：科室 + 科室 Agent 配置。

设计要点：
- 科室 Agent 不是十套模型，而是同一底层模型服务上的不同配置
  （system prompt / 知识权限 / 模板 / 推荐任务）；
- agent_configs 不保存任何安全规则或权限位，权限仍由 RBAC + department_code 决定，
  知识管理员只能改业务配置，不能改权限。
"""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base, IdMixin


class DepartmentModel(Base):
    __tablename__ = "departments"

    code: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)        # 正式名称
    short_name: Mapped[str] = mapped_column(String(60), default="")       # 简称
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AgentConfigModel(Base, IdMixin):
    __tablename__ = "agent_configs"

    dept_code: Mapped[str] = mapped_column(
        String(40), ForeignKey("departments.code"), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(60), default="")             # 如「复议科 Agent」
    intro: Mapped[str] = mapped_column(Text, default="")
    model: Mapped[str] = mapped_column(String(120), default="")           # 底层模型标识（只读展示）
    system_prompt: Mapped[str] = mapped_column(Text, default="")
    # JSON 文本：scopes / recommended_tasks / templates，避免引入新依赖
    scopes_json: Mapped[str] = mapped_column(Text, default="[]")
    tasks_json: Mapped[str] = mapped_column(Text, default="[]")
    templates_json: Mapped[str] = mapped_column(Text, default="[]")
    manager: Mapped[str] = mapped_column(String(100), default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now())
