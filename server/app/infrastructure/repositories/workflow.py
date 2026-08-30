"""工作流仓储 SQLAlchemy 实现。"""
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.workflow.entities import (
    NodeInstance,
    WorkflowInstance,
    WorkflowNode,
    WorkflowTemplate,
)
from app.domain.workflow.repositories import (
    NodeInstanceRepository,
    WorkflowInstanceRepository,
    WorkflowNodeRepository,
    WorkflowTemplateRepository,
)
from app.infrastructure.database.models.workflow import (
    NodeInstanceModel,
    WorkflowInstanceModel,
    WorkflowNodeModel,
    WorkflowTemplateModel,
)

_TPL_FIELDS = ["id", "name", "code", "category", "description", "icon",
               "is_builtin", "is_active", "sort_order", "created_at"]
_NODE_FIELDS = ["id", "template_id", "name", "stage", "description",
                "write_guide", "sort_order", "optional"]
_INST_FIELDS = ["id", "template_id", "user_id", "title", "status",
                "basic_info", "created_at", "updated_at"]
_NI_FIELDS = ["id", "instance_id", "node_id", "sort_order", "status",
              "content", "created_at", "updated_at"]


def _tpl(m: WorkflowTemplateModel) -> WorkflowTemplate:
    return WorkflowTemplate(**{f: getattr(m, f) for f in _TPL_FIELDS})


def _node(m: WorkflowNodeModel) -> WorkflowNode:
    return WorkflowNode(**{f: getattr(m, f) for f in _NODE_FIELDS})


def _inst(m: WorkflowInstanceModel) -> WorkflowInstance:
    return WorkflowInstance(**{f: getattr(m, f) for f in _INST_FIELDS})


def _ni(m: NodeInstanceModel) -> NodeInstance:
    return NodeInstance(**{f: getattr(m, f) for f in _NI_FIELDS})


class SqlAlchemyWorkflowTemplateRepository(WorkflowTemplateRepository):
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, id: str) -> Optional[WorkflowTemplate]:
        m = self.db.get(WorkflowTemplateModel, id)
        return _tpl(m) if m else None

    def get_by_code(self, code: str) -> Optional[WorkflowTemplate]:
        m = self.db.scalars(
            select(WorkflowTemplateModel).where(WorkflowTemplateModel.code == code)
        ).first()
        return _tpl(m) if m else None

    def add(self, tpl: WorkflowTemplate) -> WorkflowTemplate:
        m = WorkflowTemplateModel(
            name=tpl.name, code=tpl.code, category=tpl.category,
            description=tpl.description, icon=tpl.icon,
            is_builtin=tpl.is_builtin, is_active=tpl.is_active,
            sort_order=tpl.sort_order,
        )
        self.db.add(m)
        self.db.flush()
        return _tpl(m)

    def delete(self, tpl: WorkflowTemplate) -> None:
        m = self.db.get(WorkflowTemplateModel, tpl.id)
        if m:
            self.db.delete(m)


class SqlAlchemyWorkflowNodeRepository(WorkflowNodeRepository):
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, id: str) -> Optional[WorkflowNode]:
        m = self.db.get(WorkflowNodeModel, id)
        return _node(m) if m else None

    def list_by_template(self, template_id: str) -> List[WorkflowNode]:
        q = select(WorkflowNodeModel).where(
            WorkflowNodeModel.template_id == template_id
        ).order_by(WorkflowNodeModel.sort_order)
        return [_node(m) for m in self.db.scalars(q).all()]

    def list_by_ids(self, ids: List[str]) -> List[WorkflowNode]:
        if not ids:
            return []
        q = select(WorkflowNodeModel).where(WorkflowNodeModel.id.in_(ids))
        return [_node(m) for m in self.db.scalars(q).all()]

    def add(self, node: WorkflowNode) -> WorkflowNode:
        m = WorkflowNodeModel(
            template_id=node.template_id, name=node.name, stage=node.stage,
            description=node.description, write_guide=node.write_guide,
            sort_order=node.sort_order, optional=node.optional,
        )
        self.db.add(m)
        self.db.flush()
        return _node(m)

    def delete(self, node: WorkflowNode) -> None:
        m = self.db.get(WorkflowNodeModel, node.id)
        if m:
            self.db.delete(m)


class SqlAlchemyWorkflowInstanceRepository(WorkflowInstanceRepository):
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, id: str) -> Optional[WorkflowInstance]:
        m = self.db.get(WorkflowInstanceModel, id)
        return _inst(m) if m else None

    def list_by_user(self, user_id: str, status: Optional[str] = None) -> List[WorkflowInstance]:
        q = select(WorkflowInstanceModel).where(WorkflowInstanceModel.user_id == user_id)
        if status:
            q = q.where(WorkflowInstanceModel.status == status)
        q = q.order_by(WorkflowInstanceModel.created_at.desc())
        return [_inst(m) for m in self.db.scalars(q).all()]

    def add(self, inst: WorkflowInstance) -> WorkflowInstance:
        m = WorkflowInstanceModel(
            template_id=inst.template_id, user_id=inst.user_id, title=inst.title,
            status=inst.status, basic_info=inst.basic_info or {},
        )
        self.db.add(m)
        self.db.flush()
        return _inst(m)

    def update(self, inst: WorkflowInstance) -> WorkflowInstance:
        m = self.db.get(WorkflowInstanceModel, inst.id)
        if m:
            m.title = inst.title
            m.status = inst.status
            m.basic_info = dict(inst.basic_info or {})
            self.db.flush()
            self.db.refresh(m)
            return _inst(m)
        return inst

    def delete(self, inst: WorkflowInstance) -> None:
        m = self.db.get(WorkflowInstanceModel, inst.id)
        if m:
            self.db.delete(m)


class SqlAlchemyNodeInstanceRepository(NodeInstanceRepository):
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, id: str) -> Optional[NodeInstance]:
        m = self.db.get(NodeInstanceModel, id)
        return _ni(m) if m else None

    def list_by_instance(self, instance_id: str) -> List[NodeInstance]:
        q = select(NodeInstanceModel).where(
            NodeInstanceModel.instance_id == instance_id
        ).order_by(NodeInstanceModel.sort_order)
        return [_ni(m) for m in self.db.scalars(q).all()]

    def list_upstream(self, instance_id: str, sort_order: int) -> List[NodeInstance]:
        q = select(NodeInstanceModel).where(
            NodeInstanceModel.instance_id == instance_id,
            NodeInstanceModel.sort_order < sort_order,
        ).order_by(NodeInstanceModel.sort_order)
        return [_ni(m) for m in self.db.scalars(q).all()]

    def add(self, ni: NodeInstance) -> NodeInstance:
        m = NodeInstanceModel(
            instance_id=ni.instance_id, node_id=ni.node_id,
            sort_order=ni.sort_order, status=ni.status, content=ni.content or "",
        )
        self.db.add(m)
        self.db.flush()
        return _ni(m)

    def update(self, ni: NodeInstance) -> NodeInstance:
        m = self.db.get(NodeInstanceModel, ni.id)
        if m:
            m.content = ni.content
            m.status = ni.status
            m.sort_order = ni.sort_order
            self.db.flush()
            self.db.refresh(m)
            return _ni(m)
        return ni

    def delete(self, ni: NodeInstance) -> None:
        m = self.db.get(NodeInstanceModel, ni.id)
        if m:
            self.db.delete(m)

    def delete_by_instance(self, instance_id: str) -> None:
        for m in self.db.scalars(
            select(NodeInstanceModel).where(NodeInstanceModel.instance_id == instance_id)
        ).all():
            self.db.delete(m)
