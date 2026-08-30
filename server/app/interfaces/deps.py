"""FastAPI 共享依赖：认证与 RBAC。各业务路由统一从这里取当前用户。"""
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.exceptions import AppError, PermissionDeniedError
from app.core.security import decode_token
from app.domain.identity.entities import ADMIN_OR_ABOVE, ROLE_DEVELOPER, User
from app.infrastructure.database import get_db
from app.infrastructure.repositories.identity import SqlAlchemyUserRepository

security = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> User:
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


def require_knowledge_admin(user: User = Depends(get_current_user)) -> User:
    if user.role not in ADMIN_OR_ABOVE:
        raise PermissionDeniedError("Knowledge admin required")
    return user


def require_developer(user: User = Depends(get_current_user)) -> User:
    if user.role != ROLE_DEVELOPER:
        raise PermissionDeniedError("Developer required")
    return user


def require_admin_or_above(user: User = Depends(get_current_user)) -> User:
    if user.role not in ADMIN_OR_ABOVE:
        raise PermissionDeniedError("Admin required")
    return user
