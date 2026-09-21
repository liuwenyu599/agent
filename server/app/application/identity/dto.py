"""身份模块请求/响应模型。"""
from typing import Optional

from pydantic import BaseModel


class LoginRequest(BaseModel):
    username: str
    password: str


class RegisterRequest(BaseModel):
    username: str
    email: str
    password: str
    real_name: str = ""
    department: str = ""
    department_code: str = ""
    role: str = "user"


class UserCreateRequest(BaseModel):
    username: str
    email: str
    password: str
    real_name: str = ""
    department: str = ""
    # 所属科室只能用科室字典 code（前端下拉），不再接受自由输入的名称
    department_code: str = ""
    role: str = "user"


class UserUpdateRequest(BaseModel):
    real_name: Optional[str] = None
    department: Optional[str] = None
    department_code: Optional[str] = None
    is_active: Optional[bool] = None
    role: Optional[str] = None


class ResetPasswordRequest(BaseModel):
    password: str


class ChangePasswordRequest(BaseModel):
    """本人修改密码：必须验证旧密码，并二次确认新密码。"""
    old_password: str
    new_password: str
    confirm_password: str
