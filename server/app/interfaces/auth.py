"""认证路由：登录 / 注册 / 改密。

首个系统管理员不再允许通过匿名 HTTP 创建；必须使用
``python -m scripts.create_admin`` 在部署主机本地初始化，消除抢注窗口。
"""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.application.audit.service import AuditService
from app.application.identity.dto import (
    ChangePasswordRequest,
    LoginRequest,
    RegisterRequest,
)
from app.application.identity.login_limiter import login_rate_limiter
from app.application.identity.service import AuthService
from app.core.exceptions import AppError
from app.domain.identity.entities import User
from app.infrastructure.database import get_db
from app.infrastructure.repositories.identity import SqlAlchemyUserRepository
from app.interfaces.deps import get_current_user_unchecked, require_developer

router = APIRouter(prefix="/auth", tags=["认证"])


def get_auth_service(db: Session = Depends(get_db)) -> AuthService:
    return AuthService(SqlAlchemyUserRepository(db), db=db, audit=AuditService.from_db(db))


def _client_ip(request: Request) -> str:
    """Use the socket peer IP; do not trust spoofable X-Forwarded-For by default."""
    return request.client.host if request.client else "unknown"


@router.post("/login")
def login(req: LoginRequest, request: Request,
          svc: AuthService = Depends(get_auth_service)):
    ip = _client_ip(request)
    login_rate_limiter.check(ip, req.username)
    try:
        token, user = svc.login(req.username, req.password)
    except AppError as exc:
        # Only wrong credentials count as brute-force failures. Disabled accounts (403),
        # validation errors, etc. must not let an attacker lock arbitrary users cheaply.
        if exc.status_code == 401:
            login_rate_limiter.record_failure(ip, req.username)
        raise
    login_rate_limiter.record_success(ip, req.username)
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
