"""写作模板路由。路径与响应结构与旧系统一致。"""
from typing import Optional

from fastapi import APIRouter, Depends

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
