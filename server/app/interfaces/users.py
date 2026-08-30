"""用户管理路由（管理端）。响应结构与旧系统一致。"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.application.identity.dto import (
    ResetPasswordRequest,
    UserCreateRequest,
    UserUpdateRequest,
)
from app.application.identity.service import UserService
from app.domain.identity.entities import User
from app.infrastructure.database import get_db
from app.infrastructure.repositories.identity import SqlAlchemyUserRepository
from app.interfaces.deps import require_admin_or_above

router = APIRouter(prefix="/users", tags=["用户"])


def get_user_service(db: Session = Depends(get_db)) -> UserService:
    return UserService(SqlAlchemyUserRepository(db))


@router.get("/")
def list_users(
    admin: User = Depends(require_admin_or_above),
    svc: UserService = Depends(get_user_service),
):
    return [
        {
            "id": u.id,
            "username": u.username,
            "real_name": u.real_name,
            "email": u.email,
            "department": u.department,
            "role": u.role,
            "is_active": u.is_active,
            "created_at": u.created_at.isoformat() if u.created_at else None,
        }
        for u in svc.list_users()
    ]


@router.post("/")
def create_user(
    req: UserCreateRequest,
    admin: User = Depends(require_admin_or_above),
    svc: UserService = Depends(get_user_service),
):
    user = svc.create_user(admin, req.username, req.email, req.password,
                           req.real_name, req.department, req.role)
    return {"id": user.id, "message": "User created"}


@router.put("/{user_id}")
def update_user(
    user_id: str,
    req: UserUpdateRequest,
    admin: User = Depends(require_admin_or_above),
    svc: UserService = Depends(get_user_service),
):
    svc.update_user(admin, user_id, req.real_name, req.department, req.is_active, req.role)
    return {"message": "User updated"}


@router.post("/{user_id}/reset-password")
def reset_password(
    user_id: str,
    req: ResetPasswordRequest,
    admin: User = Depends(require_admin_or_above),
    svc: UserService = Depends(get_user_service),
):
    svc.reset_password(user_id, req.password)
    return {"message": "Password reset successfully"}


@router.delete("/{user_id}")
def delete_user(
    user_id: str,
    admin: User = Depends(require_admin_or_above),
    svc: UserService = Depends(get_user_service),
):
    svc.deactivate_user(admin, user_id)
    return {"message": "User deactivated"}
