"""组织架构与科室 Agent 路由（v3.1）。

对外只暴露：
- 科室字典（正式名 + 简称）
- 当前用户的科室归属 / Agent / 允许作用域
- 科室 Agent 业务配置（知识管理员可维护本科室，管理员可维护全部）

权限与知识作用域由后端解析下发，前端不得自行构造。
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.application.organization.service import OrganizationService
from app.domain.identity.entities import User
from app.infrastructure.database import get_db
from app.infrastructure.database.models.identity import UserModel
from app.interfaces.deps import get_current_user

router = APIRouter(prefix="/organization", tags=["组织架构"])


class AgentUpdate(BaseModel):
    name: str | None = None
    intro: str | None = None
    manager: str | None = None
    system_prompt: str | None = None
    tasks: list | None = None
    templates: list | None = None


@router.get("/departments")
def list_departments(db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    return {"items": OrganizationService(db).list_departments(user.id)}


@router.get("/me")
def my_context(db: Session = Depends(get_db),
               user: User = Depends(get_current_user)):
    """当前用户所属科室 + Agent + 允许作用域；前端据此渲染工作台上下文。"""
    svc = OrganizationService(db)
    ctx = svc.user_context(user.id)
    ctx["department_code"] = ctx["dept_code"]
    ctx["department_name"] = ctx["dept_name"]
    return ctx


@router.get("/agents/{dept_code}")
def get_agent(dept_code: str, db: Session = Depends(get_db),
              user: User = Depends(get_current_user)):
    """查看科室 Agent：系统管理员可看全部，其余只能看本人所属科室。"""
    svc = OrganizationService(db)
    ctx = svc.user_context(user.id)
    admin = ctx.get("is_admin")
    # 非本科室且非系统管理员：直接 403，不泄漏任何他科室配置
    if not admin and ctx.get("dept_code") != dept_code:
        raise HTTPException(status_code=403, detail="无权查看该科室 Agent")
    agent = svc.agent_of(dept_code)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent 未配置")
    return agent


@router.put("/agents/{dept_code}")
def update_agent(dept_code: str, payload: AgentUpdate,
                 db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    """维护本科室 Agent 的业务配置。scopes 与权限不可修改。"""
    row = db.get(UserModel, user.id)
    if row is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    try:
        return OrganizationService(db).update_agent(row, dept_code, payload.model_dump())
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
