"""AI 显式反馈 SQLAlchemy 仓储。"""
from __future__ import annotations

from typing import Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.timeutil import now_local
from app.domain.chat.entities import AIResponseFeedback
from app.domain.chat.repositories import ChatFeedbackRepository
from app.infrastructure.database.models.chat import (
    AIResponseFeedbackModel,
    ChatMessageModel,
    ChatSessionModel,
)
from app.infrastructure.database.models.document import MyDocumentModel, MyDocumentVersionModel


def _to_entity(row: AIResponseFeedbackModel) -> AIResponseFeedback:
    return AIResponseFeedback(
        id=row.id,
        user_id=row.user_id,
        target_type=row.target_type,
        target_id=row.target_id,
        message_id=row.message_id,
        rating=row.rating,
        detail=row.detail,
        source_chunk_ids=row.source_chunk_ids or [],
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class SqlAlchemyChatFeedbackRepository(ChatFeedbackRepository):
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, id: str) -> Optional[AIResponseFeedback]:
        row = self.db.get(AIResponseFeedbackModel, id)
        return _to_entity(row) if row else None

    def add(self, entity: AIResponseFeedback) -> AIResponseFeedback:
        row = AIResponseFeedbackModel(
            user_id=entity.user_id,
            target_type=entity.target_type,
            target_id=entity.target_id,
            message_id=entity.message_id,
            rating=entity.rating,
            detail=entity.detail,
            source_chunk_ids=entity.source_chunk_ids or [],
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return _to_entity(row)

    def delete(self, entity: AIResponseFeedback) -> None:
        row = self.db.get(AIResponseFeedbackModel, entity.id)
        if row:
            self.db.delete(row)
            self.db.commit()

    def _owned_target(self, user_id: str, target_type: str, target_id: str):
        if target_type == "chat_message":
            row = self.db.scalar(
                select(ChatMessageModel)
                .join(ChatSessionModel, ChatSessionModel.id == ChatMessageModel.session_id)
                .where(
                    ChatMessageModel.id == target_id,
                    ChatMessageModel.role == "assistant",
                    ChatSessionModel.user_id == user_id,
                )
            )
            if not row:
                return None, None, []
            chunk_ids = []
            for source in row.sources or []:
                if isinstance(source, dict) and source.get("chunk_id"):
                    cid = str(source["chunk_id"])
                    if cid not in chunk_ids:
                        chunk_ids.append(cid)
            return row, row.id, chunk_ids

        if target_type == "document_version":
            row = self.db.scalar(
                select(MyDocumentVersionModel)
                .join(MyDocumentModel, MyDocumentModel.id == MyDocumentVersionModel.document_id)
                .where(
                    MyDocumentVersionModel.id == target_id,
                    MyDocumentModel.user_id == user_id,
                )
            )
            return (row, None, []) if row else (None, None, [])

        return None, None, []

    def upsert_for_user(self, user_id: str, target_type: str, target_id: str,
                        rating: int, detail: str = "") -> AIResponseFeedback:
        _, message_id, chunk_ids = self._owned_target(user_id, target_type, target_id)
        if target_type not in {"chat_message", "document_version"}:
            raise ValueError("unsupported_target_type")
        if message_id is None and target_type == "chat_message":
            raise PermissionError("target_not_owned")
        if target_type == "document_version":
            owned, _, _ = self._owned_target(user_id, target_type, target_id)
            if owned is None:
                raise PermissionError("target_not_owned")

        row = self.db.scalar(select(AIResponseFeedbackModel).where(
            AIResponseFeedbackModel.user_id == user_id,
            AIResponseFeedbackModel.target_type == target_type,
            AIResponseFeedbackModel.target_id == target_id,
        ))
        if row is None:
            row = AIResponseFeedbackModel(
                user_id=user_id,
                target_type=target_type,
                target_id=target_id,
                message_id=message_id,
                rating=rating,
                detail=(detail or "").strip() or None,
                source_chunk_ids=chunk_ids,
            )
            self.db.add(row)
        else:
            row.rating = rating
            row.detail = (detail or "").strip() or None
            row.message_id = message_id
            row.source_chunk_ids = chunk_ids
            row.updated_at = now_local()
        self.db.commit()
        self.db.refresh(row)
        return _to_entity(row)

    def chunk_weights(self, user_id: str, chunk_ids: List[str]) -> Dict[str, float]:
        """User-local source feedback: praise +3%, dislike -5%, bounded to [-15%, +9%]."""
        wanted = {str(cid) for cid in chunk_ids if cid}
        if not wanted:
            return {}
        rows = self.db.scalars(select(AIResponseFeedbackModel).where(
            AIResponseFeedbackModel.user_id == user_id,
            AIResponseFeedbackModel.message_id.isnot(None),
        )).all()
        scores: Dict[str, float] = {cid: 0.0 for cid in wanted}
        for row in rows:
            delta = 0.03 if row.rating > 0 else -0.05
            for cid in row.source_chunk_ids or []:
                cid = str(cid)
                if cid in wanted:
                    scores[cid] = max(-0.15, min(0.09, scores[cid] + delta))
        return {cid: delta for cid, delta in scores.items() if delta}
