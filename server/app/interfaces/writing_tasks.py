"""写作任务（Writing Task）路由。

智能写作工作台专属 API：任务 = 结构化上下文 + 当前文档 + 持续对话 + 版本链。
与普通 /chat/send 分离，所有接口强制登录且按 user_id 隔离。
"""
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.application.chat.attachment_service import AttachmentService
from app.application.knowledge.rag_service import RagService
from app.application.shared.writing_assistant import WritingAssistant
from app.application.writing.task_service import WritingTaskService
from app.domain.identity.entities import User
from app.infrastructure.ai import get_llm_gateway
from app.infrastructure.database import get_db
from app.infrastructure.rag import get_embedder, get_vector_store
from app.interfaces.deps import get_current_user

router = APIRouter(prefix="/writing/tasks", tags=["智能写作工作台"])

_DOCX_MEDIA = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def get_task_service(db: Session = Depends(get_db)) -> WritingTaskService:
    return WritingTaskService(
        db,
        assistant=WritingAssistant(get_llm_gateway()),
        rag=RagService(db, get_embedder(), get_vector_store()),
        attachments=AttachmentService(db),
    )


class TaskCreateRequest(BaseModel):
    message: str
    session_id: Optional[str] = None


class TaskChatRequest(BaseModel):
    message: str


class TaskPatchRequest(BaseModel):
    context: Dict[str, Any]


class TaskDraftRequest(BaseModel):
    outline_only: bool = False


class TaskReviseRequest(BaseModel):
    instruction: str
    mode: str = "revise"           # expand/polish/condense/normalize/complete/rewrite/revise
    selection: Optional[str] = None
    current_content: Optional[str] = None  # 前端编辑器最新内容（用户可能手改过）


class TaskSaveRequest(BaseModel):
    content: str
    note: Optional[str] = None


class TaskTrainingRequest(BaseModel):
    final_content: str


@router.post("", status_code=201)
def create_task(req: TaskCreateRequest,
                user: User = Depends(get_current_user),
                svc: WritingTaskService = Depends(get_task_service)):
    return svc.create_task(user.id, req.message, req.session_id)


@router.get("")
def list_tasks(user: User = Depends(get_current_user),
               svc: WritingTaskService = Depends(get_task_service)):
    return {"items": svc.list_tasks(user.id)}


@router.get("/{task_id}")
def get_task(task_id: str,
             user: User = Depends(get_current_user),
             svc: WritingTaskService = Depends(get_task_service)):
    return svc.get_task(task_id, user.id)


@router.patch("/{task_id}")
@router.put("/{task_id}")  # 桌面客户端 ApiClient 暂不支持 PATCH
def patch_task(task_id: str, req: TaskPatchRequest,
               user: User = Depends(get_current_user),
               svc: WritingTaskService = Depends(get_task_service)):
    return svc.update_context(task_id, user.id, req.context)


@router.post("/{task_id}/chat")
def task_chat(task_id: str, req: TaskChatRequest,
              user: User = Depends(get_current_user),
              svc: WritingTaskService = Depends(get_task_service)):
    return svc.chat(task_id, user.id, req.message)


@router.post("/{task_id}/draft")
def task_draft(task_id: str, req: TaskDraftRequest,
               user: User = Depends(get_current_user),
               svc: WritingTaskService = Depends(get_task_service)):
    return svc.draft(task_id, user.id, req.outline_only)


@router.post("/{task_id}/revise")
def task_revise(task_id: str, req: TaskReviseRequest,
                user: User = Depends(get_current_user),
                svc: WritingTaskService = Depends(get_task_service)):
    # 前端编辑器内容可能领先于服务端（用户手改未保存），以请求携带的为准
    if req.current_content is not None:
        task = svc._get_owned(task_id, user.id)
        task.current_content = req.current_content
        svc.db.commit()
    return svc.revise(task_id, user.id, req.instruction, req.mode, req.selection)


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


@router.get("/{task_id}/export")
def export_task(task_id: str, red_header: bool = True,
                user: User = Depends(get_current_user),
                svc: WritingTaskService = Depends(get_task_service)):
    buf, fname = svc.export_docx(task_id, user.id, red_header)
    return StreamingResponse(buf, media_type=_DOCX_MEDIA, headers={
        "Content-Disposition": f"attachment; filename*=UTF-8''{fname}"
    })


@router.post("/{task_id}/training-sample")
def add_training_sample(task_id: str, req: TaskTrainingRequest,
                        user: User = Depends(get_current_user),
                        svc: WritingTaskService = Depends(get_task_service)):
    return svc.add_to_training(task_id, user.id, req.final_content)
