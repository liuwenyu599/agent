"""参考材料仓储接口。"""
from typing import List, Optional

from app.domain.base import Repository
from app.domain.references.entities import TaskReference, TemplateReference


class TemplateReferenceRepository(Repository[TemplateReference]):
    def list_active_by_template(self, template_id: str, limit: int = None) -> List[TemplateReference]:
        raise NotImplementedError

    def update(self, ref: TemplateReference) -> TemplateReference:
        raise NotImplementedError


class TaskReferenceRepository(Repository[TaskReference]):
    def list_by_user(self, user_id: str, template_id: Optional[str] = None,
                     session_id: Optional[str] = None) -> List[TaskReference]:
        raise NotImplementedError

    def list_by_ids_for_user(self, ids: List[str], user_id: str) -> List[TaskReference]:
        raise NotImplementedError

    def update(self, ref: TaskReference) -> TaskReference:
        raise NotImplementedError

    def hard_delete(self, ref: TaskReference) -> None:
        raise NotImplementedError
