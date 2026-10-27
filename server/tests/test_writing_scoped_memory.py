"""Writing memory scope isolation, management rights and prompt injection budget."""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.application.writing.scoped_memory import ScopedWritingMemory
from app.infrastructure.database.base import Base
from app.infrastructure.database.models import identity, writing_memory  # noqa: F401
from app.infrastructure.database.models.identity import UserModel
from app.application.writing.async_task_service import AsyncWritingTaskService
from app.application.writing import prompt_snapshot
from app.infrastructure.database.models.writing_task import WritingTaskModel


def _setup():
    engine = create_engine("sqlite:///:memory:",
                           connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    users = {}
    for name, role, department in (
        ("sys", "developer", "D1"),
        ("dept1", "knowledge_admin", "D1"),
        ("a", "user", "D1"),
        ("b", "user", "D1"),
        ("c", "user", "D2"),
    ):
        user = UserModel(username=name, email=f"{name}@test.local",
                         hashed_password="x", role=role, department_code=department)
        db.add(user)
        users[name] = user
    db.commit()
    return db, ScopedWritingMemory(db), users


def test_memory_visibility_and_write_permissions():
    db, memory, u = _setup()
    public = memory.create(u["sys"].id, "public", "", "文字简洁")
    dept = memory.create(u["dept1"].id, "department", "通知", "本单位通知写明执行节点")
    personal = memory.create(u["a"].id, "personal", "通知", "标题短一些")
    assert {m["id"] for m in memory.list_visible(u["a"].id)} == {
        public["id"], dept["id"], personal["id"]}
    assert {m["id"] for m in memory.list_visible(u["b"].id)} == {
        public["id"], dept["id"]}
    assert {m["id"] for m in memory.list_visible(u["c"].id)} == {public["id"]}
    from fastapi import HTTPException
    import pytest
    with pytest.raises(HTTPException):
        memory.create(u["a"].id, "department", "", "越权")
    with pytest.raises(HTTPException):
        memory.update(u["b"].id, personal["id"], content="越权")
    with pytest.raises(HTTPException):
        memory.delete(u["c"].id, dept["id"])
    assert memory.update(u["dept1"].id, dept["id"], enabled=False)["enabled"] is False
    assert "本单位通知" not in memory.prompt_block(u["a"].id, "通知")
    db.close()


def test_memory_http_routes_enforce_server_side_scope():
    from types import SimpleNamespace
    from fastapi.testclient import TestClient
    from app.main import app
    from app.interfaces.deps import get_current_user
    from app.infrastructure.database import get_db

    db, _memory, users = _setup()
    actor = SimpleNamespace(id=users["a"].id)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: actor
    base = "/api/v1/writing/memories"
    try:
        client = TestClient(app)
        assert client.post(base, json={"scope": "public", "content": "越权"}).status_code == 403
        created = client.post(base, json={"scope": "personal", "content": "句子简短"})
        assert created.status_code == 200, created.text
        memory_id = created.json()["id"]
        actor.id = users["b"].id
        assert all(item["id"] != memory_id for item in client.get(base).json()["items"])
        assert client.patch(f"{base}/{memory_id}", json={"enabled": False}).status_code == 404
        actor.id = users["a"].id
        assert client.patch(f"{base}/{memory_id}", json={"enabled": False}).json()["enabled"] is False
        assert client.delete(f"{base}/{memory_id}").json() == {"deleted": True}
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_user, None)
        db.close()


def test_memory_prompt_is_genre_scoped_bounded_and_ordered():
    db, memory, u = _setup()
    memory.create(u["sys"].id, "public", "", "公共风格")
    memory.create(u["dept1"].id, "department", "通知", "科室通知风格")
    memory.create(u["a"].id, "personal", "通知", "个人通知风格")
    memory.create(u["a"].id, "personal", "致辞稿", "只属于致辞稿")
    text = memory.prompt_block(u["a"].id, "通知", budget=200)
    assert "只属于致辞稿" not in text
    assert text.index("公共风格") < text.index("科室通知风格") < text.index("个人通知风格")
    assert "不得把记忆中的事实" in text
    assert "科室通知风格" not in memory.prompt_block(u["c"].id, "通知")
    db.close()


def test_draft_prompt_reads_only_current_users_scoped_memories():
    db, memory, u = _setup()
    memory.create(u["sys"].id, "public", "", "公共简洁写法")
    memory.create(u["dept1"].id, "department", "通知", "本科室通知先写责任")
    memory.create(u["c"].id, "personal", "通知", "其他科室用户的秘密风格")
    task = WritingTaskModel(user_id=u["a"].id,
                            context={"document_type": "通知", "title": "测试通知"},
                            current_content="", version_no=0, status="editing")
    db.add(task)
    db.commit()
    prompt_snapshot.enter_task(task.id, u["a"].id)
    service = AsyncWritingTaskService(db, rag=None)

    prompt = service._draft_prompt("写通知", [], None, u["a"].id, style_card="")

    assert "公共简洁写法" in prompt
    assert "本科室通知先写责任" in prompt
    assert "其他科室用户的秘密风格" not in prompt
    db.close()
