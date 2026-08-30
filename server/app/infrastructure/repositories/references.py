"""参考材料仓储 SQLAlchemy 实现。"""
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.references.entities import TaskReference, TemplateReference
from app.domain.references.repositories import (
    TaskReferenceRepository,
    TemplateReferenceRepository,
)
from app.infrastructure.database.models.references import (
    TaskReferenceModel,
    TemplateReferenceModel,
)

_TREF_FIELDS = ["id", "template_id", "name", "ref_type", "file_path", "file_size",
                "source_url", "text_content", "char_count", "parse_status",
                "parse_note", "created_by", "is_active", "created_at"]

_TASK_FIELDS = ["id", "user_id", "template_id", "session_id", "name", "ref_type",
                "file_path", "file_size", "source_url", "text_content", "char_count",
                "parse_status", "parse_note", "promoted_doc_id", "created_at"]


def _tref_to_entity(m: TemplateReferenceModel) -> TemplateReference:
    return TemplateReference(**{f: getattr(m, f) for f in _TREF_FIELDS})


def _task_to_entity(m: TaskReferenceModel) -> TaskReference:
    return TaskReference(**{f: getattr(m, f) for f in _TASK_FIELDS})


class SqlAlchemyTemplateReferenceRepository(TemplateReferenceRepository):
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, id: str) -> Optional[TemplateReference]:
        m = self.db.get(TemplateReferenceModel, id)
        return _tref_to_entity(m) if m else None

    def list_active_by_template(self, template_id: str, limit: int = None) -> List[TemplateReference]:
        q = select(TemplateReferenceModel).where(
            TemplateReferenceModel.template_id == template_id,
            TemplateReferenceModel.is_active == True,  # noqa: E712
        ).order_by(TemplateReferenceModel.created_at.desc())
        if limit:
            q = q.limit(limit)
        return [_tref_to_entity(m) for m in self.db.scalars(q).all()]

    def add(self, ref: TemplateReference) -> TemplateReference:
        m = TemplateReferenceModel(
            template_id=ref.template_id, name=ref.name, ref_type=ref.ref_type,
            file_path=ref.file_path, file_size=ref.file_size, source_url=ref.source_url,
            text_content=ref.text_content, char_count=ref.char_count,
            parse_status=ref.parse_status, parse_note=ref.parse_note,
            created_by=ref.created_by, is_active=ref.is_active,
        )
        self.db.add(m)
        self.db.commit()
        self.db.refresh(m)
        return _tref_to_entity(m)

    def update(self, ref: TemplateReference) -> TemplateReference:
        m = self.db.get(TemplateReferenceModel, ref.id)
        if m:
            for f in _TREF_FIELDS:
                if f in ("id", "created_at"):
                    continue
                setattr(m, f, getattr(ref, f))
            self.db.commit()
            self.db.refresh(m)
            return _tref_to_entity(m)
        return ref

    def delete(self, ref: TemplateReference) -> None:
        m = self.db.get(TemplateReferenceModel, ref.id)
        if m:
            m.is_active = False
            self.db.commit()


class SqlAlchemyTaskReferenceRepository(TaskReferenceRepository):
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, id: str) -> Optional[TaskReference]:
        m = self.db.get(TaskReferenceModel, id)
        return _task_to_entity(m) if m else None

    def list_by_user(self, user_id: str, template_id: Optional[str] = None,
                     session_id: Optional[str] = None) -> List[TaskReference]:
        q = select(TaskReferenceModel).where(TaskReferenceModel.user_id == user_id)
        if template_id:
            q = q.where(TaskReferenceModel.template_id == template_id)
        if session_id:
            q = q.where(TaskReferenceModel.session_id == session_id)
        q = q.order_by(TaskReferenceModel.created_at.desc())
        return [_task_to_entity(m) for m in self.db.scalars(q).all()]

    def list_by_ids_for_user(self, ids: List[str], user_id: str) -> List[TaskReference]:
        if not ids:
            return []
        items = self.db.scalars(select(TaskReferenceModel).where(
            TaskReferenceModel.id.in_(ids),
            TaskReferenceModel.user_id == user_id,
        )).all()
        return [_task_to_entity(m) for m in items]

    def add(self, ref: TaskReference) -> TaskReference:
        m = TaskReferenceModel(
            user_id=ref.user_id, template_id=ref.template_id, session_id=ref.session_id,
            name=ref.name, ref_type=ref.ref_type, file_path=ref.file_path,
            file_size=ref.file_size, source_url=ref.source_url,
            text_content=ref.text_content, char_count=ref.char_count,
            parse_status=ref.parse_status, parse_note=ref.parse_note,
            promoted_doc_id=ref.promoted_doc_id,
        )
        self.db.add(m)
        self.db.commit()
        self.db.refresh(m)
        return _task_to_entity(m)

    def update(self, ref: TaskReference) -> TaskReference:
        m = self.db.get(TaskReferenceModel, ref.id)
        if m:
            for f in _TASK_FIELDS:
                if f in ("id", "created_at"):
                    continue
                setattr(m, f, getattr(ref, f))
            self.db.commit()
            self.db.refresh(m)
            return _task_to_entity(m)
        return ref

    def delete(self, ref: TaskReference) -> None:
        self.hard_delete(ref)

    def hard_delete(self, ref: TaskReference) -> None:
        m = self.db.get(TaskReferenceModel, ref.id)
        if m:
            self.db.delete(m)
            self.db.commit()
