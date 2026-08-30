"""写作参考材料路由。路径与响应结构与旧系统一致。"""
from typing import Optional

from fastapi import APIRouter, Depends, File, Query, UploadFile
from sqlalchemy.orm import Session

from app.application.knowledge.document_service import DocumentService
from app.application.references.dto import (
    PromoteRequest,
    TaskTextRefRequest,
    TaskUrlRefRequest,
    TemplateTextRefRequest,
    TemplateUrlRefRequest,
)
from app.application.references.service import ReferenceService
from app.domain.identity.entities import User
from app.infrastructure.database import get_db
from app.infrastructure.rag import get_embedder, get_vector_store
from app.interfaces.deps import get_current_user, require_admin_or_above

router = APIRouter(prefix="/references", tags=["写作参考材料"])


def get_reference_service(db: Session = Depends(get_db)) -> ReferenceService:
    return ReferenceService(db)


# ========== A. 模板固定参考材料（管理员维护） ==========

@router.get("/template/{template_id}")
def list_template_refs(template_id: str, user: User = Depends(get_current_user),
                       svc: ReferenceService = Depends(get_reference_service)):
    return svc.list_template_refs(template_id)


@router.post("/template/{template_id}/upload")
async def upload_template_ref(template_id: str, file: UploadFile = File(...),
                              admin: User = Depends(require_admin_or_above),
                              svc: ReferenceService = Depends(get_reference_service)):
    parsed = await svc.parse_upload(file, admin.id, "template")
    return svc.add_template_ref_file(template_id, parsed, admin)


@router.post("/template/{template_id}/text")
def add_template_text_ref(template_id: str, req: TemplateTextRefRequest,
                          admin: User = Depends(require_admin_or_above),
                          svc: ReferenceService = Depends(get_reference_service)):
    return svc.add_template_ref_text(template_id, req.name, req.text, admin)


@router.post("/template/{template_id}/url")
def add_template_url_ref(template_id: str, req: TemplateUrlRefRequest,
                         admin: User = Depends(require_admin_or_above),
                         svc: ReferenceService = Depends(get_reference_service)):
    return svc.add_template_ref_url(template_id, req.url, req.name, admin)


@router.delete("/template/refs/{ref_id}")
def delete_template_ref(ref_id: str, admin: User = Depends(require_admin_or_above),
                        svc: ReferenceService = Depends(get_reference_service)):
    return svc.delete_template_ref(ref_id)


# ========== B. 当前任务佐证材料（归属用户本人，不进知识库） ==========

@router.get("/task")
def list_task_refs(template_id: Optional[str] = Query(None),
                   session_id: Optional[str] = Query(None),
                   user: User = Depends(get_current_user),
                   svc: ReferenceService = Depends(get_reference_service)):
    return svc.list_task_refs(user, template_id, session_id)


@router.post("/task/upload")
async def upload_task_ref(file: UploadFile = File(...),
                          template_id: Optional[str] = Query(None),
                          user: User = Depends(get_current_user),
                          svc: ReferenceService = Depends(get_reference_service)):
    parsed = await svc.parse_upload(file, user.id, "task")
    return svc.add_task_ref_file(user, parsed, template_id)


@router.post("/task/text")
def add_task_text_ref(req: TaskTextRefRequest, user: User = Depends(get_current_user),
                      svc: ReferenceService = Depends(get_reference_service)):
    return svc.add_task_ref_text(user, req.text, req.name, req.template_id)


@router.post("/task/url")
def add_task_url_ref(req: TaskUrlRefRequest, user: User = Depends(get_current_user),
                     svc: ReferenceService = Depends(get_reference_service)):
    return svc.add_task_ref_url(user, req.url, req.name, req.template_id)


@router.delete("/task/{ref_id}")
def delete_task_ref(ref_id: str, user: User = Depends(get_current_user),
                    svc: ReferenceService = Depends(get_reference_service)):
    return svc.delete_task_ref(ref_id, user)


@router.post("/task/{ref_id}/promote")
def promote_task_ref(ref_id: str, req: PromoteRequest,
                     user: User = Depends(get_current_user),
                     db: Session = Depends(get_db),
                     svc: ReferenceService = Depends(get_reference_service)):
    doc_service = DocumentService(embedder=get_embedder(), vector_store=get_vector_store())
    return svc.promote_task_ref(ref_id, req.kb_id, user, doc_service)
