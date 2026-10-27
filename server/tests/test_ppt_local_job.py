"""PPT 异步 job 的「无 PPTAgent」路径：本地严格套模板渲染。

正式链路已定为 35B + drawio + 确定性排版引擎，DP9B（PPTAgent）退出。
本文件锁死这条契约：``PPT_AGENT_URL`` 为空时 ``POST /ppt/jobs`` **不能**
直接失败，而要改由本地渲染接管同一条异步 job 链路——否则桌面端「AI 生成 PPT」
主路径（异步 job）在 DP9B 下线后彻底不可用，只有下载到本地文件才退回同步导出。

覆盖：
1. 有带大纲的文档：提交 → 轮询 → succeeded，renderer=local，导出得到真 pptx
2. 提交不受阻塞（本地渲染也在后台线程，不拖慢请求）
3. 没有大纲的文档：明确 failed 且原因是缺大纲，不是「未配置 PPT_AGENT_URL」
4. 全程不触达 PPTAgent 客户端（无 URL 时任何外呼都是错的）
5. 排队封装层（queued_agent_job）同样降级到本地渲染，不占用排队名额
"""
import os
import sys
import time
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("AI_PROVIDER", "mock")
os.environ.setdefault("DATA_DIR", f"/tmp/test-pptlocal-{uuid.uuid4().hex[:8]}")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

BASE = "/api/v1"
TERMINAL = ("succeeded", "failed", "cancelled")

OUTLINE = {
    "title": "2026 年社区矫正工作汇报",
    "slides": [
        {"type": "cover", "title": "2026 年社区矫正工作汇报"},
        {"type": "toc", "title": "汇报目录", "points": ["总体情况", "典型案例"]},
        {"type": "content", "title": "总体情况", "points": ["在册人员 320 人", "重新犯罪率 0.3%"]},
        {"type": "closing", "title": "谢谢聆听"},
    ],
}


@pytest.fixture(scope="module", autouse=True)
def _offline_ppt_agent():
    """关掉 PPTAgent 开关：本文件验证的正是「没有它」时的行为。

    同时也保证离线可跑——``server/.env`` 里配着生产内网地址，不关会真起线程去连。
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
def token(client):
    r = client.post(f"{BASE}/auth/login", json={
        "username": "developer", "password": "Passw0rd!2026"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _new_doc(client, token, title):
    r = client.post(f"{BASE}/ppt/blank", headers=_hdr(token),
                    json={"title": title})
    assert r.status_code == 200, r.text
    return r.json()["doc_id"]


def _doc_with_outline(client, token, title="本地渲染汇报"):
    doc_id = _new_doc(client, token, title)
    saved = client.put(f"{BASE}/ppt/documents/{doc_id}/draft",
                       headers=_hdr(token), json={"outline": OUTLINE})
    assert saved.status_code == 200, saved.text
    return doc_id


def _wait_terminal(client, token, job_id, timeout=60.0):
    end = time.time() + timeout
    last = {}
    while time.time() < end:
        r = client.get(f"{BASE}/ppt/jobs/{job_id}/status", headers=_hdr(token))
        assert r.status_code == 200, r.text
        last = r.json()
        if last.get("status") in TERMINAL:
            return last
        time.sleep(0.1)
    raise AssertionError(f"本地渲染未在 {timeout}s 内走到终态，当前 {last}")


# ------------------------------------------------ 1. 无 PPTAgent 也能出成品

def test_submit_without_agent_url_returns_pending_not_failed(client, token):
    """提交必须立即返回 pending：本地渲染同样在后台线程里跑。"""
    doc_id = _doc_with_outline(client, token)
    t0 = time.monotonic()
    r = client.post(f"{BASE}/ppt/jobs", headers=_hdr(token), json={"doc_id": doc_id})
    elapsed = time.monotonic() - t0
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["job_id"] == doc_id
    assert body["status"] in ("pending", "running", "succeeded"), body
    assert elapsed < 5, f"提交耗时 {elapsed:.1f}s，疑似退化成同步渲染"


def test_local_job_succeeds_and_exports_real_pptx(client, token):
    """端到端：job 成功 → renderer=local → 导出接口给出可打开的 pptx。"""
    doc_id = _doc_with_outline(client, token, "本地渲染成品")
    client.post(f"{BASE}/ppt/jobs", headers=_hdr(token), json={"doc_id": doc_id})
    final = _wait_terminal(client, token, doc_id)
    assert final["status"] == "succeeded", final
    assert final["renderer"] == "local", final

    exported = client.get(f"{BASE}/ppt/jobs/{doc_id}/export", headers=_hdr(token))
    assert exported.status_code == 200, exported.text
    assert exported.content[:2] == b"PK", "导出内容不是 pptx（zip）"
    assert len(exported.content) > 10_000

    doc = client.get(f"{BASE}/ppt/documents/{doc_id}", headers=_hdr(token))
    assert doc.status_code == 200, doc.text
    assert doc.json()["status"] == "generated"
    assert doc.json()["template_id"] is None


# ------------------------------------------------ 2. 不触达 PPTAgent

def test_local_job_never_calls_ppt_agent(client, token, monkeypatch):
    """没有 URL 时任何 HTTP 外呼都是错的：客户端被调用即失败。"""
    from app.infrastructure.ppt import ppt_agent_client as mod

    def _boom(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("未配置 PPT_AGENT_URL 时不允许创建/调用 PPTAgent 客户端")

    monkeypatch.setattr(mod.PPTAgentClient, "from_settings", classmethod(_boom))
    doc_id = _doc_with_outline(client, token, "不外呼")
    client.post(f"{BASE}/ppt/jobs", headers=_hdr(token), json={"doc_id": doc_id})
    final = _wait_terminal(client, token, doc_id)
    assert final["status"] == "succeeded", final


# ------------------------------------------------ 3. 空文档也有默认结构；失败给出可读原因

def test_blank_document_renders_default_structure(client, token):
    """新建的空文档自带默认大纲（封面/目录/结束），本地渲染应直接出成品。"""
    doc_id = _new_doc(client, token, "空文档")
    client.post(f"{BASE}/ppt/jobs", headers=_hdr(token), json={"doc_id": doc_id})
    final = _wait_terminal(client, token, doc_id)
    assert final["status"] == "succeeded", final
    assert final["renderer"] == "local", final
    assert final["total_pages"] >= 1, final


def test_local_render_reports_missing_document():
    """渲染函数本身要对「拿不到文档」给出可读原因，而不是抛异常穿透后台线程。"""
    from app.application.ppt.agent_job import _render_local_and_store

    ok, why = _render_local_and_store("no-such-doc")
    assert ok is False
    assert why == "文档不存在"
    assert "PPT_AGENT_URL" not in why


# ------------------------------------------------ 4. 排队封装层同样降级

def test_queued_wrapper_delegates_to_local_render(client, token):
    """queued_agent_job 不应再以「未配置」拒绝，也不占排队名额。"""
    from app.application.ppt import queued_agent_job

    doc_id = _doc_with_outline(client, token, "排队层本地渲染")
    result = queued_agent_job.submit_job(doc_id, "developer", "")
    assert result["job_id"] == doc_id
    assert result["status"] in ("pending", "running", "succeeded"), result
    assert result.get("queue_position") is None, result

    final = _wait_terminal(client, token, doc_id)
    assert final["status"] == "succeeded", final
    assert final["renderer"] == "local", final


# ------------------------------------------------ 5. 逐页预览图（本地路径）

def test_render_local_previews_without_tools_is_noop(monkeypatch):
    """缺 soffice/pdftoppm 时必须静默跳过（返回 0），绝不能拖垮 job。"""
    from app.application.ppt import agent_job

    monkeypatch.setattr(agent_job.shutil, "which", lambda name: None)
    assert agent_job._render_local_previews(Path("whatever.pptx"), "doc-x") == 0


def test_local_previews_served_by_job_preview_endpoint(client, token, monkeypatch):
    """本地页图按 preview_document 同款目录约定存放后，job 预览接口必须能列出并按页序取图。

    两段验证：
    A. job 成功后若环境里有 soffice/pdftoppm，真转换应产出与大纲页数一致的页图
      （缺工具的环境允许 0 张——这正是「尽力而为」契约）。
    B. 清空目录后放假 PNG（pg-1/pg-2/pg-10，乱序写入 + 含两位数页码），
       验证列表按页序排、单页取图内容一一对应（pg-10 必须排最后）。
    """
    import shutil as _shutil

    from app.core.config import settings

    doc_id = _doc_with_outline(client, token, "本地页图")
    client.post(f"{BASE}/ppt/jobs", headers=_hdr(token), json={"doc_id": doc_id})
    final = _wait_terminal(client, token, doc_id)
    assert final["status"] == "succeeded", final

    prev_dir = settings.ppt_dir / "preview" / doc_id

    # A. 真转换（环境有工具时）
    listed = client.get(f"{BASE}/ppt/jobs/{doc_id}/preview", headers=_hdr(token))
    assert listed.status_code == 200, listed.text
    pages = listed.json()["pages"]
    tools_present = bool(_shutil.which("soffice") and _shutil.which("pdftoppm"))
    if tools_present:
        assert len(pages) == final["total_pages"], (pages, final)
    else:
        assert len(pages) == 0, pages

    # B. 隔离目录，专测排序与取图
    import shutil
    shutil.rmtree(prev_dir, ignore_errors=True)
    prev_dir.mkdir(parents=True, exist_ok=True)
    contents = {}
    for name in ("pg-2.png", "pg-10.png", "pg-1.png"):  # 乱序写入
        data = f"fake-png:{name}".encode()
        (prev_dir / name).write_bytes(data)
        contents[name] = data

    listed = client.get(f"{BASE}/ppt/jobs/{doc_id}/preview", headers=_hdr(token))
    assert listed.status_code == 200, listed.text
    pages = listed.json()["pages"]
    assert [p["index"] for p in pages] == [0, 1, 2]
    assert [p["url"].rsplit("/", 1)[-1] for p in pages] == \
        ["0.png", "1.png", "2.png"], pages

    # 单页取图：内容与写入的假 PNG 一一对应（pg-10 在 index=2）
    for idx, name in ((0, "pg-1.png"), (1, "pg-2.png"), (2, "pg-10.png")):
        r = client.get(f"{BASE}/ppt/jobs/{doc_id}/preview/{idx}",
                       headers=_hdr(token))
        assert r.status_code == 200, r.text
        assert r.content == contents[name], (idx, name)
