"""写作参考材料模块契约测试（TC-057~TC-062）。

覆盖 §7.1 里 references 模块 11 条此前零测试的端点。

这个模块的核心风险不是功能写错，而是**归属**——任务级材料是「用户本人
的佐证材料，不进知识库」，一旦 list/delete 漏了 user_id 过滤，就是
跨用户读材料。模板级材料反过来只能管理员写、所有人可读。两条线方向相反，
必须分开锁。

另有一条链路值得盯：/task/{ref_id}/promote 会把任务材料转进知识库，
kb_id 来自客户端入参，是这条链路上唯一的外部输入口。
"""
import os
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("AI_PROVIDER", "mock")
os.environ.setdefault("DATA_DIR", f"/tmp/test-ref-{uuid.uuid4().hex[:8]}")
os.environ.setdefault("DATABASE_URL", f"sqlite:////tmp/test-ref-{uuid.uuid4().hex[:8]}.db")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.infrastructure.database import Base, engine  # noqa: E402

Base.metadata.create_all(bind=engine)

BASE = "/api/v1"
DEPT_FUYI = "行政复议科"
DEPT_RENSHI = "人事科"


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

    def reg(username, role, dept):
        rr = client.post(f"{BASE}/auth/register", json={
            "username": username, "email": f"{username}@test.local",
            "password": "Passw0rd!2026", "real_name": username,
            "department": dept, "role": role,
        }, headers=_hdr(out["developer"]))
        assert rr.status_code == 200, rr.text
        tok = client.post(f"{BASE}/auth/login", json={
            "username": username, "password": "Passw0rd!2026"}).json()["access_token"]
        changed = client.post(f"{BASE}/auth/change-password", json={
            "old_password": "Passw0rd!2026", "new_password": "Changed@2026",
            "confirm_password": "Changed@2026"}, headers=_hdr(tok))
        assert changed.status_code == 200, changed.text
        return tok

    out["user_a"] = reg("refusera", "user", DEPT_FUYI)
    out["user_b"] = reg("refuserb", "user", DEPT_RENSHI)
    return out


@pytest.fixture(scope="module")
def template_id(client, users):
    r = client.post(f"{BASE}/templates/", headers=_hdr(users["developer"]), json={
        "name": f"参考材料宿主模板_{uuid.uuid4().hex[:6]}",
        "category": "通用", "content_template": "正文",
    })
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _add_text_ref(client, token, text=None):
    r = client.post(f"{BASE}/references/task/text", headers=_hdr(token),
                    json={"text": text or f"材料内容 {uuid.uuid4().hex[:6]}",
                          "name": f"材料_{uuid.uuid4().hex[:4]}"})
    assert r.status_code == 200, r.text
    return r.json()["reference"]


# ------------------------------------------------ TC-057 鉴权：未登录一律 401

@pytest.mark.parametrize("method,path", [
    ("get", "/references/task"),
    ("post", "/references/task/text"),
    ("post", "/references/task/url"),
    ("delete", "/references/task/whatever"),
    ("get", "/references/template/whatever"),
    ("post", "/references/template/whatever/text"),
    ("post", "/references/template/whatever/url"),
    ("delete", "/references/template/refs/whatever"),
])
def test_endpoints_require_auth(client, method, path):
    r = getattr(client, method)(f"{BASE}{path}")
    assert r.status_code in (401, 403), r.text


# ------------------------------------------------ TC-058 模板级：管理员写、所有人读

def test_template_refs_readable_by_normal_user(client, users, template_id):
    r = client.get(f"{BASE}/references/template/{template_id}",
                   headers=_hdr(users["user_a"]))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["template_id"] == template_id
    assert "references" in body


@pytest.mark.parametrize("path", ["/text", "/url"])
def test_template_ref_write_requires_admin(client, users, template_id, path):
    payload = ({"name": "n", "text": "正文"} if path == "/text"
               else {"url": "https://example.gov.cn/a"})
    r = client.post(f"{BASE}/references/template/{template_id}{path}",
                    headers=_hdr(users["user_a"]), json=payload)
    assert r.status_code == 403, r.text


def test_template_ref_delete_requires_admin(client, users):
    r = client.delete(f"{BASE}/references/template/refs/no-such-ref",
                      headers=_hdr(users["user_a"]))
    assert r.status_code == 403, r.text


def test_template_ref_crud_by_admin(client, users, template_id):
    added = client.post(f"{BASE}/references/template/{template_id}/text",
                        headers=_hdr(users["developer"]),
                        json={"name": "管理员材料", "text": "模板级材料正文"})
    assert added.status_code == 200, added.text
    ref_id = added.json()["reference"]["id"]

    listed = client.get(f"{BASE}/references/template/{template_id}",
                        headers=_hdr(users["developer"]))
    assert any(x["id"] == ref_id for x in listed.json()["references"])

    deleted = client.delete(f"{BASE}/references/template/refs/{ref_id}",
                            headers=_hdr(users["developer"]))
    assert deleted.status_code == 200, deleted.text


def test_template_refs_of_unknown_template_is_404(client, users):
    r = client.get(f"{BASE}/references/template/no-such-template",
                   headers=_hdr(users["user_a"]))
    assert r.status_code == 404


# ------------------------------------------------ TC-059 任务级：只归本人

def test_task_refs_are_scoped_to_owner(client, users):
    ref = _add_text_ref(client, users["user_a"])
    mine = client.get(f"{BASE}/references/task", headers=_hdr(users["user_a"]))
    assert mine.status_code == 200, mine.text
    assert any(x["id"] == ref["id"] for x in mine.json()["references"])

    theirs = client.get(f"{BASE}/references/task", headers=_hdr(users["user_b"]))
    assert theirs.status_code == 200, theirs.text
    assert all(x["id"] != ref["id"] for x in theirs.json()["references"]), \
        "用户 B 看到了用户 A 的任务材料——list 漏了 user_id 过滤"


def test_delete_other_users_task_ref_is_denied(client, users):
    ref = _add_text_ref(client, users["user_a"])
    r = client.delete(f"{BASE}/references/task/{ref['id']}",
                      headers=_hdr(users["user_b"]))
    assert r.status_code in (403, 404), r.text
    # 本人的材料仍在
    assert any(x["id"] == ref["id"] for x in
               client.get(f"{BASE}/references/task",
                          headers=_hdr(users["user_a"])).json()["references"])


def test_delete_own_task_ref(client, users):
    ref = _add_text_ref(client, users["user_a"])
    r = client.delete(f"{BASE}/references/task/{ref['id']}",
                      headers=_hdr(users["user_a"]))
    assert r.status_code == 200, r.text
    assert all(x["id"] != ref["id"] for x in
               client.get(f"{BASE}/references/task",
                          headers=_hdr(users["user_a"])).json()["references"])


# ------------------------------------------------ TC-060 入参校验

def test_empty_text_is_rejected(client, users):
    r = client.post(f"{BASE}/references/task/text", headers=_hdr(users["user_a"]),
                    json={"text": "   "})
    assert r.status_code == 400, r.text


def test_bad_url_is_rejected(client, users):
    r = client.post(f"{BASE}/references/task/url", headers=_hdr(users["user_a"]),
                    json={"url": "not-a-url"})
    assert r.status_code == 400, r.text


def test_task_ref_with_unknown_template_is_404(client, users):
    r = client.post(f"{BASE}/references/task/text", headers=_hdr(users["user_a"]),
                    json={"text": "正文", "template_id": "no-such-template"})
    assert r.status_code == 404


# ------------------------------------------------ TC-061 promote：kb_id 来自客户端

def test_promote_unknown_kb_is_404(client, users):
    ref = _add_text_ref(client, users["user_a"])
    r = client.post(f"{BASE}/references/task/{ref['id']}/promote",
                    headers=_hdr(users["user_a"]), json={"kb_id": "no-such-kb"})
    assert r.status_code == 404, r.text


def test_promote_other_users_ref_is_denied(client, users):
    ref = _add_text_ref(client, users["user_a"])
    r = client.post(f"{BASE}/references/task/{ref['id']}/promote",
                    headers=_hdr(users["user_b"]), json={"kb_id": "whatever"})
    assert r.status_code in (403, 404), r.text


def test_promote_into_personal_kb_of_another_user_is_denied(client, users):
    """个人库归属必须校验：否则能把自己的材料塞进别人的个人库。"""
    kb = client.post(f"{BASE}/knowledge/create", headers=_hdr(users["user_a"]), json={
        "name": f"refpersonal_{uuid.uuid4().hex[:6]}",
        "description": "personal", "kb_type": "personal"})
    assert kb.status_code == 200, kb.text
    kb_id = kb.json()["id"]

    ref = _add_text_ref(client, users["user_a"])
    r = client.post(f"{BASE}/references/task/{ref['id']}/promote",
                    headers=_hdr(users["user_b"]), json={"kb_id": kb_id})
    assert r.status_code in (403, 404), r.text
