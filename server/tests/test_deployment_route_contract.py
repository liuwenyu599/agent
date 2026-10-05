"""部署形态契约：哪些路由必须注册、哪些必须保持不注册。

为什么专门写这两个测试
----------------------
查「各个按钮和流程」时发现两件事，值得固化下来防止漂移：

1. `/api/v1/training/*` 全部返回 404，**这不是缺陷**。提交 e89d247
   「disable training APIs in inference-only deployment」是有意注销的：
   本部署只有推理卡（昇腾 310P3），不训练，所以训练 REST 不该暴露。
   这很容易被后来者当成「哦路由忘了注册」顺手加回去——那就把该考场的一次
   有意决策丢掉了。所以这里反着测：**training 必须 404**。

2. 反过来，核心模块必须都在。这类 równie 漏{}注册的事没人会立刻发现：
   UI 上只是那个按钮转一圈报错。用「预期模块前缀是否存在」一次性兜住。

另外顺手验了 training 不注册这件事不影响其它模块照常鉴权，
两边互不牵连。
"""
import os
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("AI_PROVIDER", "mock")
os.environ.setdefault("DATA_DIR", f"/tmp/test-routecontract-{uuid.uuid4().hex[:8]}")
os.environ.setdefault("DATABASE_URL", f"sqlite:////tmp/test-routecontract-{uuid.uuid4().hex[:8]}.db")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.infrastructure.database import Base, engine  # noqa: E402

Base.metadata.create_all(bind=engine)

BASE = "/api/v1"


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _registered_paths():
    """取真实路由全集。

    别用 ``app.routes``——include_router 挂上去的路由不在那里面，
    实测只能拿到 8 个（/docs、/ready 这些），用它判断会全盘误报。
    """
    return set(app.openapi()["paths"])


class TestTrainingStaysDisabled:
    """训练 REST 在本部署是**有意**不注册的，别当 bug 修回去。"""

    def test_training_endpoints_are_not_routed(self, client):
        for p in ("/api/v1/training/overview", "/api/v1/training/assets",
                  "/api/v1/training/samples", "/api/v1/training/models"):
            assert client.get(p).status_code == 404, (
                f"{p} 不该可达。本部署只有推理卡不训练，训练 REST 是有意注销的"
                f"（见提交 e89d247）。如果现在确实要开训练，请先确认部署环境已经换成训练卡。")

    def test_disabling_training_does_not_affect_other_modules(self, client):
        """同一个 app 实例里，其它模块该鉴权鉴权，不受它影响。"""
        probes = ("/training/overview", "/knowledge/list",
                  "/writing/tasks", "/users/")
        codes = {p: client.get(f"{BASE}{p}").status_code for p in probes}

        assert codes["/training/overview"] == 404, "训练 REST 应当保持不可达"
        # 其余三个都已注册，只是没带令牌——应当 401/403，而不是 404
        for p in ("/knowledge/list", "/writing/tasks", "/users/"):
            assert codes[p] != 404, f"{p} 应当已注册"


class TestCoreModulesAreRouted:
    @pytest.mark.parametrize("module", [
        "auth", "users", "knowledge", "writing", "documents", "templates",
        "format-check", "ppt", "chat", "workflow", "references",
        "organization", "dashboard", "system", "preferences", "files",
    ])
    def test_module_has_endpoints(self, module):
        paths = _registered_paths()
        assert any(f"/api/v1/{module}/" in p or f"/api/v1/{module}" in p
                   for p in paths), (
            f"模块 {module} 在 app 里一条路由都没有。"
            f"常见原因是 main.py 的 include_router 列表漏了它——"
            f"那样 UI 上对应按钮会直接转圈报错，很难当场看出来。")

    def test_health_and_ready_exist(self, client):
        assert client.get("/health").status_code == 200
        assert client.get("/ready").status_code in (200, 503)
