"""格式校验应用服务：编排校验流程、记录与规则管理、审阅模式文件存取。"""
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.application.format_check.check_engine import FormatCheckEngine
from app.application.shared.writing_assistant import WritingAssistant
from app.core.config import settings
from app.core.exceptions import AppError, NotFoundError, PermissionDeniedError
from app.domain.format_check.entities import (
    VALID_RULE_TARGETS,
    FormatCheckRecord,
    FormatRule,
)
from app.domain.identity.entities import ADMIN_OR_ABOVE, User
from app.infrastructure.repositories.format_check import (
    SqlAlchemyFormatCheckRecordRepository,
    SqlAlchemyFormatRuleRepository,
)

SUPPORTED_SUFFIXES = ("docx", "txt", "md", "pdf")


def _rule_to_dict(r: FormatRule) -> dict:
    return {
        "id": r.id, "name": r.name, "target": r.target, "checks": r.checks,
        "severity": r.severity, "is_default": r.is_default, "is_active": r.is_active,
        "remark": r.remark,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


def _record_brief(r: FormatCheckRecord) -> dict:
    return {
        "id": r.id, "filename": r.filename, "file_type": r.file_type,
        "issue_count": r.issue_count, "rule_issue_count": r.rule_issue_count,
        "ai_issue_count": r.ai_issue_count,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


class FormatCheckService:
    def __init__(self, db: Session, assistant: Optional[WritingAssistant] = None) -> None:
        self.db = db
        self.rules = SqlAlchemyFormatRuleRepository(db)
        self.records = SqlAlchemyFormatCheckRecordRepository(db)
        self.engine = FormatCheckEngine(assistant)

    # ---- 校验文件存放（审阅/修正用，docx 保留，其他类型校验后即删） ----
    @property
    def check_dir(self) -> Path:
        d = settings.DATA_DIR / "format-check"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def record_file(self, record_id: str) -> Path:
        return self.check_dir / f"{record_id}.docx"

    # ========== 校验 ==========
    async def check_upload(self, file, user: User, use_ai: bool = True,
                           rule_ids: Optional[str] = None) -> dict:
        filename = file.filename or "unnamed"
        suffix = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
        if suffix not in SUPPORTED_SUFFIXES:
            raise AppError(400, f"暂不支持 .{suffix} 文件的格式校验，请上传 Word(.docx) 文件")

        data = await file.read()
        if len(data) > settings.FORMAT_CHECK_MAX_SIZE:
            raise AppError(400, "文件超过大小限制")
        if not data:
            raise AppError(400, "文件为空")

        ids = [i for i in rule_ids.split(",") if i] if rule_ids else None
        rules = self.rules.list_for_check(ids)
        if not rules:
            raise AppError(
                400,
                "尚未配置任何格式规则。请管理员先在「格式校验-规则管理」中录入司法局正式格式规范。"
            )
        rule_dicts = [_rule_to_dict(r) for r in rules]

        tmp_path = self.check_dir / f"{uuid.uuid4().hex}_{filename}"
        tmp_path.write_bytes(data)
        try:
            result = self.engine.check_file(tmp_path, filename, rule_dicts, use_ai=use_ai)
        except ValueError as e:
            tmp_path.unlink(missing_ok=True)
            raise AppError(400, str(e))
        except Exception as e:
            tmp_path.unlink(missing_ok=True)
            raise AppError(500, f"校验过程出错: {e}")

        issues = result["issues"]
        record = self.records.add(FormatCheckRecord(
            user_id=user.id, filename=filename, file_type=result["file_type"],
            rule_snapshot=[{"id": r["id"], "name": r["name"], "target": r["target"],
                            "checks": r["checks"]} for r in rule_dicts],
            issues=issues, issue_count=len(issues),
            rule_issue_count=len([i for i in issues if i["source"] == "rule"]),
            ai_issue_count=len([i for i in issues if i["source"] == "ai"]),
        ))

        # docx 保留源文件（以记录ID命名），供审阅模式与自动修正使用；其他类型删除
        if result["file_type"] == "docx":
            tmp_path.replace(self.record_file(record.id))
        else:
            tmp_path.unlink(missing_ok=True)

        return {
            "record_id": record.id,
            "filename": filename,
            "file_type": result["file_type"],
            "ai_used": result["ai_used"],
            "issue_count": len(issues),
            "issues": issues,
            "rules_used": [{"id": r["id"], "name": r["name"], "target": r["target"]}
                           for r in rule_dicts],
        }

    # ========== 记录 ==========
    def list_records(self, user: User, page: int, page_size: int) -> dict:
        records, total = self.records.list_by_user(user.id, page, page_size)
        return {
            "total": total, "page": page, "page_size": page_size,
            "data": [_record_brief(r) for r in records],
        }

    def get_record_checked(self, record_id: str, user: User) -> FormatCheckRecord:
        record = self.records.get(record_id)
        if not record:
            raise NotFoundError("Record not found")
        if record.user_id != user.id and user.role not in ADMIN_OR_ABOVE:
            raise PermissionDeniedError("No permission")
        return record

    def get_record(self, record_id: str, user: User) -> dict:
        record = self.get_record_checked(record_id, user)
        return {
            "id": record.id, "filename": record.filename, "file_type": record.file_type,
            "issues": record.issues, "issue_count": record.issue_count,
            "rule_snapshot": record.rule_snapshot,
            "created_at": record.created_at.isoformat() if record.created_at else None,
        }

    # ========== 审阅模式 ==========
    def _get_record_docx(self, record: FormatCheckRecord) -> Path:
        if record.file_type != "docx":
            raise AppError(400, "仅 Word(.docx) 文件支持审阅与自动修正")
        path = self.record_file(record.id)
        if not path.exists():
            raise AppError(410, "源文件已过期，请重新上传校验")
        return path

    def get_record_paragraphs(self, record_id: str, user: User) -> dict:
        from docx import Document as DocxDocument
        record = self.get_record_checked(record_id, user)
        path = self._get_record_docx(record)
        doc = DocxDocument(str(path))
        return {"paragraphs": [
            {"index": i, "text": p.text} for i, p in enumerate(doc.paragraphs)
        ]}

    def preview_fix(self, record_id: str, accepted_indices: List[int], user: User) -> dict:
        record = self.get_record_checked(record_id, user)
        path = self._get_record_docx(record)
        out_path = self.check_dir / f"{record.id}_preview.docx"
        fixed = self.engine.apply_fixes(path, record.issues or [], accepted_indices, out_path)
        return {"paragraphs": [{"index": i, "text": t} for i, t in enumerate(fixed)]}

    def fix_document(self, record_id: str, accepted_indices: List[int],
                     user: User) -> Tuple[Path, str]:
        """生成修正稿。返回 (文件路径, 下载文件名)。"""
        record = self.get_record_checked(record_id, user)
        path = self._get_record_docx(record)
        out_path = self.check_dir / f"{record.id}_fixed.docx"
        self.engine.apply_fixes(path, record.issues or [], accepted_indices, out_path)
        return out_path, f"修正稿_{record.filename}"

    # ========== 规则管理 ==========
    def list_rules(self) -> List[dict]:
        return [_rule_to_dict(r) for r in self.rules.list_active()]

    def create_rule(self, req, admin: User) -> dict:
        if req.target not in VALID_RULE_TARGETS:
            raise AppError(400, f"target 必须是: {', '.join(VALID_RULE_TARGETS)}")
        rule = self.rules.add(FormatRule(
            name=req.name, target=req.target, checks=req.checks,
            severity=req.severity, is_default=req.is_default,
            is_active=req.is_active, remark=req.remark, created_by=admin.id,
        ))
        return {"id": rule.id, "message": "规则已创建"}

    def update_rule(self, rule_id: str, req) -> dict:
        if req.target not in VALID_RULE_TARGETS:
            raise AppError(400, f"target 必须是: {', '.join(VALID_RULE_TARGETS)}")
        rule = self.rules.get(rule_id)
        if not rule:
            raise NotFoundError("Rule not found")
        rule.name = req.name
        rule.target = req.target
        rule.checks = req.checks
        rule.severity = req.severity
        rule.is_default = req.is_default
        rule.is_active = req.is_active
        rule.remark = req.remark
        self.rules.update(rule)
        return {"message": "规则已更新"}

    def delete_rule(self, rule_id: str) -> dict:
        rule = self.rules.get(rule_id)
        if not rule:
            raise NotFoundError("Rule not found")
        self.rules.hard_delete(rule)
        return {"message": "规则已删除"}
