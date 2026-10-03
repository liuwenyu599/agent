"""Shared pytest lifecycle guards.

PPT interface tests intentionally start daemon background workers. Item 7 added a
per-user admission guard, so allowing one test to end while its worker is still
running can make the next test (same developer token) correctly receive a conflict
and then observe an untouched document with status ``unknown``. That is test leakage,
not product behavior.
"""
from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path

import pytest


@pytest.fixture(autouse=True, scope="module")
def _isolate_database_per_module(request):
    """每个测试模块使用独立的 SQLite 库，使 DB 隔离与 import 顺序无关。

    问题根因：``app.infrastructure.database.session`` 的 ``engine`` 是进程级单例，
    在「第一个 import 它的模块」处即被锁定到当时的 ``DATABASE_URL``。各测试模块虽用
    ``os.environ.setdefault("DATABASE_URL", ...)`` 声明自己的临时库，但若本模块不是
    第一个 import 该 session 的模块，``setdefault`` 失效，本模块会落到别人的库（默认
    即 ``server/data/judicial_app.db`` 这个真实且含用户的库），导致 ``register-first``
    因 ``is_first_user()==False`` 而 KeyError，整模块 fixture 全挂。

    修复：在每个模块开始前，强制给本模块分配一个独立的临时库并重建引擎，彻底隔离，
    不再依赖 ``setdefault`` 的先后顺序。仅隔离数据库连接，不动 ``DATA_DIR``（避免影响
    文件类测试）。生产代码不触发本 fixture。
    """
    tmp = Path(tempfile.mkdtemp(prefix=f"pytest-{request.module.__name__}-"))
    os.environ["DATABASE_URL"] = f"sqlite:///{tmp / 'isolated.sqlite'}"
    from app.infrastructure.database.session import configure_engine
    from app.infrastructure.ai import reset_gateway

    configure_engine(database_url=os.environ["DATABASE_URL"], data_dir=None)
    # 各模块通过 os.environ.setdefault("AI_PROVIDER", "mock") 声明用 mock 网关，但
    # AI 网关工厂会缓存首建实例，且 settings.AI_PROVIDER 在首次 import 时即被固化。
    # 这里按当前模块的环境重建网关缓存，避免「上一个模块固化了真实网关」污染本模块。
    reset_gateway()
    yield


@pytest.fixture(autouse=True)
def _drain_ppt_job_threads_between_interface_tests(request):
    yield
    if request.module.__name__ != "test_ppt_agent_jobs":
        return

    from app.application.ppt import agent_job

    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        with agent_job._RUNNING_LOCK:
            threads = [thread for thread in agent_job._RUNNING.values() if thread.is_alive()]
        if not threads:
            return
        for thread in threads:
            thread.join(timeout=0.1)
