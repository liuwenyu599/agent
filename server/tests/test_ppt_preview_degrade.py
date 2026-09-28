"""PPT 逐页预览接口 `POST /api/v1/ppt/documents/{id}/preview` 的降级护栏。

背景（生产缺陷）：
    容器镜像里没有 LibreOffice（soffice）/ poppler（pdftoppm）时，
    `subprocess.run([...])` 抛 `FileNotFoundError`，旧实现把它包成
    `AppError(500)` 冒泡出去，桌面端拿到 HTTP 500。

修复后约定：
    任何"外部工具缺失 / 命令超时 / 转换无产物"都**不返回 5xx**，而是返回与
    "无预览"同构的正常响应 `{pages: [], count: 0, degraded: true, reason: ...}`。
    桌面端 `PptViewModel.refreshPreview()` 读到空 pages 即回退到结构化示意卡，
    与 `ApiResult.Err` 分支行为一致，因此该契约对桌面端安全。

运行方式（在 server/ 目录下）：
    D:/apps/anaconda3/python.exe -m pytest tests/test_ppt_preview_degrade.py -v
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("AI_PROVIDER", "mock")

_TMPDIR = Path(tempfile.mkdtemp(prefix="test-ppt-prev-"))
os.environ.setdefault("DATA_DIR", str(_TMPDIR))
os.environ.setdefault("DATABASE_URL", f"sqlite:///{(_TMPDIR / 'test.db').as_posix()}")

from fastapi.testclient import TestClient  # noqa: E402

from app.infrastructure.database import Base, engine  # noqa: E402
from app.main import app  # noqa: E402

Base.metadata.create_all(bind=engine)

BASE = "/api/v1"
PWD = "Passw0rd!2026"


def _hdr(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def token(client):
    """系统管理员令牌（首个用户已被其它测试文件占用时直接为库内管理员签发）。"""
    r = client.post(f"{BASE}/auth/register-first", json={
        "username": "ppt_prev_dev", "email": "ppt_prev_dev@test.local",
        "password": PWD, "real_name": "系统管理员",
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


@pytest.fixture
def doc_id(client, token):
    """一份带大纲的空白 PPT 文档（blank 自带封面/正文/结束页）。"""
    r = client.post(f"{BASE}/ppt/blank", json={"title": "预览降级测试"},
                    headers=_hdr(token))
    assert r.status_code == 200, r.text
    return r.json()["doc_id"]


@pytest.fixture
def no_renderer(monkeypatch):
    """模拟容器内完全没有 soffice / pdftoppm。"""
    monkeypatch.setattr(shutil, "which", lambda name, *a, **k: None)
    return None


def _stub_run(monkeypatch, handler):
    """只拦截预览用的 soffice / pdftoppm，其它进程的 subprocess.run 一律放行。

    必须放行：运行环境（含 pytest 自身）会用 subprocess 起别的进程，
    无差别打桩会把无关调用一起打断，导致整轮测试连锁失败。
    """
    real_run = subprocess.run

    def _run(cmd, *a, **k):
        head = str(cmd[0]) if isinstance(cmd, (list, tuple)) and cmd else str(cmd)
        if os.path.basename(head) in ("soffice", "soffice.exe", "soffice.bin",
                                      "pdftoppm", "pdftoppm.exe"):
            return handler(cmd, *a, **k)
        return real_run(cmd, *a, **k)

    monkeypatch.setattr(subprocess, "run", _run)
    return _run


# ============================================================ 1. 命令缺失不得 500


def test_preview_without_any_renderer_is_200_not_500(client, token, doc_id,
                                                     no_renderer):
    """核心回归：两个外部命令都缺失时，接口必须 200 + 空页数，绝不 500。"""
    r = client.post(f"{BASE}/ppt/documents/{doc_id}/preview", headers=_hdr(token))
    assert r.status_code == 200, r.text          # 旧实现这里返回 500
    body = r.json()
    assert body["pages"] == []
    assert body["count"] == 0
    assert body["degraded"] is True
    # 原因要能让运维一眼看出缺什么
    assert "soffice" in body["reason"] and "pdftoppm" in body["reason"]


def test_preview_without_pdftoppm_only_is_200(client, token, doc_id, monkeypatch):
    """只缺 pdftoppm（镜像装了 libreoffice 却没装 poppler-utils）同样降级。"""
    real_which = shutil.which
    monkeypatch.setattr(
        shutil, "which",
        lambda name, *a, **k: None if name == "pdftoppm" else real_which(name))
    r = client.post(f"{BASE}/ppt/documents/{doc_id}/preview", headers=_hdr(token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["pages"] == [] and body["degraded"] is True
    assert "pdftoppm" in body["reason"]


def test_preview_degraded_body_is_safe_for_desktop(client, token, doc_id,
                                                   no_renderer):
    """降级响应体必须能被桌面端 `pages.arr().map{str}` 安全消费（不多不少）。"""
    body = client.post(f"{BASE}/ppt/documents/{doc_id}/preview",
                       headers=_hdr(token)).json()
    assert isinstance(body.get("pages"), list)
    assert isinstance(body.get("count"), int)
    assert isinstance(body.get("reason"), str) and body["reason"]


# ============================================================ 2. 其它失败路径


def _present_tools(monkeypatch):
    """让体检通过（两个命令都"存在"），再单独打桩 subprocess.run 制造各种失败。"""
    monkeypatch.setattr(shutil, "which", lambda name, *a, **k: f"/usr/bin/{name}")


def test_preview_command_timeout_is_200(client, token, doc_id, monkeypatch):
    """外部命令超时（TimeoutExpired）也必须降级，不能冒泡成 500。"""
    _present_tools(monkeypatch)

    def _boom(cmd, *a, **k):
        raise subprocess.TimeoutExpired(cmd, k.get("timeout") or 180)

    _stub_run(monkeypatch, _boom)
    r = client.post(f"{BASE}/ppt/documents/{doc_id}/preview", headers=_hdr(token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["pages"] == [] and body["degraded"] is True
    assert "超时" in body["reason"]


def test_preview_no_pdf_output_is_200(client, token, doc_id, monkeypatch):
    """命令执行成功但没产出 PDF（转换静默失败）时降级，不留空预览目录。"""
    _present_tools(monkeypatch)
    _stub_run(monkeypatch,
              lambda cmd, *a, **k: subprocess.CompletedProcess(cmd, 0))
    r = client.post(f"{BASE}/ppt/documents/{doc_id}/preview", headers=_hdr(token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["pages"] == [] and body["degraded"] is True
    assert body["reason"]


def test_preview_no_png_output_is_200(client, token, doc_id, monkeypatch):
    """PDF 出来了但 pdftoppm 没写出任何 PNG，同样降级而不是返回 count=0 的 200 假象。"""
    _present_tools(monkeypatch)

    def _fake_run(cmd, *a, **k):
        if "soffice" in str(cmd[0]):
            outdir = cmd[cmd.index("--outdir") + 1]
            Path(outdir, "prev.pdf").write_bytes(b"%PDF-1.4\n")  # 只产 PDF，不产 PNG
        return subprocess.CompletedProcess(cmd, 0)

    _stub_run(monkeypatch, _fake_run)
    r = client.post(f"{BASE}/ppt/documents/{doc_id}/preview", headers=_hdr(token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["pages"] == [] and body["count"] == 0
    assert body["degraded"] is True and body["reason"]


def test_preview_render_failure_is_200(client, token, doc_id, monkeypatch):
    """命令存在但执行抛未预期异常（OSError 等）时降级。"""
    _present_tools(monkeypatch)

    def _boom(cmd, *a, **k):
        raise OSError("soffice 启动失败：缺少共享库")

    _stub_run(monkeypatch, _boom)
    r = client.post(f"{BASE}/ppt/documents/{doc_id}/preview", headers=_hdr(token))
    assert r.status_code == 200, r.text
    assert r.json()["degraded"] is True


# ============================================================ 3. 正常路径不回归


def test_preview_success_returns_page_urls(client, token, doc_id, monkeypatch):
    """命令齐备且转换成功时，行为与改动前一致：返回逐页 PNG 路径与页数。"""
    _present_tools(monkeypatch)

    def _fake_run(cmd, *a, **k):
        if "soffice" in str(cmd[0]):
            outdir = cmd[cmd.index("--outdir") + 1]
            Path(outdir, "prev.pdf").write_bytes(b"%PDF-1.4\n")
        elif "pdftoppm" in str(cmd[0]):
            prefix = cmd[-1]                      # .../preview/{doc_id}/pg
            for i in range(1, 4):
                Path(f"{prefix}-{i}.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        return subprocess.CompletedProcess(cmd, 0)

    _stub_run(monkeypatch, _fake_run)
    r = client.post(f"{BASE}/ppt/documents/{doc_id}/preview", headers=_hdr(token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] == 3
    assert body["degraded"] is False
    assert body["pages"] == [f"/api/v1/ppt/preview/{doc_id}/pg-{i}.png"
                             for i in (1, 2, 3)]


# ============================================================ 4. 鉴权与 404


def test_preview_requires_login(client, doc_id):
    r = client.post(f"{BASE}/ppt/documents/{doc_id}/preview")
    assert r.status_code in (401, 403), r.text


def test_preview_missing_document_is_404(client, token, no_renderer):
    """文档不存在仍是 404（不因为降级改造而变成 200 空结果）。"""
    r = client.post(f"{BASE}/ppt/documents/no-such-doc/preview", headers=_hdr(token))
    assert r.status_code == 404, r.text
