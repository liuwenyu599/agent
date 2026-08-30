"""系统配置仓储接口。"""
from typing import List, Optional

from app.domain.base import Repository
from app.domain.system.entities import ModelVersion, SystemConfig


class ModelVersionRepository(Repository[ModelVersion]):
    def get_active(self) -> Optional[ModelVersion]:
        raise NotImplementedError

    def list_all(self) -> List[ModelVersion]:
        raise NotImplementedError

    def update(self, mv: ModelVersion) -> ModelVersion:
        raise NotImplementedError


class SystemConfigRepository(Repository[SystemConfig]):
    def get_by_key(self, key: str) -> Optional[SystemConfig]:
        raise NotImplementedError

    def list_by_category(self, category: str) -> List[SystemConfig]:
        raise NotImplementedError

    def upsert(self, cfg: SystemConfig) -> SystemConfig:
        raise NotImplementedError
