"""PPT 助手领域层。"""
from app.domain.ppt.entities import (
    PPTDocument,
    PPTMaterial,
    PPTTemplate,
    PPTTemplateFavorite,
)
from app.domain.ppt.repositories import (
    PPTDocumentRepository,
    PPTMaterialRepository,
    PPTTemplateFavoriteRepository,
    PPTTemplateRepository,
)

__all__ = [
    "PPTTemplate",
    "PPTMaterial",
    "PPTDocument",
    "PPTTemplateFavorite",
    "PPTTemplateRepository",
    "PPTMaterialRepository",
    "PPTDocumentRepository",
    "PPTTemplateFavoriteRepository",
]
