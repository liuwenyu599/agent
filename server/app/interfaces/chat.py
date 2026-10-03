"""对话路由。路径与响应结构与旧系统一致。"""
import os
from typing import List
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.application.chat.async_service import AsyncChatService
from app.application.chat.attachment_service import AttachmentService
from app.application.chat.docx_export import generate_official_document, markdown_to_docx
from app.application.chat.dto import (
    ChatRequest,
    ChatResponse,
    ExportRequest,
    FeedbackRequest,
    OfficialExportRequest,
    SessionRenameRequest,
)
from app.application.chat.feedback_service import FeedbackService
from app.application.knowledge.rag_service import RagService
from app.application.shared.async_writing_assistant import AsyncWritingAssistant
from app.core.config import settings
from app.core.exceptions import AppError, NotFoundError
from app.domain.identity.entities import User
from app.infrastructure.ai import get_llm_gateway, get_vision_gateway
from app.infrastructure.database import get_db
from app.infrastructure.database.models.chat import AIResponseFeedbackModel, ChatMessageModel
from app.infrastructure.rag import get_embedder, get_vector_store
from app.infrastructure.repositories.chat import (
    SqlAlchemyChatMessageRepository,
    SqlAlchemyChatSessionRepository,
)
from app.infrastructure.repositories.feedback import SqlAlchemyChatFeedbackRepository
from app.interfaces.deps import get_current_user, require_admin_or_above

router = APIRouter(prefix="/chat", tags=["对话"])

_DOCX_MEDIA = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def get_chat_service(db: Session = Depends(get_db)) -> AsyncChatService:
    return AsyncChatService(
        db,
        AsyncWritingAssistant(get_llm_gateway(), get_vision_gateway()),
        RagService(db, get_embedder(), get_vector_store()),
    )


@router.post("/export/docx")
def export_docx(req: ExportRequest, user: User = Depends(get_current_user)):
    buf = markdown_to_docx(
        text=req.content, title=req.title, doc_number=req.doc_number,
        recipient=req.recipient, signature=req.signature,
        date_text=req.date_text, use_red_header=req.use_red_header,
    )
    fname = quote(f"{req.title}.docx")
    return StreamingResponse(buf, media_type=_DOCX_MEDIA, headers={
        "Content-Disposition": f"attachment; filename*=UTF-8''{fname}"
    })


@router.post("/export/official")
def export_official(req: OfficialExportRequest, user: User = Depends(get_current_user)):
    buf = generate_official_document(
        content=req.content, title=req.title, doc_number=req.doc_number,
        recipient=req.recipient, signature=req.signature, date_text=req.date_text,
    )
    fname = quote(f"{req.title or '公文'}.docx")
    return StreamingResponse(buf, media_type=_DOCX_MEDIA, headers={
        "Content-Disposition": f"attachment; filename*=UTF-8''{fname}"
    })


@router.post("/attachments/upload")
async def upload_attachments(
    files: List[UploadFile] = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if len(files) > settings.CHAT_MAX_ATTACHMENTS:
        raise AppError(400, f"单次最多上传 {settings.CHAT_MAX_ATTACHMENTS} 个附件")
    svc = AttachmentService(db)
    results = []
    for f in files:
        try:
            att = await svc.save_and_parse(f, user.id, db)
            results.append({
                "id": att.id, "filename": att.filename, "kind": att.kind,
                "file_size": att.file_size, "parse_status": att.parse_status,
                "parse_note": att.parse_note,
                "text_length": len(att.text_content or ""),
            })
        except ValueError as e:
            raise AppError(400, f"{f.filename}: {e}")
    return {"attachments": results}


@router.get("/attachments/{attachment_id}")
def get_attachment(attachment_id: str, user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    from app.infrastructure.repositories.chat import SqlAlchemyChatAttachmentRepository
    att = SqlAlchemyChatAttachmentRepository(db).get_for_user(attachment_id, user.id)
    if not att:
        raise NotFoundError("Attachment not found")
    return {
        "id": att.id, "filename": att.filename, "kind": att.kind,
        "file_size": att.file_size, "parse_status": att.parse_status,
        "parse_note": att.parse_note, "text_content": att.text_content,
        "created_at": att.created_at,
    }


@router.delete("/attachments/{attachment_id}")
def delete_attachment(attachment_id: str, user: User = Depends(get_current_user),
                      db: Session = Depends(get_db)):
    from app.infrastructure.repositories.chat import SqlAlchemyChatAttachmentRepository
    repo = SqlAlchemyChatAttachmentRepository(db)
    att = repo.get_for_user(attachment_id, user.id)
    if not att:
        raise NotFoundError("Attachment not found")
    if att.file_path and os.path.exists(att.file_path):
        os.remove(att.file_path)
    repo.delete(att)
    return {"message": "附件已删除"}


@router.post("/send", response_model=ChatResponse)
async def chat(req: ChatRequest, user: User = Depends(get_current_user),
               db: Session = Depends(get_db),
               svc: AsyncChatService = Depends(get_chat_service)):
    result = await svc.send_message_async(
        user, message=req.message, session_id=req.session_id, use_rag=req.use_rag,
        system_prompt=req.system_prompt, template_category=req.template_category,
        source=req.source or "chat", attachment_ids=req.attachment_ids,
        reference_template_id=req.reference_template_id,
        task_reference_ids=req.task_reference_ids,
    )
    assistant_row = db.scalar(
        select(ChatMessageModel)
        .where(
            ChatMessageModel.session_id == result["session_id"],
            ChatMessageModel.role == "assistant",
        )
        .order_by(ChatMessageModel.created_at.desc(), ChatMessageModel.id.desc())
        .limit(1)
    )
    result["message_id"] = assistant_row.id if assistant_row else None
    return result


@router.post("/feedback")
def submit_feedback(req: FeedbackRequest,
                    user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    return FeedbackService(SqlAlchemyChatFeedbackRepository(db)).submit(
        user.id, req.target_type, req.target_id, req.rating, req.detail)


@router.get("/sessions")
def list_sessions(user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    sessions = SqlAlchemyChatSessionRepository(db).list_by_user(user.id)
    return [{"id": s.id, "title": s.title, "created_at": s.created_at} for s in sessions]


@router.get("/sessions/{session_id}/messages")
def get_messages(session_id: str, user: User = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    sessions = SqlAlchemyChatSessionRepository(db)
    if not sessions.get_for_user(session_id, user.id):
        raise NotFoundError("Session not found")
    messages = SqlAlchemyChatMessageRepository(db).list_by_session(session_id)
    message_ids = [m.id for m in messages if m.id and m.role == "assistant"]
    feedback_rows = db.scalars(select(AIResponseFeedbackModel).where(
        AIResponseFeedbackModel.user_id == user.id,
        AIResponseFeedbackModel.target_type == "chat_message",
        AIResponseFeedbackModel.target_id.in_(message_ids),
    )).all() if message_ids else []
    feedback_by_target = {row.target_id: row for row in feedback_rows}
    return [{
        "id": m.id, "role": m.role, "content": m.content,
        "sources": m.sources, "attachments": m.attachments or [],
        "feedback": (
            {"rating": feedback_by_target[m.id].rating,
             "detail": feedback_by_target[m.id].detail or ""}
            if m.id in feedback_by_target else None
        ),
        "created_at": m.created_at,
    } for m in messages]


@router.patch("/sessions/{session_id}")
def rename_session(session_id: str, req: SessionRenameRequest,
                   user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    sessions = SqlAlchemyChatSessionRepository(db)
    if not sessions.get_for_user(session_id, user.id):
        raise NotFoundError("会话不存在")
    title = (req.title or "").strip()
    if not title:
        raise AppError(422, "会话标题不能为空")
    if len(title) > 200:
        raise AppError(422, "会话标题不能超过 200 字")
    row = sessions.get_model(session_id)
    row.title = title
    db.commit()
    return {"id": row.id, "title": row.title, "created_at": row.created_at}


@router.delete("/sessions/{session_id}")
def delete_session(session_id: str, user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    sessions = SqlAlchemyChatSessionRepository(db)
    session = sessions.get_for_user(session_id, user.id)
    if not session:
        raise NotFoundError("会话不存在")
    sessions.delete(session)
    return {"ok": True}


@router.get("/admin/sessions")
def list_all_sessions(user: User = Depends(require_admin_or_above),
                      db: Session = Depends(get_db),
                      page: int = Query(1), page_size: int = Query(20)):
    sessions_repo = SqlAlchemyChatSessionRepository(db)
    messages_repo = SqlAlchemyChatMessageRepository(db)
    total, items = sessions_repo.list_all_paged(page, page_size)
    return {
        "total": total, "page": page, "page_size": page_size,
        "data": [{
            "id": s.id, "title": s.title, "user_id": s.user_id,
            "user_name": user_name,
            "message_count": messages_repo.count_by_session(s.id),
            "created_at": s.created_at, "updated_at": s.created_at,
        } for s, user_name in items],
    }


@router.delete("/admin/sessions/{session_id}")
def admin_delete_session(session_id: str, user: User = Depends(require_admin_or_above),
                         db: Session = Depends(get_db)):
    sessions_repo = SqlAlchemyChatSessionRepository(db)
    session = sessions_repo.get(session_id)
    if not session:
        raise NotFoundError("Session not found")
    sessions_repo.delete(session)
    return {"message": "Session deleted"}
