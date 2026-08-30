"""知识库路由。路径与响应结构与旧系统一致（desktop 依赖该契约）。"""
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from sqlalchemy.orm import Session

from app.application.knowledge.document_service import DocumentService
from app.application.knowledge.dto import (
    DocUpdateRequest,
    KBCreateRequest,
    KBUpdateRequest,
    ReviewRequest,
    UrlImportRequest,
    UrlTextImportRequest,
)
from app.application.knowledge.service import KnowledgeService
from app.application.knowledge.task_queue import (
    BatchImportTask,
    get_queue_status,
    submit_task,
)
from app.application.knowledge.web_fetcher import extract_urls_from_text
from app.application.knowledge.web_import_service import (
    WebImportService,
    parse_urls_from_excel,
)
from app.core.config import settings
from app.core.exceptions import AppError
from app.domain.identity.entities import ROLE_KNOWLEDGE_ADMIN, User
from app.infrastructure.database import get_db
from app.infrastructure.database.models.identity import UserModel
from app.infrastructure.rag import get_embedder, get_vector_store
from app.interfaces.deps import (
    get_current_user,
    require_admin_or_above,
    require_knowledge_admin,
)

router = APIRouter(prefix="/knowledge", tags=["知识库"])


def get_knowledge_service(db: Session = Depends(get_db)) -> KnowledgeService:
    return KnowledgeService(db)


def get_document_service() -> DocumentService:
    return DocumentService(embedder=get_embedder(), vector_store=get_vector_store())


@router.get("/list")
def list_kbs(user: User = Depends(get_current_user),
             svc: KnowledgeService = Depends(get_knowledge_service)):
    return svc.list_accessible(user)


@router.post("/create")
def create_kb(req: KBCreateRequest, user: User = Depends(get_current_user),
              svc: KnowledgeService = Depends(get_knowledge_service)):
    return svc.create_kb(user, req.name, req.description, req.kb_type)


@router.post("/upload")
async def upload_document(
    kb_id: str = Query(...),
    title: Optional[str] = Form(None),
    doc_type: Optional[str] = Form(None),
    department: Optional[str] = Form(None),
    doc_number: Optional[str] = Form(None),
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    svc: KnowledgeService = Depends(get_knowledge_service),
):
    svc.get_kb_checked(kb_id, user)
    return await get_document_service().process_upload(
        file, kb_id, user.id, user.role, db,
        title=title, doc_type=doc_type, department=department, doc_number=doc_number,
    )


@router.get("/documents/{doc_id}")
def get_document(doc_id: str, user: User = Depends(get_current_user),
                 svc: KnowledgeService = Depends(get_knowledge_service)):
    return svc.get_document_detail(doc_id, user)


@router.put("/documents/{doc_id}")
def update_document(doc_id: str, req: DocUpdateRequest,
                    user: User = Depends(get_current_user),
                    svc: KnowledgeService = Depends(get_knowledge_service)):
    return svc.update_document(doc_id, user, req.title, req.doc_type, req.status,
                               req.department, req.doc_number)


@router.delete("/documents/{doc_id}")
def delete_document(doc_id: str, user: User = Depends(get_current_user),
                    svc: KnowledgeService = Depends(get_knowledge_service)):
    return svc.archive_document(doc_id, user)


@router.get("/pending")
def list_pending_documents(user: User = Depends(require_knowledge_admin),
                           svc: KnowledgeService = Depends(get_knowledge_service)):
    return svc.list_pending()


@router.post("/review")
def review_document(req: ReviewRequest, user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    # 仅知识管理员可审核，系统管理员不可审核（旧规则）
    if user.role != ROLE_KNOWLEDGE_ADMIN:
        raise AppError(403, "仅知识管理员可执行审核操作")
    return get_document_service().review_document(req.doc_id, req.action, req.comment, user.id, db)


@router.get("/stats")
def get_stats(user: User = Depends(require_admin_or_above),
              db: Session = Depends(get_db),
              svc: KnowledgeService = Depends(get_knowledge_service)):
    from sqlalchemy import select
    from app.infrastructure.database.models.chat import ChatSessionModel
    user_count = len(db.scalars(select(UserModel.id)).all())
    session_count = len(db.scalars(select(ChatSessionModel.id)).all())
    return svc.stats(user_count, session_count)


@router.get("/documents")
def list_all_documents(status: str = Query("all"),
                       user: User = Depends(require_admin_or_above),
                       page: int = Query(1), page_size: int = Query(20),
                       svc: KnowledgeService = Depends(get_knowledge_service)):
    return svc.list_all_documents(status, page, page_size)


@router.post("/documents/{doc_id}/archive")
def archive_document(doc_id: str, user: User = Depends(require_admin_or_above),
                     svc: KnowledgeService = Depends(get_knowledge_service)):
    return svc.archive_document(doc_id)


@router.get("/{kb_id}")
def get_kb(kb_id: str, user: User = Depends(get_current_user),
           svc: KnowledgeService = Depends(get_knowledge_service)):
    kb = svc.get_kb_checked(kb_id, user)
    return svc.kb_to_dict(kb)


@router.put("/{kb_id}")
def update_kb(kb_id: str, req: KBUpdateRequest,
              user: User = Depends(require_knowledge_admin),
              svc: KnowledgeService = Depends(get_knowledge_service)):
    return svc.update_kb(kb_id, req.name, req.description)


@router.delete("/{kb_id}")
def delete_kb(kb_id: str, user: User = Depends(require_admin_or_above),
              svc: KnowledgeService = Depends(get_knowledge_service)):
    return svc.delete_kb(kb_id)


@router.get("/{kb_id}/documents")
def list_documents(kb_id: str, status: str = Query("published"),
                   page: int = Query(1), page_size: int = Query(20),
                   user: User = Depends(get_current_user),
                   svc: KnowledgeService = Depends(get_knowledge_service)):
    return svc.list_kb_documents(kb_id, user, status, page, page_size)


@router.post("/batch-upload")
async def batch_upload(kb_id: str = Query(...), files: List[UploadFile] = File(...),
                       user: User = Depends(get_current_user),
                       svc: KnowledgeService = Depends(get_knowledge_service)):
    svc.get_kb_checked(kb_id, user)
    task = BatchImportTask(kb_id=kb_id, user_id=user.id, total_files=len(files))
    tmp_dir = settings.DATA_DIR / "tmp" / "batch"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    for file in files:
        tmp_path = tmp_dir / f"{task.id}_{file.filename}"
        content_data = await file.read()
        with open(tmp_path, "wb") as f:
            f.write(content_data)
        submit_task(task_id=task.id, file_path=str(tmp_path), kb_id=kb_id,
                    user_id=user.id, user_role=user.role, original_name=file.filename)
    return {"task_id": task.id, "total_files": len(files), "status": "pending",
            "message": f"已提交 {len(files)} 个文件到处理队列"}


@router.get("/batch-tasks")
def list_batch_tasks(user: User = Depends(get_current_user)):
    return {"tasks": BatchImportTask.list_by_user(user.id)}


@router.get("/batch-tasks/{task_id}")
def get_batch_task(task_id: str, user: User = Depends(get_current_user)):
    task = BatchImportTask.get(task_id)
    if not task:
        raise AppError(404, "Task not found")
    if task["user_id"] != user.id:
        raise AppError(403, "No permission")
    return task


@router.get("/queue-status")
def queue_status(user: User = Depends(require_knowledge_admin)):
    return get_queue_status()


# ========== 网页链接导入知识库 ==========

@router.post("/import-urls")
def import_urls(req: UrlImportRequest, user: User = Depends(get_current_user),
                db: Session = Depends(get_db),
                svc: KnowledgeService = Depends(get_knowledge_service)):
    kb = svc.check_kb_write(req.kb_id, user)
    urls = [u.strip() for u in req.urls if u and u.strip()]
    if not urls:
        raise AppError(400, "未提供有效链接")
    if len(urls) > 500:
        raise AppError(400, "单次最多导入 500 个链接")
    items = [{"url": u} for u in urls]
    return WebImportService(doc_service=get_document_service()).import_urls(
        db, kb.id, user.id, user.role, items
    )


@router.post("/import-urls-text")
def import_urls_text(req: UrlTextImportRequest, user: User = Depends(get_current_user),
                     db: Session = Depends(get_db),
                     svc: KnowledgeService = Depends(get_knowledge_service)):
    kb = svc.check_kb_write(req.kb_id, user)
    urls = extract_urls_from_text(req.text)
    if not urls:
        raise AppError(400, "文本中未识别到 http(s) 链接")
    items = [{"url": u} for u in urls]
    return WebImportService(doc_service=get_document_service()).import_urls(
        db, kb.id, user.id, user.role, items
    )


@router.post("/import-urls-excel")
async def import_urls_excel(kb_id: str = Query(...), file: UploadFile = File(...),
                            user: User = Depends(get_current_user),
                            db: Session = Depends(get_db),
                            svc: KnowledgeService = Depends(get_knowledge_service)):
    kb = svc.check_kb_write(kb_id, user)
    filename = file.filename or ""
    if not filename.lower().endswith((".xlsx", ".xlsm", ".xltx", ".xltm")):
        raise AppError(400, "请上传 .xlsx 格式的 Excel 文件")
    data = await file.read()
    try:
        items = parse_urls_from_excel(data, filename)
    except ValueError as e:
        raise AppError(400, str(e))
    if not items:
        raise AppError(400, "Excel 中未识别到任何 http(s) 链接")
    if len(items) > 1000:
        raise AppError(400, "单次最多导入 1000 条")
    return WebImportService(doc_service=get_document_service()).import_urls(
        db, kb.id, user.id, user.role, items
    )
