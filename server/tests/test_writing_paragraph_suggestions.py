"""Regression coverage for exact paragraph replacement and isolated feedback memory."""
import asyncio

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, update
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
    # 主送机关行回归正文：「各科室：」作为正文行显示并可逐段建议。
    assert [item["line_index"] for item in items] == [0, 1, 2]
    assert items[0]["content"] == "各科室："
    assert items[2]["content"] == "坚持依法办理。"
    suggestion = asyncio.run(svc.suggest_paragraph_async(task.id, "user-1", items[2]["id"]))
    result = svc.accept_paragraph_suggestion(task.id, "user-1", suggestion["id"], "依法办理。")
    assert result["current_content"] == "各科室：\n一、工作目标\n依法办理。"
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


def test_continuation_prompt_keeps_feedback_and_both_ends_within_8k_budget(monkeypatch):
    from app.core.config import settings

    db, task = setup_task()
    task.current_content = "开头示例" + "甲" * 2400 + "乙" * 2400 + "结尾示例"
    db.commit()
    svc = AsyncWritingTaskService(db)
    monkeypatch.setattr(settings, "MODEL_CTX_LIMIT", 8192)
    monkeypatch.setattr(svc, "_draft_system", lambda *_args: "基准" * 350)
    monkeypatch.setattr(svc, "_example_style_block", lambda *_args: "范文" * 600)
    monkeypatch.setattr(svc, "_accepted_style_memory", lambda *_args: "采纳偏好" * 75)
    prompt_snapshot.enter_task(task.id, "user-1")

    prompt = svc._draft_prompt("继续生成", [], None, "user-1")

    system_budget = int((8192 - 512) * 0.75 * 0.5)
    assert len(prompt) <= system_budget
    assert "采纳偏好" in prompt
    assert "开头示例" in prompt
    assert "结尾示例" in prompt


def test_feedback_lookup_is_cached_within_one_generation_request(monkeypatch):
    db, task = setup_task()
    svc = AsyncWritingTaskService(db)
    calls = []
    monkeypatch.setattr(svc, "_accepted_style_memory",
                        lambda *_args: calls.append(1) or "已采纳偏好")
    prompt_snapshot.enter_task(task.id, "user-1")
    svc._draft_prompt("继续生成", [], None, "user-1")
    svc._draft_prompt("继续生成", [], None, "user-1")
    assert calls == [1]


def test_continuation_excerpt_preserves_middle_section_headings():
    content = ("一、开头\n" + "甲" * 1200 + "\n二、中间任务\n" +
               "乙" * 1200 + "\n三、结尾安排\n" + "丙" * 1200)
    excerpt = AsyncWritingTaskService._head_tail(content, 600)
    assert len(excerpt) <= 600
    assert "一、开头" in excerpt
    assert "二、中间任务" in excerpt
    assert "三、结尾安排" in excerpt
    assert "丙" in excerpt


def test_revise_rejects_a_stale_client_body_before_any_write(monkeypatch):
    from app.application.writing.paragraph_suggestions import content_hash
    from app.interfaces.writing_tasks import TaskReviseRequest, task_revise

    db, task = setup_task()
    svc = AsyncWritingTaskService(db)
    old_display = svc._to_dict(task)["current_content"]
    task.current_content = "另一客户端已保存的新正文。"
    task.version_no = 1
    db.commit()

    async def no_ai(*_args, **_kwargs):
        return svc._to_dict(task)

    monkeypatch.setattr(svc, "revise_async", no_ai)
    req = TaskReviseRequest(
        instruction="润色", current_content=old_display,
        base_version=0, base_content_hash=content_hash(old_display),
    )
    user = type("User", (), {"id": "user-1"})()
    with pytest.raises(HTTPException) as error:
        # The conflict is raised before the first await; avoid a Windows event
        # loop here, which requires socketpair access in restricted CI runners.
        task_revise(task.id, req, user, svc).send(None)
    assert error.value.status_code == 409
    assert task.current_content == "另一客户端已保存的新正文。"


def test_revise_passes_manual_text_without_precommitting(monkeypatch):
    from app.application.writing.paragraph_suggestions import content_hash
    from app.interfaces.writing_tasks import TaskReviseRequest, task_revise

    db, task = setup_task()
    svc = AsyncWritingTaskService(db)
    saved = task.current_content
    captured = {}

    async def observe(*_args, **kwargs):
        captured.update(kwargs)
        assert task.current_content == saved
        return {"current_content": saved}

    monkeypatch.setattr(svc, "revise_async", observe)
    req = TaskReviseRequest(
        instruction="润色", current_content="用户刚编辑的正文。",
        base_version=0, base_content_hash=content_hash(svc._to_dict(task)["current_content"]),
    )
    user = type("User", (), {"id": "user-1"})()
    with pytest.raises(StopIteration) as done:
        task_revise(task.id, req, user, svc).send(None)
    assert done.value.value["current_content"] == saved
    assert captured["current_override"] == "用户刚编辑的正文。"
    assert captured["client_base_version"] == 0
    db.expire_all()
    assert db.get(WritingTaskModel, task.id).current_content == saved


def test_revision_claim_rejects_intervening_write_and_preserves_it():
    db, task = setup_task()
    svc = AsyncWritingTaskService(db)
    before = (task.current_content, task.version_no)
    task.current_content = "另一请求保存的正文。"
    task.version_no = 1
    db.commit()
    with pytest.raises(HTTPException) as error:
        svc._claim_revision_state(task, "user-1", before)
    assert error.value.status_code == 409
    db.expire_all()
    assert db.get(WritingTaskModel, task.id).current_content == "另一请求保存的正文。"


def test_revision_supersedes_pending_suggestions_with_events():
    db, task = setup_task()
    svc = AsyncWritingTaskService(db)
    row = WritingSuggestionModel(
        user_id="user-1", task_id=task.id, paragraph_id="paragraph",
        line_index=1, document_type="通知", base_version=0,
        base_content_hash="old", original_content="坚持依法办理。",
        proposed_content="坚持依法依规办理。", instruction="润色", status="pending",
    )
    db.add(row)
    db.commit()
    assert svc._supersede_pending_suggestions(task.id, "user-1")
    db.commit()
    assert row.status == "superseded"
    assert db.scalar(select(WritingSuggestionEventModel).where(
        WritingSuggestionEventModel.suggestion_id == row.id)).action == "supersede"


def test_revise_saves_manual_edit_atomically_and_invalidates_old_suggestions(monkeypatch):
    db, task = setup_task()
    svc = AsyncWritingTaskService(db)
    row = WritingSuggestionModel(
        user_id="user-1", task_id=task.id, paragraph_id="paragraph",
        line_index=1, document_type="通知", base_version=0,
        base_content_hash="old", original_content="坚持依法办理。",
        proposed_content="坚持依法依规办理。", instruction="润色", status="pending",
    )
    db.add(row)
    db.commit()
    manual = task.current_content.replace("按时完成。", "人工补充的安排。")

    async def revise_text(*_args, **_kwargs):
        assert task.current_content != manual  # No write before the model returns.
        return manual.replace("坚持依法办理。", "坚持依法依规办理。")

    monkeypatch.setattr(svc, "_llm_revise_async", revise_text)
    monkeypatch.setattr(svc, "_retrieve", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(svc, "_attachment_context", lambda *_args: "")
    from app.application.writing.paragraph_suggestions import content_hash
    with pytest.raises(StopIteration) as done:
        svc.revise_async(
            task.id, "user-1", "润色", current_override=manual,
            client_base_version=0,
            client_base_hash=content_hash(svc._to_dict(task)["current_content"]),
        ).send(None)
    result = done.value.value
    assert "人工补充的安排" in result["current_content"]
    assert result["version_no"] == 1
    assert result["document_id"]
    assert row.status == "superseded"
    assert "重新获取建议" in result["reply"]


def test_revise_does_not_overwrite_a_change_while_model_runs(monkeypatch):
    db, task = setup_task()
    svc = AsyncWritingTaskService(db)

    async def concurrent_change(*_args, **_kwargs):
        db.execute(update(WritingTaskModel).where(WritingTaskModel.id == task.id).values(
            current_content="另一请求刚保存的正文。", version_no=1))
        db.commit()
        return "模型刚生成的旧版修改。"

    monkeypatch.setattr(svc, "_llm_revise_async", concurrent_change)
    monkeypatch.setattr(svc, "_retrieve", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(svc, "_attachment_context", lambda *_args: "")
    with pytest.raises(HTTPException) as error:
        svc.revise_async(task.id, "user-1", "润色").send(None)
    assert error.value.status_code == 409
    db.expire_all()
    assert db.get(WritingTaskModel, task.id).current_content == "另一请求刚保存的正文。"


def test_service_rechecks_client_base_after_route_check():
    from app.application.writing.paragraph_suggestions import content_hash

    db, task = setup_task()
    svc = AsyncWritingTaskService(db)
    old = svc._to_dict(task)["current_content"]
    task.current_content = "路由检查之后另一请求更新的正文。"
    task.version_no = 1
    db.commit()
    with pytest.raises(HTTPException) as error:
        svc.revise_async(
            task.id, "user-1", "润色", current_override=old,
            client_base_version=0, client_base_hash=content_hash(old),
        ).send(None)
    assert error.value.status_code == 409
    assert task.current_content == "路由检查之后另一请求更新的正文。"


def test_manual_save_checks_base_and_invalidates_pending_suggestions():
    from app.application.writing.paragraph_suggestions import content_hash
    from app.interfaces.writing_tasks import TaskSaveRequest, save_version

    db, task = setup_task()
    svc = AsyncWritingTaskService(db)
    user = type("User", (), {"id": "user-1"})()
    old = svc._to_dict(task)["current_content"]
    row = WritingSuggestionModel(
        user_id="user-1", task_id=task.id, paragraph_id="paragraph",
        line_index=1, document_type="通知", base_version=0,
        base_content_hash=content_hash(task.current_content),
        original_content="坚持依法办理。",
        proposed_content="坚持依法依规办理。", instruction="润色", status="pending",
    )
    db.add(row)
    db.commit()

    saved = save_version(task.id, TaskSaveRequest(
        content=old + "\n人工补充。", base_version=0,
        base_content_hash=content_hash(old)), user, svc)
    assert saved["suggestions_reset"] is True
    assert row.status == "superseded"
    assert saved["version_no"] == 1
    with pytest.raises(HTTPException) as error:
        save_version(task.id, TaskSaveRequest(
            content="旧版客户端覆盖", base_version=0,
            base_content_hash=content_hash(old)), user, svc)
    assert error.value.status_code == 409
    assert "人工补充" in task.current_content


def test_failed_model_does_not_commit_unsaved_manual_edits(monkeypatch):
    from app.application.writing.paragraph_suggestions import content_hash

    db, task = setup_task()
    svc = AsyncWritingTaskService(db)
    original = task.current_content

    async def fail_model(*_args, **_kwargs):
        raise HTTPException(status_code=502, detail="模型不可用")

    monkeypatch.setattr(svc, "_llm_revise_async", fail_model)
    monkeypatch.setattr(svc, "_retrieve", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(svc, "_attachment_context", lambda *_args: "")
    with pytest.raises(HTTPException) as error:
        svc.revise_async(
            task.id, "user-1", "润色", current_override="用户未保存的编辑",
            client_base_version=0, client_base_hash=content_hash(
                svc._to_dict(task)["current_content"]),
        ).send(None)
    assert error.value.status_code == 502
    db.expire_all()
    assert db.get(WritingTaskModel, task.id).current_content == original


def test_metadata_only_revision_saves_title_without_new_body_version(monkeypatch):
    db, task = setup_task()
    svc = AsyncWritingTaskService(db)
    original = task.current_content

    async def same_body(*_args, **_kwargs):
        return original

    monkeypatch.setattr(svc, "_llm_revise_async", same_body)
    monkeypatch.setattr(svc, "_retrieve", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(svc, "_attachment_context", lambda *_args: "")
    with pytest.raises(StopIteration) as done:
        svc.revise_async(task.id, "user-1", "标题改成关于加强普法宣传的通知").send(None)
    result = done.value.value
    assert result["content_changed"] is False
    assert result["version_no"] == 0
    assert result["task_context"]["title"] == "关于加强普法宣传的通知"
    assert "任务信息已更新" in result["reply"]
