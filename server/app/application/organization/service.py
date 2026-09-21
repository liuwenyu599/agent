"""组织架构与科室 Agent 应用服务（v3.1）。

核心约束：
- 科室 Agent 不是十套模型，而是同一个底层模型服务上的不同配置
  （system prompt / 知识权限 / 模板 / 推荐任务）；
- 知识管理员只能改业务配置（简介、推荐任务、模板、system prompt），
  不能改 scopes（由所属科室决定）与任何权限位；
- 所有查询按 department_code 强隔离，不依赖前端隐藏。
"""
import json
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.domain.identity.authorization import (
    can_manage_department,
    is_system_admin,
    role_of,
)
from app.domain.organization.departments import (
    DEPARTMENTS,
    SCOPE_GLOBAL,
    dept_scope,
    resolve_code,
    user_scope,
)
from app.infrastructure.database.models.identity import UserModel
from app.infrastructure.database.models.organization import (
    AgentConfigModel,
    DepartmentModel,
)

logger = get_logger(__name__)


def _loads(text: str, default):
    try:
        return json.loads(text or "")
    except Exception:
        return default


def _dumps(value) -> str:
    try:
        return json.dumps(value or [], ensure_ascii=False)
    except Exception:
        return "[]"


class OrganizationService:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ---------------- 初始化 ----------------

    def ensure_seeded(self) -> int:
        """幂等写入科室字典与默认 Agent 配置。启动时调用，不改动业务数据。"""
        created = 0
        for i, d in enumerate(DEPARTMENTS):
            row = self.db.get(DepartmentModel, d.code)
            if not row:
                self.db.add(DepartmentModel(
                    code=d.code, name=d.name, short_name=d.short_name, sort_order=i))
                created += 1
            elif not row.short_name:
                row.short_name = d.short_name
                row.name = d.name
        if created:
            self.db.flush()

        for d in DEPARTMENTS:
            if self.db.scalar(select(AgentConfigModel).where(
                    AgentConfigModel.dept_code == d.code)):
                continue
            self.db.add(AgentConfigModel(
                dept_code=d.code,
                name=f"{d.short_name} Agent",
                intro=f"面向{d.name}业务的 AI 助手，默认只检索全局公共知识与{d.short_name}知识库。",
                model="Qwen2.5-VL-3B-Instruct",
                system_prompt=(
                    f"你是{d.name}（{d.short_name}）的公文写作助手。"
                    f"你熟悉{d.short_name}的业务范围、常用文种与行文口径；"
                    "只依据提供的资料与知识库内容写作，不得编造事实、数据、文号与人名；"
                    "涉及其他科室内部事项时，提示用户切换到对应科室 Agent。"
                ),
                scopes_json=_dumps([SCOPE_GLOBAL, dept_scope(d.code)]),
                tasks_json=_dumps([]),
                templates_json=_dumps([]),
            ))
            created += 1
        if created:
            self.db.commit()
            logger.info("[组织] 初始化科室与 Agent 配置: %d 条", created)
        return created

    # ---------------- 查询 ----------------

    def list_departments(self, user_id: str = "") -> List[Dict[str, Any]]:
        """科室列表：正式名 + 简称 + 真实统计（成员数 / 知识库数 / 模板数）。"""
        from sqlalchemy import func
        from app.infrastructure.database.models.knowledge import KnowledgeBaseModel
        from app.infrastructure.database.models.templates import WritingTemplateModel

        rows = self.db.scalars(
            select(DepartmentModel).where(DepartmentModel.is_active.is_(True))
            .order_by(DepartmentModel.sort_order)).all()
        if not rows:
            return []

        codes = [r.code for r in rows]
        # 一次性聚合，避免 N+1
        member_map = dict(self.db.execute(
            select(UserModel.department_code, func.count(UserModel.id))
            .where(UserModel.department_code.in_(codes))
            .group_by(UserModel.department_code)).all())
        kb_map = dict(self.db.execute(
            select(KnowledgeBaseModel.department_code, func.count(KnowledgeBaseModel.id))
            .where(KnowledgeBaseModel.department_code.in_(codes))
            .group_by(KnowledgeBaseModel.department_code)).all())
        tpl_map = dict(self.db.execute(
            select(WritingTemplateModel.department_code, func.count(WritingTemplateModel.id))
            .where(WritingTemplateModel.department_code.in_(codes))
            .group_by(WritingTemplateModel.department_code)).all())

        mine = ""
        if user_id:
            mine = self._effective_code(self.db.get(UserModel, user_id) or UserModel())

        return [{
            "code": r.code,
            "name": r.name,
            "short_name": r.short_name,
            "member_count": int(member_map.get(r.code, 0)),
            "kb_count": int(kb_map.get(r.code, 0)),
            "template_count": int(tpl_map.get(r.code, 0)),
            "is_mine": r.code == mine,
        } for r in rows]

    def agent_of(self, dept_code: str) -> Optional[Dict[str, Any]]:
        if not dept_code:
            return None
        cfg = self.db.scalar(
            select(AgentConfigModel).where(AgentConfigModel.dept_code == dept_code))
        if not cfg:
            return None
        dept = self.db.get(DepartmentModel, dept_code)
        tasks = _loads(cfg.tasks_json, [])
        return {
            "dept_code": cfg.dept_code,
            "dept_name": dept.name if dept else "",
            "short_name": dept.short_name if dept else "",
            "name": cfg.name,
            "intro": cfg.intro,
            "model": cfg.model,
            "system_prompt": cfg.system_prompt,
            "scopes": _loads(cfg.scopes_json, []),
            "tasks": tasks,
            # 客户端字段名：推荐任务
            "recommended_tasks": tasks,
            "templates": _loads(cfg.templates_json, []),
            "manager": cfg.manager,
        }

    def user_context(self, user_id: str) -> Dict[str, Any]:
        """一次性返回用户所属科室 + Agent + 允许作用域（前端据此渲染工作台）。"""
        user = self.db.get(UserModel, user_id)
        if not user:
            return {"dept_code": "", "dept_name": "", "short_name": "",
                    "agent": None, "scopes": [SCOPE_GLOBAL]}
        code = self._effective_code(user)
        dept = self.db.get(DepartmentModel, code) if code else None
        agent = self.agent_of(code)
        scopes = [SCOPE_GLOBAL]
        if getattr(user, "id", ""):
            scopes.append(user_scope(user.id))
        if code:
            scopes.append(dept_scope(code))
        return {
            "dept_code": code,
            "dept_name": dept.name if dept else "",
            "short_name": dept.short_name if dept else "",
            "agent": agent,
            "scopes": scopes,
            # 系统管理员：developer（正式）或 admin（历史遗留）
            "is_admin": is_system_admin(role_of(user)),
        }

    @staticmethod
    def _effective_code(user: UserModel) -> str:
        """users.department_code 为空时，按 department 名称回填并落库。"""
        code = getattr(user, "department_code", "") or ""
        if code:
            return code
        return resolve_code(getattr(user, "department", "") or "")

    def backfill_user_codes(self) -> int:
        """把历史 users.department（名称）回填成 department_code。"""
        users = self.db.scalars(select(UserModel)).all()
        n = 0
        for u in users:
            code = self._effective_code(u)
            if code and code != (getattr(u, "department_code", "") or ""):
                u.department_code = code
                n += 1
        if n:
            self.db.commit()
            logger.info("[组织] 回填用户科室归属: %d 人", n)
        return n

    # ---------------- 维护（知识管理员 / 管理员） ----------------

    def can_manage(self, user: UserModel, dept_code: str) -> bool:
        """系统管理员可管理全部科室；知识管理员仅限本人所属科室。

        用户科室归属由服务端从 users 表解析，不采信任何客户端提交的 dept_code。
        """
        return can_manage_department(role_of(user), self._effective_code(user), dept_code)

    def update_agent(self, user: UserModel, dept_code: str,
                     payload: Dict[str, Any]) -> Dict[str, Any]:
        if not self.can_manage(user, dept_code):
            raise PermissionError("无权维护该科室 Agent")
        cfg = self.db.scalar(
            select(AgentConfigModel).where(AgentConfigModel.dept_code == dept_code))
        if not cfg:
            cfg = AgentConfigModel(dept_code=dept_code, name=f"{dept_code} Agent")
            self.db.add(cfg)
        # 只允许改业务配置，scopes / 权限不可改
        for field in ("name", "intro", "manager"):
            if field in payload and payload[field] is not None:
                setattr(cfg, field, str(payload[field])[:500])
        if payload.get("system_prompt") is not None:
            cfg.system_prompt = str(payload["system_prompt"])[:4000]
        if payload.get("tasks") is not None:
            cfg.tasks_json = _dumps(payload["tasks"])
        if payload.get("templates") is not None:
            cfg.templates_json = _dumps(payload["templates"])
        cfg.scopes_json = _dumps([SCOPE_GLOBAL, dept_scope(dept_code)])
        self.db.commit()
        return self.agent_of(dept_code) or {}

    def agent_system_prompt(self, user_id: str) -> str:
        """供写作/问答链路注入的科室上下文提示。"""
        ctx = self.user_context(user_id)
        agent = ctx.get("agent")
        if not agent:
            return ""
        dept = ctx.get("dept_name") or ctx.get("short_name")
        return (
            f"【当前科室 Agent】{agent['name']}（{dept}）\n"
            f"{agent.get('intro') or ''}\n"
            f"{agent.get('system_prompt') or ''}\n"
            f"知识范围：{', '.join(ctx.get('scopes') or [])}\n"
        ).strip()
