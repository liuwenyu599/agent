"""写作模板路由。路径与响应结构与旧系统一致。"""
from typing import Optional

from fastapi import APIRouter, Body, Depends

from app.application.templates.dto import (
    CategoryCreateRequest,
    TemplateCreateRequest,
    TemplateUpdateRequest,
)
from app.application.templates.service import TemplateService
from app.domain.identity.entities import User
from app.infrastructure.database import get_db
from app.interfaces.deps import get_current_user, require_admin_or_above

router = APIRouter(prefix="/templates", tags=["写作模板"])


def get_template_service(db=Depends(get_db)) -> TemplateService:
    return TemplateService(db)


@router.post("/init")
def init_builtin_templates(admin: User = Depends(require_admin_or_above),
                           svc: TemplateService = Depends(get_template_service)):
    """初始化/同步内置模板（仅管理员，幂等）。"""
    return svc.init_builtin(admin)


@router.get("/categories")
def list_categories(user: User = Depends(get_current_user),
                    svc: TemplateService = Depends(get_template_service)):
    return svc.list_categories()


@router.post("/categories")
def create_category(req: CategoryCreateRequest,
                    admin: User = Depends(require_admin_or_above),
                    svc: TemplateService = Depends(get_template_service)):
    return svc.create_category(req.name, req.code, req.description or "",
                               req.icon, req.sort_order)


@router.get("/")
def list_templates(category: Optional[str] = None,
                   user: User = Depends(get_current_user),
                   svc: TemplateService = Depends(get_template_service)):
    return svc.list_templates(user, category)


@router.get("/{template_id}")
def get_template(template_id: str, user: User = Depends(get_current_user),
                 svc: TemplateService = Depends(get_template_service)):
    return svc.get_template(template_id)


@router.post("/")
def create_template(req: TemplateCreateRequest,
                    user: User = Depends(get_current_user),
                    svc: TemplateService = Depends(get_template_service)):
    return svc.create_template(user, req)


@router.put("/{template_id}")
def update_template(template_id: str, req: TemplateUpdateRequest,
                    user: User = Depends(get_current_user),
                    svc: TemplateService = Depends(get_template_service)):
    return svc.update_template(user, template_id, req)


@router.delete("/{template_id}")
def delete_template(template_id: str, admin: User = Depends(require_admin_or_above),
                    svc: TemplateService = Depends(get_template_service)):
    return svc.delete_template(admin, template_id)


@router.post("/{template_id}/use")
def use_template(template_id: str, user: User = Depends(get_current_user),
                 svc: TemplateService = Depends(get_template_service)):
    return svc.record_use(template_id)


@router.post("/{template_id}/adapt")
def adapt_for_department(template_id: str,
                         hints: str = Body("", embed=True),
                         user: User = Depends(get_current_user),
                         svc: TemplateService = Depends(get_template_service)):
    """基于现有模板生成「本科室版」草案（AI 按本科室写作习惯调整）。

    只返回草案，不落库；科室由服务端解析。需人工确认后调用 /templates/department 保存。
    """
    return svc.adapt_for_department(user, template_id, hints)


@router.post("/department")
def save_department_template(payload: dict = Body(...),
                             user: User = Depends(get_current_user),
                             svc: TemplateService = Depends(get_template_service)):
    """人工确认后保存为本科室模板（department_code 由服务端写入）。"""
    return svc.save_department_template(user, payload)
