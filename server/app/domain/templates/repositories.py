"""写作模板仓储接口。"""
from typing import List, Optional

from app.domain.base import Repository
from app.domain.templates.entities import TemplateCategory, WritingTemplate


class WritingTemplateRepository(Repository[WritingTemplate]):
    def list_active(self, category: Optional[str] = None) -> List[WritingTemplate]:
        raise NotImplementedError

    def find_builtin_by_name(self, name: str) -> Optional[WritingTemplate]:
        raise NotImplementedError

    def update(self, tmpl: WritingTemplate) -> WritingTemplate:
        raise NotImplementedError

    def increment_use_count(self, template_id: str) -> None:
        raise NotImplementedError

    def deactivate_builtin_in(self, names: List[str]) -> None:
        raise NotImplementedError


class TemplateCategoryRepository(Repository[TemplateCategory]):
    def get_by_code(self, code: str) -> Optional[TemplateCategory]:
        raise NotImplementedError

    def list_active(self) -> List[TemplateCategory]:
        raise NotImplementedError

    def deactivate_codes(self, codes: List[str]) -> None:
        raise NotImplementedError
