"""工作流路由。路径与响应结构与旧系统一致（/workflow/...）。"""
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.application.shared.writing_assistant import WritingAssistant
from app.application.workflow.dto import (
    ConfirmContextRequest,
    CreateInstanceRequest,
    GenerateNodeRequest,
    ParseKeyValueRequest,
    ParseNaturalLanguageRequest,
    UpdateInstanceRequest,
    UpdateNodeRequest,
)
from app.application.workflow.service import WorkflowService
from app.domain.identity.entities import User
from app.infrastructure.ai import get_llm_gateway
from app.infrastructure.database import get_db
from app.interfaces.deps import get_current_user

router = APIRouter(prefix="/workflow", tags=["workflow"])


def get_workflow_service(db: Session = Depends(get_db)) -> WorkflowService:
    return WorkflowService(db, WritingAssistant(get_llm_gateway()))


@router.get("/templates")
def list_templates(user: User = Depends(get_current_user),
                   svc: WorkflowService = Depends(get_workflow_service)):
    return svc.list_templates()


@router.get("/instances")
def list_instances(status: Optional[str] = Query(None),
                   user: User = Depends(get_current_user),
                   svc: WorkflowService = Depends(get_workflow_service)):
    return svc.list_instances(user, status)


@router.post("/instances")
def create_instance(req: CreateInstanceRequest,
                    user: User = Depends(get_current_user),
                    svc: WorkflowService = Depends(get_workflow_service)):
    return svc.create_instance(user, req.template_code, req.title, req.workflow_context)


@router.get("/instances/{inst_id}")
def get_instance(inst_id: str, user: User = Depends(get_current_user),
                 svc: WorkflowService = Depends(get_workflow_service)):
    return svc.get_instance(inst_id)


@router.put("/instances/{inst_id}")
def update_instance(inst_id: str, req: UpdateInstanceRequest,
                    user: User = Depends(get_current_user),
                    svc: WorkflowService = Depends(get_workflow_service)):
    return svc.update_instance(inst_id, req.title, req.status,
                               req.basic_info, req.workflow_context)


@router.delete("/instances/{inst_id}")
def delete_instance(inst_id: str, user: User = Depends(get_current_user),
                    svc: WorkflowService = Depends(get_workflow_service)):
    return svc.delete_instance(inst_id)


@router.post("/instances/{inst_id}/parse-natural-language")
def parse_natural_language(inst_id: str, req: ParseNaturalLanguageRequest,
                           user: User = Depends(get_current_user),
                           svc: WorkflowService = Depends(get_workflow_service)):
    return svc.parse_natural_language(inst_id, req.text)


@router.post("/instances/{inst_id}/parse-key-value")
def parse_key_value(inst_id: str, req: ParseKeyValueRequest,
                    user: User = Depends(get_current_user),
                    svc: WorkflowService = Depends(get_workflow_service)):
    return svc.parse_key_value(inst_id, req.text)


@router.post("/instances/{inst_id}/confirm-context")
def confirm_context(inst_id: str, req: ConfirmContextRequest,
                    user: User = Depends(get_current_user),
                    svc: WorkflowService = Depends(get_workflow_service)):
    return svc.confirm_context(inst_id, req.workflow_context, req.confirm_overrides or {})


@router.put("/nodes/{node_inst_id}")
def update_node(node_inst_id: str, req: UpdateNodeRequest,
                user: User = Depends(get_current_user),
                svc: WorkflowService = Depends(get_workflow_service)):
    return svc.update_node(node_inst_id, req.content, req.status)


@router.post("/nodes/{node_inst_id}/generate")
def generate_node(node_inst_id: str, req: GenerateNodeRequest,
                  user: User = Depends(get_current_user),
                  svc: WorkflowService = Depends(get_workflow_service)):
    return svc.generate_node(node_inst_id, req.instruction, req.save)
