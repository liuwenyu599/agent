from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query, Form
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional
from pathlib import Path

from backend.database.postgres import get_db
from backend.database.models import KnowledgeBase, Document, User, ChatSession
from backend.auth.permission import get_current_user, require_knowledge_admin, require_admin_or_above
from backend.knowledge.manager import KnowledgeManager
from backend.services.document_service import DocumentService
from backend.services.task_queue import BatchImportTask, submit_task, get_queue_status
from backend.infrastructure.embedding.bge_embedder import BGEEmbedder

router = APIRouter(prefix="/knowledge", tags=["知识库"])

class KBCreateRequest(BaseModel):
    name: str
    description: str = ""
    kb_type: Optional[str] = None

class KBUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None

class ReviewRequest(BaseModel):
    doc_id: str
    action: str
    comment: str = ""

class DocUpdateRequest(BaseModel):
    title: Optional[str] = None
    doc_type: Optional[str] = None
    status: Optional[str] = None
    department: Optional[str] = None
    doc_number: Optional[str] = None

embedder = BGEEmbedder()
doc_service = DocumentService(embedder=embedder)

@router.get("/list")
async def list_kbs(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    manager = KnowledgeManager(db)
    kbs = manager.list_accessible_kbs(user.id, user.role)
    return [{"id": kb.id, "name": kb.name, "type": kb.kb_type, "description": kb.description, "doc_count": len([d for d in kb.documents if d.status == "published"]), "created_at": kb.created_at} for kb in kbs]

@router.post("/create")
async def create_kb(req: KBCreateRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    manager = KnowledgeManager(db)
    # 管理员可以创建公共知识库
    if user.role in ["developer", "knowledge_admin", "admin"]:
        kb_type = req.kb_type or "public"
        if kb_type == "public":
            kb = manager.create_public_kb(req.name, req.description)
            return {"id": kb.id, "name": kb.name, "type": "public"}
        else:
            kb = manager.get_or_create_personal_kb(user.id)
            kb.name = req.name or kb.name
            kb.description = req.description or kb.description
            db.commit()
            return {"id": kb.id, "name": kb.name, "type": "personal"}
    # 普通用户只能创建个人知识库
    kb = manager.get_or_create_personal_kb(user.id)
    kb.name = req.name or kb.name
    kb.description = req.description or kb.description
    db.commit()
    return {"id": kb.id, "name": kb.name, "type": "personal"}
@router.post("/upload")
async def upload_document(
    kb_id: str = Query(...),
    title: Optional[str] = Form(None),
    doc_type: Optional[str] = Form(None),
    department: Optional[str] = Form(None),
    doc_number: Optional[str] = Form(None),
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).first()
    if not kb: raise HTTPException(status_code=404, detail="Knowledge base not found")
    if kb.kb_type == "personal" and kb.owner_id != user.id: raise HTTPException(status_code=403, detail="No permission")
    result = await doc_service.process_upload(
        file, kb_id, user.id, user.role, db,
        title=title, doc_type=doc_type, department=department, doc_number=doc_number
    )
    return result

@router.get("/documents/{doc_id}")
async def get_document(doc_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc: raise HTTPException(status_code=404, detail="Document not found")
    kb = doc.knowledge_base
    if kb.kb_type == "personal" and kb.owner_id != user.id: raise HTTPException(status_code=403, detail="No permission")
    if user.role not in ["knowledge_admin", "developer"] and doc.status != "published": raise HTTPException(status_code=403, detail="Document not available")
    return {
        "id": doc.id, "title": doc.title, "doc_type": doc.doc_type, "status": doc.status,
        "content": doc.content or "", "department": doc.department, "doc_number": doc.doc_number,
        "uploaded_by": doc.uploader.real_name if doc.uploader else None,
        "reviewed_by": doc.reviewer.real_name if doc.reviewer else None,
        "review_comment": doc.review_comment, "created_at": doc.created_at
    }

@router.put("/documents/{doc_id}")
async def update_document(doc_id: str, req: DocUpdateRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc: raise HTTPException(status_code=404, detail="Document not found")
    if doc.uploaded_by != user.id and user.role not in ["knowledge_admin", "developer"]: raise HTTPException(status_code=403, detail="No permission")
    if req.title is not None: doc.title = req.title
    if req.doc_type is not None: doc.doc_type = req.doc_type
    if req.status is not None and user.role in ["knowledge_admin", "developer"]: doc.status = req.status
    if req.department is not None: doc.department = req.department
    if req.doc_number is not None: doc.doc_number = req.doc_number
    db.commit()
    return {"id": doc.id, "message": "Updated"}

@router.delete("/documents/{doc_id}")
async def delete_document(doc_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc: raise HTTPException(status_code=404, detail="Document not found")
    if doc.uploaded_by != user.id and user.role not in ["knowledge_admin", "developer"]: raise HTTPException(status_code=403, detail="No permission")
    doc.status = "archived"
    db.commit()
    return {"message": "Document archived"}

@router.get("/pending")
async def list_pending_documents(user: User = Depends(require_knowledge_admin), db: Session = Depends(get_db)):
    docs = db.query(Document).filter(Document.status == "pending").all()
    return [{"id": d.id, "title": d.title, "doc_type": d.doc_type, "uploaded_by": d.uploader.real_name if d.uploader else None, "uploaded_at": d.created_at, "kb_name": d.knowledge_base.name if d.knowledge_base else None} for d in docs]

@router.post("/review")
async def review_document(req: ReviewRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    # 仅知识管理员可审核，系统管理员不可审核
    if user.role != "knowledge_admin":
        raise HTTPException(status_code=403, detail="仅知识管理员可执行审核操作")
    result = doc_service.review_document(req.doc_id, req.action, req.comment, user.id, db)
    return result

@router.get("/stats")
async def get_stats(user: User = Depends(require_knowledge_admin), db: Session = Depends(get_db)):
    total_docs = db.query(Document).count()
    published_docs = db.query(Document).filter(Document.status == "published").count()
    pending_docs = db.query(Document).filter(Document.status == "pending").count()
    users = db.query(User).count()
    kb_count = db.query(KnowledgeBase).filter(KnowledgeBase.is_active == True).count()
    session_count = db.query(ChatSession).count()
    return {"user_count": users, "doc_count": total_docs, "session_count": session_count, "kb_count": kb_count, "published": published_docs, "pending": pending_docs}

@router.get("/documents")
async def list_all_documents(status: str = Query("all"), user: User = Depends(require_admin_or_above), db: Session = Depends(get_db), page: int = Query(1), page_size: int = Query(20)):
    query = db.query(Document)
    if status != "all": query = query.filter(Document.status == status)
    total = query.count()
    docs = query.order_by(Document.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return {"total": total, "page": page, "page_size": page_size, "data": [{"id": d.id, "title": d.title, "doc_type": d.doc_type, "status": d.status, "kb_name": d.knowledge_base.name if d.knowledge_base else "", "uploader_name": d.uploader.real_name if d.uploader else "", "reviewer_name": d.reviewer.real_name if d.reviewer else "", "review_comment": d.review_comment, "reviewed_at": d.reviewed_at, "created_at": d.created_at} for d in docs]}

@router.post("/documents/{doc_id}/archive")
async def archive_document(doc_id: str, user: User = Depends(require_admin_or_above), db: Session = Depends(get_db)):
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc: raise HTTPException(status_code=404, detail="Document not found")
    doc.status = "archived"
    db.commit()
    return {"message": "Document archived"}

@router.get("/{kb_id}")
async def get_kb(kb_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).first()
    if not kb: raise HTTPException(status_code=404, detail="Knowledge base not found")
    if kb.kb_type == "personal" and kb.owner_id != user.id: raise HTTPException(status_code=403, detail="No permission")
    return {"id": kb.id, "name": kb.name, "type": kb.kb_type, "description": kb.description, "doc_count": len([d for d in kb.documents if d.status == "published"]), "created_at": kb.created_at}

@router.put("/{kb_id}")
async def update_kb(kb_id: str, req: KBUpdateRequest, user: User = Depends(require_knowledge_admin), db: Session = Depends(get_db)):
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).first()
    if not kb: raise HTTPException(status_code=404, detail="Knowledge base not found")
    if req.name is not None: kb.name = req.name
    if req.description is not None: kb.description = req.description
    db.commit()
    return {"id": kb.id, "message": "Updated"}

@router.delete("/{kb_id}")
async def delete_kb(kb_id: str, user: User = Depends(require_admin_or_above), db: Session = Depends(get_db)):
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).first()
    if not kb: raise HTTPException(status_code=404, detail="Knowledge base not found")
    for doc in kb.documents: doc.status = "archived"
    kb.is_active = False
    db.commit()
    return {"message": "Knowledge base deleted"}

@router.get("/{kb_id}/documents")
async def list_documents(kb_id: str, status: str = Query("published"), page: int = Query(1), page_size: int = Query(20), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).first()
    if not kb: raise HTTPException(status_code=404, detail="Knowledge base not found")
    if kb.kb_type == "personal" and kb.owner_id != user.id: raise HTTPException(status_code=403, detail="No permission")
    query = db.query(Document).filter(Document.kb_id == kb_id)
    if user.role not in ["knowledge_admin", "developer"]: query = query.filter(Document.status == "published")
    elif status != "all": query = query.filter(Document.status == status)
    total = query.count()
    docs = query.offset((page - 1) * page_size).limit(page_size).all()
    return {"total": total, "page": page, "page_size": page_size, "data": [{"id": d.id, "title": d.title, "doc_type": d.doc_type, "status": d.status, "department": d.department, "doc_number": d.doc_number, "uploaded_by": d.uploader.real_name if d.uploader else None, "reviewed_by": d.reviewer.real_name if d.reviewer else None, "review_comment": d.review_comment, "created_at": d.created_at} for d in docs]}

@router.post("/batch-upload")
async def batch_upload(kb_id: str = Query(...), files: List[UploadFile] = File(...), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).first()
    if not kb: raise HTTPException(status_code=404, detail="Knowledge base not found")
    if kb.kb_type == "personal" and kb.owner_id != user.id: raise HTTPException(status_code=403, detail="No permission")
    task = BatchImportTask(kb_id=kb_id, user_id=user.id, total_files=len(files))
    tmp_dir = Path("/tmp/judicial-batch")
    tmp_dir.mkdir(exist_ok=True)
    for file in files:
        tmp_path = tmp_dir / f"{task.id}_{file.filename}"
        content_data = await file.read()
        with open(tmp_path, "wb") as f: f.write(content_data)
        submit_task(task_id=task.id, file_path=str(tmp_path), kb_id=kb_id, user_id=user.id, user_role=user.role, original_name=file.filename)
    return {"task_id": task.id, "total_files": len(files), "status": "pending", "message": f"已提交 {len(files)} 个文件到处理队列"}

@router.get("/batch-tasks")
async def list_batch_tasks(user: User = Depends(get_current_user)):
    tasks = BatchImportTask.list_by_user(user.id)
    return {"tasks": tasks}

@router.get("/batch-tasks/{task_id}")
async def get_batch_task(task_id: str, user: User = Depends(get_current_user)):
    task = BatchImportTask.get(task_id)
    if not task: raise HTTPException(status_code=404, detail="Task not found")
    if task["user_id"] != user.id: raise HTTPException(status_code=403, detail="No permission")
    return task

@router.get("/queue-status")
async def queue_status(user: User = Depends(require_knowledge_admin)):
    return get_queue_status()

# ========== 网页链接导入知识库 ==========
from backend.services.web_import_service import WebImportService, parse_urls_from_excel
from backend.services.web_fetcher import extract_urls_from_text

class UrlImportRequest(BaseModel):
    kb_id: str
    urls: List[str]

class UrlTextImportRequest(BaseModel):
    """批量粘贴文本（每行一个或多个链接）"""
    kb_id: str
    text: str

web_import_service = WebImportService(doc_service=doc_service)

def _check_kb_write(kb_id: str, user: User, db: Session) -> KnowledgeBase:
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).first()
    if not kb: raise HTTPException(status_code=404, detail="Knowledge base not found")
    if kb.kb_type == "personal" and kb.owner_id != user.id: raise HTTPException(status_code=403, detail="No permission")
    if kb.kb_type == "public" and user.role not in ["knowledge_admin", "developer", "admin"]:
        raise HTTPException(status_code=403, detail="公共知识库仅管理员可导入")
    return kb

@router.post("/import-urls")
async def import_urls(req: UrlImportRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """导入一个或多个网页链接。单个失败不影响其他（部分成功）。"""
    kb = _check_kb_write(req.kb_id, user, db)
    urls = [u.strip() for u in req.urls if u and u.strip()]
    if not urls:
        raise HTTPException(status_code=400, detail="未提供有效链接")
    if len(urls) > 500:
        raise HTTPException(status_code=400, detail="单次最多导入 500 个链接")
    items = [{"url": u} for u in urls]
    return web_import_service.import_urls(db, kb.id, user.id, user.role, items)

@router.post("/import-urls-text")
async def import_urls_text(req: UrlTextImportRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """粘贴一段文本（可含多个链接），自动识别并导入"""
    kb = _check_kb_write(req.kb_id, user, db)
    urls = extract_urls_from_text(req.text)
    if not urls:
        raise HTTPException(status_code=400, detail="文本中未识别到 http(s) 链接")
    items = [{"url": u} for u in urls]
    return web_import_service.import_urls(db, kb.id, user.id, user.role, items)

@router.post("/import-urls-excel")
async def import_urls_excel(kb_id: str = Query(...), file: UploadFile = File(...),
                            user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """从 Excel 批量导入链接（如外宣统计表：标题/媒体/刊发时间/佐证材料列）。

    Excel 中的标题、媒体、刊发时间优先作为文档元数据，网页抓取结果兜底。
    """
    kb = _check_kb_write(kb_id, user, db)
    filename = file.filename or ""
    if not filename.lower().endswith((".xlsx", ".xlsm", ".xltx", ".xltm")):
        raise HTTPException(status_code=400, detail="请上传 .xlsx 格式的 Excel 文件")
    data = await file.read()
    try:
        items = parse_urls_from_excel(data, filename)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not items:
        raise HTTPException(status_code=400, detail="Excel 中未识别到任何 http(s) 链接")
    if len(items) > 1000:
        raise HTTPException(status_code=400, detail="单次最多导入 1000 条")
    return web_import_service.import_urls(db, kb.id, user.id, user.role, items)
