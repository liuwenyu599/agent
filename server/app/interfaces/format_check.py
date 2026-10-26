"""格式校验路由。路径与响应结构与旧系统一致（/format-check/...）。

路由统一挂载在 /api/v1 前缀下（见 app/interfaces/api.py 的 include_router）。
"""
import asyncio
from typing import Optional

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.application.format_check.dto import (
    ContentUpdateRequest,
    FixRequest,
    IssueActionRequest,
    RuleActiveRequest,
    RuleCompileRequest,
    RuleRequest,
)
from app.application.format_check.service import FormatCheckService
from app.application.knowledge.rag_service import RagService
from app.application.shared.writing_assistant import WritingAssistant
from app.domain.identity.entities import User
from app.infrastructure.ai import get_llm_gateway
from app.infrastructure.database import get_db
from app.infrastructure.rag import get_embedder, get_vector_store
from app.interfaces.deps import get_current_user

router = APIRouter(prefix="/format-check", tags=["格式校验"])


def get_format_check_service(db: Session = Depends(get_db)) -> FormatCheckService:
    return FormatCheckService(
        db,
        WritingAssistant(get_llm_gateway()),
        RagService(db, get_embedder(), get_vector_store()),
    )


# ========== 校验 ==========

@router.post("/check")
def check_document(
    file: UploadFile = File(...),
    use_ai: bool = Query(True, description="是否启用 AI 辅助判断"),
    rule_ids: Optional[str] = Query(None, description="逗号分隔的规则ID；不传则用全部默认规则"),
    user: User = Depends(get_current_user),
    svc: FormatCheckService = Depends(get_format_check_service),
):
    """上传文件进行格式校验。返回逐条问题清单（位置/当前/要求/建议）。

    该链路内部仍包含同步文档解析、RAG 与模型 HTTP 调用，因此路由故意保持
    ``def``：FastAPI 会把整个处理放进 worker thread，避免阻塞主事件循环。
    service 暂时保留 async 签名只是为了复用 UploadFile.read()。
    """
    return asyncio.run(svc.check_upload(file, user, use_ai=use_ai, rule_ids=rule_ids))


@router.get("/records")
def list_records(page: int = Query(1), page_size: int = Query(20),
                 user: User = Depends(get_current_user),
                 svc: FormatCheckService = Depends(get_format_check_service)):
    return svc.list_records(user, page, page_size)


@router.get("/records/{record_id}")
def get_record(record_id: str, user: User = Depends(get_current_user),
               svc: FormatCheckService = Depends(get_format_check_service)):
    return svc.get_record(record_id, user)


@router.delete("/records/{record_id}")
def delete_record(record_id: str, user: User = Depends(get_current_user),
                  svc: FormatCheckService = Depends(get_format_check_service)):
    """删除校验记录及其关联文件（原始稿/预览稿/当前稿/修正稿）。"""
    return svc.delete_record(record_id, user)


# ========== 审校工作台 ==========

@router.get("/records/{record_id}/paragraphs")
def get_record_paragraphs(
    record_id: str,
    version: str = Query("current", description="original=原始文件；current=已应用修正后的当前稿"),
    user: User = Depends(get_current_user),
    svc: FormatCheckService = Depends(get_format_check_service),
):
    """段落排版属性快照（审校工作台左栏 / 修改前后对比）。"""
    return svc.get_record_paragraphs(record_id, user, version=version)


@router.put("/records/{record_id}/content")
def update_record_content(record_id: str, req: ContentUpdateRequest,
                          user: User = Depends(get_current_user),
                          svc: FormatCheckService = Depends(get_format_check_service)):
    """保存工作台中栏的人工正文修改：写回记录文件成为新基线，应用/解决状态重置。"""
    return svc.update_record_content(record_id, req.paragraphs, user, req.formatting)


@router.post("/records/{record_id}/apply")
def apply_issue(record_id: str, req: IssueActionRequest,
                user: User = Depends(get_current_user),
                svc: FormatCheckService = Depends(get_format_check_service)):
    """应用单条修正（只更新 applied_ids，不改动 issues；原始文件不被修改）。"""
    return svc.apply_issue(record_id, req.issue_id, user)


@router.post("/records/{record_id}/undo")
def undo_issue(record_id: str, req: IssueActionRequest,
               user: User = Depends(get_current_user),
               svc: FormatCheckService = Depends(get_format_check_service)):
    """撤销单条修正（从 applied_ids 移除；未知 id 视为空操作返回 200）。"""
    return svc.undo_issue(record_id, req.issue_id, user)


@router.post("/records/{record_id}/recheck")
def recheck(record_id: str, user: User = Depends(get_current_user),
            svc: FormatCheckService = Depends(get_format_check_service)):
    """对当前（已应用修正后）的文档重跑规则检查，结果收敛回同一条记录。"""
    return svc.recheck(record_id, user)


@router.post("/preview-fix")
def preview_fix(req: FixRequest, user: User = Depends(get_current_user),
                svc: FormatCheckService = Depends(get_format_check_service)):
    """按已接受的问题生成修正预览（不落库，审阅模式右栏实时刷新）。"""
    return svc.preview_fix(req.record_id, req.accepted_indices, user)


@router.post("/fix")
def fix_document(req: FixRequest, user: User = Depends(get_current_user),
                 svc: FormatCheckService = Depends(get_format_check_service)):
    """按已接受的问题生成修正稿并下载（不传 accepted_indices 时用持久化的 applied_ids）。"""
    out_path, download_name = svc.fix_document(req.record_id, req.accepted_indices, user)
    return FileResponse(
        str(out_path),
        filename=download_name,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


# ========== 规则管理 ==========

@router.get("/rules")
def list_rules(user: User = Depends(get_current_user),
               svc: FormatCheckService = Depends(get_format_check_service)):
    return svc.list_rules(user)


@router.post("/rules/compile")
def compile_rule(req: RuleCompileRequest, user: User = Depends(get_current_user),
                 svc: FormatCheckService = Depends(get_format_check_service)):
    """白话描述 → AI 生成校验项（不落库，登录用户可保存个人规则）。"""
    return svc.compile_rule(req, user)


@router.post("/rules")
def create_rule(req: RuleRequest, user: User = Depends(get_current_user),
                svc: FormatCheckService = Depends(get_format_check_service)):
    return svc.create_rule(req, user)


@router.put("/rules/{rule_id}")
def update_rule(rule_id: str, req: RuleRequest,
                user: User = Depends(get_current_user),
                svc: FormatCheckService = Depends(get_format_check_service)):
    return svc.update_rule(rule_id, req, user)


@router.patch("/rules/{rule_id}/active")
def set_rule_active(rule_id: str, req: RuleActiveRequest,
                    user: User = Depends(get_current_user),
                    svc: FormatCheckService = Depends(get_format_check_service)):
    return svc.set_rule_active(rule_id, req.is_active, user)


@router.delete("/rules/{rule_id}")
def delete_rule(rule_id: str, user: User = Depends(get_current_user),
                svc: FormatCheckService = Depends(get_format_check_service)):
    return svc.delete_rule(rule_id, user)
