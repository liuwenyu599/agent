"""PPT 助手仓储接口。"""
from typing import List, Optional

from app.domain.base import Repository
from app.domain.ppt.entities import (
    PPTDocument,
    PPTMaterial,
    PPTTemplate,
    PPTTemplateFavorite,
)


class PPTTemplateRepository(Repository[PPTTemplate]):
    def get_by_builtin_id(self, builtin_id: str) -> Optional[PPTTemplate]:
        raise NotImplementedError

    def list_for_user(self, user_id: str, scope: str = "all",
                      category: Optional[str] = None,
                      keyword: Optional[str] = None) -> List[PPTTemplate]:
        raise NotImplementedError

    def list_categories(self) -> List[str]:
        raise NotImplementedError

    def update(self, tpl: PPTTemplate) -> PPTTemplate:
        raise NotImplementedError

    def hard_delete(self, tpl: PPTTemplate) -> None:
        raise NotImplementedError


class PPTTemplateFavoriteRepository(Repository[PPTTemplateFavorite]):
    def get(self, user_id: str, template_id: str) -> Optional[PPTTemplateFavorite]:  # type: ignore[override]
        raise NotImplementedError

    def list_template_ids(self, user_id: str) -> List[str]:
        raise NotImplementedError

    def delete_by_template(self, template_id: str) -> None:
        raise NotImplementedError


class PPTMaterialRepository(Repository[PPTMaterial]):
    def list_by_user(self, user_id: str) -> List[PPTMaterial]:
        raise NotImplementedError

    def get_for_user(self, id: str, user_id: str) -> Optional[PPTMaterial]:
        raise NotImplementedError

    def update(self, m: PPTMaterial) -> PPTMaterial:
        raise NotImplementedError


class PPTDocumentRepository(Repository[PPTDocument]):
    def list_by_user(self, user_id: str, tab: str = "all",
                     keyword: Optional[str] = None) -> List[PPTDocument]:
        raise NotImplementedError

    def get_for_user(self, id: str, user_id: str) -> Optional[PPTDocument]:
        raise NotImplementedError

    def update(self, doc: PPTDocument) -> PPTDocument:
        raise NotImplementedError
