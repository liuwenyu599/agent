"""首管理员密码策略与安全 bootstrap 回归测试。

首个系统管理员只能通过部署主机本地 CLI 创建；匿名 HTTP bootstrap 端点必须不存在。
服务层仍保留 register_first() 作为 CLI 初始化能力，因此这里继续验证：
1. 首管理员自设强密码后不被强制改密；
2. 弱密码被拒绝；
3. 管理员代建普通账号仍必须改密；
4. _create_user_checked() 默认行为保持向后兼容；
5. 改密后清除强制改密标记；
6. HTTP 层不暴露 register-first/check-first-user。
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

from app.application.identity.service import AuthService  # noqa: E402
from app.domain.identity.entities import ROLE_DEVELOPER, ROLE_USER, User  # noqa: E402
from app.domain.identity.repositories import UserRepository  # noqa: E402
from app.main import create_app  # noqa: E402

STRONG_PWD = "Passw0rd!2026"
WEAK_PWD = "123456"
NEW_PWD = "Newpass@2026"


class InMemoryUserRepository(UserRepository):
    """纯内存用户仓储：服务层断言不依赖数据库与测试执行顺序。"""

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


def test_register_first_does_not_force_password_change():
    svc = AuthService(InMemoryUserRepository())
    _token, user = svc.register_first(
        username="firstadmin",
        email="firstadmin@test.local",
        password=STRONG_PWD,
        real_name="首个系统管理员",
        role=ROLE_DEVELOPER,
    )
    assert user.role == ROLE_DEVELOPER
    assert user.must_change_password is False


def test_register_first_rejects_weak_password():
    svc = AuthService(InMemoryUserRepository())
    with pytest.raises(Exception):
        svc.register_first(
            username="firstadmin",
            email="firstadmin@test.local",
            password=WEAK_PWD,
            role=ROLE_DEVELOPER,
        )
    assert svc.users.count() == 0


def test_admin_created_user_still_forced_to_change_password():
    repo = InMemoryUserRepository()
    svc = AuthService(repo)
    _token, admin = svc.register_first(
        username="firstadmin",
        email="firstadmin@test.local",
        password=STRONG_PWD,
        role=ROLE_DEVELOPER,
    )
    normal = svc.register(
        actor=admin,
        username="normaluser",
        email="normaluser@test.local",
        password=WEAK_PWD,
        role=ROLE_USER,
    )
    assert normal.must_change_password is True


def test_create_user_checked_defaults_to_forced_change():
    svc = AuthService(InMemoryUserRepository())
    created = svc._create_user_checked(
        "someone", "someone@test.local", WEAK_PWD, "", "", ROLE_USER,
    )
    assert created.must_change_password is True


def test_change_password_clears_the_flag():
    repo = InMemoryUserRepository()
    svc = AuthService(repo)
    _token, admin = svc.register_first(
        username="firstadmin",
        email="firstadmin@test.local",
        password=STRONG_PWD,
        role=ROLE_DEVELOPER,
    )
    normal = svc.register(
        actor=admin,
        username="normaluser",
        email="normaluser@test.local",
        password=WEAK_PWD,
        role=ROLE_USER,
    )
    assert normal.must_change_password is True
    svc.change_password(normal, WEAK_PWD, NEW_PWD, NEW_PWD)
    assert repo.get_by_username("normaluser").must_change_password is False


def test_first_admin_bootstrap_is_not_exposed_over_http():
    paths = {route.path for route in create_app().routes}
    assert "/api/v1/auth/register-first" not in paths
    assert "/api/v1/auth/check-first-user" not in paths
