"""系统配置与模型版本应用服务。"""
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import AppError, NotFoundError, PermissionDeniedError
from app.domain.identity.entities import ADMIN_OR_ABOVE, ROLE_DEVELOPER, User
from app.domain.system.entities import ModelVersion, SystemConfig
from app.infrastructure.repositories.system import (
    SqlAlchemyModelVersionRepository,
    SqlAlchemySystemConfigRepository,
)


class SystemService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.mv_repo = SqlAlchemyModelVersionRepository(db)
        self.cfg_repo = SqlAlchemySystemConfigRepository(db)

    # ---- 模型版本 ----
    def get_active_model(self) -> Dict[str, Any]:
        mv = self.mv_repo.get_active()
        if not mv:
            return {
                "id": None,
                "name": settings.MODEL_NAME,
                "provider": settings.AI_PROVIDER or "qwen",
                "endpoint": settings.MODEL_SERVICE_URL,
                "source": "env",
            }
        return self._mv_to_dict(mv)

    def list_models(self) -> List[Dict[str, Any]]:
        return [self._mv_to_dict(mv) for mv in self.mv_repo.list_all()]

    def create_model(self, actor: User, req: Any) -> Dict[str, Any]:
        if actor.role not in ADMIN_OR_ABOVE:
            raise PermissionDeniedError("仅管理员可维护模型版本")
        mv = ModelVersion(
            name=req.name, version=req.version, provider=req.provider,
            endpoint=req.endpoint, capabilities=req.capabilities,
            status=req.status, is_active=req.is_active,
            activated_at=datetime.utcnow() if req.is_active else None,
        )
        mv = self.mv_repo.add(mv)
        return {"id": mv.id, "message": "Model version created"}

    def activate_model(self, actor: User, model_id: str) -> Dict[str, Any]:
        if actor.role != ROLE_DEVELOPER:
            raise PermissionDeniedError("仅系统管理员可切换生产模型")
        for mv in self.mv_repo.list_all():
            if mv.is_active:
                mv.is_active = False
                mv.status = "standby"
                self.mv_repo.update(mv)
        target = self.mv_repo.get(model_id)
        if not target:
            raise NotFoundError("Model version not found")
        target.is_active = True
        target.status = "active"
        target.activated_at = datetime.utcnow()
        self.mv_repo.update(target)
        return {"message": "Model activated", "id": target.id}

    def _mv_to_dict(self, mv: ModelVersion) -> Dict[str, Any]:
        return {
            "id": mv.id,
            "name": mv.name,
            "version": mv.version,
            "provider": mv.provider,
            "endpoint": mv.endpoint,
            "capabilities": mv.capabilities,
            "status": mv.status,
            "is_active": mv.is_active,
            "created_at": mv.created_at.isoformat() if mv.created_at else None,
            "activated_at": mv.activated_at.isoformat() if mv.activated_at else None,
        }

    # ---- 系统配置 ----
    def get_config(self, key: str) -> Dict[str, Any]:
        cfg = self.cfg_repo.get_by_key(key)
        if not cfg:
            raise NotFoundError("Config not found")
        return self._cfg_to_dict(cfg)

    def list_configs(self, category: Optional[str] = None) -> List[Dict[str, Any]]:
        if category:
            items = self.cfg_repo.list_by_category(category)
        else:
            # 没有通用 list 方法，按 category 为 general 查询；不够时扩展
            items = self.cfg_repo.list_by_category("general") + self.cfg_repo.list_by_category("security")
        return [self._cfg_to_dict(c) for c in items]

    def upsert_config(self, actor: User, req: Any) -> Dict[str, Any]:
        if actor.role not in ADMIN_OR_ABOVE:
            raise PermissionDeniedError("仅管理员可修改系统配置")
        cfg = SystemConfig(
            key=req.key, value=req.value, category=req.category,
            description=req.description, updated_by=actor.id,
        )
        cfg = self.cfg_repo.upsert(cfg)
        return {"id": cfg.id, "message": "Config upserted"}

    def _cfg_to_dict(self, cfg: SystemConfig) -> Dict[str, Any]:
        return {
            "id": cfg.id,
            "key": cfg.key,
            "value": cfg.value,
            "category": cfg.category,
            "description": cfg.description,
            "updated_by": cfg.updated_by,
            "updated_at": cfg.updated_at.isoformat() if cfg.updated_at else None,
        }
