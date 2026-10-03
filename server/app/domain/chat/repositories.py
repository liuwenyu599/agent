"""对话模块仓储接口。"""
from typing import Dict, List, Optional

from app.domain.base import Repository
from app.domain.chat.entities import AIResponseFeedback, ChatAttachment, ChatMessage, ChatSession


class ChatSessionRepository(Repository[ChatSession]):
    def list_by_user(self, user_id: str) -> List[ChatSession]:
        raise NotImplementedError

    def list_all_paged(self, page: int = 1, page_size: int = 20) -> tuple:
        raise NotImplementedError


class ChatMessageRepository(Repository[ChatMessage]):
    def list_by_session(self, session_id: str, limit: int = None,
                        desc: bool = False) -> List[ChatMessage]:
        raise NotImplementedError

    def count_by_session(self, session_id: str) -> int:
        raise NotImplementedError

    def delete_by_session(self, session_id: str) -> None:
        raise NotImplementedError


class ChatFeedbackRepository(Repository[AIResponseFeedback]):
    def upsert_for_user(self, user_id: str, target_type: str, target_id: str,
                        rating: int, detail: str = "") -> AIResponseFeedback:
        raise NotImplementedError

    def chunk_weights(self, user_id: str, chunk_ids: List[str]) -> Dict[str, float]:
        """Return user-local rerank deltas for cited chunks."""
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