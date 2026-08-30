"""统一业务异常体系。"""
from fastapi import HTTPException


class AppError(HTTPException):
    """业务错误基类，detail 面向用户可读。"""

    def __init__(self, status_code: int = 400, detail: str = "请求错误"):
        super().__init__(status_code=status_code, detail=detail)


class NotFoundError(AppError):
    def __init__(self, detail: str = "资源不存在"):
        super().__init__(404, detail)


class PermissionDeniedError(AppError):
    def __init__(self, detail: str = "无权限执行该操作"):
        super().__init__(403, detail)


class ConflictError(AppError):
    def __init__(self, detail: str = "资源冲突"):
        super().__init__(409, detail)


class AIServiceError(AppError):
    """AI Gateway / Model Service 调用失败。"""

    def __init__(self, detail: str = "AI 服务暂时不可用"):
        super().__init__(502, detail)
