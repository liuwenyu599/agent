"""用户个人偏好路由（v3.3）。

权限边界：
- 全部端点只依赖 `get_current_user`（任意已登录角色，含普通 user）；
- 路径中**不带 user_id**，因此天然只能读写本人的偏好；
- **不提供** `GET/PUT /preferences/{user_id}` 及任何管理员代改端点，
  避免"管理员改他人偏好"的越权面；
- 字段白名单 + `extra="forbid"`：提交 department_code / scope / role 等一律 400。
"""
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.application.shared.user_preference import UserPreferenceService
from app.domain.identity.entities import User
from app.infrastructure.database import get_db
from app.interfaces.deps import get_current_user

router = APIRouter(prefix="/preferences", tags=["个人偏好"])

# 本路由的端点路径：校验失败只对这些路径转 400，其余路由保持 FastAPI 默认 422
_OWN_PATH = "/preferences/me"


class BehaviorUpdate(BaseModel):
    """默认行为开关（部分合并）。键白名单由服务端固定，未知键直接 400。

    strict=True：不做宽松类型转换（如 "yes" → True），类型不符一律 400，
    避免"我以为改了其实被悄悄解释成别的值"。
    """

    cite_sources: bool | None = None
    confirm_structure: bool | None = None

    model_config = {"extra": "forbid", "strict": True}


class PreferenceUpdate(BaseModel):
    """偏好整体更新请求体：全部字段可选，缺省字段保持原值。"""

    assistant_name: str | None = None
    work_preference: str | None = None
    writing_style: str | None = None
    writing_style_custom: str | None = None
    behaviors: BehaviorUpdate | None = None

    model_config = {"extra": "forbid", "strict": True}


def _zh_detail(exc: RequestValidationError) -> str:
    """把 Pydantic 校验错误翻译成面向用户的中文 detail。"""
    for err in exc.errors():
        loc = [str(p) for p in (err.get("loc") or []) if str(p) != "body"]
        etype = err.get("type") or ""
        if etype == "extra_forbidden" and loc:
            if len(loc) >= 2 and loc[0] == "behaviors":
                return f"不支持的默认行为：{loc[-1]}"
            return "不支持的字段：" + "、".join(loc)
        if not loc:
            continue
        if loc[0] == "behaviors":
            if len(loc) >= 2:
                return f"behaviors.{loc[1]} 必须是布尔值"
            return "behaviors 必须是对象"
        field = loc[0]
        if field in _FIELD_ERRORS:
            return _FIELD_ERRORS[field]
        return f"请求参数不正确：{field}"
    return "请求参数不正确"


_FIELD_ERRORS: Dict[str, str] = {
    "assistant_name": "助手称呼必须是文本",
    "work_preference": "工作偏好必须是文本",
    "writing_style": "writing_style 取值无效",
    "writing_style_custom": "自定义说明必须是文本",
    "behaviors": "behaviors 必须是对象",
}


async def validation_error_handler(request: Request,
                                   exc: RequestValidationError) -> JSONResponse:
    """仅对 /preferences/me 把 422 统一成 400 + 中文 detail（明确拒绝而非静默）。"""
    if _OWN_PATH not in (request.url.path or ""):
        return JSONResponse(
            status_code=422,
            content={"detail": jsonable_encoder(exc.errors())},
        )
    return JSONResponse(status_code=400, content={"detail": _zh_detail(exc)})


@router.get("/me")
def get_my_preferences(db: Session = Depends(get_db),
                       user: User = Depends(get_current_user)) -> Dict[str, Any]:
    """读取当前登录用户的个人偏好；不存在时返回全空默认值，不 404。"""
    return UserPreferenceService(db).public_payload(user.id)


@router.put("/me")
def update_my_preferences(payload: PreferenceUpdate,
                          db: Session = Depends(get_db),
                          user: User = Depends(get_current_user)) -> Dict[str, Any]:
    """保存当前登录用户的个人偏好，返回保存后的完整结构（含 options）。

    behaviors 为部分合并，只更新传入的键；缺省字段保持原值。
    """
    svc = UserPreferenceService(db)
    try:
        svc.upsert(user.id, payload.model_dump(exclude_none=True))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return svc.public_payload(user.id)
