"""对话模块仓储 SQLAlchemy 实现。"""
from typing import List, Optional

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.domain.chat.entities import ChatAttachment, ChatMessage, ChatSession
from app.domain.chat.repositories import (
    ChatAttachmentRepository,
    ChatMessageRepository,
    ChatSessionRepository,
)
from app.infrastructure.database.models.chat import (
    ChatAttachmentModel,
    ChatMessageModel,
    ChatSessionModel,
)


def _session_to_entity(m: ChatSessionModel) -> ChatSession:
    return ChatSession(id=m.id, user_id=m.user_id, title=m.title or "",
                       created_at=m.created_at)


def _msg_to_entity(m: ChatMessageModel) -> ChatMessage:
    return ChatMessage(
        id=m.id, session_id=m.session_id, role=m.role, content=m.content,
        source=m.source or "chat", sources=m.sources or [],
        attachments=m.attachments or [], tool_calls=m.tool_calls,
        tokens_used=m.tokens_used, latency_ms=m.latency_ms, created_at=m.created_at,
    )


def _att_to_entity(m: ChatAttachmentModel) -> ChatAttachment:
    return ChatAttachment(
        id=m.id, session_id=m.session_id, user_id=m.user_id, filename=m.filename,
        kind=m.kind, file_path=m.file_path, file_size=m.file_size,
        text_content=m.text_content, parse_status=m.parse_status or "ok",
        parse_note=m.parse_note, created_at=m.created_at,
    )


class SqlAlchemyChatSessionRepository(ChatSessionRepository):
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, id: str) -> Optional[ChatSession]:
        m = self.db.get(ChatSessionModel, id)
        return _session_to_entity(m) if m else None

    def get_model(self, id: str) -> Optional[ChatSessionModel]:
        return self.db.get(ChatSessionModel, id)

    def get_for_user(self, session_id: str, user_id: str) -> Optional[ChatSession]:
        m = self.db.scalar(select(ChatSessionModel).where(
            ChatSessionModel.id == session_id,
            ChatSessionModel.user_id == user_id,
        ))
        return _session_to_entity(m) if m else None

    def list_by_user(self, user_id: str) -> List[ChatSession]:
        items = self.db.scalars(select(ChatSessionModel).where(
            ChatSessionModel.user_id == user_id
        ).order_by(ChatSessionModel.created_at.desc())).all()
        return [_session_to_entity(m) for m in items]

    def list_all_paged(self, page: int = 1, page_size: int = 20) -> tuple:
        q = select(ChatSessionModel).order_by(ChatSessionModel.created_at.desc())
        total = len(self.db.scalars(select(ChatSessionModel.id)).all())
        items = self.db.scalars(q.offset((page - 1) * page_size).limit(page_size)).all()
        return total, [(
            _session_to_entity(m),
            m.user.real_name or m.user.username if m.user else "未知",
        ) for m in items]

    def add(self, session: ChatSession) -> ChatSession:
        m = ChatSessionModel(user_id=session.user_id, title=session.title)
        self.db.add(m)
        self.db.commit()
        self.db.refresh(m)
        return _session_to_entity(m)

    def delete(self, session: ChatSession) -> None:
        m = self.db.get(ChatSessionModel, session.id)
        if m:
            self.db.delete(m)  # cascade 删除 messages / attachments
            self.db.commit()


class SqlAlchemyChatMessageRepository(ChatMessageRepository):
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, id: str) -> Optional[ChatMessage]:
        m = self.db.get(ChatMessageModel, id)
        return _msg_to_entity(m) if m else None

    def list_by_session(self, session_id: str, limit: int = None,
                        desc: bool = False) -> List[ChatMessage]:
        q = select(ChatMessageModel).where(ChatMessageModel.session_id == session_id)
        q = q.order_by(
            ChatMessageModel.created_at.desc() if desc else ChatMessageModel.created_at
        )
        if limit:
            q = q.limit(limit)
        return [_msg_to_entity(m) for m in self.db.scalars(q).all()]

    def count_by_session(self, session_id: str) -> int:
        return len(self.db.scalars(select(ChatMessageModel.id).where(
            ChatMessageModel.session_id == session_id
        )).all())

    def add(self, message: ChatMessage) -> ChatMessage:
        m = ChatMessageModel(
            session_id=message.session_id, role=message.role, content=message.content,
            source=message.source, sources=message.sources,
            attachments=message.attachments, tool_calls=message.tool_calls,
            tokens_used=message.tokens_used, latency_ms=message.latency_ms,
        )
        self.db.add(m)
        return message

    def delete(self, message: ChatMessage) -> None:
        m = self.db.get(ChatMessageModel, message.id)
        if m:
            self.db.delete(m)

    def delete_by_session(self, session_id: str) -> None:
        for m in self.db.scalars(select(ChatMessageModel).where(
                ChatMessageModel.session_id == session_id)).all():
            self.db.delete(m)


class SqlAlchemyChatAttachmentRepository(ChatAttachmentRepository):
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, id: str) -> Optional[ChatAttachment]:
        m = self.db.get(ChatAttachmentModel, id)
        return _att_to_entity(m) if m else None

    def get_for_user(self, attachment_id: str, user_id: str) -> Optional[ChatAttachment]:
        m = self.db.scalar(select(ChatAttachmentModel).where(
            ChatAttachmentModel.id == attachment_id,
            ChatAttachmentModel.user_id == user_id,
        ))
        return _att_to_entity(m) if m else None

    def list_by_ids_for_user(self, ids: List[str], user_id: str) -> List[ChatAttachment]:
        if not ids:
            return []
        items = self.db.scalars(select(ChatAttachmentModel).where(
            ChatAttachmentModel.id.in_(ids),
            ChatAttachmentModel.user_id == user_id,
        )).all()
        return [_att_to_entity(m) for m in items]

    def list_by_session(self, session_id: str) -> List[ChatAttachment]:
        items = self.db.scalars(select(ChatAttachmentModel).where(
            ChatAttachmentModel.session_id == session_id
        ).order_by(ChatAttachmentModel.created_at)).all()
        return [_att_to_entity(m) for m in items]

    def bind_to_session(self, ids: List[str], session_id: str, user_id: str) -> None:
        if not ids:
            return
        self.db.execute(
            update(ChatAttachmentModel)
            .where(ChatAttachmentModel.id.in_(ids),
                   ChatAttachmentModel.user_id == user_id)
            .values(session_id=session_id)
        )
        self.db.commit()

    def add(self, att: ChatAttachment) -> ChatAttachment:
        m = ChatAttachmentModel(
            id=att.id, session_id=att.session_id, user_id=att.user_id,
            filename=att.filename, kind=att.kind, file_path=att.file_path,
            file_size=att.file_size, text_content=att.text_content,
            parse_status=att.parse_status, parse_note=att.parse_note,
        )
        self.db.add(m)
        self.db.commit()
        return att

    def delete(self, att: ChatAttachment) -> None:
        m = self.db.get(ChatAttachmentModel, att.id)
        if m:
            self.db.delete(m)
            self.db.commit()
