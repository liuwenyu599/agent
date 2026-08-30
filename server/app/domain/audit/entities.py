"""审计领域实体。"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional


@dataclass
class AuditLog:
    """审计日志。"""
    action: str
    resource_type: str
    id: Optional[str] = None
    user_id: Optional[str] = None
    resource_id: Optional[str] = None
    detail: Dict[str, Any] = field(default_factory=dict)
    result: str = "success"
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    created_at: Optional[datetime] = None
