"""登录支持「用户名或邮箱」：含 @ 的标识符按邮箱查账号（email 列唯一）。

覆盖：邮箱可登录、大小写不敏感、用户名路径不受影响、错误密码仍 401。
依赖 conftest 种子：本模块的开发者账号为 maildev / Passw0rd!2026。
"""
import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app

BASE = "/api/v1"
PWD = "Passw0rd!2026"
SEED_DEV = "maildev"


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def dev_token(client):
    r = client.post(f"{BASE}/auth/login",
                    json={"username": SEED_DEV, "password": PWD})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _mk(client, dev_token):
    """经管理端创建一个普通用户，返回 (username, email)。"""
    suffix = uuid.uuid4().hex[:8]
    username, email = f"mail{suffix}", f"mail{suffix}@bysfj.local"
    r = client.post(f"{BASE}/users/", json={
        "username": username, "email": email, "password": PWD,
        "real_name": "邮箱登录", "department_code": "bangongshi", "role": "user",
    }, headers={"Authorization": f"Bearer {dev_token}"})
    assert r.status_code in (200, 201), r.text
    return username, email


def test_login_with_email(client, dev_token):
    username, email = _mk(client, dev_token)
    r = client.post(f"{BASE}/auth/login", json={"username": email, "password": PWD})
    assert r.status_code == 200, r.text
    assert r.json()["user"]["username"] == username


def test_login_with_email_case_insensitive(client, dev_token):
    _, email = _mk(client, dev_token)
    r = client.post(f"{BASE}/auth/login",
                    json={"username": email.upper(), "password": PWD})
    assert r.status_code == 200, r.text


def test_login_with_username_still_works(client, dev_token):
    username, _ = _mk(client, dev_token)
    r = client.post(f"{BASE}/auth/login", json={"username": username, "password": PWD})
    assert r.status_code == 200, r.text


def test_login_email_wrong_password_401(client, dev_token):
    _, email = _mk(client, dev_token)
    r = client.post(f"{BASE}/auth/login",
                    json={"username": email, "password": "Wrong@2026x"})
    assert r.status_code == 401
