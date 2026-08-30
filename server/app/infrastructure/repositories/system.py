"""系统配置仓储 SQLAlchemy 实现。"""
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.system.entities import ModelVersion, SystemConfig
from app.domain.system.repositories import ModelVersionRepository, SystemConfigRepository
from app.infrastructure.database.models.system import ModelVersionModel, SystemConfigModel


_MV_FIELDS = ["id", "name", "version", "provider", "endpoint", "capabilities",
              "status", "is_active", "created_at", "activated_at"]
_SC_FIELDS = ["id", "key", "value", "category", "description", "updated_by", "updated_at"]


def _mv_to_entity(m: ModelVersionModel) -> ModelVersion:
    return ModelVersion(**{f: getattr(m, f) for f in _MV_FIELDS})


def _sc_to_entity(m: SystemConfigModel) -> SystemConfig:
    return SystemConfig(**{f: getattr(m, f) for f in _SC_FIELDS})


class SqlAlchemyModelVersionRepository(ModelVersionRepository):
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, id: str) -> Optional[ModelVersion]:
        m = self.db.get(ModelVersionModel, id)
        return _mv_to_entity(m) if m else None

    def get_active(self) -> Optional[ModelVersion]:
        m = self.db.scalars(select(ModelVersionModel).where(
            ModelVersionModel.is_active == True).order_by(  # noqa: E712
                ModelVersionModel.activated_at.desc())).first()
        return _mv_to_entity(m) if m else None

    def list_all(self) -> List[ModelVersion]:
        return [_mv_to_entity(m) for m in self.db.scalars(
            select(ModelVersionModel).order_by(ModelVersionModel.created_at.desc())).all()]

    def add(self, mv: ModelVersion) -> ModelVersion:
        m = ModelVersionModel(
            name=mv.name, version=mv.version, provider=mv.provider,
            endpoint=mv.endpoint, capabilities=mv.capabilities,
            status=mv.status, is_active=mv.is_active, activated_at=mv.activated_at,
        )
        self.db.add(m)
        self.db.commit()
        self.db.refresh(m)
        return _mv_to_entity(m)

    def update(self, mv: ModelVersion) -> ModelVersion:
        m = self.db.get(ModelVersionModel, mv.id)
        if m:
            for f in _MV_FIELDS:
                if f in ("id", "created_at"):
                    continue
                setattr(m, f, getattr(mv, f))
            self.db.commit()
            self.db.refresh(m)
            return _mv_to_entity(m)
        return mv

    def delete(self, mv: ModelVersion) -> None:
        m = self.db.get(ModelVersionModel, mv.id)
        if m:
            self.db.delete(m)
            self.db.commit()


class SqlAlchemySystemConfigRepository(SystemConfigRepository):
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, id: str) -> Optional[SystemConfig]:
        m = self.db.get(SystemConfigModel, id)
        return _sc_to_entity(m) if m else None

    def get_by_key(self, key: str) -> Optional[SystemConfig]:
        m = self.db.scalars(select(SystemConfigModel).where(
            SystemConfigModel.key == key)).first()
        return _sc_to_entity(m) if m else None

    def list_by_category(self, category: str) -> List[SystemConfig]:
        return [_sc_to_entity(m) for m in self.db.scalars(
            select(SystemConfigModel).where(
                SystemConfigModel.category == category)).all()]

    def add(self, cfg: SystemConfig) -> SystemConfig:
        m = SystemConfigModel(
            key=cfg.key, value=cfg.value, category=cfg.category,
            description=cfg.description, updated_by=cfg.updated_by,
        )
        self.db.add(m)
        self.db.commit()
        self.db.refresh(m)
        return _sc_to_entity(m)

    def upsert(self, cfg: SystemConfig) -> SystemConfig:
        m = self.db.scalars(select(SystemConfigModel).where(
            SystemConfigModel.key == cfg.key)).first()
        if m:
            m.value = cfg.value
            m.category = cfg.category
            m.description = cfg.description
            m.updated_by = cfg.updated_by
        else:
            m = SystemConfigModel(
                key=cfg.key, value=cfg.value, category=cfg.category,
                description=cfg.description, updated_by=cfg.updated_by)
            self.db.add(m)
        self.db.commit()
        self.db.refresh(m)
        return _sc_to_entity(m)

    def delete(self, cfg: SystemConfig) -> None:
        m = self.db.get(SystemConfigModel, cfg.id)
        if m:
            self.db.delete(m)
            self.db.commit()
