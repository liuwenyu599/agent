"""系统配置路由：公文与审批配置（文号代字 / 会签 / 用印 / 业务类型）。"""
from typing import Any, Dict

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.application.system.service import SystemService
from app.domain.identity.entities import User
from app.infrastructure.database import get_db
from app.interfaces.deps import get_current_user, require_admin_or_above

router = APIRouter(prefix="/system", tags=["系统配置"])


class ApprovalConfigRequest(BaseModel):
    doc_number_daizi: str = None
    countersign_enabled: Any = None
    seal_required: Any = None
    business_types: str = None


def get_system_service(db: Session = Depends(get_db)) -> SystemService:
    return SystemService(db)


@router.get("/approval-config")
def approval_config(
    user: User = Depends(get_current_user),
    svc: SystemService = Depends(get_system_service),
) -> Dict[str, Any]:
    return svc.get_approval_config()


@router.put("/approval-config")
def update_approval_config(
    req: ApprovalConfigRequest,
    user: User = Depends(require_admin_or_above),
    svc: SystemService = Depends(get_system_service),
) -> Dict[str, Any]:
    data = {k: v for k, v in req.dict(exclude_unset=True).items() if v is not None}
    return svc.upsert_approval_config(user, data)
