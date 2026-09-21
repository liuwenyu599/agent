"""FastAPI 共享依赖：认证与 RBAC。各业务路由统一从这里取当前用户。"""
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.exceptions import AppError, PermissionDeniedError
from app.core.security import decode_token
from app.domain.identity.authorization import is_privileged, is_system_admin
from app.domain.identity.entities import User
from app.infrastructure.database import get_db
from app.infrastructure.repositories.identity import SqlAlchemyUserRepository

security = HTTPBearer(auto_error=False)


def get_current_user_unchecked(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    """只做登录态校验，不校验「是否必须先改密码」。

    仅用于 /auth/change-password、/auth/me 等改密自身所需的端点。
    """
    if credentials is None:
        raise AppError(401, "未登录")
    payload = decode_token(credentials.credentials)
    if not payload:
        raise AppError(401, "Invalid token")
    user = SqlAlchemyUserRepository(db).get(payload.get("sub", ""))
    if not user:
        raise AppError(404, "User not found")
    if not user.is_active:
        raise PermissionDeniedError("Account disabled")
    return user


def get_current_user(user: User = Depends(get_current_user_unchecked)) -> User:
    """业务端点统一依赖：管理员重置过密码的账号必须先改密才能继续操作。"""
    if getattr(user, "must_change_password", False):
        raise AppError(403, "请先修改初始密码后再使用系统功能")
    return user


def require_knowledge_admin(user: User = Depends(get_current_user)) -> User:
    if not is_privileged(user):
        raise PermissionDeniedError("Knowledge admin required")
    return user


def require_developer(user: User = Depends(get_current_user)) -> User:
    """系统管理员：developer（正式）与 admin（历史遗留）等价。"""
    if not is_system_admin(user):
        raise PermissionDeniedError("System admin required")
    return user


def require_admin_or_above(user: User = Depends(get_current_user)) -> User:
    if not is_privileged(user):
        raise PermissionDeniedError("Admin required")
    return user
