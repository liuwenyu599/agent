"""系统配置领域层。"""
from app.domain.system.entities import ModelVersion, SystemConfig
from app.domain.system.repositories import ModelVersionRepository, SystemConfigRepository

__all__ = ["ModelVersion", "SystemConfig", "ModelVersionRepository", "SystemConfigRepository"]
