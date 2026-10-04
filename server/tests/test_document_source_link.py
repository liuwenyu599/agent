"""历史记录里的文档要能回到「当初生成它的写作台 / 对话」。

桌面端在历史记录里点一篇文档，期望回到**写作台**并看到当时的对话，而不是去一个
只能改正文的文档页。写作台恢复任务时会把正文、版本链和 ``task_context.history``
（当时的对话）一起带回来，所以服务端必须在文档上回带来源：

- ``task_id``：反查 ``writing_tasks.document_id``（写作台起草 / 保存版本时绑定）；
- ``session_id``：对话里生成的文档记下的来源会话（``my_documents.session_id``）。

这两个键一旦被改掉或漏传，桌面端就会退化成「跳到文档页、对话全丢」——
而界面上没有任何报错，用户只会觉得「历史记录点进去就只剩正文了」。
"""
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.domain.identity.entities import ROLE_USER, User
from app.infrastructure.database.base import Base
from app.infrastructure.database.models.document import MyDocumentModel
from app.infrastructure.database.models.identity import UserModel
from app.infrastructure.database.models.writing_task import WritingTaskModel
from app.infrastructure.database.session import SessionLocal, engine
from app.interfaces.deps import get_current_user
from app.main import app

Base.metadata.create_all(bind=engine)

BASE = "/api/v1"

USER = User(username="docowner", email="docowner@test.local", hashed_password="x",
            id="u-doc-1", role=ROLE_USER, department_code="bangongshi")


def _ensure_user(db):
    if db.get(UserModel, USER.id) is None:
        db.add(UserModel(id=USER.id, username=USER.username, email=USER.email,
                         hashed_password="x", role=USER.role,
                         department_code=USER.department_code, is_active=True))
        db.commit()


def _doc(db, title, session_id=None):
    d = MyDocumentModel(user_id=USER.id, title=title, doc_type="通知",
                        session_id=session_id, current_version=1, status="draft")
    db.add(d)
    db.commit()
    db.refresh(d)
    return d


def _task(db, document_id, session_id=None, updated_hours=0):
    from datetime import timedelta

    from app.core.timeutil import now_local
    t = WritingTaskModel(user_id=USER.id, document_id=document_id,
                         session_id=session_id, context={"history": [
                             {"role": "user", "content": "写一份申报通知"}]},
                         current_content="正文", status="editing",
                         updated_at=now_local() + timedelta(hours=updated_hours))
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


@pytest.fixture()
def env():
    db = SessionLocal()
    try:
        _ensure_user(db)
        yield db
        db.query(WritingTaskModel).delete()
        db.query(MyDocumentModel).delete()
        db.commit()
    finally:
        db.close()


@pytest.fixture(autouse=True)
def _clear_auth_override():
    yield
    app.dependency_overrides.pop(get_current_user, None)


def _client():
    app.dependency_overrides[get_current_user] = lambda: USER
    return TestClient(app)


def test_document_list_carries_source_task(env):
    """列表必须下发 task_id，历史记录才知道该跳哪个写作任务。"""
    db = env
    doc = _doc(db, "写作台生成的通知")
    task = _task(db, doc.id)
    with _client() as c:
        r = c.get(f"{BASE}/documents")
    assert r.status_code == 200, r.text
    row = next(x for x in r.json()["items"] if x["id"] == doc.id)
    assert row["task_id"] == task.id


def test_document_detail_carries_source_task(env):
    """详情同样要带 task_id：弹窗预览后正是按它跳写作台。"""
    db = env
    doc = _doc(db, "带任务的文档")
    task = _task(db, doc.id)
    with _client() as c:
        r = c.get(f"{BASE}/documents/{doc.id}")
    assert r.status_code == 200, r.text
    assert r.json()["task_id"] == task.id


def test_chat_generated_document_carries_session(env):
    """对话里生成的文档没有 task，但必须带回 session_id，否则找不到原对话。"""
    db = env
    doc = _doc(db, "对话生成的草稿", session_id="s-chat-1")
    with _client() as c:
        r = c.get(f"{BASE}/documents/{doc.id}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["session_id"] == "s-chat-1"
    assert not body["task_id"]


def test_document_without_source_has_null_task_id(env):
    """手工新建等没有来源的文档：task_id 为 null，桌面端据此退回文档页。"""
    db = env
    doc = _doc(db, "手工新建的文档")
    with _client() as c:
        r = c.get(f"{BASE}/documents/{doc.id}")
    assert r.status_code == 200, r.text
    assert r.json()["task_id"] is None


def test_multiple_tasks_on_one_document_pick_latest(env):
    """同一文档被多次快照时取最近更新的任务，避免回到一份旧对话。"""
    db = env
    doc = _doc(db, "多次快照的文档")
    _task(db, doc.id, updated_hours=0)
    latest = _task(db, doc.id, updated_hours=5)
    with _client() as c:
        r = c.get(f"{BASE}/documents/{doc.id}")
    assert r.json()["task_id"] == latest.id
