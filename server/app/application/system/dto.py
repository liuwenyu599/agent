"""系统配置/模型版本请求模型。"""
from typing import Any, Dict, Optional

from pydantic import BaseModel


class ModelVersionCreateRequest(BaseModel):
    name: str
    version: str
    provider: str = "qwen"
    endpoint: Optional[str] = None
    capabilities: Dict[str, Any] = {}
    status: str = "active"
    is_active: bool = True


class ModelVersionActivateRequest(BaseModel):
    id: str


class SystemConfigUpsertRequest(BaseModel):
    key: str
    value: Any
    category: str = "general"
    description: Optional[str] = None
