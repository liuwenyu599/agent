"""Regression tests for 2026-10-03 delivery-review P0 security findings."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.application.identity.login_limiter import (
    LOCK_SECONDS,
    MAX_FAILURES,
    LoginRateLimiter,
)
from app.core.exceptions import AppError, NotFoundError
from app.interfaces.files import _safe_attachment_path


def test_login_limiter_locks_after_five_failures(monkeypatch):
    limiter = LoginRateLimiter()
    now = [1000.0]
    monkeypatch.setattr("app.application.identity.login_limiter.time.monotonic", lambda: now[0])

    for _ in range(MAX_FAILURES):
        limiter.check("10.0.0.8", "Alice")
        limiter.record_failure("10.0.0.8", "Alice")

    with pytest.raises(AppError) as exc:
        limiter.check("10.0.0.8", "alice")
    assert exc.value.status_code == 429

    now[0] += LOCK_SECONDS + 1
    limiter.check("10.0.0.8", "alice")


def test_login_success_clears_ip_and_username_buckets(monkeypatch):
    limiter = LoginRateLimiter()
    monkeypatch.setattr("app.application.identity.login_limiter.time.monotonic", lambda: 1000.0)
    for _ in range(MAX_FAILURES - 1):
        limiter.record_failure("10.0.0.9", "bob")
    limiter.record_success("10.0.0.9", "bob")
    limiter.check("10.0.0.9", "bob")


def test_uploaded_file_path_must_stay_under_upload_root(tmp_path, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    owned = tmp_path / "uploads" / "chat" / "u1" / "a.docx"
    owned.parent.mkdir(parents=True)
    owned.write_bytes(b"ok")
    assert _safe_attachment_path(str(owned)) == owned.resolve()

    outside = tmp_path / "secret.docx"
    outside.write_bytes(b"no")
    with pytest.raises(NotFoundError):
        _safe_attachment_path(str(outside))


def test_bootstrap_http_routes_are_removed():
    from app.main import create_app

    # 用 OpenAPI 路径表而不是遍历 app.routes：新版 FastAPI 把子路由包进
    # _IncludedRouter，route.path 不再稳定存在，遍历会抛 AttributeError。
    paths = set(create_app().openapi()["paths"])
    assert "/api/v1/auth/register-first" not in paths
    assert "/api/v1/auth/check-first-user" not in paths
    assert "/uploads" not in paths
    assert "/api/v1/files/{attachment_id}" in paths
