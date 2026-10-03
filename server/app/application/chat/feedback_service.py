"""AI 回复/文本版本显式反馈用例。"""
from app.core.exceptions import AppError, NotFoundError
from app.domain.chat.repositories import ChatFeedbackRepository


class FeedbackService:
    def __init__(self, repo: ChatFeedbackRepository) -> None:
        self.repo = repo

    def submit(self, user_id: str, target_type: str, target_id: str,
               rating: int, detail: str = "") -> dict:
        if rating not in (-1, 1):
            raise AppError(422, "反馈只能为赞或踩")
        if target_type not in {"chat_message", "document_version"}:
            raise AppError(422, "不支持的反馈对象")
        try:
            item = self.repo.upsert_for_user(
                user_id=user_id,
                target_type=target_type,
                target_id=target_id,
                rating=rating,
                detail=detail,
            )
        except PermissionError:
            # 不暴露他人消息/版本是否存在。
            raise NotFoundError("反馈对象不存在")
        except ValueError:
            raise AppError(422, "不支持的反馈对象")
        return {
            "id": item.id,
            "target_type": item.target_type,
            "target_id": item.target_id,
            "rating": item.rating,
            "detail": item.detail or "",
            "updated_at": item.updated_at or item.created_at,
        }
