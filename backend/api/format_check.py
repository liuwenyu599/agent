# -*- coding: utf-8 -*-
"""格式校验 API（系统级独立功能，与写作模板/对话解耦）

接口：
- POST   /format-check/check          上传文件并校验（任何登录用户）
- GET    /format-check/records        我的校验历史
- GET    /format-check/records/{id}   校验详情
- GET    /format-check/rules          规则列表（登录用户可见，用于预览）
- POST   /format-check/rules          新增规则（管理员）
- PUT    /format-check/rules/{id}     修改规则（管理员）
- DELETE /format-check/rules/{id}     删除规则（管理员）
- POST   /format-check/fix            （预留）自动修正
"""
import uuid
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel

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


def _rule_to_dict(r: FormatRule) -> dict:
    return {
        "id": r.id, "name": r.name, "target": r.target, "checks": r.checks,
        "severity": r.severity, "is_default": r.is_default, "is_active": r.is_active,
        "remark": r.remark,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


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

    tmp_path = CHECK_DIR / f"{uuid.uuid4().hex}_{filename}"
    tmp_path.write_bytes(data)
    try:
        result = check_service.check_file(tmp_path, filename, rules, use_ai=use_ai)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"校验过程出错: {e}")
    finally:
        tmp_path.unlink(missing_ok=True)

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
    record = db.query(FormatCheckRecord).filter(FormatCheckRecord.id == record_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Record not found")
    if record.user_id != user.id and user.role not in ["developer", "knowledge_admin", "admin"]:
        raise HTTPException(status_code=403, detail="No permission")
    return {
        "id": record.id, "filename": record.filename, "file_type": record.file_type,
        "issues": record.issues, "issue_count": record.issue_count,
        "rule_snapshot": record.rule_snapshot,
        "created_at": record.created_at.isoformat() if record.created_at else None,
    }


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


# ========== （预留）自动修正 ==========

@router.post("/fix")
async def fix_document(file: UploadFile = File(...),
                       user: User = Depends(get_current_user)):
    """预留接口：自动修正格式。当前版本未启用，仅返回明确提示。"""
    raise HTTPException(status_code=501, detail="自动修正功能将在后续版本提供，当前仅支持格式校验")
