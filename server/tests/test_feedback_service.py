from dataclasses import replace

import pytest

from app.application.chat.feedback_service import FeedbackService
from app.core.exceptions import AppError, NotFoundError
from app.domain.chat.entities import AIResponseFeedback


class _Repo:
    def __init__(self):
        self.item = None
        self.permission_error = False

    def upsert_for_user(self, user_id, target_type, target_id, rating, detail=""):
        if self.permission_error:
            raise PermissionError("target_not_owned")
        self.item = AIResponseFeedback(
            id="feedback-1",
            user_id=user_id,
            target_type=target_type,
            target_id=target_id,
            rating=rating,
            detail=detail,
            source_chunk_ids=["chunk-1"],
        )
        return self.item


def test_submit_feedback_returns_stable_target_and_rating():
    repo = _Repo()
    result = FeedbackService(repo).submit(
        "user-1", "chat_message", "message-1", 1, "依据很准确"
    )
    assert result["id"] == "feedback-1"
    assert result["target_id"] == "message-1"
    assert result["rating"] == 1
    assert result["detail"] == "依据很准确"


def test_submit_feedback_rejects_non_owned_target_without_leaking_existence():
    repo = _Repo()
    repo.permission_error = True
    with pytest.raises(NotFoundError) as exc:
        FeedbackService(repo).submit("user-1", "chat_message", "other-message", -1)
    assert exc.value.status_code == 404


def test_submit_feedback_only_accepts_thumb_values_and_known_targets():
    service = FeedbackService(_Repo())
    with pytest.raises(AppError) as exc:
        service.submit("user-1", "chat_message", "message-1", 0)
    assert exc.value.status_code == 422

    with pytest.raises(AppError) as exc:
        service.submit("user-1", "unknown", "x", 1)
    assert exc.value.status_code == 422
