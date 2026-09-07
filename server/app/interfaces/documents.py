"""我的文档：文档与版本管理路由。

- 所有接口强制登录，且只能访问本人文档（服务端按 user_id 过滤）
- 保存编辑 = 新增版本快照，历史版本可回溯、可导出
"""
from urllib.parse import quote

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.application.chat.docx_export import generate_official_document
from app.application.documents.dto import (
    DocumentCreateRequest,
    DocumentSaveRequest,
)
from app.application.documents.service import DocumentService
from app.domain.identity.entities import User
from app.infrastructure.database import get_db
from app.interfaces.deps import get_current_user

router = APIRouter(prefix="/documents", tags=["我的文档"])

_DOCX_MEDIA = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def get_document_service(db: Session = Depends(get_db)) -> DocumentService:
    return DocumentService(db)


@router.get("")
def list_documents(
    user: User = Depends(get_current_user),
    svc: DocumentService = Depends(get_document_service),
):
    return {"items": svc.list_documents(user.id)}


@router.post("", status_code=201)
def create_document(
    req: DocumentCreateRequest,
    user: User = Depends(get_current_user),
    svc: DocumentService = Depends(get_document_service),
):
    return svc.create_document(user.id, req)


@router.get("/{doc_id}")
def get_document(
    doc_id: str,
    user: User = Depends(get_current_user),
    svc: DocumentService = Depends(get_document_service),
):
    return svc.get_document(doc_id, user.id)


@router.put("/{doc_id}")
def save_document_version(
    doc_id: str,
    req: DocumentSaveRequest,
    user: User = Depends(get_current_user),
    svc: DocumentService = Depends(get_document_service),
):
    return svc.save_version(doc_id, user.id, req)


@router.get("/{doc_id}/versions/{version_no}")
def get_document_version(
    doc_id: str,
    version_no: int,
    user: User = Depends(get_current_user),
    svc: DocumentService = Depends(get_document_service),
):
    return svc.get_version(doc_id, version_no, user.id)


@router.delete("/{doc_id}", status_code=204)
def delete_document(
    doc_id: str,
    user: User = Depends(get_current_user),
    svc: DocumentService = Depends(get_document_service),
):
    svc.delete_document(doc_id, user.id)


@router.get("/{doc_id}/export/docx")
def export_document_docx(
    doc_id: str,
    version_no: int | None = None,
    user: User = Depends(get_current_user),
    svc: DocumentService = Depends(get_document_service),
):
    """导出指定版本（默认当前版本）为党政机关公文格式 Word。"""
    doc = svc.get_document(doc_id, user.id)
    if version_no is not None:
        content = svc.get_version(doc_id, version_no, user.id)["content"]
    else:
        content = doc["content"]
    buf = generate_official_document(
        content=content, title=doc["title"],
        doc_number=doc.get("document_number") or "",
        recipient="", signature="", date_text=doc.get("document_date") or "",
    )
    fname = quote(f"{doc['title']}.docx")
    return StreamingResponse(buf, media_type=_DOCX_MEDIA, headers={
        "Content-Disposition": f"attachment; filename*=UTF-8''{fname}"
    })
