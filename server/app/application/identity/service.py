"""身份用例：登录、注册、用户管理（业务规则与旧系统一致）。"""
from typing import List, Optional, Tuple

from app.core.exceptions import AppError, NotFoundError, PermissionDeniedError
from app.core.security import create_access_token, get_password_hash, verify_password
from app.domain.identity.entities import (
    ROLE_DEVELOPER,
    ROLE_KNOWLEDGE_ADMIN,
    ROLE_USER,
    User,
)
from app.domain.identity.repositories import UserRepository


class AuthService:
    def __init__(self, users: UserRepository) -> None:
        self.users = users

    # ---- 认证 ----
    def login(self, username: str, password: str) -> Tuple[str, User]:
        user = self.users.get_by_username(username)
        if not user or not verify_password(password, user.hashed_password):
            raise AppError(401, "用户名或密码错误")
        if not user.is_active:
            raise AppError(403, "账号已停用")
        token = create_access_token(
            {"sub": user.id, "username": user.username, "role": user.role}
        )
        return token, user

    def is_first_user(self) -> bool:
        return self.users.count() == 0

    def register_first(self, username: str, email: str, password: str,
                       real_name: str = "", department: str = "", role: str = ROLE_DEVELOPER) -> Tuple[str, User]:
        if not self.is_first_user():
            raise PermissionDeniedError("系统已有用户，请登录后注册")
        if role != ROLE_DEVELOPER:
            raise AppError(400, "首次注册必须是系统管理员(developer)角色")
        user = self._create_user_checked(username, email, password, real_name, department, ROLE_DEVELOPER)
        token = create_access_token(
            {"sub": user.id, "username": user.username, "role": user.role}
        )
        return token, user

    def register(self, actor: User, username: str, email: str, password: str,
                 real_name: str = "", department: str = "", role: str = ROLE_USER) -> User:
        if actor.role == ROLE_DEVELOPER:
            allowed = [ROLE_USER, ROLE_KNOWLEDGE_ADMIN, ROLE_DEVELOPER]
        elif actor.role == ROLE_KNOWLEDGE_ADMIN:
            allowed = [ROLE_USER, ROLE_KNOWLEDGE_ADMIN]
        else:
            raise PermissionDeniedError("普通用户无权注册新用户")
        if role not in allowed:
            raise PermissionDeniedError(f"无权注册该角色，允许: {', '.join(allowed)}")
        return self._create_user_checked(username, email, password, real_name, department, role)

    def _create_user_checked(self, username, email, password, real_name, department, role) -> User:
        if self.users.get_by_username(username):
            raise AppError(400, "用户名已存在")
        if self.users.get_by_email(email):
            raise AppError(400, "邮箱已存在")
        return self.users.add(User(
            username=username, email=email, hashed_password=get_password_hash(password),
            real_name=real_name, department=department, role=role,
        ))


class UserService:
    """用户管理（管理端）。"""

    def __init__(self, users: UserRepository) -> None:
        self.users = users

    def list_users(self) -> List[User]:
        return self.users.list_all()

    def create_user(self, actor: User, username: str, email: str, password: str,
                    real_name: str = "", department: str = "", role: str = ROLE_USER) -> User:
        if role == ROLE_DEVELOPER and actor.role != ROLE_DEVELOPER:
            raise PermissionDeniedError("只有系统管理员可以创建系统管理员")
        if actor.role == ROLE_KNOWLEDGE_ADMIN and role not in (ROLE_USER, ROLE_KNOWLEDGE_ADMIN):
            raise PermissionDeniedError("知识管理员只能创建普通用户和知识管理员")
        if self.users.get_by_username(username):
            raise AppError(400, "Username exists")
        if self.users.get_by_email(email):
            raise AppError(400, "Email exists")
        return self.users.add(User(
            username=username, email=email, hashed_password=get_password_hash(password),
            real_name=real_name, department=department, role=role,
        ))

    def update_user(self, actor: User, user_id: str, real_name: Optional[str] = None,
                    department: Optional[str] = None, is_active: Optional[bool] = None,
                    role: Optional[str] = None) -> User:
        user = self.users.get(user_id)
        if not user:
            raise NotFoundError("User not found")
        if role is not None:
            if role == ROLE_DEVELOPER and actor.role != ROLE_DEVELOPER:
                raise PermissionDeniedError("只有系统管理员可以设置系统管理员角色")
            if user.id == actor.id and role != actor.role:
                raise PermissionDeniedError("不能修改自己的角色")
            user.role = role
        if real_name is not None:
            user.real_name = real_name
        if department is not None:
            user.department = department
        if is_active is not None:
            user.is_active = is_active
        return self.users.update(user)

    def reset_password(self, user_id: str, password: str) -> None:
        user = self.users.get(user_id)
        if not user:
            raise NotFoundError("User not found")
        if len(password) < 6:
            raise AppError(400, "密码至少6位")
        user.hashed_password = get_password_hash(password)
        self.users.update(user)

    def deactivate_user(self, actor: User, user_id: str) -> None:
        user = self.users.get(user_id)
        if not user:
            raise NotFoundError("User not found")
        if user.id == actor.id:
            raise PermissionDeniedError("不能删除自己")
        self.users.delete(user)
