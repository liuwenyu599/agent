
from urllib.parse import quote
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional

from backend.database.postgres import get_db
from backend.database.models import ChatSession, ChatMessage, ChatAttachment, User, WritingTemplate
from backend.auth.permission import get_current_user, require_admin_or_above
from backend.services.llm_service import LLMService
from backend.services.rag_service import RAGService
from backend.services.memory_service import MemoryService
from backend.services.docx_export import markdown_to_docx, generate_official_document
from backend.services.attachment_service import AttachmentService
from backend.services.intent_service import IntentService
from backend.config.settings import CHAT_MAX_ATTACHMENTS

router = APIRouter(prefix="/chat", tags=["对话"])

llm_service = LLMService()
rag_service = RAGService()
attachment_service = AttachmentService()
intent_service = IntentService(llm_service)


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    use_rag: bool = True
    system_prompt: Optional[str] = None
    template_category: Optional[str] = None
    source: Optional[str] = "chat"  # chat / template
    attachment_ids: Optional[List[str]] = None  # 本次消息引用的附件
    reference_template_id: Optional[str] = None  # 对话中选择的"参考模板"（信息写作）
    task_reference_ids: Optional[List[str]] = None  # 模板中心"当前写作材料"的 id 列表（不进知识库）


class ChatResponse(BaseModel):
    reply: str
    sources: List[dict] = []
    attachments: List[dict] = []
    session_id: str


class ExportRequest(BaseModel):
    content: str
    title: str = "公文"
    doc_number: str = ""
    recipient: str = ""
    signature: str = ""
    date_text: str = ""
    use_red_header: bool = False


class OfficialExportRequest(BaseModel):
    content: str
    title: str = ""
    doc_number: str = ""
    recipient: str = ""
    signature: str = ""
    date_text: str = ""


@router.post("/export/docx")
async def export_docx(req: ExportRequest, user: User = Depends(get_current_user)):
    """导出为 Word 文档（通用格式）"""
    buf = markdown_to_docx(
        text=req.content,
        title=req.title,
        doc_number=req.doc_number,
        recipient=req.recipient,
        signature=req.signature,
        date_text=req.date_text,
        use_red_header=req.use_red_header
    )
    fname = quote(f"{req.title}.docx")
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{fname}"}
    )


@router.post("/export/official")
async def export_official(req: OfficialExportRequest, user: User = Depends(get_current_user)):
    """导出为标准党政机关公文格式 Word 文档"""
    buf = generate_official_document(
        content=req.content,
        title=req.title,
        doc_number=req.doc_number,
        recipient=req.recipient,
        signature=req.signature,
        date_text=req.date_text
    )
    fname = quote(f"{req.title or '公文'}.docx")
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{fname}"}
    )


# ========== 对话附件 ==========

@router.post("/attachments/upload")
async def upload_attachments(
    files: List[UploadFile] = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """上传对话附件（Word/PDF/TXT/图片），解析为文本后供对话引用。

    附件只属于当前用户的对话，不进入知识库、不需要审核。
    返回附件列表，前端把 id 放进 /chat/send 的 attachment_ids。
    """
    if len(files) > CHAT_MAX_ATTACHMENTS:
        raise HTTPException(status_code=400, detail=f"单次最多上传 {CHAT_MAX_ATTACHMENTS} 个附件")

    results = []
    for f in files:
        try:
            att = await attachment_service.save_and_parse(f, user.id, db)
            results.append({
                "id": att.id,
                "filename": att.filename,
                "kind": att.kind,
                "file_size": att.file_size,
                "parse_status": att.parse_status,
                "parse_note": att.parse_note,
                "text_length": len(att.text_content or ""),
            })
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"{f.filename}: {e}")
    return {"attachments": results}


@router.get("/attachments/{attachment_id}")
async def get_attachment(attachment_id: str, user: User = Depends(get_current_user),
                         db: Session = Depends(get_db)):
    att = db.query(ChatAttachment).filter(
        ChatAttachment.id == attachment_id,
        ChatAttachment.user_id == user.id
    ).first()
    if not att:
        raise HTTPException(status_code=404, detail="Attachment not found")
    return {
        "id": att.id, "filename": att.filename, "kind": att.kind,
        "file_size": att.file_size, "parse_status": att.parse_status,
        "parse_note": att.parse_note, "text_content": att.text_content,
        "created_at": att.created_at,
    }


@router.delete("/attachments/{attachment_id}")
async def delete_attachment(attachment_id: str, user: User = Depends(get_current_user),
                            db: Session = Depends(get_db)):
    att = db.query(ChatAttachment).filter(
        ChatAttachment.id == attachment_id,
        ChatAttachment.user_id == user.id
    ).first()
    if not att:
        raise HTTPException(status_code=404, detail="Attachment not found")
    import os
    if att.file_path and os.path.exists(att.file_path):
        os.remove(att.file_path)
    db.delete(att)
    db.commit()
    return {"message": "附件已删除"}


def _load_reference_template(template_id: Optional[str], db: Session) -> Optional[dict]:
    """加载对话中选择的参考模板，转为注入上下文的字典。找不到/已停用则返回 None。"""
    if not template_id:
        return None
    tmpl = db.query(WritingTemplate).filter(
        WritingTemplate.id == template_id,
        WritingTemplate.is_active == True
    ).first()
    if not tmpl:
        return None
    return {
        "id": tmpl.id,
        "name": tmpl.name,
        "content_template": tmpl.content_template,
        "system_prompt": tmpl.system_prompt,
        "writing_style": tmpl.writing_style,
        "word_count": tmpl.word_count,
        "need_red_header": tmpl.need_red_header,
        "need_signature": tmpl.need_signature,
        "need_date": tmpl.need_date,
        "need_doc_number": tmpl.need_doc_number,
        "keywords": tmpl.keywords,
    }


@router.post("/send", response_model=ChatResponse)
async def chat(req: ChatRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    # 获取或创建会话
    session = None
    if req.session_id:
        session = db.query(ChatSession).filter(
            ChatSession.id == req.session_id,
            ChatSession.user_id == user.id
        ).first()

    if not session:
        session = ChatSession(user_id=user.id, title=req.message[:30])
        db.add(session)
        db.commit()

    # 处理本次消息引用的附件：绑定到会话（多轮对话中持续可用）
    new_attachments = []
    if req.attachment_ids:
        new_attachments = attachment_service.get_attachments(req.attachment_ids, user.id, db)
        attachment_service.bind_to_session(req.attachment_ids, session.id, user.id, db)

    # 会话级附件上下文：只要会话中有附件，就持续注入（多轮引用）
    session_attachments = attachment_service.get_session_attachments(session.id, db)
    attachment_context = attachment_service.build_attachment_context(session_attachments, query=req.message)

    # 加载对话级参考模板（信息写作）
    reference_template = _load_reference_template(req.reference_template_id, db)

    # 加载写作参考材料（需求九：三类信息职责分离）
    # - task_reference_context：本次写作的事实材料（优先级最高）
    # - template_reference_context：模板固定参考材料（仅用于学习风格范式）
    from backend.api.references import (
        build_task_reference_context, build_template_reference_context,
    )
    task_reference_context = build_task_reference_context(
        req.task_reference_ids or [], user.id, db
    ) or None
    template_reference_context = None
    if req.reference_template_id:
        template_reference_context = build_template_reference_context(
            req.reference_template_id, db
        ) or None

    # 使用 MemoryService 获取上下文（包含历史对话）
    memory_service = MemoryService(llm_service)
    history_messages = memory_service.get_session_context(session.id, db)

    # ===== P1：写作类请求的信息完整度判断 =====
    # 信息不足时，AI 主动询问最关键的 2~3 个问题（提问也作为正常消息入库，
    # 用户下一轮直接回答即可继续）。模板表单生成模式（带 system_prompt）跳过。
    clarify_reply = None
    if not req.system_prompt:
        clarify_reply = intent_service.check_writing_clarification(
            message=req.message,
            history=history_messages,
            has_materials=bool(attachment_context),
            reference_template=reference_template,
        )

    if clarify_reply:
        reply = clarify_reply
        sources = []
    else:
        # 只有 use_rag=true 才检索
        sources = []
        if req.use_rag:
            sources = rag_service.search(
                query=req.message,
                user_id=user.id,
                kb_types=["public", "personal"]
            )

        # 写作类请求：额外检索同类范文作为模仿样例
        examples = []
        if any(k in req.message for k in ["写", "起草", "生成", "撰写", "拟"]):
            examples = rag_service.search_examples(req.message, user.id, top_k=2)

        # 调用 LLM（附件材料、参考模板作为独立上下文注入）
        reply = llm_service.chat(
            message=req.message,
            history=history_messages,
            sources=sources,
            user_role=user.role,
            memories=None,  # 关闭长期记忆注入
            examples=examples,
            system_prompt=req.system_prompt,
            template_category=req.template_category,
            attachment_context=attachment_context or None,
            reference_template=reference_template,
            task_reference_context=task_reference_context,
            template_reference_context=template_reference_context
        )

    # 保存消息
    user_msg = ChatMessage(
        session_id=session.id,
        role="user",
        content=req.message,
        source=req.source,
        sources=[s["source"] for s in sources] if sources else [],
        attachments=attachment_service.summarize_for_message(new_attachments) if new_attachments else []
    )
    assistant_msg = ChatMessage(
        session_id=session.id,
        role="assistant",
        content=reply,
        source=req.source,
        tokens_used=len(reply)
    )
    db.add(user_msg)
    db.add(assistant_msg)
    db.commit()

    # 检查是否需要总结会话（每20轮）
    msg_count = db.query(ChatMessage).filter(
        ChatMessage.session_id == session.id
    ).count()
    if msg_count > 0 and msg_count % 20 == 0:
        try:
            memory_service.summarize_session(session.id, db)
        except Exception as e:
            print(f"[Memory] 总结会话失败: {e}")

    return ChatResponse(
        reply=reply,
        sources=sources,
        attachments=attachment_service.summarize_for_message(new_attachments),
        session_id=session.id
    )


@router.get("/sessions")
async def list_sessions(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    sessions = db.query(ChatSession).filter(ChatSession.user_id == user.id).order_by(ChatSession.created_at.desc()).all()
    return [{"id": s.id, "title": s.title, "created_at": s.created_at} for s in sessions]


@router.get("/sessions/{session_id}/messages")
async def get_messages(session_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    session = db.query(ChatSession).filter(
        ChatSession.id == session_id,
        ChatSession.user_id == user.id
    ).first()

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    messages = db.query(ChatMessage).filter(
        ChatMessage.session_id == session_id
    ).order_by(ChatMessage.created_at).all()

    return [{
        "id": m.id,
        "role": m.role,
        "content": m.content,
        "sources": m.sources,
        "attachments": m.attachments or [],
        "created_at": m.created_at
    } for m in messages]


# ========== 管理员接口 ==========
from fastapi import Query
from sqlalchemy import func

@router.get("/admin/sessions")
async def list_all_sessions(
    user: User = Depends(require_admin_or_above),
    db: Session = Depends(get_db),
    page: int = Query(1),
    page_size: int = Query(20)
):
    """管理员获取所有会话"""
    query = db.query(ChatSession).order_by(ChatSession.created_at.desc())
    total = query.count()
    sessions = query.offset((page - 1) * page_size).limit(page_size).all()
    result = []
    for s in sessions:
        msg_count = db.query(func.count(ChatMessage.id)).filter(
            ChatMessage.session_id == s.id
        ).scalar()
        result.append({
            "id": s.id, "title": s.title, "user_id": s.user_id,
            "user_name": s.user.real_name or s.user.username if s.user else "未知",
            "message_count": msg_count,
            "created_at": s.created_at, "updated_at": s.created_at
        })
    return {"total": total, "page": page, "page_size": page_size, "data": result}

@router.delete("/admin/sessions/{session_id}")
async def admin_delete_session(
    session_id: str,
    user: User = Depends(require_admin_or_above),
    db: Session = Depends(get_db)
):
    """管理员删除会话"""
    session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    db.query(ChatMessage).filter(ChatMessage.session_id == session.id).delete()
    db.delete(session)
    db.commit()
    return {"message": "Session deleted"}
