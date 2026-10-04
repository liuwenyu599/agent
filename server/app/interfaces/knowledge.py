"""知识库路由。路径与响应结构与旧系统一致（desktop 依赖该契约）。"""
import uuid
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from sqlalchemy.orm import Session

from app.application.chat.service import ChatService
from app.application.knowledge.hardened_document_service import HardenedDocumentService
from app.application.knowledge.dto import (
    DocUpdateRequest,
    KBCreateRequest,
    KBUpdateRequest,
    KnowledgeAskRequest,
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
from app.application.knowledge.upload_security import safe_client_filename, stream_upload_to_file
from app.application.knowledge.web_fetcher import extract_urls_from_text
from app.application.knowledge.web_import_service import (
    WebImportService,
    parse_urls_from_excel,
)
from app.core.config import settings
from app.application.knowledge.rag_service import RagService
from app.application.shared.writing_assistant import WritingAssistant
from app.infrastructure.ai import get_llm_gateway, get_vision_gateway
from app.core.exceptions import AppError
from app.core.logging import get_logger
from app.domain.identity.entities import ROLE_KNOWLEDGE_ADMIN, User
from app.infrastructure.database import get_db
from app.infrastructure.database.models.identity import UserModel
from app.infrastructure.database.models.chat import ChatMessageModel, ChatSessionModel
from app.infrastructure.rag import get_embedder, get_vector_store
from app.interfaces.deps import (
    get_current_user,
    require_admin_or_above,
    require_developer,
    require_knowledge_admin,
)

logger = get_logger(__name__)
router = APIRouter(prefix="/knowledge", tags=["知识库"])


def get_knowledge_service(db: Session = Depends(get_db)) -> KnowledgeService:
    return KnowledgeService(db)


def get_document_service() -> HardenedDocumentService:
    return HardenedDocumentService(embedder=get_embedder(), vector_store=get_vector_store())


def _archive_with_index_cleanup(doc_id: str, user: User, svc: KnowledgeService) -> dict:
    result = svc.archive_document(doc_id, user)
    try:
        removed = get_vector_store().delete_by_document(doc_id)
        result["indexing_status"] = "removed"
        result["removed_vectors"] = removed
    except Exception as exc:
        logger.exception("[RAG] 归档后物理删除向量失败: doc=%s", doc_id)
        result["indexing_status"] = "cleanup_failed"
        result["indexing_error"] = str(exc)[:500]
    return result


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
    svc.check_kb_write(kb_id, user)
    return await get_document_service().process_upload(
        file, kb_id, user.id, user.role, db,
        title=title, doc_type=doc_type, department=department, doc_number=doc_number,
    )


@router.get("/documents/{doc_id}")
def get_document(doc_id: str, user: User = Depends(get_current_user),
                 svc: KnowledgeService = Depends(get_knowledge_service)):
    result = svc.get_document_detail(doc_id, user)
    doc = svc.docs.get_model(doc_id)
    meta = dict((doc.doc_metadata if doc else None) or {})
    result["indexing_status"] = meta.get("indexing_status") or (
        "indexed" if result.get("status") == "published" else "pending_review"
    )
    if meta.get("indexing_error"):
        result["indexing_error"] = meta["indexing_error"]
    result["indexed_chunks"] = int(meta.get("indexed_chunks") or 0)
    return result


@router.put("/documents/{doc_id}")
def update_document(doc_id: str, req: DocUpdateRequest,
                    user: User = Depends(get_current_user),
                    db: Session = Depends(get_db),
                    svc: KnowledgeService = Depends(get_knowledge_service)):
    """更新文档元数据；传 content 时同步重新分块并重建该文档的向量索引。"""
    result = svc.update_document(doc_id, user, req.title, req.doc_type, req.status,
                                 req.department, req.doc_number)
    if req.content is not None:
        result = {**result,
                  **get_document_service().update_content(db, doc_id, req.content)}
    return result


@router.delete("/documents/{doc_id}")
def delete_document(doc_id: str, user: User = Depends(get_current_user),
                    svc: KnowledgeService = Depends(get_knowledge_service)):
    return _archive_with_index_cleanup(doc_id, user, svc)


@router.post("/documents/{doc_id}/reindex")
def retry_document_index(
    doc_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    svc: KnowledgeService = Depends(get_knowledge_service),
):
    """Retry a failed vectorization without re-uploading the source document."""
    doc = svc.docs.get_model(doc_id)
    if not doc:
        raise AppError(404, "文档不存在")
    if not (svc.access.can_manage_doc(doc, user) or doc.uploaded_by == user.id):
        raise AppError(403, "无权重建该文档索引")
    return get_document_service().retry_index(db, doc_id)


@router.get("/pending")
def list_pending_documents(user: User = Depends(require_knowledge_admin),
                           svc: KnowledgeService = Depends(get_knowledge_service)):
    """待审队列：知识管理员仅本人科室，系统管理员全部。"""
    return svc.list_pending(user)


@router.post("/review")
def review_document(req: ReviewRequest, user: User = Depends(get_current_user),
                    db: Session = Depends(get_db),
                    svc: KnowledgeService = Depends(get_knowledge_service)):
    """审核：知识管理员仅限本科室内容；系统管理员全局。"""
    svc.assert_can_review(req.doc_id, user)
    return get_document_service().review_document(req.doc_id, req.action, req.comment, user.id, db)


@router.get("/stats")
def get_stats(user: User = Depends(require_developer),
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
    return svc.list_all_documents(user, status, page, page_size)


@router.post("/documents/{doc_id}/archive")
def archive_document(doc_id: str, user: User = Depends(require_admin_or_above),
                     svc: KnowledgeService = Depends(get_knowledge_service)):
    return _archive_with_index_cleanup(doc_id, user, svc)


@router.post("/documents/{doc_id}/unarchive")
def unarchive_document(doc_id: str, user: User = Depends(require_admin_or_above),
                       db: Session = Depends(get_db),
                       svc: KnowledgeService = Depends(get_knowledge_service)):
    """恢复归档文档：退出归档状态并重新发布，随后重建向量索引。

    归档会物理删除向量，恢复必须补回索引，否则文档虽显示「已发布」却检索不到。
    """
    result = svc.unarchive_document(doc_id, user)
    try:
        result.update(get_document_service().retry_index(db, doc_id))
    except Exception as exc:  # 索引失败不影响状态恢复，用户可另行「重建索引」
        logger.exception("[RAG] 恢复归档后重建向量失败: doc=%s", doc_id)
        result["indexing_status"] = "failed"
        result["indexing_error"] = str(exc)[:500]
    return result


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


@router.get("/ask/sessions")
def list_knowledge_qa_sessions(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """仅返回当前用户的知识问答会话，按最近创建时间倒序。"""
    from sqlalchemy import select
    rows = db.scalars(
        select(ChatSessionModel)
        .join(ChatMessageModel, ChatMessageModel.session_id == ChatSessionModel.id)
        .where(
            ChatSessionModel.user_id == user.id,
            ChatMessageModel.source == "knowledge_qa",
        )
        .distinct()
        .order_by(ChatSessionModel.created_at.desc())
    ).all()
    return [{"id": s.id, "title": s.title or "未命名会话", "created_at": s.created_at}
            for s in rows]


@router.post("/ask")
def ask_knowledge(
    req: KnowledgeAskRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """科室空间知识问答。

    检索范围不接受客户端指定，固定由 RagService 按登录用户解析为：
    公共知识库 + 本科室知识库 + 本人个人知识库。
    图片附件自动走视觉模型；纯文本/文档走主语言模型。
    会话与消息复用 chat_sessions/chat_messages，因此自动进入“历史记录”。
    """
    question = (req.message or "").strip()
    if not question:
        raise AppError(400, "请输入问题")

    chat = ChatService(
        db,
        WritingAssistant(get_llm_gateway(), get_vision_gateway()),
        RagService(db, get_embedder(), get_vector_store()),
    )
    result = chat.send_message(
        user,
        message=question,
        session_id=req.session_id,
        use_rag=True,
        source="knowledge_qa",
        attachment_ids=req.attachment_ids or [],
        system_prompt=(
            "你是司法行政知识库问答助手。回答必须优先依据本轮检索到的知识库材料和用户附件；"
            "不得编造政策、文号、数字、人名或出处。检索材料不足时明确说明“现有知识库未检索到足够依据”。"
            "回答正文保持简洁清楚，不要伪造引用编号；引用由系统在答案下方结构化展示。"
        ),
    )
    return {
        "reply": result.get("reply", ""),
        "sources": result.get("sources", []),
        "attachments": result.get("attachments", []),
        "session_id": result.get("session_id"),
    }


@router.get("/{kb_id}")
def get_kb(kb_id: str, user: User = Depends(get_current_user),
           svc: KnowledgeService = Depends(get_knowledge_service)):
    kb = svc.get_kb_checked(kb_id, user)
    return svc.kb_to_dict(kb)


@router.put("/{kb_id}")
def update_kb(kb_id: str, req: KBUpdateRequest,
              user: User = Depends(require_knowledge_admin),
              svc: KnowledgeService = Depends(get_knowledge_service)):
    """编辑知识库：名称 / 描述 / 类型（类型调整的细粒度权限在服务端按角色校验）。"""
    return svc.update_kb(kb_id, req.name, req.description, user, req.kb_type)


@router.delete("/{kb_id}")
def delete_kb(kb_id: str, user: User = Depends(require_admin_or_above),
              svc: KnowledgeService = Depends(get_knowledge_service)):
    svc.get_kb_managed(kb_id, user)
    _, docs = svc.docs.list_by_kb(kb_id, page=1, page_size=100000)
    result = svc.delete_kb(kb_id, user)
    removed = 0
    cleanup_errors = []
    store = get_vector_store()
    for doc in docs:
        try:
            removed += int(store.delete_by_document(doc.id) or 0)
        except Exception as exc:
            logger.exception("[RAG] 删除知识库后物理删除向量失败: kb=%s doc=%s", kb_id, doc.id)
            cleanup_errors.append({"doc_id": doc.id, "error": str(exc)[:300]})
    result["removed_vectors"] = removed
    result["indexing_status"] = "cleanup_failed" if cleanup_errors else "removed"
    if cleanup_errors:
        result["indexing_errors"] = cleanup_errors
    return result


@router.get("/{kb_id}/documents")
def list_documents(kb_id: str, status: str = Query("published"),
                   page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                   sort: str = Query("newest"),
                   user: User = Depends(get_current_user),
                   svc: KnowledgeService = Depends(get_knowledge_service)):
    return svc.list_kb_documents(kb_id, user, status, page, page_size, sort)


@router.get("/{kb_id}/documents/search")
def search_documents(kb_id: str, q: str = Query(""), limit: int = Query(50),
                     user: User = Depends(get_current_user),
                     svc: KnowledgeService = Depends(get_knowledge_service)):
    """库内文档搜索：标题命中排前、内容命中排后，一次请求返回全部结果。"""
    return svc.search_kb_documents(kb_id, user, q, limit)


@router.post("/batch-upload")
async def batch_upload(kb_id: str = Query(...), files: List[UploadFile] = File(...),
                       user: User = Depends(get_current_user),
                       svc: KnowledgeService = Depends(get_knowledge_service)):
    svc.check_kb_write(kb_id, user)
    if not files:
        raise AppError(400, "未选择文件")
    tmp_dir = settings.DATA_DIR / "tmp" / "batch"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    staged = []
    try:
        for file in files:
            original_name, suffix = safe_client_filename(
                file.filename or "", settings.SUPPORTED_DOC_TYPES
            )
            tmp_path = tmp_dir / f"{uuid.uuid4().hex}{suffix}"
            await stream_upload_to_file(file, tmp_path, settings.UPLOAD_MAX_SIZE)
            staged.append((tmp_path, original_name))
    except Exception:
        for path, _ in staged:
            path.unlink(missing_ok=True)
        raise

    task = BatchImportTask(kb_id=kb_id, user_id=user.id, total_files=len(staged))
    for tmp_path, original_name in staged:
        submit_task(task_id=task.id, file_path=str(tmp_path), kb_id=kb_id,
                    user_id=user.id, user_role=user.role, original_name=original_name)
    return {"task_id": task.id, "total_files": len(staged), "status": "pending",
            "message": f"已提交 {len(staged)} 个文件到处理队列"}


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
    data = await file.read(settings.UPLOAD_MAX_SIZE + 1)
    if len(data) > settings.UPLOAD_MAX_SIZE:
        raise AppError(413, "Excel 文件超过上传大小限制")
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
