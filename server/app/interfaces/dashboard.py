"""首页聚合路由。

设计约束：
- 本接口是客户端首页的轻量数据源，任何子系统不可用时接口本身必须尽量保持可用；
- 首页只展示文档事实，不承载已下线的审批/待办语义；
- AI 在线状态只做轻量连通性探测，失败即 ai_online=False，不阻断办公。
"""
from app.core.timeutil import now_local
import logging
import socket
from urllib.parse import urlparse

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.config import settings
from app.domain.identity.entities import User
from app.domain.identity.roles import data_scope_of, role_name_of
from app.infrastructure.database import get_db
from app.infrastructure.database.models.document import MyDocumentModel
from app.interfaces.deps import get_current_user

router = APIRouter(prefix="/dashboard", tags=["首页"])
logger = logging.getLogger(__name__)

_ai_cache = {"ts": 0.0, "online": False}


def _probe_ai() -> bool:
    """轻量探测模型服务连通性；失败一律返回 False，绝不抛异常。"""
    import time

    now = time.time()
    if now - _ai_cache["ts"] < 30:
        return _ai_cache["online"]
    online = False
    try:
        url = urlparse(getattr(settings, "MODEL_SERVICE_URL", "") or "")
        host = url.hostname or "127.0.0.1"
        port = url.port or 80
        with socket.create_connection((host, port), timeout=0.8):
            online = True
    except Exception:
        online = False
    _ai_cache["ts"] = now
    _ai_cache["online"] = online
    return online


@router.get("/summary")
def summary(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    q = db.query(MyDocumentModel)
    if data_scope_of(user.role) != "all":
        q = q.filter(MyDocumentModel.user_id == user.id)

    doc_total = q.count()
    doc_draft = q.filter(MyDocumentModel.status == "draft").count()
    doc_final = q.filter(MyDocumentModel.status == "final").count()

    now = now_local()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month_created = q.filter(MyDocumentModel.created_at >= month_start).count()
    recent_rows = q.order_by(MyDocumentModel.updated_at.desc()).limit(4).all()

    return {
        "real_name": user.real_name or user.username,
        "department": user.department or "",
        "department_code": getattr(user, "department_code", "") or "",
        "role_name": role_name_of(user.role),
        "ai_online": _probe_ai(),
        "stats": {
            "doc_total": doc_total,
            "doc_draft": doc_draft,
            "doc_final": doc_final,
            "month_created": month_created,
        },
        "recent": [
            {
                "id": d.id,
                "title": d.title,
                "status": d.status or "draft",
                "updated_at": d.updated_at.isoformat() if d.updated_at else "",
            }
            for d in recent_rows
        ],
    }
