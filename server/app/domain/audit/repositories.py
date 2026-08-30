"""审计日志仓储接口。"""
from typing import List, Optional, Tuple

from app.domain.base import Repository
from app.domain.audit.entities import AuditLog


class AuditLogRepository(Repository[AuditLog]):
    def list(self, user_id: Optional[str] = None, action: Optional[str] = None,
             resource_type: Optional[str] = None, page: int = 1,
             page_size: int = 50) -> Tuple[List[AuditLog], int]:
        raise NotImplementedError
