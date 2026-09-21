"""公文审核流转路由（v3.0）

所有写操作均走 ApprovalService.transition() 单一入口，权限由权限码在 service 内判定。
流程不依赖任何 AI 能力。
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.application.approval.service import ApprovalService
from app.domain.identity.entities import User
from app.infrastructure.database import get_db
from app.interfaces.deps import get_current_user

router = APIRouter(prefix="/approvals", tags=["审核流转"])


class SubmitRequest(BaseModel):
    document_id: str
    flow: Optional[List[str]] = None
    urgency: str = "normal"


class ActionRequest(BaseModel):
    action: str
    comment: str = ""


class NumberRequest(BaseModel):
    daizi: str = ""


def get_approval_service(db: Session = Depends(get_db)) -> ApprovalService:
    return ApprovalService(db)


@router.post("")
def submit(req: SubmitRequest,
           user: User = Depends(get_current_user),
           svc: ApprovalService = Depends(get_approval_service)):
    return svc.submit(user, req.document_id, req.flow, req.urgency)


@router.get("")
def list_approvals(view: str = Query("todo"),
                   page: int = Query(1),
                   page_size: int = Query(20),
                   user: User = Depends(get_current_user),
                   svc: ApprovalService = Depends(get_approval_service)):
    return svc.list(user, view, page, page_size)


@router.get("/counts")
def counts(user: User = Depends(get_current_user),
           svc: ApprovalService = Depends(get_approval_service)):
    return svc.counts(user)


@router.get("/{instance_id}")
def detail(instance_id: str,
           user: User = Depends(get_current_user),
           svc: ApprovalService = Depends(get_approval_service)):
    return svc.detail(user, instance_id)


@router.get("/{instance_id}/actions")
def actions(instance_id: str,
            user: User = Depends(get_current_user),
            svc: ApprovalService = Depends(get_approval_service)):
    return svc.actions(user, instance_id)


@router.post("/{instance_id}/action")
def do_action(instance_id: str, req: ActionRequest,
              user: User = Depends(get_current_user),
              svc: ApprovalService = Depends(get_approval_service)):
    return svc.transition(user, instance_id, req.action, req.comment)


@router.post("/{instance_id}/number")
def assign_number(instance_id: str, req: NumberRequest,
                  user: User = Depends(get_current_user),
                  svc: ApprovalService = Depends(get_approval_service)):
    return svc.assign_number(user, instance_id, req.daizi)
