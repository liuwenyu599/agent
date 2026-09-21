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
    name: Mapped[str] = mapped_column(String(60), default="")             # 如「复议科助手」
    intro: Mapped[str] = mapped_column(Text, default="")
    model: Mapped[str] = mapped_column(String(120), default="")           # 底层模型标识（只读展示）

    # ---- Prompt 分层 ----
    # 1) 系统基础 Prompt：仅 developer 可维护
    system_prompt: Mapped[str] = mapped_column(Text, default="")
    # 2) 安全 / 权限约束：仅 developer 可维护，任何业务配置都不得覆盖
    safety_prompt: Mapped[str] = mapped_column(Text, default="")
    # 3) 科室业务 Prompt：knowledge_admin 可维护本科室
    business_prompt: Mapped[str] = mapped_column(Text, default="")
    # 4) 工作要求（写作口径 / 行文习惯）：knowledge_admin 可维护本科室
    work_requirements: Mapped[str] = mapped_column(Text, default="")

    # JSON 文本：scopes / recommended_tasks / templates / 关联知识库
    scopes_json: Mapped[str] = mapped_column(Text, default="[]")
    tasks_json: Mapped[str] = mapped_column(Text, default="[]")
    templates_json: Mapped[str] = mapped_column(Text, default="[]")
    kb_json: Mapped[str] = mapped_column(Text, default="[]")
    manager: Mapped[str] = mapped_column(String(100), default="")
    version: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now())


class AgentConfigVersionModel(Base, IdMixin):
    """科室 Agent 配置变更版本记录：每次修改留一份快照，用于审计与回滚追溯。

    只记录配置内容与操作人 / 时间，不记录任何凭据。
    """
    __tablename__ = "agent_config_versions"

    dept_code: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    operator_id: Mapped[str] = mapped_column(String(36), default="")
    operator_name: Mapped[str] = mapped_column(String(100), default="")
    # 变更字段清单（人类可读，不含大段正文）
    change_note: Mapped[str] = mapped_column(Text, default="")
    snapshot_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
