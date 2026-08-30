"""工作流仓储接口。"""
from typing import List, Optional

from app.domain.base import Repository
from app.domain.workflow.entities import (
    NodeInstance,
    WorkflowInstance,
    WorkflowNode,
    WorkflowTemplate,
)


class WorkflowTemplateRepository(Repository[WorkflowTemplate]):
    def get_by_code(self, code: str) -> Optional[WorkflowTemplate]:
        raise NotImplementedError


class WorkflowNodeRepository(Repository[WorkflowNode]):
    def list_by_template(self, template_id: str) -> List[WorkflowNode]:
        raise NotImplementedError

    def list_by_ids(self, ids: List[str]) -> List[WorkflowNode]:
        raise NotImplementedError


class WorkflowInstanceRepository(Repository[WorkflowInstance]):
    def list_by_user(self, user_id: str, status: Optional[str] = None) -> List[WorkflowInstance]:
        raise NotImplementedError

    def update(self, inst: WorkflowInstance) -> WorkflowInstance:
        raise NotImplementedError


class NodeInstanceRepository(Repository[NodeInstance]):
    def list_by_instance(self, instance_id: str) -> List[NodeInstance]:
        raise NotImplementedError

    def list_upstream(self, instance_id: str, sort_order: int) -> List[NodeInstance]:
        raise NotImplementedError

    def update(self, ni: NodeInstance) -> NodeInstance:
        raise NotImplementedError

    def delete_by_instance(self, instance_id: str) -> None:
        raise NotImplementedError
