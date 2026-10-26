"""PPT 异步任务链路契约测试（TC-030~TC-032）。

覆盖 §7.1 与 R-04 指出的缺口：异步 job 链路（提交→轮询→取消→导出）此前
**没有任何 HTTP 层的端到端用例**——现有 test_ppt_agent_jobs.py 全是把
PPTAgentClient monkeypatch 掉的单元级测试，路由、鉴权、归属、参数校验这一层
从来没被走过。

未配置 PPT_AGENT_URL 时 submit_job **不再直接失败**，而是改走本地严格套模板
渲染（正式链路不含 DP9B）——详见 test_ppt_local_job.py。本文件因此不依赖
真实 PPTAgent，在不联网的机器上也能跑。

本文件重点锁三类行为：
1. 提交必须立即返回，不得阻塞（这是「异步」的定义，退化成同步会拖死请求线程）
2. 产物未完成时 export 必须是明确的 404，绝不能返回半成品或空文件
3. 预览分页的页码来自客户端入参，必须挡住越界 / 非数字 / 目录穿越
"""
import os
import sys
import time
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("AI_PROVIDER", "mock")
os.environ.setdefault("DATA_DIR", f"/tmp/test-pptjob-{uuid.uuid4().hex[:8]}")
os.environ.setdefault("DATABASE_URL", f"sqlite:////tmp/test-pptjob-{uuid.uuid4().hex[:8]}.db")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.infrastructure.database import Base, engine  # noqa: E402

Base.metadata.create_all(bind=engine)

BASE = "/api/v1"
TERMINAL = ("succeeded", "failed", "cancelled")


@pytest.fixture(scope="module", autouse=True)
def _offline_ppt_agent():
    """把 PPTAgent 开关关掉，保证本模块离线可跑且结果确定。

    不关会怎样：``server/.env`` 里配着生产内网地址（10.128.85.133:7861），
    submit_job 一旦看到 URL 就会真起后台线程去连。开发机连不上时任务会一直
    停在 running 直到 PPT_AGENT_TOTAL_TIMEOUT（默认 1800s）——测试表现为
    轮询 30s 拿不到终态而超时失败，且留下一个跑不完的线程。

    关掉之后走的是 submit_job 的本地渲染分支：后台线程用严格套模板排版，
    本文档没有大纲，因此很快落到 failed（这不是缺陷，是「没有内容可排版」）。
    该分支本身也是要覆盖的契约。
    """
    from app.core.config import settings

    original = settings.PPT_AGENT_URL
    settings.PPT_AGENT_URL = ""
    yield
    settings.PPT_AGENT_URL = original


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

    def reg(username):
        rr = client.post(f"{BASE}/auth/register", json={
            "username": username, "email": f"{username}@test.local",
            "password": "Passw0rd!2026", "real_name": username,
            "department": "行政复议科", "role": "user",
        }, headers=_hdr(out["developer"]))
        assert rr.status_code == 200, rr.text
        tok = client.post(f"{BASE}/auth/login", json={
            "username": username, "password": "Passw0rd!2026"}).json()["access_token"]
        changed = client.post(f"{BASE}/auth/change-password", json={
            "old_password": "Passw0rd!2026", "new_password": "Changed@2026",
            "confirm_password": "Changed@2026"}, headers=_hdr(tok))
        assert changed.status_code == 200, changed.text
        return tok

    out["user_a"] = reg("pptjobusera")
    out["user_b"] = reg("pptjobuserb")
    return out


def _new_doc(client, token):
    r = client.post(f"{BASE}/ppt/blank", headers=_hdr(token),
                    json={"title": f"异步链路_{uuid.uuid4().hex[:6]}"})
    assert r.status_code == 200, r.text
    return r.json()["doc_id"]


# ------------------------------------------------ TC-030 提交 → 轮询 → 终态

def test_submit_returns_immediately(client, users):
    """提交不能阻塞：十几分钟的生成必须由后台线程接管。"""
    doc_id = _new_doc(client, users["user_a"])
    t0 = time.monotonic()
    r = client.post(f"{BASE}/ppt/jobs", headers=_hdr(users["user_a"]),
                    json={"doc_id": doc_id, "message": "生成一份工作汇报"})
    elapsed = time.monotonic() - t0
    assert r.status_code == 200, r.text
    assert elapsed < 20, f"提交耗时 {elapsed:.1f}s，疑似退化成同步生成"
    body = r.json()
    # doc_id 即 job_id，一个文档同时只允许一个进行中的任务
    assert body["job_id"] == doc_id
    assert body["status"] in ("pending", "running", "failed", "succeeded"), r.text


def test_status_is_queryable_and_reaches_terminal(client, users):
    doc_id = _new_doc(client, users["user_a"])
    client.post(f"{BASE}/ppt/jobs", headers=_hdr(users["user_a"]),
                json={"doc_id": doc_id})

    deadline = time.monotonic() + 30
    status = None
    while time.monotonic() < deadline:
        r = client.get(f"{BASE}/ppt/jobs/{doc_id}/status", headers=_hdr(users["user_a"]))
        assert r.status_code == 200, r.text
        status = r.json().get("status")
        if status in TERMINAL:
            break
        time.sleep(0.2)
    assert status in TERMINAL, f"30s 内未走到终态，当前 {status}"


def test_export_before_completion_is_404_not_half_file(client, users):
    """未完成时必须是明确 404——返回半成品/空文件比报错更糟。"""
    doc_id = _new_doc(client, users["user_a"])
    r = client.get(f"{BASE}/ppt/jobs/{doc_id}/export", headers=_hdr(users["user_a"]))
    assert r.status_code == 404, r.text


def test_submit_unknown_doc_is_404(client, users):
    r = client.post(f"{BASE}/ppt/jobs", headers=_hdr(users["user_a"]),
                    json={"doc_id": "no-such-doc"})
    assert r.status_code == 404


# ------------------------------------------------ TC-031 取消

def test_cancel_is_accepted(client, users):
    doc_id = _new_doc(client, users["user_a"])
    r = client.post(f"{BASE}/ppt/jobs/{doc_id}/cancel", headers=_hdr(users["user_a"]))
    assert r.status_code == 200, r.text
    assert r.json()["job_id"] == doc_id


def test_cancel_unknown_job_is_404(client, users):
    r = client.post(f"{BASE}/ppt/jobs/no-such-doc/cancel", headers=_hdr(users["user_a"]))
    assert r.status_code == 404


def test_clarify_unknown_job_is_404(client, users):
    r = client.post(f"{BASE}/ppt/jobs/no-such-doc/clarify",
                    headers=_hdr(users["user_a"]), json={"answer": "按你判断来"})
    assert r.status_code == 404


def test_clarify_when_not_awaiting_is_not_accepted(client, users):
    """任务不在等待回答状态时作答，必须给出明确状态而不是静默重跑。"""
    doc_id = _new_doc(client, users["user_a"])
    client.post(f"{BASE}/ppt/jobs", headers=_hdr(users["user_a"]), json={"doc_id": doc_id})
    r = client.post(f"{BASE}/ppt/jobs/{doc_id}/clarify",
                    headers=_hdr(users["user_a"]), json={"answer": "补充说明"})
    assert r.status_code == 200, r.text
    assert r.json().get("message"), "不在等待状态时作答应带说明文案"


# ------------------------------------------------ TC-032 预览分页

def test_preview_list_is_empty_before_generation(client, users):
    doc_id = _new_doc(client, users["user_a"])
    r = client.get(f"{BASE}/ppt/jobs/{doc_id}/preview", headers=_hdr(users["user_a"]))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["job_id"] == doc_id
    assert body["pages"] == []


@pytest.mark.parametrize("page", ["9999", "9999.png", "9999.jpg"])
def test_preview_page_out_of_range_is_404(client, users, page):
    """越界必须 404，不能 500——前端翻页按钮会连续触发。"""
    doc_id = _new_doc(client, users["user_a"])
    r = client.get(f"{BASE}/ppt/jobs/{doc_id}/preview/{page}",
                   headers=_hdr(users["user_a"]))
    assert r.status_code == 404, r.text


@pytest.mark.parametrize("page", ["abc", "-1", "1.bmp", "1.exe", "1.tiff"])
def test_preview_page_malformed_is_400(client, users, page):
    # .png/.jpg/.jpeg/.webp/.gif 是受支持的扩展名，走得到 404（无此页）而非 400
    doc_id = _new_doc(client, users["user_a"])
    r = client.get(f"{BASE}/ppt/jobs/{doc_id}/preview/{page}",
                   headers=_hdr(users["user_a"]))
    assert r.status_code == 400, r.text


def test_preview_page_rejects_path_traversal(client, users):
    """页码最终拼成文件路径，必须挡住目录穿越。"""
    doc_id = _new_doc(client, users["user_a"])
    for page in ("..%2F..%2Fetc%2Fpasswd", "....//....//etc/passwd"):
        r = client.get(f"{BASE}/ppt/jobs/{doc_id}/preview/{page}",
                       headers=_hdr(users["user_a"]))
        assert r.status_code in (400, 404), f"{page} -> {r.status_code}"


# ------------------------------------------------ 归属：job 只归本人

def test_other_user_cannot_see_job_status(client, users):
    doc_id = _new_doc(client, users["user_a"])
    client.post(f"{BASE}/ppt/jobs", headers=_hdr(users["user_a"]), json={"doc_id": doc_id})
    r = client.get(f"{BASE}/ppt/jobs/{doc_id}/status", headers=_hdr(users["user_b"]))
    assert r.status_code == 404, r.text


def test_other_user_cannot_cancel_job(client, users):
    doc_id = _new_doc(client, users["user_a"])
    r = client.post(f"{BASE}/ppt/jobs/{doc_id}/cancel", headers=_hdr(users["user_b"]))
    assert r.status_code == 404, r.text


def test_other_user_cannot_export_job(client, users):
    doc_id = _new_doc(client, users["user_a"])
    r = client.get(f"{BASE}/ppt/jobs/{doc_id}/export", headers=_hdr(users["user_b"]))
    assert r.status_code == 404, r.text


# ------------------------------------------------ 鉴权

@pytest.mark.parametrize("method,path", [
    ("post", "/ppt/jobs"),
    ("get", "/ppt/jobs/whatever/status"),
    ("get", "/ppt/jobs/whatever/preview"),
    ("get", "/ppt/jobs/whatever/preview/0"),
    ("post", "/ppt/jobs/whatever/cancel"),
    ("post", "/ppt/jobs/whatever/clarify"),
    ("get", "/ppt/jobs/whatever/export"),
])
def test_endpoints_require_auth(client, method, path):
    r = getattr(client, method)(f"{BASE}{path}")
    assert r.status_code in (401, 403), r.text
