"""chat 会话管理契约测试（TC-080~TC-082）。

覆盖 §7.1 里 chat 的会话管理端点：
    GET    /chat/sessions
    GET    /chat/sessions/{session_id}/messages
    PATCH  /chat/sessions/{session_id}
    DELETE /chat/sessions/{session_id}
    GET    /chat/admin/sessions
    DELETE /chat/admin/sessions/{session_id}

这一组是安全面：会话里存的是用户与 AI 的全部往来，删除他人会话更是直接
的数据销毁。归属判断写在每个端点的 service 分支里（get_for_user 带
user_id），任一条漏掉就是跨用户读/删，而路由层没有统一拦截器兜底。

注意本文件**刻意不动** POST /chat/send 的语义验证——那是 AI 链路，
归 test_chat_quality_retry 等文件管；这里只把它当作「造一个会话」的手段。
"""
import os
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("AI_PROVIDER", "mock")
os.environ.setdefault("DATA_DIR", f"/tmp/test-chatsess-{uuid.uuid4().hex[:8]}")
os.environ.setdefault("DATABASE_URL", f"sqlite:////tmp/test-chatsess-{uuid.uuid4().hex[:8]}.db")

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


@pytest.fixture(scope="module")
def users(client):
    r = client.post(f"{BASE}/auth/login", json={
        "username": "developer", "password": "Passw0rd!2026"})
    assert r.status_code == 200, r.text
    out = {"developer": r.json()["access_token"]}

    def reg(username):
        rr = client.post(f"{BASE}/auth/register", json={
            "username": username, "email": f"{username}@test.local",
            "password": "Passw0rd!2026", "real_name": username,
            "department": "行政复议科", "role": "user",
        }, headers=_hdr(out["developer"]))
        assert rr.status_code == 200, rr.text
        tok = client.post(f"{BASE}/auth/login", json={
            "username": username, "password": "Passw0rd!2026"}).json()["access_token"]
        changed = client.post(f"{BASE}/auth/change-password", json={
            "old_password": "Passw0rd!2026", "new_password": "Changed@2026",
            "confirm_password": "Changed@2026"}, headers=_hdr(tok))
        assert changed.status_code == 200, changed.text
        return tok

    out["user_a"] = reg("csusera")
    out["user_b"] = reg("csuserb")
    return out


def _new_session(client, token):
    r = client.post(f"{BASE}/chat/send", headers=_hdr(token),
                    json={"message": "帮我拟一份会议通知"})
    assert r.status_code == 200, r.text
    return r.json()["session_id"]


@pytest.fixture(scope="module")
def session_a(client, users):
    return _new_session(client, users["user_a"])


# ------------------------------------------------ TC-080 鉴权与管理员端点

@pytest.mark.parametrize("method,path", [
    ("get", "/chat/sessions"),
    ("get", "/chat/sessions/whatever/messages"),
    ("patch", "/chat/sessions/whatever"),
    ("delete", "/chat/sessions/whatever"),
    ("get", "/chat/admin/sessions"),
    ("delete", "/chat/admin/sessions/whatever"),
])
def test_endpoints_require_auth(client, method, path):
    r = getattr(client, method)(f"{BASE}{path}")
    assert r.status_code in (401, 403), r.text


def test_admin_sessions_requires_admin(client, users):
    r = client.get(f"{BASE}/chat/admin/sessions", headers=_hdr(users["user_a"]))
    assert r.status_code == 403, r.text


def test_admin_delete_session_requires_admin(client, users, session_a):
    r = client.delete(f"{BASE}/chat/admin/sessions/{session_a}",
                      headers=_hdr(users["user_a"]))
    assert r.status_code == 403, r.text


def test_admin_sessions_lists_all_users(client, users, session_a):
    r = client.get(f"{BASE}/chat/admin/sessions", headers=_hdr(users["developer"]))
    assert r.status_code == 200, r.text
    body = r.json()
    assert "total" in body and "data" in body
    assert any(x["id"] == session_a for x in body["data"])


def test_admin_delete_unknown_session_is_404(client, users):
    r = client.delete(f"{BASE}/chat/admin/sessions/no-such-session",
                      headers=_hdr(users["developer"]))
    assert r.status_code == 404


# ------------------------------------------------ TC-081 归属：会话只归本人

def test_list_sessions_is_scoped_to_owner(client, users, session_a):
    mine = client.get(f"{BASE}/chat/sessions", headers=_hdr(users["user_a"]))
    assert mine.status_code == 200, mine.text
    assert any(x["id"] == session_a for x in mine.json())

    theirs = client.get(f"{BASE}/chat/sessions", headers=_hdr(users["user_b"]))
    assert theirs.status_code == 200, theirs.text
    assert all(x["id"] != session_a for x in theirs.json()), \
        "用户 B 的会话列表里出现了用户 A 的会话"


def test_other_user_cannot_read_messages(client, users, session_a):
    r = client.get(f"{BASE}/chat/sessions/{session_a}/messages",
                   headers=_hdr(users["user_b"]))
    assert r.status_code == 404, r.text


def test_other_user_cannot_rename_session(client, users, session_a):
    r = client.patch(f"{BASE}/chat/sessions/{session_a}",
                     headers=_hdr(users["user_b"]), json={"title": "被改名"})
    assert r.status_code == 404, r.text


def test_other_user_cannot_delete_session(client, users, session_a):
    r = client.delete(f"{BASE}/chat/sessions/{session_a}",
                      headers=_hdr(users["user_b"]))
    assert r.status_code == 404, r.text
    # 本人仍能读到
    assert client.get(f"{BASE}/chat/sessions/{session_a}/messages",
                      headers=_hdr(users["user_a"])).status_code == 200


def test_owner_reads_own_messages(client, users, session_a):
    r = client.get(f"{BASE}/chat/sessions/{session_a}/messages",
                   headers=_hdr(users["user_a"]))
    assert r.status_code == 200, r.text
    msgs = r.json()
    assert isinstance(msgs, list) and msgs
    assert {m["role"] for m in msgs} & {"user", "assistant"}


# ------------------------------------------------ TC-082 改名校验与删除生效

def test_rename_session(client, users, session_a):
    r = client.patch(f"{BASE}/chat/sessions/{session_a}",
                     headers=_hdr(users["user_a"]), json={"title": "会议通知会话"})
    assert r.status_code == 200, r.text
    assert r.json()["title"] == "会议通知会话"
    assert any(x["id"] == session_a and x["title"] == "会议通知会话"
               for x in client.get(f"{BASE}/chat/sessions",
                                   headers=_hdr(users["user_a"])).json())


def test_rename_rejects_blank_title(client, users, session_a):
    r = client.patch(f"{BASE}/chat/sessions/{session_a}",
                     headers=_hdr(users["user_a"]), json={"title": "   "})
    assert r.status_code == 422, r.text


def test_rename_rejects_overlong_title(client, users, session_a):
    r = client.patch(f"{BASE}/chat/sessions/{session_a}",
                     headers=_hdr(users["user_a"]), json={"title": "标" * 201})
    assert r.status_code == 422, r.text


def test_delete_session_removes_it_from_list(client, users):
    sid = _new_session(client, users["user_b"])
    assert any(x["id"] == sid for x in
               client.get(f"{BASE}/chat/sessions", headers=_hdr(users["user_b"])).json())

    r = client.delete(f"{BASE}/chat/sessions/{sid}", headers=_hdr(users["user_b"]))
    assert r.status_code == 200, r.text
    assert all(x["id"] != sid for x in
               client.get(f"{BASE}/chat/sessions", headers=_hdr(users["user_b"])).json())
