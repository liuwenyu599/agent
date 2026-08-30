"""身份领域：用户实体与角色常量。"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

# 角色常量（与旧系统保持一致，勿改字符串）
ROLE_DEVELOPER = "developer"        # 系统管理员
ROLE_KNOWLEDGE_ADMIN = "knowledge_admin"  # 知识管理员
ROLE_USER = "user"                  # 普通用户

ALL_ROLES = (ROLE_DEVELOPER, ROLE_KNOWLEDGE_ADMIN, ROLE_USER)
# 兼容旧数据中出现的 "admin"
ADMIN_OR_ABOVE = (ROLE_DEVELOPER, ROLE_KNOWLEDGE_ADMIN, "admin")


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

    def to_public_dict(self) -> dict:
        return {
            "id": self.id,
            "username": self.username,
            "real_name": self.real_name,
            "role": self.role,
        }
