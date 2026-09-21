"""首页聚合路由（v3.0）

设计约束：
- 本接口是客户端首页的唯一数据源，**任何子系统不可用时接口本身必须返回 200**。
- AI 在线状态只做轻量连通性探测（0.8s 超时），失败即 ai_online=False，
  前端据此显示「AI 助手离线 · 基础功能正常」，不弹窗、不阻断办公。
"""
import logging
import socket
from datetime import datetime
from urllib.parse import urlparse

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.config import settings
from app.domain.identity.entities import User
from app.domain.identity.roles import data_scope_of, role_name_of
from app.infrastructure.database import get_db
from app.infrastructure.database.models.approval import ApprovalInstanceModel
from app.infrastructure.database.models.document import MyDocumentModel
from app.interfaces.deps import get_current_user

router = APIRouter(prefix="/dashboard", tags=["首页"])
logger = logging.getLogger(__name__)

_ai_cache = {"ts": 0.0, "online": False}


def _probe_ai() -> bool:
    """轻量探测模型服务连通性；失败一律返回 False，绝不抛异常。"""
    import time
    now = time.time()
    if now - _ai_cache["ts"] < 30:  # 30 秒内复用结果，避免每次刷新都探测
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
    now = datetime.now()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month_created = q.filter(MyDocumentModel.created_at >= month_start).count()

    # 流转中 / 已办结：来自审批实例
    from app.domain.approval import state_machine as sm
    ap = db.query(ApprovalInstanceModel).filter(
        ApprovalInstanceModel.submitter_id == user.id)
    doc_pending = ap.filter(
        ApprovalInstanceModel.current_status.notin_(sm.TERMINAL_STATES)).count()
    doc_approved = ap.filter(
        ApprovalInstanceModel.current_status.in_(sm.TERMINAL_STATES)).count()

    recent_rows = (q.order_by(MyDocumentModel.updated_at.desc()).limit(4).all())

    # 待办数（与 /approvals/counts 同源逻辑，此处内联避免额外依赖）
    from app.domain.identity.roles import has_perm
    STEP_PERM = {"dept": "doc:review_dept", "office": "doc:review_office",
                 "leader": "doc:approve", "number": "doc:number",
                 "issue": "doc:seal", "archive": "doc:archive"}
    steps = [s for s, p in STEP_PERM.items() if has_perm(user.role, p)]
    todo_count = 0
    if steps:
        tq = db.query(ApprovalInstanceModel).filter(
            ApprovalInstanceModel.current_step.in_(steps),
            ApprovalInstanceModel.current_status.notin_(sm.TERMINAL_STATES))
        if not has_perm(user.role, "doc:view_all"):
            tq = tq.filter(ApprovalInstanceModel.department == (user.department or ""))
        todo_count = tq.count()

    return {
        "real_name": user.real_name or user.username,
        "department": user.department or "",
        "role_name": role_name_of(user.role),
        "todo_count": todo_count,
        "ai_online": _probe_ai(),
        "stats": {
            "doc_total": doc_total,
            "doc_pending": doc_pending,
            "doc_approved": doc_approved,
            "month_created": month_created,
        },
        "recent": [{
            "id": d.id,
            "title": d.title,
            "status": d.status or "draft",
            "updated_at": d.updated_at.isoformat() if d.updated_at else "",
        } for d in recent_rows],
    }
