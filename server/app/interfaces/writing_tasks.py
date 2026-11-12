"""写作任务（Writing Task）路由。

智能写作工作台专属 API：任务 = 结构化上下文 + 当前文档 + 持续对话 + 版本链。
与普通 /chat/send 分离，所有接口强制登录且按 user_id 隔离。
起草支持 SSE 流式（/draft/stream）：正文边生成边推给前端。
"""
import asyncio
import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.application.chat.attachment_service import AttachmentService
from app.application.knowledge.rag_service import RagService
from app.application.shared.async_writing_assistant import AsyncWritingAssistant
from app.application.shared.writing_assistant import WritingAssistant
from app.application.writing import ProductionWritingTaskService
from app.core.config import settings
from app.core.exceptions import AppError
from app.core.logging import get_logger
from app.domain.chat.entities import ChatSession
from app.domain.identity.entities import User
from app.domain.official_document_format import writing_preview_profile
from app.infrastructure.ai import get_llm_gateway, get_vision_gateway
from app.infrastructure.database import get_db
from app.infrastructure.database.models.chat import ChatAttachmentModel
from app.infrastructure.rag import get_embedder, get_vector_store
from app.infrastructure.repositories.chat import SqlAlchemyChatSessionRepository
from app.interfaces.deps import get_current_user

logger = get_logger(__name__)

router = APIRouter(prefix="/writing/tasks", tags=["智能写作工作台"])

_DOCX_MEDIA = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def get_task_service(db: Session = Depends(get_db)) -> ProductionWritingTaskService:
    return ProductionWritingTaskService(
        db,
        assistant=AsyncWritingAssistant(get_llm_gateway()),
        rag=RagService(db, get_embedder(), get_vector_store()),
        attachments=AttachmentService(db),
    )


@router.get("/{task_id}/render-profile")
def render_profile(task_id: str,
                   user: User = Depends(get_current_user),
                   svc: ProductionWritingTaskService = Depends(get_task_service)):
    svc._get_owned(task_id, user.id)
    return writing_preview_profile()


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
    base_version: Optional[int] = None
    base_content_hash: Optional[str] = None


class TaskSaveRequest(BaseModel):
    content: str
    formatting: Optional[Dict[str, Any]] = None
    note: Optional[str] = None
    base_version: Optional[int] = None
    base_content_hash: Optional[str] = None


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
                      svc: ProductionWritingTaskService = Depends(get_task_service)):
    return await svc.create_task_async(
        user.id, req.message, req.session_id,
        template_id=req.template_id, kb_ids=req.kb_ids,
        planned_context=req.planned_context)


class TaskPlanRequest(BaseModel):
    message: str


@router.post("/plan")
async def plan_task(req: TaskPlanRequest,
                    user: User = Depends(get_current_user),
                    svc: ProductionWritingTaskService = Depends(get_task_service)):
    """一句话指令 → 本次写作的工作台配置（WorkspaceSpec）。"""
    return await svc.plan_task_async(user.id, req.message)


@router.get("")
def list_tasks(user: User = Depends(get_current_user),
               svc: ProductionWritingTaskService = Depends(get_task_service)):
    return {"items": svc.list_tasks(user.id)}


@router.get("/{task_id}")
def get_task(task_id: str,
             user: User = Depends(get_current_user),
             svc: ProductionWritingTaskService = Depends(get_task_service)):
    return svc.get_task(task_id, user.id)


@router.get("/{task_id}/paragraphs")
def list_paragraphs(task_id: str,
                    user: User = Depends(get_current_user),
                    svc: ProductionWritingTaskService = Depends(get_task_service)):
    return svc.list_paragraphs(task_id, user.id)


@router.post("/{task_id}/paragraphs/{paragraph_id}/suggest")
async def suggest_paragraph(task_id: str, paragraph_id: str, req: ParagraphSuggestRequest,
                            user: User = Depends(get_current_user),
                            svc: ProductionWritingTaskService = Depends(get_task_service)):
    return await svc.suggest_paragraph_async(
        task_id, user.id, paragraph_id, req.instruction, req.regenerate)


@router.post("/{task_id}/suggestions/{suggestion_id}/accept")
def accept_paragraph_suggestion(task_id: str, suggestion_id: str, req: ParagraphAcceptRequest,
                                user: User = Depends(get_current_user),
                                svc: ProductionWritingTaskService = Depends(get_task_service)):
    return svc.accept_paragraph_suggestion(task_id, user.id, suggestion_id, req.final_content)


@router.post("/{task_id}/suggestions/{suggestion_id}/reject")
def reject_paragraph_suggestion(task_id: str, suggestion_id: str,
                                user: User = Depends(get_current_user),
                                svc: ProductionWritingTaskService = Depends(get_task_service)):
    return svc.reject_paragraph_suggestion(task_id, user.id, suggestion_id)


@router.patch("/{task_id}")
@router.put("/{task_id}")
def patch_task(task_id: str, req: TaskPatchRequest,
               user: User = Depends(get_current_user),
               svc: ProductionWritingTaskService = Depends(get_task_service)):
    return svc.update_context(task_id, user.id, req.context)


@router.post("/{task_id}/chat")
async def task_chat(task_id: str, req: TaskChatRequest,
                    user: User = Depends(get_current_user),
                    svc: ProductionWritingTaskService = Depends(get_task_service)):
    return await svc.chat_async(task_id, user.id, req.message)


@router.post("/{task_id}/chat/stream")
async def task_chat_stream(task_id: str, req: TaskChatRequest,
                           user: User = Depends(get_current_user),
                           svc: ProductionWritingTaskService = Depends(get_task_service)):
    """Keep the dialog responsive while intent routing or revision is running."""
    async def events():
        job = asyncio.create_task(svc.chat_async(task_id, user.id, req.message))
        try:
            yield "data: " + json.dumps({"type": "stage", "label": "正在理解并处理要求"}, ensure_ascii=False) + "\n\n"
            while not job.done():
                try:
                    await asyncio.wait_for(asyncio.shield(job), timeout=3)
                except asyncio.TimeoutError:
                    yield "data: " + json.dumps({"type": "stage", "label": "正在处理文稿"}, ensure_ascii=False) + "\n\n"
                except Exception:
                    break  # report the job failure through the terminal error event
            try:
                result = await job
                yield "data: " + json.dumps({"type": "done", "data": result}, ensure_ascii=False) + "\n\n"
            except Exception:
                logger.exception("写作对话流失败")
                yield "data: " + json.dumps({"type": "error", "message": "对话处理失败，请稍后重试"}, ensure_ascii=False) + "\n\n"
        finally:
            if not job.done():
                job.cancel()
    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/{task_id}/draft")
async def task_draft(task_id: str, req: TaskDraftRequest,
                     user: User = Depends(get_current_user),
                     svc: ProductionWritingTaskService = Depends(get_task_service)):
    return await svc.draft_async(task_id, user.id, req.outline_only)


@router.post("/{task_id}/draft/stream")
async def task_draft_stream(task_id: str, req: TaskDraftRequest,
                            user: User = Depends(get_current_user),
                            svc: ProductionWritingTaskService = Depends(get_task_service)):
    return StreamingResponse(
        svc.draft_stream_async(task_id, user.id, req.outline_only),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/{task_id}/agent-runs/{run_id}")
def get_agent_run(task_id: str, run_id: str,
                  user: User = Depends(get_current_user),
                  svc: ProductionWritingTaskService = Depends(get_task_service)):
    """查询本人的写作智能体运行摘要，不返回提示词或正文中间态。"""
    return svc.get_agent_run(task_id, user.id, run_id)


@router.post("/{task_id}/agent-runs/{run_id}/resume")
async def resume_agent_run(task_id: str, run_id: str,
                           user: User = Depends(get_current_user),
                           svc: ProductionWritingTaskService = Depends(get_task_service)):
    return await svc.resume_agent_run_async(task_id, user.id, run_id)


@router.post("/{task_id}/agent-runs/{run_id}/cancel")
def cancel_agent_run(task_id: str, run_id: str,
                     user: User = Depends(get_current_user),
                     svc: ProductionWritingTaskService = Depends(get_task_service)):
    return svc.cancel_agent_run(task_id, user.id, run_id)


@router.post("/{task_id}/revise")
async def task_revise(task_id: str, req: TaskReviseRequest,
                      user: User = Depends(get_current_user),
                      svc: ProductionWritingTaskService = Depends(get_task_service)):
    if req.current_content is not None:
        from app.application.writing.paragraph_suggestions import content_hash

        task = svc._get_owned(task_id, user.id)
        displayed = svc._to_dict(task)["current_content"]
        if (req.base_version is None or req.base_content_hash is None or
                req.base_version != (task.version_no or 0) or
                req.base_content_hash != content_hash(displayed)):
            raise HTTPException(status_code=409, detail="正文已变化或客户端版本过旧，请刷新后重试")
    return await svc.revise_async(
        task_id, user.id, req.instruction, req.mode, req.selection,
        current_override=req.current_content,
        client_base_version=req.base_version,
        client_base_hash=req.base_content_hash)


_IMAGE_RECOGNIZE_PROMPT = (
    "请识别这张图片中的全部文字内容，尽量按原文的段落与结构转写；"
    "若是表格，用「|」分隔各列逐行输出。只输出识别到的内容，不要解释、不要发挥；"
    "图片中没有文字时，用一两句话客观描述画面内容。"
)


@router.post("/{task_id}/images")
async def upload_task_images(task_id: str,
                             files: List[UploadFile] = File(...),
                             user: User = Depends(get_current_user),
                             svc: ProductionWritingTaskService = Depends(get_task_service),
                             db: Session = Depends(get_db)):
    return await _store_task_materials(task_id, files, user, svc, db, image_only=True)


@router.post("/{task_id}/materials")
async def upload_task_materials(task_id: str,
                                files: List[UploadFile] = File(...),
                                user: User = Depends(get_current_user),
                                svc: ProductionWritingTaskService = Depends(get_task_service),
                                db: Session = Depends(get_db)):
    """One batch may contain documents and pictures; both become task context."""
    return await _store_task_materials(task_id, files, user, svc, db, image_only=False)


async def _store_task_materials(task_id, files, user, svc, db, *, image_only):
    task = svc._get_owned(task_id, user.id)
    if not files:
        raise AppError(400, "未选择材料")
    limit = settings.VISION_MAX_IMAGES if image_only else settings.CHAT_MAX_ATTACHMENTS
    if len(files) > limit:
        raise AppError(400, f"单次最多上传 {limit} 个文件")

    for f in files:
        name = f.filename or ""
        suffix = "." + name.lower().rsplit(".", 1)[-1] if "." in name else ""
        accepted = settings.CHAT_IMAGE_TYPES if image_only else settings.CHAT_SUPPORTED_TYPES
        if suffix not in accepted:
            raise AppError(400, f"{name or '(未命名文件)'} 类型不支持，支持：{'、'.join(accepted)}")
    image_count = sum(
        ("." + (f.filename or "").lower().rsplit(".", 1)[-1]) in settings.CHAT_IMAGE_TYPES
        for f in files)
    if image_count > settings.VISION_MAX_IMAGES:
        raise AppError(400, f"单次最多识别 {settings.VISION_MAX_IMAGES} 张图片")

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

        if att.kind == "image" and vision is not None and att.file_path:
            try:
                part = WritingAssistant._image_part(att.file_path)
                if part:
                    messages = [{"role": "user", "content": [
                        {"type": "text", "text": _IMAGE_RECOGNIZE_PROMPT}, part]}]
                    async_complete = getattr(vision, "acomplete", None)
                    text = (await async_complete(messages, 0.1, 2048)
                            if callable(async_complete)
                            else await asyncio.to_thread(vision.complete, messages, 0.1, 2048))
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
            "id": att.id, "filename": att.filename, "kind": att.kind,
            "text": att.text_content or "", "parse_status": att.parse_status,
            "parse_note": att.parse_note or "",
        })

    attach_svc.bind_to_session([it["id"] for it in items], task.session_id, user.id, db)
    return {"items": items, "vision": vision is not None}


@router.post("/{task_id}/versions")
def save_version(task_id: str, req: TaskSaveRequest,
                 user: User = Depends(get_current_user),
                 svc: ProductionWritingTaskService = Depends(get_task_service)):
    task = svc._get_owned(task_id, user.id)
    svc._assert_revision_client_base(task, req.base_version, req.base_content_hash)
    svc._claim_revision_state(task, user.id, (task.current_content, task.version_no))
    reset = svc._supersede_pending_suggestions(task_id, user.id)
    result = svc.save_version(task_id, user.id, req.content, req.note, req.formatting)
    result["suggestions_reset"] = reset
    return result


@router.get("/{task_id}/versions")
def list_versions(task_id: str,
                  user: User = Depends(get_current_user),
                  svc: ProductionWritingTaskService = Depends(get_task_service)):
    return {"items": svc.list_versions(task_id, user.id)}


@router.get("/{task_id}/format-check")
def check_current_format(task_id: str,
                         user: User = Depends(get_current_user),
                         svc: ProductionWritingTaskService = Depends(get_task_service)):
    return svc.check_current_format(task_id, user.id)


@router.get("/{task_id}/content-check")
async def check_current_content(task_id: str,
                                user: User = Depends(get_current_user),
                                svc: ProductionWritingTaskService = Depends(get_task_service)):
    """Semantic audit of the saved text draft with evidence-backed law/KB checks."""
    from app.application.format_check.check_engine import FormatCheckEngine
    from app.application.format_check.service import FormatCheckService

    task = svc._get_owned(task_id, user.id)
    text = (task.current_content or "").strip()
    if not text:
        return {"issues": [], "issue_count": 0, "ai_used": False}
    audit = FormatCheckService(svc.db, assistant=WritingAssistant(get_llm_gateway()),
                               rag=svc.rag)
    grammar = await asyncio.to_thread(
        audit.engine._ai_check, text[:settings.FORMAT_CHECK_AI_BUDGET], [])
    try:
        conflicts = await asyncio.to_thread(audit._knowledge_conflict_issues, text, user)
    except Exception as exc:
        logger.warning("写作正文知识库核验失败: %s", exc)
        conflicts = []
    try:
        laws = await asyncio.to_thread(audit._law_citation_issues, text, user)
    except Exception as exc:
        logger.warning("写作正文法条核验失败: %s", exc)
        laws = []
    issues = (grammar or []) + conflicts + laws
    for index, issue in enumerate(issues):
        issue["id"] = index
    return {"issues": issues, "issue_count": len(issues), "ai_used": grammar is not None}


@router.get("/{task_id}/versions/{version_no}")
def get_version(task_id: str, version_no: int,
                user: User = Depends(get_current_user),
                svc: ProductionWritingTaskService = Depends(get_task_service)):
    return svc.get_version(task_id, user.id, version_no)


@router.post("/{task_id}/versions/{version_no}/restore")
def restore_version(task_id: str, version_no: int,
                    user: User = Depends(get_current_user),
                    svc: ProductionWritingTaskService = Depends(get_task_service)):
    return svc.restore_version(task_id, user.id, version_no)


@router.get("/{task_id}/versions/{version_no}/export")
def export_version(task_id: str, version_no: int, red_header: bool = True,
                   user: User = Depends(get_current_user),
                   svc: ProductionWritingTaskService = Depends(get_task_service)):
    buf, fname = svc.export_version_docx(task_id, user.id, version_no, red_header)
    return StreamingResponse(buf, media_type=_DOCX_MEDIA, headers={
        "Content-Disposition": f"attachment; filename*=UTF-8''{fname}"})


@router.get("/{task_id}/export")
def export_task(task_id: str, red_header: bool = True,
                user: User = Depends(get_current_user),
                svc: ProductionWritingTaskService = Depends(get_task_service)):
    buf, fname = svc.export_docx(task_id, user.id, red_header)
    return StreamingResponse(buf, media_type=_DOCX_MEDIA, headers={
        "Content-Disposition": f"attachment; filename*=UTF-8''{fname}"})


@router.post("/{task_id}/training-sample")
def add_training_sample(task_id: str, req: TaskTrainingRequest,
                        user: User = Depends(get_current_user),
                        svc: ProductionWritingTaskService = Depends(get_task_service)):
    return svc.add_to_training(task_id, user.id, req.final_content)
