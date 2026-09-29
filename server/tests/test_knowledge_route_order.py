"""知识库路由遮蔽回归测试。

验证：FastAPI 按注册顺序匹配，通配路由 /{kb_id} 不能抢先吞掉
/batch-tasks、/batch-tasks/{task_id}、/queue-status 三个具名端点。

运行方式（在 server/ 目录下，使用 Python 3.11 解析器）：
    AI_PROVIDER=mock python -m pytest tests/test_knowledge_route_order.py -v
"""
import os
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("AI_PROVIDER", "mock")
os.environ.setdefault("DATA_DIR", f"/tmp/test-kbroute-{uuid.uuid4().hex[:8]}")
os.environ.setdefault("DATABASE_URL", f"sqlite:////tmp/test-kbroute-{uuid.uuid4().hex[:8]}.db")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.infrastructure.database import Base, engine  # noqa: E402

Base.metadata.create_all(bind=engine)

BASE = "/api/v1"


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _hdr(token):
    return {"Authorization": f"Bearer {token}"}


def _dev_token(client):
    """取得系统管理员令牌（复用 test_password_policy 的思路）。"""
    r = client.post(f"{BASE}/auth/register-first", json={
        "username": "kbroutedev", "email": "kbroutedev@test.local",
        "password": "Passw0rd!2026", "real_name": "系统管理员",
    })
    if r.status_code == 200:
        return r.json()["access_token"]

    from sqlalchemy import select

    from app.core.security import create_access_token
    from app.infrastructure.database import SessionLocal
    from app.infrastructure.database.models.identity import UserModel

    db = SessionLocal()
    try:
        row = db.scalar(select(UserModel).where(
            UserModel.role.in_(("developer", "admin"))))
        assert row is not None, "库中没有可用的系统管理员账号"
        return create_access_token(
            {"sub": row.id, "username": row.username, "role": row.role})
    finally:
        db.close()


@pytest.fixture(scope="module")
def dev_token(client):
    return _dev_token(client)


@pytest.fixture(scope="module")
def real_kb_id(client, dev_token):
    """创建一个真实知识库，返回其 id 用于 /{kb_id} 回归测试。"""
    r = client.post(f"{BASE}/knowledge/create", json={
        "name": f"kbroute_{uuid.uuid4().hex[:6]}",
        "description": "route order test",
        "kb_type": "personal",
    }, headers=_hdr(dev_token))
    assert r.status_code == 200, r.text
    return r.json()["id"]


# ----------------------------------------------------- 关键回归：具名端点不被通配路由吃掉

def test_batch_tasks_not_shadowed_by_kb_id(client, dev_token):
    r = client.get(f"{BASE}/knowledge/batch-tasks", headers=_hdr(dev_token))
    assert r.status_code == 200, r.text
    body = r.text
    assert "Knowledge base not found" not in body
    assert "tasks" in r.json()


def test_batch_task_by_id_not_shadowed_by_kb_id(client, dev_token):
    # 不存在的 task_id 应返回 Task not found（由具名路由处理），而非被 /{kb_id} 吞掉
    r = client.get(f"{BASE}/knowledge/batch-tasks/nonexistent-id-xyz",
                   headers=_hdr(dev_token))
    assert r.status_code == 404
    assert "Knowledge base not found" not in r.text
    assert "Task not found" in r.text


def test_queue_status_not_shadowed_by_kb_id(client, dev_token):
    r = client.get(f"{BASE}/knowledge/queue-status", headers=_hdr(dev_token))
    assert r.status_code == 200, r.text
    assert "Knowledge base not found" not in r.text
    data = r.json()
    assert "queue_size" in data
    assert "worker_alive" in data


# ----------------------------------------------------- 回归：/{kb_id} 自身功能未被移动破坏

def test_existing_kb_still_resolvable(client, dev_token, real_kb_id):
    r = client.get(f"{BASE}/knowledge/{real_kb_id}", headers=_hdr(dev_token))
    assert r.status_code == 200, r.text
    assert r.json()["id"] == real_kb_id


def test_missing_kb_still_404(client, dev_token):
    r = client.get(f"{BASE}/knowledge/does-not-exist-xyz", headers=_hdr(dev_token))
    assert r.status_code == 404
    assert "Knowledge base not found" in r.text



# ----------------------------------------------------- 知识问答：具名路由 + 会话落库

def test_knowledge_ask_creates_history_session(client, dev_token):
    r = client.post(
        f"{BASE}/knowledge/ask",
        headers=_hdr(dev_token),
        json={"message": "现有知识库中有哪些司法行政工作要求？"},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["session_id"]
    assert "reply" in data
    assert isinstance(data["sources"], list)

    sessions = client.get(
        f"{BASE}/knowledge/ask/sessions", headers=_hdr(dev_token))
    assert sessions.status_code == 200, sessions.text
    assert any(x["id"] == data["session_id"] for x in sessions.json())


def test_knowledge_ask_rejects_blank_question(client, dev_token):
    r = client.post(
        f"{BASE}/knowledge/ask",
        headers=_hdr(dev_token),
        json={"message": "   "},
    )
    assert r.status_code == 400
