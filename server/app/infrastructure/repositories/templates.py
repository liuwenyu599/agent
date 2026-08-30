"""写作模板仓储 SQLAlchemy 实现。"""
from typing import List, Optional

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.domain.templates.entities import TemplateCategory, WritingTemplate
from app.domain.templates.repositories import (
    TemplateCategoryRepository,
    WritingTemplateRepository,
)
from app.infrastructure.database.models.templates import (
    TemplateCategoryModel,
    WritingTemplateModel,
)

_ENTITY_FIELDS = [
    "id", "name", "category", "base_type", "description", "icon", "params_schema",
    "content_template", "system_prompt", "writing_style", "word_count",
    "need_red_header", "need_signature", "need_date", "need_doc_number",
    "keywords", "is_active", "is_builtin", "created_by", "sort_order", "use_count",
    "template_kind", "tags", "scene", "writing_guide", "structure", "kb_ids",
    "visibility", "share_scope", "share_departments", "share_roles", "is_draft",
    "created_at", "updated_at",
]


def _to_entity(m: WritingTemplateModel) -> WritingTemplate:
    data = {f: getattr(m, f) for f in _ENTITY_FIELDS}
    for json_list in ("params_schema", "tags", "structure", "kb_ids",
                      "share_departments", "share_roles"):
        if data[json_list] is None:
            data[json_list] = []
    return WritingTemplate(**data)


def _apply(m: WritingTemplateModel, t: WritingTemplate) -> None:
    for f in _ENTITY_FIELDS:
        if f in ("id", "created_at", "updated_at"):
            continue
        setattr(m, f, getattr(t, f))


class SqlAlchemyWritingTemplateRepository(WritingTemplateRepository):
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, id: str) -> Optional[WritingTemplate]:
        m = self.db.get(WritingTemplateModel, id)
        return _to_entity(m) if m else None

    def get_model(self, id: str) -> Optional[WritingTemplateModel]:
        return self.db.get(WritingTemplateModel, id)

    def list_active(self, category: Optional[str] = None) -> List[WritingTemplate]:
        q = select(WritingTemplateModel).where(WritingTemplateModel.is_active == True)  # noqa: E712
        if category:
            q = q.where(WritingTemplateModel.category == category)
        q = q.order_by(WritingTemplateModel.sort_order, WritingTemplateModel.created_at.desc())
        return [_to_entity(m) for m in self.db.scalars(q).all()]

    def find_builtin_by_name(self, name: str) -> Optional[WritingTemplate]:
        m = self.db.scalar(select(WritingTemplateModel).where(
            WritingTemplateModel.name == name,
            WritingTemplateModel.is_builtin == True,  # noqa: E712
        ))
        return _to_entity(m) if m else None

    def add(self, tmpl: WritingTemplate) -> WritingTemplate:
        m = WritingTemplateModel()
        _apply(m, tmpl)
        self.db.add(m)
        self.db.commit()
        self.db.refresh(m)
        return _to_entity(m)

    def update(self, tmpl: WritingTemplate) -> WritingTemplate:
        m = self.db.get(WritingTemplateModel, tmpl.id)
        if m:
            _apply(m, tmpl)
            self.db.commit()
            self.db.refresh(m)
            return _to_entity(m)
        return tmpl

    def delete(self, tmpl: WritingTemplate) -> None:
        m = self.db.get(WritingTemplateModel, tmpl.id)
        if m:
            self.db.delete(m)
            self.db.commit()

    def increment_use_count(self, template_id: str) -> None:
        m = self.db.get(WritingTemplateModel, template_id)
        if m:
            m.use_count = (m.use_count or 0) + 1
            self.db.commit()

    def deactivate_builtin_in(self, names: List[str]) -> None:
        """停用分类名在 names 中的内置模板（与旧 /init 逻辑一致，只匹配 category 字段）。"""
        self.db.execute(
            update(WritingTemplateModel)
            .where(WritingTemplateModel.category.in_(names),
                   WritingTemplateModel.is_builtin == True)  # noqa: E712
            .values(is_active=False)
        )
        self.db.commit()

    def creator_name(self, created_by: Optional[str]) -> str:
        if not created_by:
            return "系统"
        from app.infrastructure.database.models.identity import UserModel
        u = self.db.get(UserModel, created_by)
        return (u.real_name or u.username) if u else "系统"


class SqlAlchemyTemplateCategoryRepository(TemplateCategoryRepository):
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, id: str) -> Optional[TemplateCategory]:
        m = self.db.get(TemplateCategoryModel, id)
        return self._to_entity(m) if m else None

    def get_by_code(self, code: str) -> Optional[TemplateCategory]:
        m = self.db.scalar(
            select(TemplateCategoryModel).where(TemplateCategoryModel.code == code)
        )
        return self._to_entity(m) if m else None

    def list_active(self) -> List[TemplateCategory]:
        items = self.db.scalars(
            select(TemplateCategoryModel)
            .where(TemplateCategoryModel.is_active == True)  # noqa: E712
            .order_by(TemplateCategoryModel.sort_order)
        ).all()
        return [self._to_entity(m) for m in items]

    def add(self, cat: TemplateCategory) -> TemplateCategory:
        m = TemplateCategoryModel(
            name=cat.name, code=cat.code, description=cat.description,
            icon=cat.icon, sort_order=cat.sort_order,
        )
        self.db.add(m)
        self.db.commit()
        self.db.refresh(m)
        return self._to_entity(m)

    def delete(self, cat: TemplateCategory) -> None:
        m = self.db.get(TemplateCategoryModel, cat.id)
        if m:
            self.db.delete(m)
            self.db.commit()

    def deactivate_codes(self, codes: List[str]) -> None:
        self.db.execute(
            update(TemplateCategoryModel)
            .where(TemplateCategoryModel.code.in_(codes))
            .values(is_active=False)
        )
        self.db.commit()

    @staticmethod
    def _to_entity(m: TemplateCategoryModel) -> TemplateCategory:
        return TemplateCategory(
            id=m.id, name=m.name, code=m.code, description=m.description or "",
            icon=m.icon, sort_order=m.sort_order or 0, is_active=bool(m.is_active),
            created_at=m.created_at,
        )
