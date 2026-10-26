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
    即 ``server/data/judicial_app.db`` 这个真实且含用户的库），导致用例因读到了
    陌生数据而集体失真。

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
    # 登录限流器是进程级单例，失败计数跨模块累积。全量跑时前面的模块用错密码把
    # testclient 的 IP 桶打满（5 次/10 分钟），后面模块的正常 /auth/login 全被 429，
    # 表现为 KeyError: 'access_token'。限流器本身有 reset() 辅助方法，按模块清零即可，
    # 限流逻辑的正确性由 test_delivery_p0_security.py 单独覆盖。
    from app.application.identity.login_limiter import login_rate_limiter

    login_rate_limiter.reset()
    _seed_developer(request.module.__name__)
    yield


# 各测试模块通过 ``POST /auth/register-first`` 建号时使用的管理员用户名。
# P0 安全整改删除该HTTP 端点后，这些模块会退到「用同名账号登录」的兜底分支，
# 因此种子账号必须与之一致，否则登录失败会累加到 IP 限流桶（5 次锁定 15 分钟），
# 把该模块后续所有正常登录一起拦掉，表现为 KeyError: 'access_token'。
_SEED_USERNAMES = {
    "test_chat_session_contract": "developer",
    "test_department_permissions": "developer",
    "test_knowledge_isolation_contract": "developer",
    "test_knowledge_route_order": "kbroutedev",
    "test_password_policy": "pwddev",
    "test_ppt_agent_jobs": "jobdev",
    "test_ppt_job_lifecycle_contract": "developer",
    "test_ppt_local_job": "developer",
    "test_ppt_kb_rag": "kbdev",
    "test_ppt_preview_degrade": "pptprevdev",
    "test_ppt_workbench": "pptdev",
    "test_references_contract": "developer",
    "test_templates_contract": "developer",
    "test_timezone": "tzadmin",
    "test_workflow_contract": "developer",
    "test_user_preferences": "prefdev",
}
_SEED_PASSWORD = "Passw0rd!2026"


def _seed_developer(module_name: str) -> None:
    """在本模块的隔离库里种一个系统管理员（developer）。

    为什么需要：P0 安全整改删除了 ``POST /auth/register-first``（改由部署时
    ``python -m scripts.create_admin`` 在服务器本地建号），但测试套件里大量用例
    仍沿用「先打 register-first，失败再查库签 token」的兜底写法。端点消失后第一步
    永远失败，全部落到第二分支，随后 ``assert row is not None, "库中没有可用的
    系统管理员账号"`` 集体报错（实测 150 errors）。这里在建库后主动补一个管理员，
    让那些兜底逻辑自然走通，无需逐个测试文件改写。

    走服务层 ``AuthService.register_first`` 而非 HTTP：一是它才是被测的正式入口
    （CLI 建号走的就是它），二是绕开端点后不再依赖被安全整改删除的路由。

    账号名取自 ``_SEED_USERNAMES``（与各模块原先注册的用户名一致），密码统一用各
    模块共用的 ``Passw0rd!2026``：这样模块内的登录兜底分支一次即成功，不会因连续
    失败触发登录限流而误伤后续用例。模块名不在映射里时退回通用名，此时该模块若有
    自建号逻辑也能正常工作。
    """
    from app.application.identity.service import AuthService
    from app.infrastructure.database import SessionLocal
    from app.infrastructure.repositories.identity import SqlAlchemyUserRepository

    username = _SEED_USERNAMES.get(module_name, "seedadmin")
    db = SessionLocal()
    try:
        service = AuthService(SqlAlchemyUserRepository(db))
        if service.is_first_user():
            service.register_first(
                username,
                f"{username}@test.local",
                _SEED_PASSWORD,
                real_name="系统管理员",
            )
    except Exception:
        # 种子失败不应让整个模块无法运行：部分用例可能自带建号逻辑。
        pass
    finally:
        db.close()


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
