"""密码策略测试：修改密码 / 管理员重置 / 强制改密 / 审计。

运行方式（在 server/ 目录下）：
    AI_PROVIDER=mock python -m pytest tests/test_password_policy.py -v
"""
import os
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("AI_PROVIDER", "mock")
os.environ.setdefault("DATA_DIR", f"/tmp/test-pwd-{uuid.uuid4().hex[:8]}")
os.environ.setdefault("DATABASE_URL", f"sqlite:////tmp/test-pwd-{uuid.uuid4().hex[:8]}.db")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.infrastructure.database import Base, engine  # noqa: E402

Base.metadata.create_all(bind=engine)

BASE = "/api/v1"
OLD_PWD = "Passw0rd!2026"
NEW_PWD = "Newpass@2026"


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _hdr(token):
    return {"Authorization": f"Bearer {token}"}


def _dev_token(client):
    """取得系统管理员令牌。

    测试进程内可能与其他测试模块共用同一个库（首用户已被占用），
    此时直接为库中的系统管理员账号签发令牌。
    """
    r = client.post(f"{BASE}/auth/register-first", json={
        "username": "pwd_dev", "email": "pwd_dev@test.local",
        "password": OLD_PWD, "real_name": "系统管理员",
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
def accounts(client):
    dev_token = _dev_token(client)

    r = client.post(f"{BASE}/auth/register", json={
        "username": "pwd_user", "email": "pwd_user@test.local",
        "password": OLD_PWD, "department": "行政复议科", "role": "user",
    }, headers=_hdr(dev_token))
    assert r.status_code == 200
    user_id = client.get(f"{BASE}/users/", headers=_hdr(dev_token)).json()
    uid = next(u["id"] for u in user_id if u["username"] == "pwd_user")
    user_token = client.post(f"{BASE}/auth/login", json={
        "username": "pwd_user", "password": OLD_PWD}).json()["access_token"]
    return {"dev": dev_token, "user": user_token, "user_id": uid}


# ---------------------------------------------------------------- 修改密码

def test_change_password_wrong_old_password(client, accounts):
    r = client.post(f"{BASE}/auth/change-password", json={
        "old_password": "WrongOld@2026", "new_password": NEW_PWD,
        "confirm_password": NEW_PWD,
    }, headers=_hdr(accounts["user"]))
    assert r.status_code == 400
    assert "当前密码" in r.json()["detail"]


def test_change_password_mismatch_confirm(client, accounts):
    r = client.post(f"{BASE}/auth/change-password", json={
        "old_password": OLD_PWD, "new_password": NEW_PWD,
        "confirm_password": "Other@2026",
    }, headers=_hdr(accounts["user"]))
    assert r.status_code == 400


def test_change_password_weak_rejected(client, accounts):
    for weak in ["12345678", "abcdefgh", "Abc1", "password"]:
        r = client.post(f"{BASE}/auth/change-password", json={
            "old_password": OLD_PWD, "new_password": weak,
            "confirm_password": weak,
        }, headers=_hdr(accounts["user"]))
        assert r.status_code == 400, weak


def test_change_password_success_and_relogin(client, accounts):
    r = client.post(f"{BASE}/auth/change-password", json={
        "old_password": OLD_PWD, "new_password": NEW_PWD,
        "confirm_password": NEW_PWD,
    }, headers=_hdr(accounts["user"]))
    assert r.status_code == 200, r.text
    # 新密码可登录
    ok = client.post(f"{BASE}/auth/login", json={
        "username": "pwd_user", "password": NEW_PWD})
    assert ok.status_code == 200
    # 旧密码失效
    bad = client.post(f"{BASE}/auth/login", json={
        "username": "pwd_user", "password": OLD_PWD})
    assert bad.status_code == 401
    accounts["user"] = ok.json()["access_token"]


def test_change_password_requires_login(client):
    r = client.post(f"{BASE}/auth/change-password", json={
        "old_password": OLD_PWD, "new_password": NEW_PWD,
        "confirm_password": NEW_PWD})
    assert r.status_code in (401, 403)


# ---------------------------------------------------------------- 管理员重置

def test_normal_user_cannot_reset_others_password(client, accounts):
    r = client.post(f"{BASE}/users/{accounts['user_id']}/reset-password",
                    json={"password": "Reset@2026x"},
                    headers=_hdr(accounts["user"]))
    assert r.status_code == 403


def test_admin_reset_success_forces_change(client, accounts):
    r = client.post(f"{BASE}/users/{accounts['user_id']}/reset-password",
                    json={"password": "Reseted@2026"},
                    headers=_hdr(accounts["dev"]))
    assert r.status_code == 200
    assert r.json()["must_change_password"] is True

    # 登录返回强制改密标记
    login = client.post(f"{BASE}/auth/login", json={
        "username": "pwd_user", "password": "Reseted@2026"})
    assert login.status_code == 200
    assert login.json()["must_change_password"] is True
    token = login.json()["access_token"]

    # 未改密前，业务接口被拦截
    blocked = client.get(f"{BASE}/knowledge/list", headers=_hdr(token))
    assert blocked.status_code == 403

    # 改密后恢复
    changed = client.post(f"{BASE}/auth/change-password", json={
        "old_password": "Reseted@2026", "new_password": "Final@2026ok",
        "confirm_password": "Final@2026ok",
    }, headers=_hdr(token))
    assert changed.status_code == 200
    ok = client.get(f"{BASE}/knowledge/list", headers=_hdr(token))
    assert ok.status_code == 200


def test_admin_reset_accepts_weak_password_but_forces_change(client, accounts):
    """管理员重置他人密码：允许弱密码，但必须强制该用户改密。

    与 `_create_user_checked()` 默认行为、批量导入初始密码 123456 属同一条设计链：
    管理员为他人设的初始密码 → 允许弱 → 强制改密 → 强度在改密时校验。
    因此这里**不**要求 400，而是钉死「弱密码可接受 + must_change_password=True」。
    """
    r = client.post(f"{BASE}/users/{accounts['user_id']}/reset-password",
                    json={"password": "12345678"},
                    headers=_hdr(accounts["dev"]))
    assert r.status_code == 200
    assert r.json()["must_change_password"] is True, "弱重置密码必须附带强制改密标记"

    # 弱密码可以登录，但业务接口仍被拦截，直到本人改成强密码
    login = client.post(f"{BASE}/auth/login", json={
        "username": "pwd_user", "password": "12345678"})
    assert login.status_code == 200
    assert login.json()["must_change_password"] is True

    blocked = client.get(f"{BASE}/knowledge/list", headers=_hdr(login.json()["access_token"]))
    assert blocked.status_code == 403
    assert "请先修改初始密码" in blocked.json()["detail"]


# ---------------------------------------------------------------- 审计

def test_password_audit_logs_without_password(client, accounts):
    from app.infrastructure.database import SessionLocal
    from sqlalchemy import select
    from app.infrastructure.database.models.audit import AuditLogModel

    db = SessionLocal()
    try:
        rows = db.scalars(select(AuditLogModel).where(
            AuditLogModel.action.in_(["password_change", "password_reset"])
        )).all()
        assert len(rows) >= 2
        blob = " ".join(str(r.detail) for r in rows)
        for secret in (OLD_PWD, NEW_PWD, "Reseted@2026", "Final@2026ok"):
            assert secret not in blob, "审计日志泄漏密码"
        # 记录用户与时间
        assert rows[0].user_id
        assert rows[0].created_at is not None
    finally:
        db.close()


def test_sms_provider_not_connected():
    """政务内网短信未接入：预留接口存在但不可用。"""
    from app.application.identity.sms import NullSmsProvider
    with pytest.raises(NotImplementedError):
        NullSmsProvider().send_code("13800000000", "123456")
