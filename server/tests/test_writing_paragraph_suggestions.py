"""Regression coverage for exact paragraph replacement and isolated feedback memory."""
import asyncio

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.application.writing.async_task_service import AsyncWritingTaskService
from app.application.writing import prompt_snapshot
from app.infrastructure.database.base import Base
from app.infrastructure.database.models import identity  # noqa: F401 - FK registration
from app.infrastructure.database.models.writing_suggestion import (
    WritingSuggestionEventModel, WritingSuggestionModel,
)
from app.infrastructure.database.models.writing_task import WritingTaskModel
from app.infrastructure.database.models.document import MyDocumentModel


class Assistant:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = 0

    async def achat(self, **kwargs):
        self.calls += 1
        return self.replies.pop(0)


def setup_task():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    task = WritingTaskModel(
        user_id="user-1", context={"title": "测试通知", "document_type": "通知"},
        current_content="一、工作目标\n坚持依法办理。\n二、工作安排\n按时完成。",
        version_no=0, status="editing",
    )
    db.add(task)
    db.commit()
    return db, task


def test_cached_suggestion_accepts_only_one_line_and_records_edit():
    db, task = setup_task()
    assistant = Assistant("坚持依法依规办理。")
    svc = AsyncWritingTaskService(db, assistant=assistant)
    pid = svc.list_paragraphs(task.id, "user-1")["items"][1]["id"]
    suggestion = asyncio.run(svc.suggest_paragraph_async(task.id, "user-1", pid))
    cached = asyncio.run(svc.suggest_paragraph_async(task.id, "user-1", pid))
    assert cached["id"] == suggestion["id"]
    assert assistant.calls == 1

    result = svc.accept_paragraph_suggestion(
        task.id, "user-1", suggestion["id"], "坚持依法依规、稳妥办理。")
    assert result["current_content"] == "一、工作目标\n坚持依法依规、稳妥办理。\n二、工作安排\n按时完成。"
    assert result["version_no"] == 1
    events = db.scalars(select(WritingSuggestionEventModel).order_by(
        WritingSuggestionEventModel.created_at)).all()
    assert [e.action for e in events] == ["generate", "accept_edited"]
    assert "坚持依法办理。" in events[-1].diff_text
    assert "坚持依法依规、稳妥办理。" in events[-1].diff_text
    assert "原：坚持依法办理。" in svc._accepted_style_memory("user-1", "通知")
    assert svc._accepted_style_memory("user-2", "通知") == ""
    assert svc._accepted_style_memory("user-1", "请示") == ""
    prompt_snapshot.enter_task(task.id, "user-1")
    assert "采纳：坚持依法依规、稳妥办理。" in svc._draft_prompt(
        "请起草一份通知", [], None, "user-1")
    assert svc.list_paragraphs(task.id, "user-1")["items"][1]["status"] == "accepted"


def test_stale_or_other_users_cannot_apply_suggestion():
    db, task = setup_task()
    svc = AsyncWritingTaskService(db, assistant=Assistant("请按时完成。"))
    pid = svc.list_paragraphs(task.id, "user-1")["items"][3]["id"]
    suggestion = asyncio.run(svc.suggest_paragraph_async(task.id, "user-1", pid))
    with pytest.raises(HTTPException) as wrong_user:
        svc.accept_paragraph_suggestion(task.id, "user-2", suggestion["id"], "请按时完成。")
    assert wrong_user.value.status_code == 404
    task.current_content = task.current_content.replace("按时完成。", "现在由人工处理。")
    db.commit()
    with pytest.raises(HTTPException) as stale:
        svc.accept_paragraph_suggestion(task.id, "user-1", suggestion["id"], "请按时完成。")
    assert stale.value.status_code == 409
    assert task.current_content.endswith("现在由人工处理。")


def test_inserted_text_with_duplicate_line_cannot_steal_old_anchor():
    db, task = setup_task()
    task.current_content = "相同段落。\n相同段落。\n结尾。"
    db.commit()
    svc = AsyncWritingTaskService(db, assistant=Assistant("优化后的段落。"))
    pid = svc.list_paragraphs(task.id, "user-1")["items"][1]["id"]
    suggestion = asyncio.run(svc.suggest_paragraph_async(task.id, "user-1", pid))
    # Position 1 still contains exactly the same bytes, but is now a different occurrence.
    task.current_content = "新增前段。\n相同段落。\n相同段落。\n结尾。"
    db.commit()
    with pytest.raises(HTTPException) as stale:
        svc.accept_paragraph_suggestion(task.id, "user-1", suggestion["id"], "优化后的段落。")
    assert stale.value.status_code == 409


def test_reject_does_not_change_document_and_regenerate_replaces_pending():
    db, task = setup_task()
    svc = AsyncWritingTaskService(db, assistant=Assistant("按要求完成。", "按节点完成。"))
    pid = svc.list_paragraphs(task.id, "user-1")["items"][3]["id"]
    first = asyncio.run(svc.suggest_paragraph_async(task.id, "user-1", pid))
    second = asyncio.run(svc.suggest_paragraph_async(task.id, "user-1", pid, regenerate=True))
    assert db.get(WritingSuggestionModel, first["id"]).status == "superseded"
    svc.reject_paragraph_suggestion(task.id, "user-1", second["id"])
    assert task.current_content.endswith("按时完成。")
    assert task.version_no == 0
    assert svc.list_paragraphs(task.id, "user-1")["items"][3]["status"] == "rejected"


def test_two_cached_paragraphs_can_be_accepted_in_sequence():
    db, task = setup_task()
    svc = AsyncWritingTaskService(db, assistant=Assistant("依法依规办理。", "按节点完成。"))
    items = svc.list_paragraphs(task.id, "user-1")["items"]
    first = asyncio.run(svc.suggest_paragraph_async(task.id, "user-1", items[1]["id"]))
    second = asyncio.run(svc.suggest_paragraph_async(task.id, "user-1", items[3]["id"]))
    svc.accept_paragraph_suggestion(task.id, "user-1", first["id"], "依法依规办理。")
    result = svc.accept_paragraph_suggestion(task.id, "user-1", second["id"], "按节点完成。")
    assert result["version_no"] == 2
    assert result["current_content"] == "一、工作目标\n依法依规办理。\n二、工作安排\n按节点完成。"


def test_model_cannot_introduce_unsupported_number():
    db, task = setup_task()
    svc = AsyncWritingTaskService(db, assistant=Assistant("到2027年完成。"))
    pid = svc.list_paragraphs(task.id, "user-1")["items"][3]["id"]
    with pytest.raises(HTTPException) as error:
        asyncio.run(svc.suggest_paragraph_async(task.id, "user-1", pid))
    assert error.value.status_code == 502
    assert db.scalars(select(WritingSuggestionModel)).all() == []


def test_accept_stores_the_users_exact_manual_line():
    db, task = setup_task()
    svc = AsyncWritingTaskService(db, assistant=Assistant("按节点完成。"))
    pid = svc.list_paragraphs(task.id, "user-1")["items"][3]["id"]
    suggestion = asyncio.run(svc.suggest_paragraph_async(task.id, "user-1", pid))
    svc.accept_paragraph_suggestion(
        task.id, "user-1", suggestion["id"], "  按节点完成。  ")
    assert task.current_content.endswith("  按节点完成。  ")
    assert db.get(WritingSuggestionModel, suggestion["id"]).final_content == "  按节点完成。  "


def test_model_suggestion_keeps_the_original_paragraph_indentation():
    db, task = setup_task()
    task.current_content = "第一段。\n　　原文。"
    db.commit()
    svc = AsyncWritingTaskService(db, assistant=Assistant("优化后的内容。"))
    pid = svc.list_paragraphs(task.id, "user-1")["items"][1]["id"]
    suggestion = asyncio.run(svc.suggest_paragraph_async(task.id, "user-1", pid))
    assert suggestion["proposed_content"] == "　　优化后的内容。"


def test_accept_rolls_back_task_document_and_status_if_audit_fails():
    db, task = setup_task()
    svc = AsyncWritingTaskService(db, assistant=Assistant("按节点完成。"))
    pid = svc.list_paragraphs(task.id, "user-1")["items"][3]["id"]
    suggestion = asyncio.run(svc.suggest_paragraph_async(task.id, "user-1", pid))
    original = task.current_content

    def fail_audit(*_args, **_kwargs):
        raise RuntimeError("audit failed")

    svc._event = fail_audit
    with pytest.raises(RuntimeError):
        svc.accept_paragraph_suggestion(task.id, "user-1", suggestion["id"],
                                        "按节点完成。")
    db.rollback()
    db.refresh(task)
    assert task.current_content == original
    assert task.version_no == 0
    assert db.get(WritingSuggestionModel, suggestion["id"]).status == "pending"
    assert db.scalars(select(MyDocumentModel)).all() == []


def test_draft_does_not_overwrite_a_newer_edit():
    db, task = setup_task()
    svc = AsyncWritingTaskService(db)
    expected_state = (task.current_content, task.version_no)
    task.current_content = "另一客户端刚保存的内容。"
    db.commit()
    with pytest.raises(HTTPException) as error:
        svc._finalize_draft(task, task.context, "原来的旧生成结果。", [], "user-1",
                            expected_state=expected_state)
    assert error.value.status_code == 409
    assert task.current_content == "另一客户端刚保存的内容。"


def test_regeneration_preserves_accepted_paragraphs():
    db, task = setup_task()
    task.current_content = ("第一节\n" + "保持其他正文。" * 30 +
                            "\n按时完成。\n" + "保持结尾正文。" * 30)
    db.commit()
    svc = AsyncWritingTaskService(db, assistant=Assistant("按节点完成。"))
    pid = svc.list_paragraphs(task.id, "user-1")["items"][2]["id"]
    suggestion = asyncio.run(svc.suggest_paragraph_async(task.id, "user-1", pid))
    svc.accept_paragraph_suggestion(task.id, "user-1", suggestion["id"], "按节点完成。")
    version = task.version_no
    candidate = task.current_content.replace("按节点完成。", "按时完成。")
    with pytest.raises(HTTPException) as error:
        svc._finalize_draft(task, task.context, candidate, [], "user-1")
    assert error.value.status_code == 422
    assert task.version_no == version


def test_continue_generation_rejects_unrelated_document():
    db, task = setup_task()
    task.current_content = ("坚持依法办理相关工作，确保各项任务按期落实。" * 8)
    db.commit()
    svc = AsyncWritingTaskService(db)
    with pytest.raises(HTTPException) as error:
        svc._finalize_draft(task, task.context, "另一个完全无关的主题。" * 8, [], "user-1")
    assert error.value.status_code == 422
    assert task.version_no == 0


def test_legacy_structural_prefix_maps_to_displayed_paragraph():
    db, task = setup_task()
    task.context = {"title": "测试通知", "recipient": "各科室", "document_type": "通知"}
    task.current_content = "测试通知\n各科室：\n一、工作目标\n坚持依法办理。"
    db.commit()
    svc = AsyncWritingTaskService(db, assistant=Assistant("依法办理。"))
    items = svc.list_paragraphs(task.id, "user-1")["items"]
    assert [item["line_index"] for item in items] == [0, 1]
    assert items[1]["content"] == "坚持依法办理。"
    suggestion = asyncio.run(svc.suggest_paragraph_async(task.id, "user-1", items[1]["id"]))
    result = svc.accept_paragraph_suggestion(task.id, "user-1", suggestion["id"], "依法办理。")
    assert result["current_content"] == "一、工作目标\n依法办理。"
    assert task.current_content == "测试通知\n各科室：\n一、工作目标\n依法办理。"


def test_paragraph_routes_are_wired_to_the_async_service():
    from app.interfaces.deps import get_current_user
    from app.interfaces.writing_tasks import (
        WritingTaskService as RouteService, get_task_service,
    )
    from app.main import app

    assert RouteService is AsyncWritingTaskService
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    task = WritingTaskModel(user_id="user-1", context={"document_type": "通知"},
                            current_content="第一段。\n第二段。", version_no=0,
                            status="editing")
    db.add(task)
    db.commit()
    svc = AsyncWritingTaskService(db, assistant=Assistant("第二段已经优化。"))
    app.dependency_overrides[get_current_user] = lambda: type("User", (), {"id": "user-1"})()
    app.dependency_overrides[get_task_service] = lambda: svc
    try:
        with TestClient(app) as client:
            base = f"/api/v1/writing/tasks/{task.id}"
            paragraphs = client.get(f"{base}/paragraphs")
            assert paragraphs.status_code == 200
            pid = paragraphs.json()["items"][1]["id"]
            suggested = client.post(f"{base}/paragraphs/{pid}/suggest", json={})
            assert suggested.status_code == 200, suggested.text
            accepted = client.post(
                f"{base}/suggestions/{suggested.json()['id']}/accept",
                json={"final_content": "第二段已经优化。"},
            )
            assert accepted.status_code == 200, accepted.text
            assert accepted.json()["current_content"] == "第一段。\n第二段已经优化。"
            assert client.get(f"{base}/paragraphs").json()["items"][1]["status"] == "accepted"
    finally:
        app.dependency_overrides.pop(get_task_service, None)
        app.dependency_overrides.pop(get_current_user, None)
        db.close()
        engine.dispose()
