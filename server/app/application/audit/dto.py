"""审计模块请求/响应模型。"""
from typing import Any, Dict, Optional

from pydantic import BaseModel


class AuditLogRequest(BaseModel):
    action: str
    resource_type: str
    resource_id: Optional[str] = None
    detail: Dict[str, Any] = {}
    result: str = "success"
