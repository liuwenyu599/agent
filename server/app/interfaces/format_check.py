"""格式校验路由。路径与响应结构与旧系统一致（/format-check/...）。"""
from typing import Optional

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.application.format_check.dto import FixRequest, RuleRequest
from app.application.format_check.service import FormatCheckService
from app.application.shared.writing_assistant import WritingAssistant
from app.domain.identity.entities import User
from app.infrastructure.ai import get_llm_gateway
from app.infrastructure.database import get_db
from app.interfaces.deps import get_current_user, require_admin_or_above

router = APIRouter(prefix="/format-check", tags=["格式校验"])


def get_format_check_service(db: Session = Depends(get_db)) -> FormatCheckService:
    return FormatCheckService(db, WritingAssistant(get_llm_gateway()))


# ========== 校验 ==========

@router.post("/check")
async def check_document(
    file: UploadFile = File(...),
    use_ai: bool = Query(True, description="是否启用 AI 辅助判断"),
    rule_ids: Optional[str] = Query(None, description="逗号分隔的规则ID；不传则用全部默认规则"),
    user: User = Depends(get_current_user),
    svc: FormatCheckService = Depends(get_format_check_service),
):
    """上传文件进行格式校验。返回逐条问题清单（位置/当前/要求/建议）。"""
    return await svc.check_upload(file, user, use_ai=use_ai, rule_ids=rule_ids)


@router.get("/records")
def list_records(page: int = Query(1), page_size: int = Query(20),
                 user: User = Depends(get_current_user),
                 svc: FormatCheckService = Depends(get_format_check_service)):
    return svc.list_records(user, page, page_size)


@router.get("/records/{record_id}")
def get_record(record_id: str, user: User = Depends(get_current_user),
               svc: FormatCheckService = Depends(get_format_check_service)):
    return svc.get_record(record_id, user)


# ========== 审阅模式 ==========

@router.get("/records/{record_id}/paragraphs")
def get_record_paragraphs(record_id: str, user: User = Depends(get_current_user),
                          svc: FormatCheckService = Depends(get_format_check_service)):
    """源文档段落列表（审阅模式左栏）。"""
    return svc.get_record_paragraphs(record_id, user)


@router.post("/preview-fix")
def preview_fix(req: FixRequest, user: User = Depends(get_current_user),
                svc: FormatCheckService = Depends(get_format_check_service)):
    """按已接受的问题生成修正预览（不落库，审阅模式右栏实时刷新）。"""
    return svc.preview_fix(req.record_id, req.accepted_indices, user)


@router.post("/fix")
def fix_document(req: FixRequest, user: User = Depends(get_current_user),
                 svc: FormatCheckService = Depends(get_format_check_service)):
    """按已接受的问题生成修正稿并下载。"""
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
    return svc.list_rules()


@router.post("/rules")
def create_rule(req: RuleRequest, admin: User = Depends(require_admin_or_above),
                svc: FormatCheckService = Depends(get_format_check_service)):
    return svc.create_rule(req, admin)


@router.put("/rules/{rule_id}")
def update_rule(rule_id: str, req: RuleRequest,
                admin: User = Depends(require_admin_or_above),
                svc: FormatCheckService = Depends(get_format_check_service)):
    return svc.update_rule(rule_id, req)


@router.delete("/rules/{rule_id}")
def delete_rule(rule_id: str, admin: User = Depends(require_admin_or_above),
                svc: FormatCheckService = Depends(get_format_check_service)):
    return svc.delete_rule(rule_id)
