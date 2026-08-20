# -*- coding: utf-8 -*-
"""格式校验 API（完整文件，直接覆盖 backend/api/format_check.py）

接口：
- POST   /format-check/check                    上传文件并校验（任何登录用户）
- GET    /format-check/records                  我的校验历史
- GET    /format-check/records/{id}             校验详情
- GET    /format-check/records/{id}/paragraphs  源文档段落（审阅模式左栏）
- POST   /format-check/preview-fix              修正预览（审阅模式右栏，不落库）
- POST   /format-check/fix                      生成并下载修正稿
- GET    /format-check/rules                    规则列表（登录用户可见，用于预览）
- POST   /format-check/rules                    新增规则（管理员）
- PUT    /format-check/rules/{id}               修改规则（管理员）
- DELETE /format-check/rules/{id}               删除规则（管理员）

说明：
- docx 校验后文件会保留在 CHECK_DIR（以记录ID命名），供审阅/修正使用；
  txt/md/pdf 不做格式修正，校验后即删除。
"""
import uuid
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
from docx import Document as DocxDocument

from backend.database.postgres import get_db
from backend.database.models import FormatRule, FormatCheckRecord, User
from backend.auth.permission import get_current_user, require_admin_or_above
from backend.services.format_check_service import FormatCheckService
from backend.services.llm_service import LLMService
from backend.config.settings import FORMAT_CHECK_MAX_SIZE

router = APIRouter(prefix="/format-check", tags=["格式校验"])

llm_service = LLMService()
check_service = FormatCheckService(llm_service=llm_service)

CHECK_DIR = Path("/tmp/judicial-format-check")
CHECK_DIR.mkdir(exist_ok=True)


class RuleRequest(BaseModel):
    name: str
    target: str
    checks: dict
    severity: str = "error"
    is_default: bool = True
    is_active: bool = True
    remark: Optional[str] = ""


class FixRequest(BaseModel):
    record_id: str
    accepted_indices: List[int]


def _rule_to_dict(r: FormatRule) -> dict:
    return {
        "id": r.id, "name": r.name, "target": r.target, "checks": r.checks,
        "severity": r.severity, "is_default": r.is_default, "is_active": r.is_active,
        "remark": r.remark,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


def _record_file(record: FormatCheckRecord) -> Path:
    """校验时保留的源 docx 路径（以记录ID命名）。"""
    return CHECK_DIR / f"{record.id}.docx"


def _get_record_checked(record_id: str, user: User, db: Session) -> FormatCheckRecord:
    record = db.query(FormatCheckRecord).filter(FormatCheckRecord.id == record_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Record not found")
    if record.user_id != user.id and user.role not in ["developer", "knowledge_admin", "admin"]:
        raise HTTPException(status_code=403, detail="No permission")
    return record


def _get_record_docx(record: FormatCheckRecord) -> Path:
    """取出记录对应的源 docx，不存在/非 docx 时给出明确报错。"""
    if record.file_type != "docx":
        raise HTTPException(status_code=400, detail="仅 Word(.docx) 文件支持审阅与自动修正")
    path = _record_file(record)
    if not path.exists():
        raise HTTPException(status_code=410, detail="源文件已过期，请重新上传校验")
    return path


# ========== 校验 ==========

@router.post("/check")
async def check_document(
    file: UploadFile = File(...),
    use_ai: bool = Query(True, description="是否启用 AI 辅助判断"),
    rule_ids: Optional[str] = Query(None, description="逗号分隔的规则ID；不传则用全部默认规则"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """上传文件进行格式校验。返回逐条问题清单（位置/当前/要求/建议）。"""
    filename = file.filename or "unnamed"
    suffix = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if suffix not in ("docx", "txt", "md", "pdf"):
        raise HTTPException(status_code=400, detail=f"暂不支持 .{suffix} 文件的格式校验，请上传 Word(.docx) 文件")

    data = await file.read()
    if len(data) > FORMAT_CHECK_MAX_SIZE:
        raise HTTPException(status_code=400, detail="文件超过 50MB 限制")
    if not data:
        raise HTTPException(status_code=400, detail="文件为空")

    # 选择规则
    query = db.query(FormatRule).filter(FormatRule.is_active == True)
    if rule_ids:
        ids = [i for i in rule_ids.split(",") if i]
        query = query.filter(FormatRule.id.in_(ids))
    else:
        query = query.filter(FormatRule.is_default == True)
    rules = [_rule_to_dict(r) for r in query.all()]

    if not rules:
        raise HTTPException(
            status_code=400,
            detail="尚未配置任何格式规则。请管理员先在「格式校验-规则管理」中录入司法局正式格式规范。"
        )

    record_id = uuid.uuid4().hex
    tmp_path = CHECK_DIR / f"{uuid.uuid4().hex}_{filename}"
    tmp_path.write_bytes(data)
    try:
        result = check_service.check_file(tmp_path, filename, rules, use_ai=use_ai)
    except ValueError as e:
        tmp_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        tmp_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"校验过程出错: {e}")

    issues = result["issues"]
    record = FormatCheckRecord(
        user_id=user.id,
        filename=filename,
        file_type=result["file_type"],
        rule_snapshot=[{"id": r["id"], "name": r["name"], "target": r["target"], "checks": r["checks"]} for r in rules],
        issues=issues,
        issue_count=len(issues),
        rule_issue_count=len([i for i in issues if i["source"] == "rule"]),
        ai_issue_count=len([i for i in issues if i["source"] == "ai"]),
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    # docx 保留源文件（以记录ID命名），供审阅模式与自动修正使用；其他类型删除
    if result["file_type"] == "docx":
        keep_path = _record_file(record)
        tmp_path.replace(keep_path)
    else:
        tmp_path.unlink(missing_ok=True)

    return {
        "record_id": record.id,
        "filename": filename,
        "file_type": result["file_type"],
        "ai_used": result["ai_used"],
        "issue_count": len(issues),
        "issues": issues,
        "rules_used": [{"id": r["id"], "name": r["name"], "target": r["target"]} for r in rules],
    }


@router.get("/records")
async def list_records(
    page: int = Query(1), page_size: int = Query(20),
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    query = db.query(FormatCheckRecord).filter(FormatCheckRecord.user_id == user.id)
    total = query.count()
    records = query.order_by(FormatCheckRecord.created_at.desc()) \
        .offset((page - 1) * page_size).limit(page_size).all()
    return {
        "total": total, "page": page, "page_size": page_size,
        "data": [{
            "id": r.id, "filename": r.filename, "file_type": r.file_type,
            "issue_count": r.issue_count, "rule_issue_count": r.rule_issue_count,
            "ai_issue_count": r.ai_issue_count,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        } for r in records]
    }


@router.get("/records/{record_id}")
async def get_record(record_id: str, user: User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    record = _get_record_checked(record_id, user, db)
    return {
        "id": record.id, "filename": record.filename, "file_type": record.file_type,
        "issues": record.issues, "issue_count": record.issue_count,
        "rule_snapshot": record.rule_snapshot,
        "created_at": record.created_at.isoformat() if record.created_at else None,
    }


# ========== 审阅模式 ==========

@router.get("/records/{record_id}/paragraphs")
async def get_record_paragraphs(record_id: str, user: User = Depends(get_current_user),
                                db: Session = Depends(get_db)):
    """源文档段落列表（审阅模式左栏）。"""
    record = _get_record_checked(record_id, user, db)
    path = _get_record_docx(record)
    doc = DocxDocument(str(path))
    return {"paragraphs": [
        {"index": i, "text": p.text} for i, p in enumerate(doc.paragraphs)
    ]}


@router.post("/preview-fix")
async def preview_fix(req: FixRequest, user: User = Depends(get_current_user),
                      db: Session = Depends(get_db)):
    """按已接受的问题生成修正预览（不落库，审阅模式右栏实时刷新）。"""
    record = _get_record_checked(req.record_id, user, db)
    path = _get_record_docx(record)
    issues = record.issues or []
    out_path = CHECK_DIR / f"{record.id}_preview.docx"
    fixed = check_service.apply_fixes(path, issues, req.accepted_indices, out_path)
    return {"paragraphs": [{"index": i, "text": t} for i, t in enumerate(fixed)]}


@router.post("/fix")
async def fix_document(req: FixRequest, user: User = Depends(get_current_user),
                       db: Session = Depends(get_db)):
    """按已接受的问题生成修正稿并下载。"""
    record = _get_record_checked(req.record_id, user, db)
    path = _get_record_docx(record)
    issues = record.issues or []
    out_path = CHECK_DIR / f"{record.id}_fixed.docx"
    check_service.apply_fixes(path, issues, req.accepted_indices, out_path)
    download_name = f"修正稿_{record.filename}"
    return FileResponse(
        str(out_path),
        filename=download_name,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


# ========== 规则管理 ==========

@router.get("/rules")
async def list_rules(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rules = db.query(FormatRule).filter(FormatRule.is_active == True).all()
    return [_rule_to_dict(r) for r in rules]


@router.post("/rules")
async def create_rule(req: RuleRequest, admin: User = Depends(require_admin_or_above),
                      db: Session = Depends(get_db)):
    valid_targets = ["title", "body", "heading1", "heading2", "page", "signature", "date", "general"]
    if req.target not in valid_targets:
        raise HTTPException(status_code=400, detail=f"target 必须是: {', '.join(valid_targets)}")
    rule = FormatRule(
        id=str(uuid.uuid4()), name=req.name, target=req.target, checks=req.checks,
        severity=req.severity, is_default=req.is_default, is_active=req.is_active,
        remark=req.remark, created_by=admin.id,
    )
    db.add(rule)
    db.commit()
    return {"id": rule.id, "message": "规则已创建"}


@router.put("/rules/{rule_id}")
async def update_rule(rule_id: str, req: RuleRequest,
                      admin: User = Depends(require_admin_or_above), db: Session = Depends(get_db)):
    rule = db.query(FormatRule).filter(FormatRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    rule.name = req.name
    rule.target = req.target
    rule.checks = req.checks
    rule.severity = req.severity
    rule.is_default = req.is_default
    rule.is_active = req.is_active
    rule.remark = req.remark
    db.commit()
    return {"message": "规则已更新"}


@router.delete("/rules/{rule_id}")
async def delete_rule(rule_id: str, admin: User = Depends(require_admin_or_above),
                      db: Session = Depends(get_db)):
    rule = db.query(FormatRule).filter(FormatRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    db.delete(rule)
    db.commit()
    return {"message": "规则已删除"}