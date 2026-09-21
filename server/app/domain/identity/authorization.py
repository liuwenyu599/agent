"""统一权限判定（v3.1 组织隔离）。

全系统**唯一**的角色判定入口。任何业务代码都不得再写 `role == "admin"` 之类的
字面量判断，必须调用本模块函数，避免新旧角色字符串语义分叉。

角色语义：
- developer：项目正式的系统管理员（拥有全局管理权限）；
- admin：历史遗留数据中的系统管理员，与 developer 等价；
- knowledge_admin：知识管理员，**只在本人所属科室范围内**拥有管理权限；
- user：普通用户，只能访问全局公共知识 + 本科室知识 + 本人个人知识。
"""
from typing import Optional

from app.domain.identity.entities import (
    ROLE_ADMIN_LEGACY,
    ROLE_DEVELOPER,
    ROLE_KNOWLEDGE_ADMIN,
)

__all__ = [
    "is_system_admin",
    "is_knowledge_admin",
    "is_privileged",
    "can_manage_department",
    "role_of",
]


def role_of(user) -> str:
    """从实体/ORM 对象上安全取角色字符串（兼容 None）。"""
    return (getattr(user, "role", "") or "").strip()


def is_system_admin(role_or_user) -> bool:
    """系统管理员：developer 为正式角色，admin 为历史遗留兼容。"""
    role = role_of(role_or_user) if not isinstance(role_or_user, str) else role_or_user
    return role in (ROLE_DEVELOPER, ROLE_ADMIN_LEGACY)


def is_knowledge_admin(role_or_user) -> bool:
    role = role_of(role_or_user) if not isinstance(role_or_user, str) else role_or_user
    return role == ROLE_KNOWLEDGE_ADMIN


def is_privileged(role_or_user) -> bool:
    """系统管理员或知识管理员（等价于旧 ADMIN_OR_ABOVE）。"""
    return is_system_admin(role_or_user) or is_knowledge_admin(role_or_user)


def can_manage_department(role_or_user, user_dept_code: str, target_dept_code: str) -> bool:
    """能否管理/维护 target_dept_code 这个科室的资产。

    - 系统管理员：全部科室；
    - 知识管理员：仅本人所属科室；
    - 其他角色：不可。
    客户端提交的科室标识一律不可信，user_dept_code 必须由服务端从 users 表解析。
    """
    if is_system_admin(role_or_user):
        return True
    if is_knowledge_admin(role_or_user):
        return bool(user_dept_code) and user_dept_code == (target_dept_code or "")
    return False
