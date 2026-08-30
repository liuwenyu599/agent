"""审计应用服务：记录并查询审计日志。"""
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.domain.audit.entities import AuditLog
from app.domain.audit.repositories import AuditLogRepository
from app.domain.identity.entities import User
from app.infrastructure.repositories.audit import SqlAlchemyAuditLogRepository


class AuditService:
    def __init__(self, repo: AuditLogRepository) -> None:
        self.repo = repo

    @classmethod
    def from_db(cls, db: Session) -> "AuditService":
        return cls(SqlAlchemyAuditLogRepository(db))

    def log(
        self,
        action: str,
        resource_type: str,
        user: Optional[User] = None,
        resource_id: Optional[str] = None,
        detail: Optional[Dict[str, Any]] = None,
        result: str = "success",
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> AuditLog:
        log = AuditLog(
            user_id=user.id if user else None,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            detail=detail or {},
            result=result,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        return self.repo.add(log)

    def list(
        self,
        user_id: Optional[str] = None,
        action: Optional[str] = None,
        resource_type: Optional[str] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> Tuple[List[AuditLog], int]:
        return self.repo.list(user_id, action, resource_type, page, page_size)
