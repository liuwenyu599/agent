"""PPT 助手仓储 SQLAlchemy 实现。"""
from typing import List, Optional

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

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
from app.infrastructure.database.models.ppt import (
    PPTDocumentModel,
    PPTMaterialModel,
    PPTTemplateFavoriteModel,
    PPTTemplateModel,
)

_TPL_FIELDS = ["id", "name", "builtin_id", "category", "description", "is_official",
               "created_by", "colors", "font", "layouts", "layout_library",
               "source_file", "use_count", "created_at", "updated_at"]
_MAT_FIELDS = ["id", "user_id", "name", "caption", "file_path", "file_size",
               "width", "height", "mime_type", "created_at"]
_DOC_FIELDS = ["id", "user_id", "title", "subtitle", "source_content", "template_id",
               "theme_id", "source_type", "status", "is_favorite", "outline",
               "file_path", "slide_count", "created_at", "updated_at"]
_FAV_FIELDS = ["id", "user_id", "template_id", "created_at"]


def _tpl(m: PPTTemplateModel) -> PPTTemplate:
    return PPTTemplate(**{f: getattr(m, f) for f in _TPL_FIELDS})


def _mat(m: PPTMaterialModel) -> PPTMaterial:
    return PPTMaterial(**{f: getattr(m, f) for f in _MAT_FIELDS})


def _doc(m: PPTDocumentModel) -> PPTDocument:
    return PPTDocument(**{f: getattr(m, f) for f in _DOC_FIELDS})


def _fav(m: PPTTemplateFavoriteModel) -> PPTTemplateFavorite:
    return PPTTemplateFavorite(**{f: getattr(m, f) for f in _FAV_FIELDS})


class SqlAlchemyPPTTemplateRepository(PPTTemplateRepository):
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, id: str) -> Optional[PPTTemplate]:
        m = self.db.get(PPTTemplateModel, id)
        return _tpl(m) if m else None

    def get_by_builtin_id(self, builtin_id: str) -> Optional[PPTTemplate]:
        m = self.db.scalars(select(PPTTemplateModel).where(
            PPTTemplateModel.builtin_id == builtin_id)).first()
        return _tpl(m) if m else None

    def list_for_user(self, user_id: str, scope: str = "all",
                      category: Optional[str] = None,
                      keyword: Optional[str] = None) -> List[PPTTemplate]:
        q = select(PPTTemplateModel)
        if scope == "official":
            q = q.where(PPTTemplateModel.is_official == True)  # noqa: E712
        elif scope == "mine":
            q = q.where(PPTTemplateModel.is_official == False,  # noqa: E712
                        PPTTemplateModel.created_by == user_id)
        elif scope == "favorite":
            fav_ids = [f.template_id for f in self.db.scalars(
                select(PPTTemplateFavoriteModel).where(
                    PPTTemplateFavoriteModel.user_id == user_id)).all()]
            q = q.where(PPTTemplateModel.id.in_(fav_ids or ["__none__"]))
        else:
            q = q.where(or_(PPTTemplateModel.is_official == True,  # noqa: E712
                            PPTTemplateModel.created_by == user_id))
        if category:
            q = q.where(PPTTemplateModel.category == category)
        if keyword:
            q = q.where(PPTTemplateModel.name.contains(keyword))
        q = q.order_by(PPTTemplateModel.is_official.desc(),
                       PPTTemplateModel.use_count.desc())
        return [_tpl(m) for m in self.db.scalars(q).all()]

    def list_categories(self) -> List[str]:
        rows = self.db.scalars(select(PPTTemplateModel.category).distinct()).all()
        return sorted({r for r in rows if r})

    def add(self, tpl: PPTTemplate) -> PPTTemplate:
        m = PPTTemplateModel(
            name=tpl.name, builtin_id=tpl.builtin_id, category=tpl.category,
            description=tpl.description, is_official=tpl.is_official,
            created_by=tpl.created_by, colors=tpl.colors, font=tpl.font,
            layouts=tpl.layouts, layout_library=tpl.layout_library,
            source_file=tpl.source_file, use_count=tpl.use_count,
        )
        self.db.add(m)
        self.db.commit()
        self.db.refresh(m)
        return _tpl(m)

    def update(self, tpl: PPTTemplate) -> PPTTemplate:
        m = self.db.get(PPTTemplateModel, tpl.id)
        if m:
            for f in _TPL_FIELDS:
                if f in ("id", "created_at"):
                    continue
                setattr(m, f, getattr(tpl, f))
            self.db.commit()
            self.db.refresh(m)
            return _tpl(m)
        return tpl

    def delete(self, tpl: PPTTemplate) -> None:
        self.hard_delete(tpl)

    def hard_delete(self, tpl: PPTTemplate) -> None:
        m = self.db.get(PPTTemplateModel, tpl.id)
        if m:
            self.db.delete(m)
            self.db.commit()


class SqlAlchemyPPTTemplateFavoriteRepository(PPTTemplateFavoriteRepository):
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, user_id: str, template_id: str = None) -> Optional[PPTTemplateFavorite]:  # type: ignore[override]
        if template_id is None:  # 兼容 Repository.get(id)
            return None
        m = self.db.scalars(select(PPTTemplateFavoriteModel).where(
            PPTTemplateFavoriteModel.user_id == user_id,
            PPTTemplateFavoriteModel.template_id == template_id)).first()
        return _fav(m) if m else None

    def list_template_ids(self, user_id: str) -> List[str]:
        return [m.template_id for m in self.db.scalars(
            select(PPTTemplateFavoriteModel).where(
                PPTTemplateFavoriteModel.user_id == user_id)).all()]

    def add(self, fav: PPTTemplateFavorite) -> PPTTemplateFavorite:
        m = PPTTemplateFavoriteModel(user_id=fav.user_id, template_id=fav.template_id)
        self.db.add(m)
        self.db.commit()
        self.db.refresh(m)
        return _fav(m)

    def delete(self, fav: PPTTemplateFavorite) -> None:
        m = self.db.get(PPTTemplateFavoriteModel, fav.id)
        if m:
            self.db.delete(m)
            self.db.commit()

    def delete_by_template(self, template_id: str) -> None:
        for m in self.db.scalars(select(PPTTemplateFavoriteModel).where(
                PPTTemplateFavoriteModel.template_id == template_id)).all():
            self.db.delete(m)
        self.db.commit()


class SqlAlchemyPPTMaterialRepository(PPTMaterialRepository):
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, id: str) -> Optional[PPTMaterial]:
        m = self.db.get(PPTMaterialModel, id)
        return _mat(m) if m else None

    def get_for_user(self, id: str, user_id: str) -> Optional[PPTMaterial]:
        m = self.db.scalars(select(PPTMaterialModel).where(
            PPTMaterialModel.id == id, PPTMaterialModel.user_id == user_id)).first()
        return _mat(m) if m else None

    def list_by_user(self, user_id: str) -> List[PPTMaterial]:
        q = select(PPTMaterialModel).where(PPTMaterialModel.user_id == user_id) \
            .order_by(PPTMaterialModel.created_at.desc())
        return [_mat(m) for m in self.db.scalars(q).all()]

    def add(self, mat: PPTMaterial) -> PPTMaterial:
        m = PPTMaterialModel(
            user_id=mat.user_id, name=mat.name, caption=mat.caption,
            file_path=mat.file_path, file_size=mat.file_size,
            width=mat.width, height=mat.height, mime_type=mat.mime_type,
        )
        self.db.add(m)
        self.db.commit()
        self.db.refresh(m)
        return _mat(m)

    def update(self, mat: PPTMaterial) -> PPTMaterial:
        m = self.db.get(PPTMaterialModel, mat.id)
        if m:
            m.name = mat.name
            m.caption = mat.caption
            self.db.commit()
            self.db.refresh(m)
            return _mat(m)
        return mat

    def delete(self, mat: PPTMaterial) -> None:
        m = self.db.get(PPTMaterialModel, mat.id)
        if m:
            self.db.delete(m)
            self.db.commit()


class SqlAlchemyPPTDocumentRepository(PPTDocumentRepository):
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, id: str) -> Optional[PPTDocument]:
        m = self.db.get(PPTDocumentModel, id)
        return _doc(m) if m else None

    def get_for_user(self, id: str, user_id: str) -> Optional[PPTDocument]:
        m = self.db.scalars(select(PPTDocumentModel).where(
            PPTDocumentModel.id == id, PPTDocumentModel.user_id == user_id)).first()
        return _doc(m) if m else None

    def list_by_user(self, user_id: str, tab: str = "all",
                     keyword: Optional[str] = None) -> List[PPTDocument]:
        q = select(PPTDocumentModel).where(PPTDocumentModel.user_id == user_id)
        if tab == "draft":
            q = q.where(PPTDocumentModel.status == "draft")
        elif tab == "generated":
            q = q.where(PPTDocumentModel.status == "generated")
        elif tab == "favorite":
            q = q.where(PPTDocumentModel.is_favorite == True)  # noqa: E712
        if keyword:
            q = q.where(PPTDocumentModel.title.contains(keyword))
        q = q.order_by(PPTDocumentModel.updated_at.desc())
        return [_doc(m) for m in self.db.scalars(q).all()]

    def add(self, doc: PPTDocument) -> PPTDocument:
        m = PPTDocumentModel(
            user_id=doc.user_id, title=doc.title, subtitle=doc.subtitle,
            source_content=doc.source_content, template_id=doc.template_id,
            theme_id=doc.theme_id, source_type=doc.source_type, status=doc.status,
            is_favorite=doc.is_favorite, outline=doc.outline,
            file_path=doc.file_path, slide_count=doc.slide_count,
        )
        self.db.add(m)
        self.db.commit()
        self.db.refresh(m)
        return _doc(m)

    def update(self, doc: PPTDocument) -> PPTDocument:
        m = self.db.get(PPTDocumentModel, doc.id)
        if m:
            for f in _DOC_FIELDS:
                if f in ("id", "created_at"):
                    continue
                setattr(m, f, getattr(doc, f))
            self.db.commit()
            self.db.refresh(m)
            return _doc(m)
        return doc

    def delete(self, doc: PPTDocument) -> None:
        m = self.db.get(PPTDocumentModel, doc.id)
        if m:
            self.db.delete(m)
            self.db.commit()
