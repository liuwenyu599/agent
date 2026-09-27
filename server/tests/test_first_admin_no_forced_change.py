"""回归测试：首个系统管理员注册后不得被强制改密（P0 权限缺陷）。

背景
----
`AuthService._create_user_checked()` 原先无条件把 `must_change_password` 置为 True，
而 `register_first()` 复用了它。首个管理员的密码已经通过 `validate_password_strength`
强度校验、是本人真实使用的密码，却被要求「首次登录必须改密」，于是
`deps.get_current_user()` 对该管理员的全部业务端点返回 403 —— 全新部署直接卡死。

本文件验证三件事：
1. 正例：首个管理员注册后 `must_change_password=False`，令牌可正常访问业务端点；
2. 反例：管理员用 `register()` 建号的人仍为 True，业务端点仍被 403 拦截
   （证明修复没有把整条强制改密策略关掉）；
3. 默认参数向后兼容：`_create_user_checked()` 不传参时仍为 True。

运行方式（在 server/ 目录下）：
    D:/apps/anaconda3/python.exe -m pytest tests/test_first_admin_no_forced_change.py -v

数据隔离：服务层用内存仓储（零 IO）；接口层用独立临时 SQLite 库并覆盖 get_db，
绝不写入测试共享库，更不会写入真实库。
"""
import os
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("AI_PROVIDER", "mock")
os.environ.setdefault("DATA_DIR", f"/tmp/test-firstadmin-{uuid.uuid4().hex[:8]}")
os.environ.setdefault("DATABASE_URL", f"sqlite:////tmp/test-firstadmin-{uuid.uuid4().hex[:8]}.db")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.application.identity.service import AuthService  # noqa: E402
from app.domain.identity.entities import ROLE_DEVELOPER, ROLE_USER, User  # noqa: E402
from app.domain.identity.repositories import UserRepository  # noqa: E402
from app.infrastructure.database.base import Base  # noqa: E402
from app.infrastructure.database.session import get_db  # noqa: E402
from app.main import app  # noqa: E402

BASE = "/api/v1"
STRONG_PWD = "Passw0rd!2026"   # 满足强度规则的管理员真实密码
WEAK_PWD = "123456"            # 管理员代建账号时允许的弱初始密码
NEW_PWD = "Newpass@2026"       # 改密后的强密码


# ============================================================ 内存仓储替身


class InMemoryUserRepository(UserRepository):
    """纯内存用户仓储：让服务层断言完全不依赖数据库与测试执行顺序。"""

    def __init__(self) -> None:
        self._rows: dict[str, User] = {}

    def _next_id(self) -> str:
        return f"u-{len(self._rows) + 1}"

    def get(self, id: str):
        return self._rows.get(id)

    def add(self, entity: User) -> User:
        if not entity.id:
            entity.id = self._next_id()
        self._rows[entity.id] = entity
        return entity

    def delete(self, entity: User) -> None:
        self._rows.pop(entity.id, None)

    def update(self, user: User) -> User:
        self._rows[user.id] = user
        return user

    def get_by_username(self, username: str):
        return next((u for u in self._rows.values() if u.username == username), None)

    def get_by_email(self, email: str):
        return next((u for u in self._rows.values() if u.email == email), None)

    def list_all(self):
        return list(self._rows.values())

    def count(self) -> int:
        return len(self._rows)


def _hdr(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ============================================================ 服务层（内存仓储，零依赖）


def test_register_first_does_not_force_password_change():
    """正例：首个管理员自设强密码，注册后不得要求改密。"""
    svc = AuthService(InMemoryUserRepository())
    _token, user = svc.register_first(
        username="first_admin", email="first_admin@test.local",
        password=STRONG_PWD, real_name="首个系统管理员", role=ROLE_DEVELOPER,
    )
    assert user.role == ROLE_DEVELOPER
    assert user.must_change_password is False, (
        "首个管理员的密码已过强度校验，不应强制首登改密，否则业务端点一律 403"
    )


def test_register_first_rejects_weak_password():
    """前置约束仍然成立：首个管理员必须设置强密码。"""
    svc = AuthService(InMemoryUserRepository())
    with pytest.raises(Exception):
        svc.register_first(
            username="first_admin", email="first_admin@test.local",
            password=WEAK_PWD, role=ROLE_DEVELOPER,
        )
    assert svc.users.count() == 0


def test_admin_created_user_still_forced_to_change_password():
    """反例：管理员为他人建号（可能用弱初始密码）仍必须强制改密。"""
    repo = InMemoryUserRepository()
    svc = AuthService(repo)
    _token, admin = svc.register_first(
        username="first_admin", email="first_admin@test.local",
        password=STRONG_PWD, role=ROLE_DEVELOPER,
    )
    normal = svc.register(
        actor=admin, username="normal_user", email="normal_user@test.local",
        password=WEAK_PWD, role=ROLE_USER,
    )
    assert normal.must_change_password is True, "管理员代建账号必须保持强制改密"


def test_create_user_checked_defaults_to_forced_change():
    """向后兼容：不显式传参时行为与修复前完全一致（True）。"""
    svc = AuthService(InMemoryUserRepository())
    created = svc._create_user_checked(
        "someone", "someone@test.local", WEAK_PWD, "", "", ROLE_USER,
    )
    assert created.must_change_password is True


def test_change_password_clears_the_flag():
    """改密后清除标记——自救通道仍然有效。"""
    repo = InMemoryUserRepository()
    svc = AuthService(repo)
    _token, admin = svc.register_first(
        username="first_admin", email="first_admin@test.local",
        password=STRONG_PWD, role=ROLE_DEVELOPER,
    )
    normal = svc.register(
        actor=admin, username="normal_user", email="normal_user@test.local",
        password=WEAK_PWD, role=ROLE_USER,
    )
    assert normal.must_change_password is True
    svc.change_password(normal, WEAK_PWD, NEW_PWD, NEW_PWD)
    assert repo.get_by_username("normal_user").must_change_password is False


# ============================================================ 接口层（独立临时库）


@pytest.fixture
def isolated_client(tmp_path):
    """TestClient + 独立 SQLite 库：保证「注册首个管理员」这条路径可被真实走到。

    测试进程内各模块共用同一个库，首个用户可能已被别的模块占用；
    这里用 dependency_overrides 把请求级 Session 指向全新临时库，
    使 register-first 永远成功，断言不受执行顺序影响。
    """
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'first_admin.db').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def _override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    previous = dict(app.dependency_overrides)
    app.dependency_overrides[get_db] = _override_get_db
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)
        engine.dispose()


def test_first_admin_token_reaches_business_endpoint(isolated_client):
    """核心回归：全新部署后首个管理员登录即可正常使用业务端点（不是 403）。"""
    client = isolated_client

    registered = client.post(f"{BASE}/auth/register-first", json={
        "username": "first_admin", "email": "first_admin@test.local",
        "password": STRONG_PWD, "real_name": "首个系统管理员",
    })
    assert registered.status_code == 200, registered.text
    token = registered.json()["access_token"]

    # 登录响应与 /auth/me 都不应报「需要改密」
    me = client.get(f"{BASE}/auth/me", headers=_hdr(token))
    assert me.status_code == 200
    assert me.json()["must_change_password"] is False

    relogin = client.post(f"{BASE}/auth/login", json={
        "username": "first_admin", "password": STRONG_PWD})
    assert relogin.status_code == 200
    assert relogin.json()["must_change_password"] is False

    # 业务端点（走 get_current_user，含强制改密校验）必须放行
    business = client.get(f"{BASE}/knowledge/list", headers=_hdr(token))
    assert business.status_code == 200, (
        f"首个管理员不应被强制改密拦截，实际：{business.status_code} {business.text}"
    )


def test_first_admin_can_immediately_create_other_users(isolated_client):
    """首个管理员注册后立刻具备管理动作权限（建号依赖 get_current_user）。"""
    client = isolated_client
    token = client.post(f"{BASE}/auth/register-first", json={
        "username": "first_admin", "email": "first_admin@test.local",
        "password": STRONG_PWD,
    }).json()["access_token"]

    created = client.post(f"{BASE}/auth/register", json={
        "username": "normal_user", "email": "normal_user@test.local",
        "password": WEAK_PWD, "role": ROLE_USER,
    }, headers=_hdr(token))
    assert created.status_code == 200, created.text


def test_admin_created_user_blocked_until_password_changed(isolated_client):
    """反例：管理员代建的账号仍被 403 拦截，改密后恢复——策略没被整体关掉。"""
    client = isolated_client
    dev_token = client.post(f"{BASE}/auth/register-first", json={
        "username": "first_admin", "email": "first_admin@test.local",
        "password": STRONG_PWD,
    }).json()["access_token"]

    assert client.post(f"{BASE}/auth/register", json={
        "username": "normal_user", "email": "normal_user@test.local",
        "password": WEAK_PWD, "role": ROLE_USER,
    }, headers=_hdr(dev_token)).status_code == 200

    login = client.post(f"{BASE}/auth/login", json={
        "username": "normal_user", "password": WEAK_PWD})
    assert login.status_code == 200
    assert login.json()["must_change_password"] is True
    user_token = login.json()["access_token"]

    blocked = client.get(f"{BASE}/knowledge/list", headers=_hdr(user_token))
    assert blocked.status_code == 403
    assert "请先修改初始密码" in blocked.json()["detail"]

    changed = client.post(f"{BASE}/auth/change-password", json={
        "old_password": WEAK_PWD, "new_password": NEW_PWD,
        "confirm_password": NEW_PWD,
    }, headers=_hdr(user_token))
    assert changed.status_code == 200, changed.text

    ok = client.get(f"{BASE}/knowledge/list", headers=_hdr(user_token))
    assert ok.status_code == 200
