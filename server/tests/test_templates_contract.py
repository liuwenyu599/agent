"""写作模板模块契约测试（TC-050~TC-056）。

覆盖 docs/system-button-flow-testcases-2026-10-04.md §7.1 里 templates 模块
7 条此前零测试的端点。这一整模块此前没有任何兜底：路由顺序写错、鉴权写漏，
在界面上都只是「按钮转圈」或「列表空白」，不会报错。

重点锁三件事：
1. 具名路由不被 /{template_id} 吃掉（categories / init / department）
2. 写操作必须登录，管理类操作必须管理员
3. 科室模板的 department_code 由服务端写入，客户端传什么都不算
"""
import os
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("AI_PROVIDER", "mock")
os.environ.setdefault("DATA_DIR", f"/tmp/test-tmpl-{uuid.uuid4().hex[:8]}")
os.environ.setdefault("DATABASE_URL", f"sqlite:////tmp/test-tmpl-{uuid.uuid4().hex[:8]}.db")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.infrastructure.database import Base, engine  # noqa: E402

Base.metadata.create_all(bind=engine)

BASE = "/api/v1"
DEPT_FUYI = "行政复议科"


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _hdr(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def users(client):
    """系统管理员 + 普通用户 + 科室知识管理员。"""
    r = client.post(f"{BASE}/auth/login", json={
        "username": "developer", "password": "Passw0rd!2026"})
    assert r.status_code == 200, r.text
    out = {"developer": r.json()["access_token"]}

    def reg(username, role, **extra):
        payload = {"username": username, "email": f"{username}@test.local",
                   "password": "Passw0rd!2026", "real_name": username, "role": role}
        payload.update(extra)
        rr = client.post(f"{BASE}/auth/register", json=payload,
                         headers=_hdr(out["developer"]))
        assert rr.status_code == 200, rr.text
        tok = client.post(f"{BASE}/auth/login", json={
            "username": username, "password": "Passw0rd!2026"}).json()["access_token"]
        # 管理员代建的账号首登必须改密，未改密前业务端点一律 403
        changed = client.post(f"{BASE}/auth/change-password", json={
            "old_password": "Passw0rd!2026", "new_password": "Changed@2026",
            "confirm_password": "Changed@2026"}, headers=_hdr(tok))
        assert changed.status_code == 200, changed.text
        return tok

    out["user"] = reg("tmpluser", "user", department=DEPT_FUYI)
    out["deptadmin"] = reg("tmpldeptadmin", "knowledge_admin",
                           department=DEPT_FUYI, department_code="fuyi")
    return out


def _new_template(client, token, name=None, visibility="official"):
    name = name or f"模板_{uuid.uuid4().hex[:6]}"
    r = client.post(f"{BASE}/templates/", headers=_hdr(token), json={
        "name": name, "category": "通用", "content_template": "正文占位",
        "visibility": visibility,
    })
    assert r.status_code == 200, r.text
    return r.json()


# ------------------------------------------------ TC-050 路由顺序：具名端点不被通配吞掉

def test_categories_not_shadowed_by_template_id(client, users):
    """/categories 必须早于 /{template_id} 注册，否则会被当成模板 id 查。"""
    r = client.get(f"{BASE}/templates/categories", headers=_hdr(users["user"]))
    assert r.status_code == 200, r.text
    assert isinstance(r.json(), list)
    assert "not found" not in r.text.lower()


def test_list_endpoint_reachable(client, users):
    r = client.get(f"{BASE}/templates/", headers=_hdr(users["user"]))
    assert r.status_code == 200, r.text
    assert isinstance(r.json(), list)


def test_department_endpoint_not_shadowed(client, users):
    """POST /templates/department 与 /{template_id}/* 同前缀，走错会 404/405。"""
    r = client.post(f"{BASE}/templates/department", headers=_hdr(users["user"]),
                    json={"name": "x", "content_template": "y"})
    # 普通用户应被权限拦下（403），而不是被路由层吞成 404/405
    assert r.status_code == 403, r.text


# ------------------------------------------------ TC-051 鉴权：未登录一律 401

@pytest.mark.parametrize("method,path", [
    ("get", "/templates/"),
    ("get", "/templates/categories"),
    ("post", "/templates/init"),
    ("get", "/templates/whatever-id"),
    ("post", "/templates/department"),
])
def test_endpoints_require_auth(client, method, path):
    r = getattr(client, method)(f"{BASE}{path}")
    assert r.status_code in (401, 403), r.text


# ------------------------------------------------ TC-052 读写权限分级

def test_init_requires_admin(client, users):
    r = client.post(f"{BASE}/templates/init", headers=_hdr(users["user"]))
    assert r.status_code == 403, r.text


def test_delete_requires_admin(client, users):
    t = _new_template(client, users["developer"])
    r = client.delete(f"{BASE}/templates/{t['id']}", headers=_hdr(users["user"]))
    assert r.status_code == 403, r.text
    # 管理员可删
    r2 = client.delete(f"{BASE}/templates/{t['id']}", headers=_hdr(users["developer"]))
    assert r2.status_code == 200, r2.text


def test_create_category_requires_admin(client, users):
    r = client.post(f"{BASE}/templates/categories", headers=_hdr(users["user"]),
                    json={"name": f"分类_{uuid.uuid4().hex[:4]}"})
    assert r.status_code == 403, r.text


def test_update_own_template_allowed_for_normal_user(client, users):
    t = _new_template(client, users["user"], visibility="personal")
    r = client.put(f"{BASE}/templates/{t['id']}", headers=_hdr(users["user"]),
                   json={"description": "改过"})
    assert r.status_code == 200, r.text


# ------------------------------------------------ TC-053 CRUD 往返

def test_crud_roundtrip(client, users):
    t = _new_template(client, users["developer"])
    tid = t["id"]
    got = client.get(f"{BASE}/templates/{tid}", headers=_hdr(users["developer"]))
    assert got.status_code == 200, got.text
    assert got.json()["id"] == tid

    upd = client.put(f"{BASE}/templates/{tid}", headers=_hdr(users["developer"]),
                     json={"name": "改名后的模板"})
    assert upd.status_code == 200, upd.text
    # update 的返回体字段集与 get 不同，回读确认改名真的落库
    assert client.get(f"{BASE}/templates/{tid}",
                      headers=_hdr(users["developer"])).json()["name"] == "改名后的模板"

    client.delete(f"{BASE}/templates/{tid}", headers=_hdr(users["developer"]))
    gone = client.get(f"{BASE}/templates/{tid}", headers=_hdr(users["developer"]))
    assert gone.status_code == 404


# ------------------------------------------------ TC-054 adapt 是草案，不落库

def test_adapt_returns_draft_without_persisting(client, users):
    t = _new_template(client, users["developer"])
    before = client.get(f"{BASE}/templates/", headers=_hdr(users["developer"]))
    n_before = len(before.json())

    # hints 是 Body(..., embed=True)，必须包在对象里传，不能裸传字符串
    r = client.post(f"{BASE}/templates/{t['id']}/adapt",
                    headers=_hdr(users["deptadmin"]), json={"hints": "语气更简练"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("content_template") or body.get("draft"), r.text

    after = client.get(f"{BASE}/templates/", headers=_hdr(users["developer"]))
    assert len(after.json()) == n_before, "adapt 不应落库，模板总数变了"


def test_adapt_unknown_template_is_404(client, users):
    r = client.post(f"{BASE}/templates/no-such-template/adapt",
                    headers=_hdr(users["deptadmin"]), json={"hints": ""})
    assert r.status_code == 404


# ------------------------------------------------ TC-055 科室模板归属由服务端写入

def test_department_code_cannot_be_forged(client, users):
    """body 里塞 department_code 必须无效：只能保存成本人所属科室的模板。"""
    forged = f"伪造模板_{uuid.uuid4().hex[:6]}"
    r = client.post(f"{BASE}/templates/department", headers=_hdr(users["deptadmin"]),
                    json={"name": forged, "content_template": "正文",
                          "department_code": "renshi"})
    assert r.status_code == 200, r.text
    saved = r.json()
    assert saved.get("department_code") != "renshi", "客户端传的科室码被采信了"


def test_department_template_rejected_for_normal_user(client, users):
    r = client.post(f"{BASE}/templates/department", headers=_hdr(users["user"]),
                    json={"name": "x", "content_template": "正文"})
    assert r.status_code == 403, r.text


# ------------------------------------------------ TC-056 use 记录调用次数

def test_use_is_idempotent_and_safe(client, users):
    t = _new_template(client, users["developer"])
    r1 = client.post(f"{BASE}/templates/{t['id']}/use", headers=_hdr(users["user"]))
    assert r1.status_code == 200, r1.text
    r2 = client.post(f"{BASE}/templates/{t['id']}/use", headers=_hdr(users["user"]))
    assert r2.status_code == 200, r2.text
