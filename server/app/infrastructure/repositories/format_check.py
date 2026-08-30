"""格式校验仓储 SQLAlchemy 实现。"""
from typing import List, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.format_check.entities import FormatCheckRecord, FormatRule
from app.domain.format_check.repositories import (
    FormatCheckRecordRepository,
    FormatRuleRepository,
)
from app.infrastructure.database.models.format_check import (
    FormatCheckRecordModel,
    FormatRuleModel,
)

_RULE_FIELDS = ["id", "name", "target", "checks", "severity", "is_active",
                "is_default", "remark", "created_by", "created_at", "updated_at"]

_RECORD_FIELDS = ["id", "user_id", "filename", "file_type", "rule_snapshot",
                  "issues", "issue_count", "rule_issue_count", "ai_issue_count",
                  "created_at"]


def _rule_to_entity(m: FormatRuleModel) -> FormatRule:
    return FormatRule(**{f: getattr(m, f) for f in _RULE_FIELDS})


def _record_to_entity(m: FormatCheckRecordModel) -> FormatCheckRecord:
    return FormatCheckRecord(**{f: getattr(m, f) for f in _RECORD_FIELDS})


class SqlAlchemyFormatRuleRepository(FormatRuleRepository):
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, id: str) -> Optional[FormatRule]:
        m = self.db.get(FormatRuleModel, id)
        return _rule_to_entity(m) if m else None

    def list_active(self) -> List[FormatRule]:
        q = select(FormatRuleModel).where(FormatRuleModel.is_active == True)  # noqa: E712
        return [_rule_to_entity(m) for m in self.db.scalars(q).all()]

    def list_for_check(self, rule_ids: Optional[List[str]]) -> List[FormatRule]:
        q = select(FormatRuleModel).where(FormatRuleModel.is_active == True)  # noqa: E712
        if rule_ids:
            q = q.where(FormatRuleModel.id.in_(rule_ids))
        else:
            q = q.where(FormatRuleModel.is_default == True)  # noqa: E712
        return [_rule_to_entity(m) for m in self.db.scalars(q).all()]

    def add(self, rule: FormatRule) -> FormatRule:
        m = FormatRuleModel(
            name=rule.name, target=rule.target, checks=rule.checks,
            severity=rule.severity, is_active=rule.is_active,
            is_default=rule.is_default, remark=rule.remark, created_by=rule.created_by,
        )
        self.db.add(m)
        self.db.commit()
        self.db.refresh(m)
        return _rule_to_entity(m)

    def update(self, rule: FormatRule) -> FormatRule:
        m = self.db.get(FormatRuleModel, rule.id)
        if m:
            for f in _RULE_FIELDS:
                if f in ("id", "created_at", "created_by"):
                    continue
                setattr(m, f, getattr(rule, f))
            self.db.commit()
            self.db.refresh(m)
            return _rule_to_entity(m)
        return rule

    def delete(self, rule: FormatRule) -> None:
        self.hard_delete(rule)

    def hard_delete(self, rule: FormatRule) -> None:
        m = self.db.get(FormatRuleModel, rule.id)
        if m:
            self.db.delete(m)
            self.db.commit()


class SqlAlchemyFormatCheckRecordRepository(FormatCheckRecordRepository):
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, id: str) -> Optional[FormatCheckRecord]:
        m = self.db.get(FormatCheckRecordModel, id)
        return _record_to_entity(m) if m else None

    def add(self, record: FormatCheckRecord) -> FormatCheckRecord:
        m = FormatCheckRecordModel(
            user_id=record.user_id, filename=record.filename, file_type=record.file_type,
            rule_snapshot=record.rule_snapshot, issues=record.issues,
            issue_count=record.issue_count, rule_issue_count=record.rule_issue_count,
            ai_issue_count=record.ai_issue_count,
        )
        self.db.add(m)
        self.db.commit()
        self.db.refresh(m)
        return _record_to_entity(m)

    def delete(self, record: FormatCheckRecord) -> None:
        m = self.db.get(FormatCheckRecordModel, record.id)
        if m:
            self.db.delete(m)
            self.db.commit()

    def list_by_user(self, user_id: str, page: int, page_size: int) -> Tuple[List[FormatCheckRecord], int]:
        base = select(FormatCheckRecordModel).where(FormatCheckRecordModel.user_id == user_id)
        total = self.db.scalar(select(func.count()).select_from(base.subquery())) or 0
        q = base.order_by(FormatCheckRecordModel.created_at.desc()) \
            .offset((page - 1) * page_size).limit(page_size)
        return [_record_to_entity(m) for m in self.db.scalars(q).all()], total
