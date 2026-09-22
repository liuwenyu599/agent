"""格式校验仓储 SQLAlchemy 实现。"""
import json
from typing import Iterable, List, Optional, Tuple

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
                  "created_at", "applied_ids", "resolved_ids"]

# 以 TEXT 列存储的整数数组字段（内容统一为 JSON 整数数组）
_ID_LIST_FIELDS = ("applied_ids", "resolved_ids")


def dump_id_list(values: Optional[Iterable]) -> str:
    """把 issue id 集合序列化为 JSON **整数**数组文本。

    容忍标量（单个 id）与 None，非法元素直接丢弃，保证落库内容永远是整数数组。
    """
    if values is None:
        return "[]"
    if isinstance(values, (int, float, str)):
        values = [values]
    try:
        items = list(values)
    except TypeError:
        return "[]"
    out: List[int] = []
    for v in items:
        try:
            out.append(int(v))
        except (TypeError, ValueError):
            continue
    return json.dumps(out, ensure_ascii=False)


def load_id_list(raw) -> List[int]:
    """反序列化 issue id 集合；数字 3 与字符串 "3" 都要能认，非法值丢弃。"""
    if raw is None:
        return []
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return []
        try:
            raw = json.loads(text)
        except ValueError:
            return []
    if isinstance(raw, (int, str)):
        raw = [raw]
    if not isinstance(raw, (list, tuple, set)):
        return []
    out: List[int] = []
    for v in raw:
        try:
            out.append(int(v))
        except (TypeError, ValueError):
            continue
    return out


def _rule_to_entity(m: FormatRuleModel) -> FormatRule:
    return FormatRule(**{f: getattr(m, f) for f in _RULE_FIELDS})


def _record_to_entity(m: FormatCheckRecordModel) -> FormatCheckRecord:
    values = {f: getattr(m, f, None) for f in _RECORD_FIELDS}
    for f in _ID_LIST_FIELDS:
        values[f] = load_id_list(values.get(f))
    return FormatCheckRecord(**values)


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
            applied_ids=dump_id_list(record.applied_ids),
            resolved_ids=dump_id_list(record.resolved_ids),
        )
        self.db.add(m)
        self.db.commit()
        self.db.refresh(m)
        return _record_to_entity(m)

    def update(self, record: FormatCheckRecord) -> Optional[FormatCheckRecord]:
        """回写记录的可变字段（不含 id / created_at）。"""
        m = self.db.get(FormatCheckRecordModel, record.id)
        if m is None:
            return None
        for f in _RECORD_FIELDS:
            if f in ("id", "created_at"):
                continue
            value = getattr(record, f)
            setattr(m, f, dump_id_list(value) if f in _ID_LIST_FIELDS else value)
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
