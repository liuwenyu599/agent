"""格式校验路由。路径与响应结构与旧系统一致（/format-check/...）。

路由统一挂载在 /api/v1 前缀下（见 app/interfaces/api.py 的 include_router）。
"""
from typing import Optional

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.application.format_check.dto import FixRequest, IssueActionRequest, RuleRequest
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
