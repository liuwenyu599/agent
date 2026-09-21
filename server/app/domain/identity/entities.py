"""身份领域：用户实体与角色常量。"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

# 角色常量（与旧系统保持一致，勿改字符串）
ROLE_DEVELOPER = "developer"        # 系统管理员（项目正式角色）
ROLE_ADMIN_LEGACY = "admin"         # 历史遗留系统管理员，与 developer 等价
ROLE_KNOWLEDGE_ADMIN = "knowledge_admin"  # 知识管理员
ROLE_USER = "user"                  # 普通用户

ALL_ROLES = (ROLE_DEVELOPER, ROLE_KNOWLEDGE_ADMIN, ROLE_USER)
# 系统管理员（正式 + 历史遗留）
SYSTEM_ADMIN_ROLES = (ROLE_DEVELOPER, ROLE_ADMIN_LEGACY)
# 系统管理员 + 知识管理员
ADMIN_OR_ABOVE = (ROLE_DEVELOPER, ROLE_KNOWLEDGE_ADMIN, ROLE_ADMIN_LEGACY)


@dataclass
class User:
    username: str
    email: str
    hashed_password: str
    id: Optional[str] = None
    real_name: str = ""
    department: str = ""
    role: str = ROLE_USER
    is_active: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    # v3.1 组织隔离主键：departments.code，空串=未归口（仅全局公共知识可见）
    department_code: str = ""
    # 管理员重置密码后强制下次登录修改
    must_change_password: bool = False

    def to_public_dict(self) -> dict:
        return {
            "id": self.id,
            "username": self.username,
            "real_name": self.real_name,
            "role": self.role,
            "department": self.department,
            "department_code": self.department_code,
        }
