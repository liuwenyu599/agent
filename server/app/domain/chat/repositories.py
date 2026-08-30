"""对话模块仓储接口。"""
from typing import List, Optional

from app.domain.base import Repository
from app.domain.chat.entities import ChatAttachment, ChatMessage, ChatSession


class ChatSessionRepository(Repository[ChatSession]):
    def list_by_user(self, user_id: str) -> List[ChatSession]:
        raise NotImplementedError

    def list_all_paged(self, page: int = 1, page_size: int = 20) -> tuple:
        """返回 (total, items)。"""
        raise NotImplementedError


class ChatMessageRepository(Repository[ChatMessage]):
    def list_by_session(self, session_id: str, limit: int = None,
                        desc: bool = False) -> List[ChatMessage]:
        raise NotImplementedError

    def count_by_session(self, session_id: str) -> int:
        raise NotImplementedError

    def delete_by_session(self, session_id: str) -> None:
        raise NotImplementedError


class ChatAttachmentRepository(Repository[ChatAttachment]):
    def list_by_ids_for_user(self, ids: List[str], user_id: str) -> List[ChatAttachment]:
        raise NotImplementedError

    def list_by_session(self, session_id: str) -> List[ChatAttachment]:
        raise NotImplementedError

    def get_for_user(self, attachment_id: str, user_id: str) -> Optional[ChatAttachment]:
        raise NotImplementedError

    def bind_to_session(self, ids: List[str], session_id: str, user_id: str) -> None:
        raise NotImplementedError
