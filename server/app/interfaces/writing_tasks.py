"""写作任务（Writing Task）路由。

智能写作工作台专属 API：任务 = 结构化上下文 + 当前文档 + 持续对话 + 版本链。
与普通 /chat/send 分离，所有接口强制登录且按 user_id 隔离。
起草支持 SSE 流式（/draft/stream）：正文边生成边推给前端。
"""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.application.chat.attachment_service import AttachmentService
from app.application.knowledge.rag_service import RagService
from app.application.shared.async_writing_assistant import AsyncWritingAssistant
from app.application.shared.writing_assistant import WritingAssistant
from app.application.writing.task_service import WritingTaskService
from app.core.config import settings
from app.core.exceptions import AppError
from app.core.logging import get_logger
from app.domain.chat.entities import ChatSession
from app.domain.identity.entities import User
from app.infrastructure.ai import get_llm_gateway, get_vision_gateway
from app.infrastructure.database import get_db
from app.infrastructure.database.models.chat import ChatAttachmentModel
from app.infrastructure.rag import get_embedder, get_vector_store
from app.infrastructure.repositories.chat import SqlAlchemyChatSessionRepository
from app.interfaces.deps import get_current_user

logger = get_logger(__name__)

router = APIRouter(prefix="/writing/tasks", tags=["智能写作工作台"])

_DOCX_MEDIA = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def get_task_service(db: Session = Depends(get_db)) -> WritingTaskService:
    return WritingTaskService(
        db,
        assistant=AsyncWritingAssistant(get_llm_gateway()),
        rag=RagService(db, get_embedder(), get_vector_store()),
        attachments=AttachmentService(db),
    )


class TaskCreateRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    template_id: Optional[str] = None
    kb_ids: Optional[list] = None
    planned_context: Optional[Dict[str, Any]] = None


class TaskChatRequest(BaseModel):
    message: str


class TaskPatchRequest(BaseModel):
    context: Dict[str, Any]


class TaskDraftRequest(BaseModel):
    outline_only: bool = False


class TaskReviseRequest(BaseModel):
    instruction: str
    mode: str = "revise"
    selection: Optional[str] = None
    current_content: Optional[str] = None


class TaskSaveRequest(BaseModel):
    content: str
    note: Optional[str] = None


class TaskTrainingRequest(BaseModel):
    final_content: str


class ParagraphSuggestRequest(BaseModel):
    instruction: str = ""
    regenerate: bool = False


class ParagraphAcceptRequest(BaseModel):
    final_content: str


@router.post("", status_code=201)
async def create_task(req: TaskCreateRequest,
                      user: User = Depends(get_current_user),
                      svc: WritingTaskService = Depends(get_task_service)):
    return await svc.create_task_async(
        user.id, req.message, req.session_id,
        template_id=req.template_id, kb_ids=req.kb_ids,
        planned_context=req.planned_context)


class TaskPlanRequest(BaseModel):
    message: str


@router.post("/plan")
async def plan_task(req: TaskPlanRequest,
                    user: User = Depends(get_current_user),
                    svc: WritingTaskService = Depends(get_task_service)):
    """一句话指令 → 本次写作的工作台配置（WorkspaceSpec）。"""
    return await svc.plan_task_async(user.id, req.message)


@router.get("")
def list_tasks(user: User = Depends(get_current_user),
               svc: WritingTaskService = Depends(get_task_service)):
    return {"items": svc.list_tasks(user.id)}


@router.get("/{task_id}")
def get_task(task_id: str,
             user: User = Depends(get_current_user),
             svc: WritingTaskService = Depends(get_task_service)):
    return svc.get_task(task_id, user.id)


@router.get("/{task_id}/paragraphs")
def list_paragraphs(task_id: str,
                    user: User = Depends(get_current_user),
                    svc: WritingTaskService = Depends(get_task_service)):
    return svc.list_paragraphs(task_id, user.id)


@router.post("/{task_id}/paragraphs/{paragraph_id}/suggest")
async def suggest_paragraph(task_id: str, paragraph_id: str, req: ParagraphSuggestRequest,
                            user: User = Depends(get_current_user),
                            svc: WritingTaskService = Depends(get_task_service)):
    return await svc.suggest_paragraph_async(
        task_id, user.id, paragraph_id, req.instruction, req.regenerate)


@router.post("/{task_id}/suggestions/{suggestion_id}/accept")
def accept_paragraph_suggestion(task_id: str, suggestion_id: str, req: ParagraphAcceptRequest,
                                user: User = Depends(get_current_user),
                                svc: WritingTaskService = Depends(get_task_service)):
    return svc.accept_paragraph_suggestion(task_id, user.id, suggestion_id, req.final_content)


@router.post("/{task_id}/suggestions/{suggestion_id}/reject")
def reject_paragraph_suggestion(task_id: str, suggestion_id: str,
                                user: User = Depends(get_current_user),
                                svc: WritingTaskService = Depends(get_task_service)):
    return svc.reject_paragraph_suggestion(task_id, user.id, suggestion_id)


@router.patch("/{task_id}")
@router.put("/{task_id}")
def patch_task(task_id: str, req: TaskPatchRequest,
               user: User = Depends(get_current_user),
               svc: WritingTaskService = Depends(get_task_service)):
    return svc.update_context(task_id, user.id, req.context)


@router.post("/{task_id}/chat")
async def task_chat(task_id: str, req: TaskChatRequest,
                    user: User = Depends(get_current_user),
                    svc: WritingTaskService = Depends(get_task_service)):
    return await svc.chat_async(task_id, user.id, req.message)


@router.post("/{task_id}/draft")
async def task_draft(task_id: str, req: TaskDraftRequest,
                     user: User = Depends(get_current_user),
                     svc: WritingTaskService = Depends(get_task_service)):
    return await svc.draft_async(task_id, user.id, req.outline_only)


@router.post("/{task_id}/draft/stream")
async def task_draft_stream(task_id: str, req: TaskDraftRequest,
                            user: User = Depends(get_current_user),
                            svc: WritingTaskService = Depends(get_task_service)):
    return StreamingResponse(
        svc.draft_stream_async(task_id, user.id, req.outline_only),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/{task_id}/revise")
async def task_revise(task_id: str, req: TaskReviseRequest,
                      user: User = Depends(get_current_user),
                      svc: WritingTaskService = Depends(get_task_service)):
    if req.current_content is not None:
        task = svc._get_owned(task_id, user.id)
        task.current_content = req.current_content
        svc.db.commit()
    return await svc.revise_async(
        task_id, user.id, req.instruction, req.mode, req.selection)


_IMAGE_RECOGNIZE_PROMPT = (
    "请识别这张图片中的全部文字内容，尽量按原文的段落与结构转写；"
    "若是表格，用「|」分隔各列逐行输出。只输出识别到的内容，不要解释、不要发挥；"
    "图片中没有文字时，用一两句话客观描述画面内容。"
)


@router.post("/{task_id}/images")
async def upload_task_images(task_id: str,
                             files: List[UploadFile] = File(...),
                             user: User = Depends(get_current_user),
                             svc: WritingTaskService = Depends(get_task_service),
                             db: Session = Depends(get_db)):
    task = svc._get_owned(task_id, user.id)
    if not files:
        raise AppError(400, "未选择图片")
    if len(files) > settings.VISION_MAX_IMAGES:
        raise AppError(400, f"单次最多识别 {settings.VISION_MAX_IMAGES} 张图片")

    for f in files:
        name = f.filename or ""
        suffix = "." + name.lower().rsplit(".", 1)[-1] if "." in name else ""
        if suffix not in settings.CHAT_IMAGE_TYPES:
            raise AppError(400, f"{name or '(未命名文件)'} 不是图片，支持：{'、'.join(settings.CHAT_IMAGE_TYPES)}")

    if not task.session_id:
        session = SqlAlchemyChatSessionRepository(db).add(
            ChatSession(user_id=user.id, title="写作台材料"))
        task.session_id = session.id
        db.commit()

    attach_svc = svc.attachments or AttachmentService(db)
    vision = get_vision_gateway()
    items = []
    for f in files:
        try:
            att = await attach_svc.save_and_parse(f, user.id, db)
        except ValueError as e:
            raise AppError(400, f"{f.filename}: {e}")

        if vision is not None and att.file_path:
            try:
                part = WritingAssistant._image_part(att.file_path)
                if part:
                    messages = [{"role": "user", "content": [
                        {"type": "text", "text": _IMAGE_RECOGNIZE_PROMPT}, part]}]
                    async_complete = getattr(vision, "acomplete", None)
                    text = (await async_complete(messages, 0.1, 2048)
                            if callable(async_complete)
                            else vision.complete(messages, 0.1, 2048))
                    if text and text.strip():
                        att.text_content = text.strip()
                        att.parse_status = "ok"
                        att.parse_note = f"图片经视觉模型识别（{settings.VISION_MODEL_NAME}）"
                        row = db.get(ChatAttachmentModel, att.id)
                        if row is not None:
                            row.text_content = att.text_content
                            row.parse_status = att.parse_status
                            row.parse_note = att.parse_note
                            db.commit()
            except Exception as e:
                logger.warning("[写作台] 图片视觉识别失败 %s: %s", att.filename, e)

        items.append({
            "id": att.id, "filename": att.filename,
            "text": att.text_content or "", "parse_status": att.parse_status,
            "parse_note": att.parse_note or "",
        })

    attach_svc.bind_to_session([it["id"] for it in items], task.session_id, user.id, db)
    return {"items": items, "vision": vision is not None}


@router.post("/{task_id}/versions")
def save_version(task_id: str, req: TaskSaveRequest,
                 user: User = Depends(get_current_user),
                 svc: WritingTaskService = Depends(get_task_service)):
    return svc.save_version(task_id, user.id, req.content, req.note)


@router.get("/{task_id}/versions")
def list_versions(task_id: str,
                  user: User = Depends(get_current_user),
                  svc: WritingTaskService = Depends(get_task_service)):
    return {"items": svc.list_versions(task_id, user.id)}


@router.get("/{task_id}/versions/{version_no}")
def get_version(task_id: str, version_no: int,
                user: User = Depends(get_current_user),
                svc: WritingTaskService = Depends(get_task_service)):
    return svc.get_version(task_id, user.id, version_no)


@router.post("/{task_id}/versions/{version_no}/restore")
def restore_version(task_id: str, version_no: int,
                    user: User = Depends(get_current_user),
                    svc: WritingTaskService = Depends(get_task_service)):
    return svc.restore_version(task_id, user.id, version_no)


@router.get("/{task_id}/versions/{version_no}/export")
def export_version(task_id: str, version_no: int, red_header: bool = True,
                   user: User = Depends(get_current_user),
                   svc: WritingTaskService = Depends(get_task_service)):
    buf, fname = svc.export_version_docx(task_id, user.id, version_no, red_header)
    return StreamingResponse(buf, media_type=_DOCX_MEDIA, headers={
        "Content-Disposition": f"attachment; filename*=UTF-8''{fname}"})


@router.get("/{task_id}/export")
def export_task(task_id: str, red_header: bool = True,
                user: User = Depends(get_current_user),
                svc: WritingTaskService = Depends(get_task_service)):
    buf, fname = svc.export_docx(task_id, user.id, red_header)
    return StreamingResponse(buf, media_type=_DOCX_MEDIA, headers={
        "Content-Disposition": f"attachment; filename*=UTF-8''{fname}"})


@router.post("/{task_id}/training-sample")
def add_training_sample(task_id: str, req: TaskTrainingRequest,
                        user: User = Depends(get_current_user),
                        svc: WritingTaskService = Depends(get_task_service)):
    return svc.add_to_training(task_id, user.id, req.final_content)
