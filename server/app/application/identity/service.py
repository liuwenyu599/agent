"""身份用例：登录、注册、用户管理（业务规则与旧系统一致）。"""
from typing import List, Optional, Tuple

from app.core.exceptions import AppError, NotFoundError, PermissionDeniedError
from app.core.security import (
    create_access_token,
    get_password_hash,
    validate_password_strength,
    verify_password,
)
from app.domain.identity.entities import (
    ROLE_DEVELOPER,
    ROLE_KNOWLEDGE_ADMIN,
    ROLE_USER,
    User,
)
from app.domain.identity.repositories import UserRepository
from app.domain.organization.departments import (
    DEPARTMENT_BY_CODE,
    resolve_code,
)

# 前端可选角色与后端权限口径一致：只允许这三类，其余一律拒绝
ASSIGNABLE_ROLES = (ROLE_USER, ROLE_KNOWLEDGE_ADMIN, ROLE_DEVELOPER)


def _resolve_department(department: str = "", department_code: str = "") -> tuple[str, str]:
    """解析所属科室，返回 (科室正式名称, 科室 code)。

    - code 优先，且必须命中科室字典，杜绝前端自由输入；
    - 兼容旧的按名称传值：同样必须命中字典，未命中直接报错，不做猜测归口；
    - 两者都为空表示未归口，只允许访问全局公共知识。
    """
    code = (department_code or "").strip()
    if code:
        if code not in DEPARTMENT_BY_CODE:
            raise AppError(400, "所属科室无效，请从科室列表中选择")
        return DEPARTMENT_BY_CODE[code].name, code
    name = (department or "").strip()
    if name:
        resolved = resolve_code(name)
        if not resolved:
            raise AppError(400, "所属科室无效，请从科室列表中选择")
        return DEPARTMENT_BY_CODE[resolved].name, resolved
    return "", ""


def _check_assignable_role(role: str) -> str:
    role = (role or "").strip()
    if role not in ASSIGNABLE_ROLES:
        raise AppError(400, "角色无效，请从角色列表中选择")
    return role


def with_department_code(user: User) -> User:
    """把正式科室名称解析成 department_code 并写入实体。

    解析不出的科室保持空串（只允许访问全局公共知识），绝不猜测归口。
    新建/更新用户时即时生效，不依赖启动回填。
    """
    user.department_code = resolve_code(user.department or "")
    return user


class AuthService:
    def __init__(self, users: UserRepository, db=None, audit=None) -> None:
        self.users = users
        self.db = db
        self.audit = audit

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

    # ---- 修改密码 ----

    def change_password(self, user: User, old_password: str, new_password: str,
                        confirm_password: str) -> None:
        """本人修改密码：校验旧密码 + 二次确认 + 复杂度，成功则清除强制改密标记。

        全程只处理 hash，日志只记录用户与结果，绝不记录任何密码明文。
        """
        if not verify_password(old_password or "", user.hashed_password):
            self._audit_password(user, "password_change", "failed", "旧密码校验失败")
            raise AppError(400, "当前密码不正确")
        if new_password != confirm_password:
            self._audit_password(user, "password_change", "failed", "两次输入的新密码不一致")
            raise AppError(400, "两次输入的新密码不一致")
        if new_password == old_password:
            self._audit_password(user, "password_change", "failed", "新密码与旧密码相同")
            raise AppError(400, "新密码不能与旧密码相同")
        validate_password_strength(new_password)

        user.hashed_password = get_password_hash(new_password)
        user.must_change_password = False
        self.users.update(user)
        self._audit_password(user, "password_change", "success", "")

    def _audit_password(self, user: User, action: str, result: str, reason: str) -> None:
        """密码类操作审计：只记录用户、时间与结果，不记录任何密码内容。"""
        if not self.audit:
            return
        try:
            self.audit.log(
                action=action,
                resource_type="user",
                user=user,
                resource_id=getattr(user, "id", None),
                detail={"result": result, "reason": reason},
                result=result,
            )
        except Exception:  # 审计失败不影响主流程
            pass

    def is_first_user(self) -> bool:
        return self.users.count() == 0

    def register_first(self, username: str, email: str, password: str,
                       real_name: str = "", department: str = "", role: str = ROLE_DEVELOPER,
                       department_code: str = "") -> Tuple[str, User]:
        if not self.is_first_user():
            raise PermissionDeniedError("系统已有用户，请登录后注册")
        if role != ROLE_DEVELOPER:
            raise AppError(400, "首次注册必须是系统管理员(developer)角色")
        dept_name, dept_code = _resolve_department(department, department_code)
        user = self._create_user_checked(username, email, password, real_name,
                                         dept_name, ROLE_DEVELOPER, dept_code)
        token = create_access_token(
            {"sub": user.id, "username": user.username, "role": user.role}
        )
        return token, user

    def register(self, actor: User, username: str, email: str, password: str,
                 real_name: str = "", department: str = "", role: str = ROLE_USER,
                 department_code: str = "") -> User:
        if actor.role == ROLE_DEVELOPER:
            allowed = [ROLE_USER, ROLE_KNOWLEDGE_ADMIN, ROLE_DEVELOPER]
        elif actor.role == ROLE_KNOWLEDGE_ADMIN:
            allowed = [ROLE_USER, ROLE_KNOWLEDGE_ADMIN]
        else:
            raise PermissionDeniedError("普通用户无权注册新用户")
        if role not in allowed:
            raise PermissionDeniedError(f"无权注册该角色，允许: {', '.join(allowed)}")
        dept_name, dept_code = _resolve_department(department, department_code)
        return self._create_user_checked(username, email, password, real_name,
                                         dept_name, role, dept_code)

    def _create_user_checked(self, username, email, password, real_name, department, role,
                             department_code: str = "") -> User:
        if self.users.get_by_username(username):
            raise AppError(400, "用户名已存在")
        if self.users.get_by_email(email):
            raise AppError(400, "邮箱已存在")
        _check_assignable_role(role)
        return self.users.add(User(
            username=username, email=email, hashed_password=get_password_hash(password),
            real_name=real_name, department=department, role=role,
            department_code=department_code,
        ))


class UserService:
    """用户管理（管理端）。"""

    def __init__(self, users: UserRepository, db=None, audit=None) -> None:
        self.users = users
        self.db = db
        self.audit = audit

    def list_users(self) -> List[User]:
        return self.users.list_all()

    def create_user(self, actor: User, username: str, email: str, password: str,
                    real_name: str = "", department: str = "", role: str = ROLE_USER,
                    department_code: str = "") -> User:
        if role == ROLE_DEVELOPER and actor.role != ROLE_DEVELOPER:
            raise PermissionDeniedError("只有系统管理员可以创建系统管理员")
        if actor.role == ROLE_KNOWLEDGE_ADMIN and role not in (ROLE_USER, ROLE_KNOWLEDGE_ADMIN):
            raise PermissionDeniedError("知识管理员只能创建普通用户和知识管理员")
        dept_name, dept_code = _resolve_department(department, department_code)
        if self.users.get_by_username(username):
            raise AppError(400, "Username exists")
        if self.users.get_by_email(email):
            raise AppError(400, "Email exists")
        return self.users.add(User(
            username=username, email=email, hashed_password=get_password_hash(password),
            real_name=real_name, department=dept_name, role=_check_assignable_role(role),
            department_code=dept_code,
        ))

    def update_user(self, actor: User, user_id: str, real_name: Optional[str] = None,
                    department: Optional[str] = None, is_active: Optional[bool] = None,
                    role: Optional[str] = None,
                    department_code: Optional[str] = None) -> User:
        user = self.users.get(user_id)
        if not user:
            raise NotFoundError("User not found")
        if role is not None:
            role = _check_assignable_role(role)
            if role == ROLE_DEVELOPER and actor.role != ROLE_DEVELOPER:
                raise PermissionDeniedError("只有系统管理员可以设置系统管理员角色")
            if user.id == actor.id and role != actor.role:
                raise PermissionDeniedError("不能修改自己的角色")
            user.role = role
        if real_name is not None:
            user.real_name = real_name
        if department is not None or department_code is not None:
            dept_name, dept_code = _resolve_department(department or "", department_code or "")
            user.department = dept_name
            user.department_code = dept_code
        if is_active is not None:
            user.is_active = is_active
        return self.users.update(user)

    def reset_password(self, actor: User, user_id: str, password: str) -> User:
        """管理员重置他人密码：重置后强制该用户下次登录修改密码。

        审计只记录操作者、目标用户、时间与结果，不记录密码。
        """
        user = self.users.get(user_id)
        if not user:
            raise NotFoundError("User not found")
        validate_password_strength(password)
        user.hashed_password = get_password_hash(password)
        user.must_change_password = True
        updated = self.users.update(user)
        self._audit_password(actor, updated, "password_reset", "success", "")
        return updated

    def _audit_password(self, actor: User, target: User, action: str,
                        result: str, reason: str) -> None:
        if not self.audit:
            return
        try:
            self.audit.log(
                action=action,
                resource_type="user",
                user=actor,
                resource_id=getattr(target, "id", None),
                detail={"result": result, "reason": reason,
                        "target_username": getattr(target, "username", "")},
                result=result,
            )
        except Exception:
            pass

    def deactivate_user(self, actor: User, user_id: str) -> None:
        user = self.users.get(user_id)
        if not user:
            raise NotFoundError("User not found")
        if user.id == actor.id:
            raise PermissionDeniedError("不能删除自己")
        self.users.delete(user)
