"""审计日志仓储 SQLAlchemy 实现。"""
from typing import List, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.audit.entities import AuditLog
from app.domain.audit.repositories import AuditLogRepository
from app.infrastructure.database.models.audit import AuditLogModel

_FIELDS = ["id", "user_id", "action", "resource_type", "resource_id", "detail",
           "result", "ip_address", "user_agent", "created_at"]


def _to_entity(m: AuditLogModel) -> AuditLog:
    return AuditLog(**{f: getattr(m, f) for f in _FIELDS})


class SqlAlchemyAuditLogRepository(AuditLogRepository):
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, id: str) -> Optional[AuditLog]:
        m = self.db.get(AuditLogModel, id)
        return _to_entity(m) if m else None

    def add(self, log: AuditLog) -> AuditLog:
        m = AuditLogModel(
            user_id=log.user_id, action=log.action, resource_type=log.resource_type,
            resource_id=log.resource_id, detail=log.detail, result=log.result,
            ip_address=log.ip_address, user_agent=log.user_agent,
        )
        self.db.add(m)
        self.db.commit()
        self.db.refresh(m)
        return _to_entity(m)

    def list(self, user_id: Optional[str] = None, action: Optional[str] = None,
             resource_type: Optional[str] = None, page: int = 1,
             page_size: int = 50) -> Tuple[List[AuditLog], int]:
        base = select(AuditLogModel)
        if user_id:
            base = base.where(AuditLogModel.user_id == user_id)
        if action:
            base = base.where(AuditLogModel.action == action)
        if resource_type:
            base = base.where(AuditLogModel.resource_type == resource_type)
        total = self.db.scalar(select(func.count()).select_from(base.subquery())) or 0
        q = base.order_by(AuditLogModel.created_at.desc()) \
            .offset((page - 1) * page_size).limit(page_size)
        return [_to_entity(m) for m in self.db.scalars(q).all()], total

    def delete(self, log: AuditLog) -> None:
        m = self.db.get(AuditLogModel, log.id)
        if m:
            self.db.delete(m)
            self.db.commit()
