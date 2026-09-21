"""公文审核流转服务（v3.0）

铁律：
- `transition()` 是状态变更的**唯一入口**，单事务内写 4 处：
  approval_instances / my_documents.status / approval_actions / audit_logs。
- 权限由后端 `require_perm` 级别的权限码判定，**不依赖前端隐藏按钮**。
- 不调用任何 AI 能力：模型不可用时审核流转必须照常可用。
"""
import logging
from datetime import datetime
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.domain.approval import state_machine as sm
from app.domain.identity.entities import User
from app.domain.identity.roles import has_perm, normalize_role, role_name_of
from app.infrastructure.database.models.approval import (
    ApprovalActionModel, ApprovalInstanceModel)
from app.infrastructure.database.models.audit import AuditLogModel
from app.infrastructure.database.models.document import MyDocumentModel

logger = logging.getLogger(__name__)

# 流转环节 → 处理该环节所需权限码
STEP_PERM: Dict[str, str] = {
    "dept": "doc:review_dept",
    "office": "doc:review_office",
    "leader": "doc:approve",
    "number": "doc:number",
    "issue": "doc:seal",
    "archive": "doc:archive",
}

DEFAULT_FLOW = ["dept", "office", "leader"]


def _uuid() -> str:
    import uuid
    return str(uuid.uuid4())


def _audit(db: Session, user: User, action: str, resource_id: str, detail: str) -> None:
    """写审计日志。审计表不可用时不能阻断业务。"""
    try:
        db.add(AuditLogModel(
            id=_uuid(), user_id=user.id, action=action,
            resource_type="approval", resource_id=resource_id,
            detail={"msg": detail}, result="success",
        ))
    except Exception as e:  # pragma: no cover
        logger.warning("审计日志写入失败（不影响业务）: %s", e)


def _doc_status_of(status: str) -> str:
    """把审批状态映射回 my_documents.status（保持 draft/final 取值兼容）。"""
    return "final" if status in (sm.APPROVED, sm.NUMBERED, sm.ISSUED, sm.ARCHIVED) else "draft"


class ApprovalService:
    def __init__(self, db: Session):
        self.db = db

    # ---------------- 提交送审 ----------------
    def submit(self, user: User, document_id: str,
               flow: Optional[List[str]] = None, urgency: str = "normal") -> dict:
        if not has_perm(user.role, "doc:submit"):
            raise AppError(403, "无提交送审权限")

        doc = self.db.get(MyDocumentModel, document_id)
        if not doc or doc.user_id != user.id:
            raise AppError(404, "公文不存在")

        exist = (self.db.query(ApprovalInstanceModel)
                 .filter(ApprovalInstanceModel.document_id == document_id,
                         ApprovalInstanceModel.current_status.notin_(sm.TERMINAL_STATES))
                 .first())
        if exist:
            raise AppError(400, "该公文已在流转中，请勿重复提交")

        steps = [s for s in (flow or DEFAULT_FLOW) if s in STEP_PERM] or DEFAULT_FLOW
        first_status = {
            "dept": sm.PENDING_DEPT, "office": sm.PENDING_OFFICE, "leader": sm.PENDING_LEADER,
        }.get(steps[0], sm.PENDING_DEPT)

        now = datetime.utcnow()
        inst = ApprovalInstanceModel(
            id=_uuid(), document_id=document_id, title=doc.title,
            submitter_id=user.id, submitter_name=user.real_name or user.username,
            department=user.department or "", current_status=first_status,
            current_step=steps[0], flow=steps, urgency=urgency or "normal",
            created_at=now, updated_at=now,
        )
        self.db.add(inst)
        # 两表间未声明 ORM 关系，SQLAlchemy 无法推断插入顺序；
        # SQLite 开启外键约束时必须先 flush 主表，否则子表插入会因外键失败。
        self.db.flush()
        self.db.add(ApprovalActionModel(
            id=_uuid(), instance_id=inst.id, action=sm.ACT_SUBMIT,
            from_status=sm.DRAFT, to_status=first_status,
            comment="提交送审", actor_id=user.id,
            actor_name=user.real_name or user.username,
            actor_role=normalize_role(user.role), created_at=now,
        ))
        doc.status = "draft"
        _audit(self.db, user, "approval.submit", inst.id, f"提交送审：{doc.title}")
        self.db.commit()
        return self._dto(inst, doc)

    # ---------------- 状态迁移（唯一入口） ----------------
    def transition(self, user: User, instance_id: str,
                   action: str, comment: str = "") -> dict:
        inst = self.db.get(ApprovalInstanceModel, instance_id)
        if not inst:
            raise AppError(404, "审批单不存在")

        tr = sm.resolve(inst.current_status, action, inst.flow)
        if tr is None:
            raise AppError(400, f"当前状态（{sm.STATUS_NAMES.get(inst.current_status)}）不允许执行该操作")

        # 权限：撤回允许拟稿人本人，其余按权限码
        is_submitter = inst.submitter_id == user.id
        if tr.allow_submitter and is_submitter:
            pass
        elif not has_perm(user.role, tr.perm):
            raise AppError(403, f"无{sm.ACTION_NAMES.get(action, action)}权限")

        # 退回/终止必须填意见
        if tr.need_comment or action in sm.COMMENT_REQUIRED_ACTIONS:
            if not comment or len(comment.strip()) < sm.MIN_COMMENT_LEN:
                raise AppError(400, f"退回或终止必须填写意见（不少于 {sm.MIN_COMMENT_LEN} 个字）")

        if inst.current_status in sm.TERMINAL_STATES:
            raise AppError(400, "流程已结束，不能再操作")

        now = datetime.utcnow()
        from_status = inst.current_status
        inst.current_status = tr.to_status
        inst.current_step = sm.STATUS_STEP.get(tr.to_status, inst.current_step)
        inst.updated_at = now

        self.db.add(ApprovalActionModel(
            id=_uuid(), instance_id=inst.id, action=action,
            from_status=from_status, to_status=tr.to_status,
            comment=(comment or "").strip() or sm.ACTION_NAMES.get(action, action),
            actor_id=user.id, actor_name=user.real_name or user.username,
            actor_role=normalize_role(user.role), created_at=now,
        ))

        doc = self.db.get(MyDocumentModel, inst.document_id) if inst.document_id else None
        if doc is not None:
            doc.status = _doc_status_of(tr.to_status)
            if tr.to_status in (sm.NUMBERED, sm.ISSUED, sm.ARCHIVED) and inst.doc_number:
                doc.document_number = inst.doc_number

        _audit(self.db, user, f"approval.{action}", inst.id,
               f"{sm.ACTION_NAMES.get(action, action)}：{from_status}→{tr.to_status}")
        self.db.commit()
        return self._dto(inst, doc)

    # ---------------- 编制文号 ----------------
    def assign_number(self, user: User, instance_id: str, daizi: str = "") -> dict:
        if not has_perm(user.role, "doc:number"):
            raise AppError(403, "无编制文号权限")
        inst = self.db.get(ApprovalInstanceModel, instance_id)
        if not inst:
            raise AppError(404, "审批单不存在")
        from app.application.writing.doc_number_service import resolve_daizi
        daizi = daizi or resolve_daizi(self.db)
        year = datetime.now().year
        seq = self.db.query(ApprovalInstanceModel).filter(
            ApprovalInstanceModel.doc_number.like(f"{daizi}〔{year}%")).count() + 1
        inst.doc_number = f"{daizi}〔{year}〕{seq}号"
        inst.updated_at = datetime.utcnow()
        _audit(self.db, user, "approval.number", inst.id, inst.doc_number)
        self.db.commit()
        return self._dto(inst, None)

    # ---------------- 查询 ----------------
    def _visible(self, user: User, view: str):
        q = self.db.query(ApprovalInstanceModel)
        if view == "mine":
            return q.filter(ApprovalInstanceModel.submitter_id == user.id)
        if view == "done":
            return q.filter(ApprovalInstanceModel.current_status.in_(sm.TERMINAL_STATES))
        if view == "todo":
            steps = [s for s, perm in STEP_PERM.items() if has_perm(user.role, perm)]
            q = q.filter(ApprovalInstanceModel.current_step.in_(steps))
            q = q.filter(ApprovalInstanceModel.current_status.notin_(sm.TERMINAL_STATES))
            if not has_perm(user.role, "doc:view_all"):
                if has_perm(user.role, "doc:view_dept"):
                    q = q.filter(ApprovalInstanceModel.department == (user.department or ""))
                else:
                    q = q.filter(ApprovalInstanceModel.submitter_id == user.id)
            return q
        # all
        if not has_perm(user.role, "doc:view_all"):
            if has_perm(user.role, "doc:view_dept"):
                q = q.filter(ApprovalInstanceModel.department == (user.department or ""))
            else:
                q = q.filter(ApprovalInstanceModel.submitter_id == user.id)
        return q

    def list(self, user: User, view: str = "todo", page: int = 1, page_size: int = 20) -> dict:
        q = self._visible(user, view)
        total = q.count()
        rows = (q.order_by(ApprovalInstanceModel.created_at.desc())
                .offset(max(0, (page - 1) * page_size)).limit(page_size).all())
        return {"items": [self._dto(r, None) for r in rows], "total": total,
                "page": page, "page_size": page_size}

    def counts(self, user: User) -> dict:
        return {
            "todo": self._visible(user, "todo").count(),
            "mine_running": self._visible(user, "mine").filter(
                ApprovalInstanceModel.current_status.notin_(sm.TERMINAL_STATES)).count(),
            "done": self._visible(user, "done").count(),
        }

    def detail(self, user: User, instance_id: str) -> dict:
        inst = self.db.get(ApprovalInstanceModel, instance_id)
        if not inst:
            raise AppError(404, "审批单不存在")
        if not self._can_view(user, inst):
            raise AppError(404, "审批单不存在")
        doc = self.db.get(MyDocumentModel, inst.document_id) if inst.document_id else None
        dto = self._dto(inst, doc, with_content=True)
        dto["actions"] = self.actions(user, instance_id)
        dto["available_actions"] = [
            {"action": a, "name": sm.ACTION_NAMES.get(a, a),
             "need_comment": a in sm.COMMENT_REQUIRED_ACTIONS}
            for a in sm.available_actions(inst.current_status, inst.flow)
            if self._can_act(user, inst, a)
        ]
        return dto

    def actions(self, user: User, instance_id: str) -> List[dict]:
        rows = (self.db.query(ApprovalActionModel)
                .filter(ApprovalActionModel.instance_id == instance_id)
                .order_by(ApprovalActionModel.created_at.desc()).all())
        return [{
            "id": r.id, "action": r.action, "action_name": sm.ACTION_NAMES.get(r.action, r.action),
            "from_status": r.from_status, "from_status_name": sm.STATUS_NAMES.get(r.from_status, ""),
            "to_status": r.to_status, "to_status_name": sm.STATUS_NAMES.get(r.to_status, ""),
            "comment": r.comment or "", "actor_name": r.actor_name,
            "actor_role": role_name_of(r.actor_role),
            "created_at": r.created_at.isoformat() if r.created_at else "",
        } for r in rows]

    # ---------------- 权限辅助 ----------------
    def _can_view(self, user: User, inst: ApprovalInstanceModel) -> bool:
        if has_perm(user.role, "doc:view_all"):
            return True
        if inst.submitter_id == user.id:
            return True
        if has_perm(user.role, "doc:view_dept") and inst.department == (user.department or ""):
            return True
        return False

    def _can_act(self, user: User, inst: ApprovalInstanceModel, action: str) -> bool:
        tr = sm.resolve(inst.current_status, action, inst.flow)
        if tr is None:
            return False
        if tr.allow_submitter and inst.submitter_id == user.id:
            return True
        return has_perm(user.role, tr.perm)

    # ---------------- DTO ----------------
    def _dto(self, inst: ApprovalInstanceModel, doc, with_content: bool = False) -> dict:
        content = ""
        if with_content and doc is not None:
            try:
                last = doc.versions[-1] if doc.versions else None
                content = (last.content or "")[:600] if last else ""
            except Exception:
                content = ""
        return {
            "id": inst.id,
            "document_id": inst.document_id,
            "title": inst.title,
            "current_status": inst.current_status,
            "current_status_name": sm.STATUS_NAMES.get(inst.current_status, inst.current_status),
            "current_step": inst.current_step,
            "current_step_name": sm.STEP_NAMES.get(inst.current_step, inst.current_step),
            "submitter_name": inst.submitter_name,
            "department": inst.department,
            "doc_number": inst.doc_number or "",
            "urgency": inst.urgency,
            "submitted_at": inst.created_at.isoformat() if inst.created_at else "",
            "updated_at": inst.updated_at.isoformat() if inst.updated_at else "",
            "content_excerpt": content,
        }
