"""系统配置领域实体。"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional


@dataclass
class ModelVersion:
    """AI 模型版本（与业务数据完全解耦）。"""
    name: str
    version: str
    id: Optional[str] = None
    provider: str = "qwen"
    endpoint: Optional[str] = None
    capabilities: Dict[str, Any] = field(default_factory=dict)
    status: str = "active"
    is_active: bool = True
    created_at: Optional[datetime] = None
    activated_at: Optional[datetime] = None


@dataclass
class SystemConfig:
    """系统配置键值对（敏感配置走环境变量，此处保存非敏感运行配置）。"""
    key: str
    value: Any
    id: Optional[str] = None
    category: str = "general"
    description: Optional[str] = None
    updated_by: Optional[str] = None
    updated_at: Optional[datetime] = None
