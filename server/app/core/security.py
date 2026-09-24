"""认证安全：JWT(HS256) + bcrypt。密钥来自配置，不硬编码。"""
from datetime import timedelta
from typing import Optional

import bcrypt
from jose import JWTError, jwt

from app.core.config import settings
from app.core.timeutil import now_utc


def verify_password(plain_password: str, hashed_password: str) -> bool:
    plain_bytes = plain_password.encode("utf-8")[:72]
    try:
        return bcrypt.checkpw(plain_bytes, hashed_password.encode("utf-8"))
    except ValueError:
        return False


def get_password_hash(password: str) -> str:
    plain_bytes = password.encode("utf-8")[:72]
    return bcrypt.hashpw(plain_bytes, bcrypt.gensalt()).decode("utf-8")


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = now_utc() + (
        expires_delta or timedelta(hours=settings.ACCESS_TOKEN_EXPIRE_HOURS)
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm="HS256")


def decode_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
    except JWTError:
        return None


# ---------------- 密码强度 ----------------

MIN_PASSWORD_LENGTH = 8

PASSWORD_RULE_HINT = "密码至少 8 位，且必须同时包含大写字母、小写字母、数字和符号"


def validate_password_strength(password: str) -> None:
    """密码复杂度校验：长度 >= 8，且同时包含大写字母、小写字母、数字、符号四类字符。

    校验失败抛 AppError(400)，错误信息只说明规则，绝不回显密码内容。
    """
    from app.core.exceptions import AppError

    if not password:
        raise AppError(400, "密码不能为空")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise AppError(400, f"密码至少 {MIN_PASSWORD_LENGTH} 位")
    if not any(c.isupper() for c in password):
        raise AppError(400, PASSWORD_RULE_HINT)
    if not any(c.islower() for c in password):
        raise AppError(400, PASSWORD_RULE_HINT)
    if not any(c.isdigit() for c in password):
        raise AppError(400, PASSWORD_RULE_HINT)
    if not any(not c.isalnum() for c in password):
        raise AppError(400, PASSWORD_RULE_HINT)
    if password.strip() != password:
        raise AppError(400, "密码首尾不能包含空格")
