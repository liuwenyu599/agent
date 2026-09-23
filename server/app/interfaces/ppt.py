"""PPT 助手路由。路径与响应结构与旧系统一致（/ppt/...）。"""
import os
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.application.ppt.dto import (
    BlankIn,
    CloudCfgIn,
    CloudGenIn,
    DocRenameIn,
    DraftIn,
    GenerateIn,
    ImportUrlIn,
    OutlineIn,
    SlideActionIn,
    StructureIn,
    TemplateIn,
    VisualIn,
)
from app.application.ppt.service import PPTService
from app.application.shared.writing_assistant import WritingAssistant
from app.domain.identity.entities import User
from app.infrastructure.ai import get_llm_gateway
from app.infrastructure.database import get_db
from app.interfaces.deps import get_current_user

# PPTX（OOXML 演示文稿）MIME，供导出/下载响应使用
_PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"

router = APIRouter(prefix="/ppt", tags=["智能PPT"])


def get_ppt_service(db: Session = Depends(get_db)) -> PPTService:
    return PPTService(db, WritingAssistant(get_llm_gateway()))
