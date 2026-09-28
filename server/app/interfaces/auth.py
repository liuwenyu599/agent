"""认证路由：登录 / 注册 / 首用户初始化。响应结构与旧系统一致。"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.application.audit.service import AuditService
from app.application.identity.dto import (
    ChangePasswordRequest,
    LoginRequest,
    RegisterRequest,
)
from app.application.identity.service import AuthService
from app.domain.identity.entities import User
from app.infrastructure.database import get_db
from app.infrastructure.repositories.identity import SqlAlchemyUserRepository
from app.interfaces.deps import get_current_user, get_current_user_unchecked, require_developer

router = APIRouter(prefix="/auth", tags=["认证"])


def get_auth_service(db: Session = Depends(get_db)) -> AuthService:
    return AuthService(SqlAlchemyUserRepository(db), db=db, audit=AuditService.from_db(db))


@router.post("/login")
def login(req: LoginRequest, svc: AuthService = Depends(get_auth_service)):
    token, user = svc.login(req.username, req.password)
    return {
        "access_token": token,
        "user": user.to_public_dict(),
        # 管理员重置过密码的账号，前端据此强制弹出修改密码
        "must_change_password": bool(getattr(user, "must_change_password", False)),
    }


@router.post("/change-password")
def change_password(req: ChangePasswordRequest,
                    user: User = Depends(get_current_user_unchecked),
                    svc: AuthService = Depends(get_auth_service)):
    """当前登录用户修改自己的密码：校验旧密码 + 二次确认 + 复杂度。"""
    svc.change_password(user, req.old_password, req.new_password, req.confirm_password)
    return {"message": "密码修改成功"}


@router.post("/register")
def register(
    req: RegisterRequest,
    current_user: User = Depends(require_developer),
    svc: AuthService = Depends(get_auth_service),
):
    user = svc.register(current_user, req.username, req.email, req.password,
                        req.real_name, req.department, req.role, req.department_code)
    return {"message": "用户创建成功", "user": user.to_public_dict()}


@router.post("/register-first")
def register_first(req: RegisterRequest, svc: AuthService = Depends(get_auth_service)):
    from app.domain.identity.entities import ROLE_DEVELOPER
    token, user = svc.register_first(req.username, req.email, req.password,
                                     req.real_name, req.department, ROLE_DEVELOPER,
                                     getattr(req, "department_code", ""))
    return {"access_token": token, "user": user.to_public_dict()}


@router.get("/check-first-user")
def check_first_user(svc: AuthService = Depends(get_auth_service)):
    return {"is_first": svc.is_first_user()}


@router.get("/me")
def get_me(user: User = Depends(get_current_user_unchecked)):
    return {
        "id": user.id,
        "username": user.username,
        "real_name": user.real_name,
        "role": user.role,
        "department": user.department,
        "department_code": getattr(user, "department_code", "") or "",
        "must_change_password": bool(getattr(user, "must_change_password", False)),
    }
