"""PPTAgent 渲染下行集成测试：开关驱动 + 失败回退本地渲染。

运行方式（在 server/ 目录下）：
    D:/apps/anaconda3/python.exe -m pytest tests/test_ppt_agent_render.py -v

覆盖三条路径（需求硬性要求）：
  (a) ``PPT_AGENT_URL`` 为空      → 走本地 render_pptx，行为与接入前一致；
  (b) PPTAgent 成功               → 落盘的是 PPTAgent 返回的 pptx；
  (c) PPTAgent 失败/超时/返回垃圾 → 回退本地，且结果仍是能被 python-pptx
                                    打开的**合法 pptx**（绝不返回空文件/占位）。

网络隔离：所有 HTTP 交互经 ``httpx.MockTransport`` 拦截，本文件不依赖真实网络。
层级：直接驱动 PPTService，绕过 HTTP 鉴权，避免与别处的登录态问题相互干扰。
"""
import io
import os
import sys
import tempfile
import time
import uuid
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("AI_PROVIDER", "mock")

_TMPDIR = Path(tempfile.mkdtemp(prefix="test-pptagent-"))
os.environ.setdefault("DATA_DIR", str(_TMPDIR))
os.environ.setdefault("DATABASE_URL", f"sqlite:///{(_TMPDIR / 'test.db').as_posix()}")

from pptx import Presentation  # noqa: E402

from app.application.ppt import ppt_engine  # noqa: E402
from app.application.ppt.service import PPTService  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.domain.identity.entities import User  # noqa: E402
from app.domain.ppt.entities import PPTDocument  # noqa: E402
from app.infrastructure.database import Base, SessionLocal, engine  # noqa: E402
from app.infrastructure.ppt.ppt_agent_client import (  # noqa: E402
    PPTAgentClient, PPTAgentError, build_outline_markdown, looks_like_pptx,
)
from app.infrastructure.repositories.identity import (  # noqa: E402
    SqlAlchemyUserRepository,
)

Base.metadata.create_all(bind=engine)

AGENT_URL = "http://fake-ppt-agent:7861"

_OUTLINE_SRC = {
    "title": "AI 赋能司法行政工作",
    "subtitle": "2026 年试点工作汇报",
    "slides": [
        {"type": "cover", "title": "AI 赋能司法行政工作", "subtitle": "2026 年试点工作汇报"},
        {"type": "content", "title": "建设背景", "points": ["政策要求", "业务需求"]},
        {"type": "content", "title": "实施路径", "points": ["平台搭建", "数据治理"]},
        {"type": "closing", "title": "谢谢聆听，请批评指正"},
    ],
}


# ============================================================ 工具


def _make_pptx_bytes(tag: str, pages: int = 3) -> bytes:
    """用 python-pptx 造一个最小可解析 pptx，正文带 tag 便于区分来源。"""
    from pptx.util import Inches

    prs = Presentation()
    for i in range(pages):
        slide = prs.slides.add_slide(prs.slide_layouts[6])  # 空白版式
        box = slide.shapes.add_textbox(Inches(0.5), Inches(0.5), Inches(8), Inches(1))
        box.text_frame.text = f"{tag}#{i}"
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


def _open_slide_count(data: bytes) -> int:
    """用 python-pptx 真的打开一次，返回页数；打不开会抛异常即测试失败。"""
    return len(Presentation(io.BytesIO(data)).slides)


def _agent_handler(*, submit_status=200, submit_body=None, status_body=None,
                   result_body=None, health_status=200):
    """构造 MockTransport 处理器，模拟 PPTAgent 的 提交/轮询/结果 三步。"""
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.rstrip("/") in ("/docs", "/", "/health"):
            return httpx.Response(health_status, text="<html>ok</html>")
        if path.startswith(settings.PPT_AGENT_SUBMIT_PATH):
            return httpx.Response(submit_status, json=submit_body or {"task_id": "task-1"})
        if path.startswith(settings.PPT_AGENT_STATUS_PATH.replace("/{task_id}", "")):
            return httpx.Response(200, json=status_body or {"status": "completed"})
        if path.startswith(settings.PPT_AGENT_RESULT_PATH.replace("/{task_id}", "")):
            return httpx.Response(200, json=result_body or {})
        return httpx.Response(404, json={"detail": f"unexpected path {path}"})

    return handler


def _install_agent(monkeypatch, handler, *, total_timeout: int = 30,
                   submit_timeout: int = 5, poll_interval: int = 1,
                   workspace_dir: str = ""):
    """把 PPTAgentClient.from_settings 替换为返回注入了 MockTransport 的实例。"""
    mock_transport = httpx.MockTransport(handler)
    base_url = AGENT_URL

    def fake_from_settings(_cls, transport=None):
        # 注意：闭包里的 mock_transport 不能被入参同名遮蔽，否则会发真实请求
        return PPTAgentClient(
            base_url=base_url, transport=transport or mock_transport,
            submit_timeout=submit_timeout, poll_interval=poll_interval,
            total_timeout=total_timeout, workspace_dir=workspace_dir,
            # 契约路径来自 settings，不能让构造函数用旧的 REST 占位默认值
            submit_path=settings.PPT_AGENT_SUBMIT_PATH,
            event_path=settings.PPT_AGENT_EVENT_PATH)

    monkeypatch.setattr(PPTAgentClient, "from_settings", classmethod(fake_from_settings))


@pytest.fixture()
def ctx():
    """每个用例一套干净的服务 + 文档（数据落在临时目录）。"""
    db = SessionLocal()
    svc = PPTService(db, None)
    # 落真实用户行，满足 ppt_documents.user_id 的外键约束（每个用例独立账号）
    uid = uuid.uuid4().hex[:8]
    user = SqlAlchemyUserRepository(db).add(User(
        username=f"pptagent_{uid}", email=f"pptagent_{uid}@test.local",
        hashed_password="x", role="user"))
    outline = ppt_engine.normalize_outline(_OUTLINE_SRC)
    doc = svc.documents.add(PPTDocument(
        user_id=user.id, title=outline.get("title", "") or "未命名",
        subtitle=outline.get("subtitle", ""), source_type="topic",
        source_content="原始素材：白云区司法局信息化建设情况综述",
        outline=outline, status="draft"))
    try:
        yield svc, doc, user
    finally:
        db.close()


# ============================================================ (a) URL 为空 → 本地渲染


def test_a_empty_url_uses_local_render(monkeypatch, ctx):
    """PPT_AGENT_URL 为空时必须完全走本地渲染，且不产生任何 HTTP 调用。"""
    svc, doc, user = ctx
    monkeypatch.setattr(settings, "PPT_AGENT_URL", "")
    called = []

    def boom(*a, **k):  # 任何来自 PPTAgent 的调用都视为回归
        called.append(True)
        raise AssertionError("PPT_AGENT_URL 为空时不该调用 PPTAgentClient")

    monkeypatch.setattr(PPTAgentClient, "from_settings", classmethod(boom))

    template, trow = svc._resolve_template(None, doc.theme_id or "")
    outline = doc.outline
    data, renderer = svc._render_pptx_bytes(doc, outline, template, None)

    assert renderer == "local", "应走本地渲染"
    assert not called
    ok, why = looks_like_pptx(data)
    assert ok, why
    # 本地渲染结果页数应与大纲一致
    assert _open_slide_count(data) == len(outline["slides"])


def test_a_empty_url_round_trip_persists(monkeypatch, ctx):
    """空配置下 _render_and_store 落盘行为与接入前一致（generated + file_path）。"""
    svc, doc, user = ctx
    monkeypatch.setattr(settings, "PPT_AGENT_URL", "")

    path = svc._render_and_store(doc, doc.outline, user, None)

    assert Path(path).exists()
    assert doc.status == "generated"
    assert doc.file_path == path
    assert doc.slide_count == len(doc.outline["slides"])
    assert _open_slide_count(Path(path).read_bytes()) >= 1


# ============================================================ (b) PPTAgent 成功


def test_b_agent_success_stores_agent_pptx(monkeypatch, ctx):
    """PPTAgent 成功：落盘的必须是它返回的那个 pptx（字节一致且可打开）。"""
    svc, doc, user = ctx
    agent_pptx = _make_pptx_bytes("AGENT")
    monkeypatch.setattr(settings, "PPT_AGENT_URL", AGENT_URL)
    _install_agent(monkeypatch, _agent_handler(
        submit_body={"task_id": "T-100"},
        status_body={"status": "completed"},
        result_body={"download_url": "/files/T-100.pptx"},
    ))
    # 让 /files/... 下载也走同一个 handler：在 handler 里补一条分支
    transport_hits = []

    orig_handler = _agent_handler(
        submit_body={"task_id": "T-100"},
        status_body={"status": "completed"},
        result_body={"download_url": "/files/T-100.pptx"},
    )

    def handler(request: httpx.Request) -> httpx.Response:
        transport_hits.append(request.url.path)
        if request.url.path == "/files/T-100.pptx":
            return httpx.Response(200, content=agent_pptx,
                                  headers={"content-type": "application/octet-stream"})
        return orig_handler(request)

    _install_agent(monkeypatch, handler)

    template, _trow = svc._resolve_template(None, doc.theme_id or "")
    data, renderer = svc._render_pptx_bytes(doc, doc.outline, template, None)

    assert renderer == "pptagent", "应走 PPTAgent 渲染"
    assert data == agent_pptx, "落盘字节必须是 PPTAgent 返回的 pptx"
    assert _open_slide_count(data) == 3
    # 三步（健康探测 / 提交 / 轮询 / 取结果）都应真实发生
    assert any(p.startswith(settings.PPT_AGENT_SUBMIT_PATH) for p in transport_hits)
    assert any("/status/" in p for p in transport_hits)
    assert any("/result/" in p for p in transport_hits)

    path = svc._render_and_store(doc, doc.outline, user, None)
    assert Path(path).read_bytes() == agent_pptx


def test_b_agent_binary_result_direct(monkeypatch, ctx):
    """结果端点直接返回二进制 pptx（无 JSON 包裹）时也能正确识别。"""
    svc, doc, _user = ctx
    agent_pptx = _make_pptx_bytes("BIN")
    monkeypatch.setattr(settings, "PPT_AGENT_URL", AGENT_URL)

    base = _agent_handler(submit_body={"id": "T-200"},
                          status_body={"state": "success"})

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.startswith(
                settings.PPT_AGENT_RESULT_PATH.replace("/{task_id}", "")):
            return httpx.Response(
                200, content=agent_pptx,
                headers={"content-type":
                         "application/vnd.openxmlformats-officedocument"
                         ".presentationml.presentation"})
        return base(request)

    _install_agent(monkeypatch, handler)
    template, _trow = svc._resolve_template(None, doc.theme_id or "")
    data, renderer = svc._render_pptx_bytes(doc, doc.outline, template, None)
    assert renderer == "pptagent"
    assert data == agent_pptx
    assert _open_slide_count(data) == 3


def test_b_gradio_files_response_json_wrapper(monkeypatch, ctx):
    """Gradio FileData 形态的结果也能正确解析（含 data 数组与 url/path）。"""
    svc, doc, user = ctx
    agent_pptx = _make_pptx_bytes("GRADIO")
    monkeypatch.setattr(settings, "PPT_AGENT_URL", AGENT_URL)
    result_body = {"data": [{"path": "/tmp/gradio/x.pptx",
                             "url": "/gradio_api/file=/tmp/gradio/x.pptx",
                             "orig_name": "x.pptx",
                             "meta": {"_type": "gradio.FileData"}}]}
    base = _agent_handler(submit_body={"task_id": "T-600"},
                          status_body={"status": "completed"},
                          result_body=result_body)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/gradio_api/file=/tmp/gradio/x.pptx":
            return httpx.Response(200, content=agent_pptx,
                                  headers={"content-type": "application/octet-stream"})
        return _handler_orig(request)

    _handler_orig = _agent_handler(
        submit_body={"task_id": "T-600"},
        status_body={"status": "completed"},
        result_body={"data": [{"url": "/gradio_api/file=/tmp/gradio/x.pptx"}]})
    _install_agent(monkeypatch, handler)

    template, _trow = svc._resolve_template(None, doc.theme_id or "")
    data, renderer = svc._render_pptx_bytes(doc, doc.outline, template, None)
    assert renderer == "pptagent"
    assert data == agent_pptx
    assert _open_slide_count(data) == 3


def test_b_gradio_one_shot_submit_returns_file(monkeypatch, ctx):
    """Gradio 同步端点：提交一次就把成品带回响应体 → 自动跳过轮询。"""
    svc, doc, user = ctx
    agent_pptx = _make_pptx_bytes("ONESHOT")
    monkeypatch.setattr(settings, "PPT_AGENT_URL", AGENT_URL)
    polled = []
    base = _agent_handler()

    def handler(request: httpx.Request) -> httpx.Response:
        if "/status/" in request.url.path:
            polled.append(request.url.path)
        if request.url.path.startswith(settings.PPT_AGENT_SUBMIT_PATH):
            return httpx.Response(200, json={"data": [{
                "url": "/gradio_api/file=/tmp/gradio/one.pptx"}]})
        if request.url.path == "/gradio_api/file=/tmp/gradio/one.pptx":
            return httpx.Response(200, content=agent_pptx,
                                  headers={"content-type": "application/octet-stream"})
        return base(request)

    _install_agent(monkeypatch, handler)
    template, _trow = svc._resolve_template(None, doc.theme_id or "")
    data, renderer = svc._render_pptx_bytes(doc, doc.outline, template, None)
    assert renderer == "pptagent"
    assert data == agent_pptx
    assert not polled, "提交即拿结果时不应再轮询状态"


# ============================================================ 共享卷取产物通道


def _seed_workspace(root: Path, payload: bytes, *, age_seconds: float = 0.0,
                    job: str = "job-abc", filename: str = "presentation.pptx") -> Path:
    """造一个 PPTAgent 风格的产物目录：<root>/<日期>/<job>/<文件>。

    ``filename`` 默认 ``presentation.pptx``（老约定），真机实测产物名是**中文标题**
    （如 ``司法局工作汇报.pptx``），故允许显式指定以覆盖动态标题场景。
    """
    job_dir = root / time.strftime("%Y-%m-%d") / job
    job_dir.mkdir(parents=True, exist_ok=True)
    f = job_dir / filename
    f.write_bytes(payload)
    stamp = time.time() - age_seconds
    os.utime(f, (stamp, stamp))
    return f


def test_workspace_channel_returns_product(monkeypatch, ctx, tmp_path):
    """配了共享卷目录 → 提交后直接扫文件系统取最新产物，不走结果端点。"""
    svc, doc, user = ctx
    agent_pptx = _make_pptx_bytes("WORKSPACE")
    _seed_workspace(tmp_path, agent_pptx)
    monkeypatch.setattr(settings, "PPT_AGENT_URL", AGENT_URL)

    polled_status = []
    base = _agent_handler(submit_body={"task_id": "T-WS"})

    def handler(request: httpx.Request) -> httpx.Response:
        if "/status/" in request.url.path or "/result/" in request.url.path:
            polled_status.append(request.url.path)
        return base(request)

    _install_agent(monkeypatch, handler, workspace_dir=str(tmp_path),
                   total_timeout=20, poll_interval=1)

    template, _trow = svc._resolve_template(None, doc.theme_id or "")
    data, renderer = svc._render_pptx_bytes(doc, doc.outline, template, None)
    assert renderer == "pptagent"
    assert data == agent_pptx
    assert not polled_status, "共享卷通道下不该再查状态/结果端点"
    assert _open_slide_count(data) == 3


def test_workspace_channel_picks_newest_and_ignores_stale(monkeypatch, ctx, tmp_path):
    """旧产物（早于本次提交）必须被忽略，只认本次新落盘的那个。"""
    svc, doc, user = ctx
    stale_pptx = _make_pptx_bytes("STALE")
    fresh_pptx = _make_pptx_bytes("FRESH")
    _seed_workspace(tmp_path, stale_pptx, age_seconds=3600, job="job-old")
    _seed_workspace(tmp_path, fresh_pptx, age_seconds=0, job="job-new")
    monkeypatch.setattr(settings, "PPT_AGENT_URL", AGENT_URL)
    _install_agent(monkeypatch, _agent_handler(submit_body={"task_id": "T-WS2"}),
                   workspace_dir=str(tmp_path), total_timeout=20, poll_interval=1)

    template, _trow = svc._resolve_template(None, doc.theme_id or "")
    data, renderer = svc._render_pptx_bytes(doc, doc.outline, template, None)
    assert renderer == "pptagent"
    assert data == fresh_pptx


def test_workspace_channel_finds_dynamic_chinese_title(monkeypatch, ctx, tmp_path):
    """真机产物名是 `<标题>.pptx`（中文动态），不能再写死 presentation.pptx。

    同时在该目录里放 Office 锁文件 `~$...` 与一个半成品，验证两者都被跳过、
    仍能准确取到真正的成品。
    """
    svc, doc, user = ctx
    agent_pptx = _make_pptx_bytes("中文标题产物")
    _seed_workspace(tmp_path, agent_pptx, job="f8439174",
                    filename="司法局工作汇报.pptx")
    # 干扰项：Office 锁文件 + 一个只有几 KB 的空壳 pptx
    _seed_workspace(tmp_path, b"0" * 512, job="f8439174", filename="~$司法局工作汇报.pptx")
    _seed_workspace(tmp_path, b"0" * 512, job="f8439174", filename="草稿.pptx")
    monkeypatch.setattr(settings, "PPT_AGENT_URL", AGENT_URL)
    _install_agent(monkeypatch, _agent_handler(submit_body={"task_id": "T-TITLE"}),
                   workspace_dir=str(tmp_path), total_timeout=20, poll_interval=1)

    template, _trow = svc._resolve_template(None, doc.theme_id or "")
    data, renderer = svc._render_pptx_bytes(doc, doc.outline, template, None)
    assert renderer == "pptagent"
    assert data == agent_pptx, "必须取到那个能通过 pptx 校验的成品"


def test_workspace_channel_half_written_then_timeout_falls_back(monkeypatch, ctx, tmp_path):
    """产物是半包/垃圾文件时不认，等到超时后回退本地渲染。"""
    svc, doc, user = ctx
    _seed_workspace(tmp_path, b"<html>still writing</html>")
    monkeypatch.setattr(settings, "PPT_AGENT_URL", AGENT_URL)
    _install_agent(monkeypatch, _agent_handler(submit_body={"task_id": "T-WS3"}),
                   workspace_dir=str(tmp_path), total_timeout=3, poll_interval=1)

    template, _trow = svc._resolve_template(None, doc.theme_id or "")
    data, renderer = svc._render_pptx_bytes(doc, doc.outline, template, None)
    assert renderer == "local", "非法产物应触发超时并回退"
    assert _open_slide_count(data) == len(doc.outline["slides"])


def test_workspace_dir_missing_falls_back(monkeypatch, ctx, tmp_path):
    """目录挂不上（路径不存在）→ 立即回退本地渲染，不能把错误抛给用户。"""
    svc, doc, user = ctx
    monkeypatch.setattr(settings, "PPT_AGENT_URL", AGENT_URL)
    _install_agent(monkeypatch, _agent_handler(submit_body={"task_id": "T-WS4"}),
                   workspace_dir=str(tmp_path / "not-mounted"),
                   total_timeout=10, poll_interval=1)

    template, _trow = svc._resolve_template(None, doc.theme_id or "")
    data, renderer = svc._render_pptx_bytes(doc, doc.outline, template, None)
    assert renderer == "local"
    assert looks_like_pptx(data)[0]


# ============================================================ (c) 失败 → 回退本地


@pytest.mark.parametrize("mode", ["500", "network_down", "invalid_file", "no_task_id"])
def test_c_agent_failure_falls_back_to_valid_local(monkeypatch, ctx, mode):
    """各类失败都必须回退本地渲染，且产物是合法 pptx。"""
    svc, doc, user = ctx
    monkeypatch.setattr(settings, "PPT_AGENT_URL", AGENT_URL)

    if mode == "500":
        handler = _agent_handler(submit_status=500, submit_body={"detail": "boom"})
    elif mode == "network_down":
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused")
    elif mode == "invalid_file":
        handler = _agent_handler(submit_body={"task_id": "T-9"},
                                 status_body={"status": "completed"})
    else:  # no_task_id
        handler = _agent_handler(submit_body={"message": "accepted"})

    if mode == "invalid_file":
        base = handler

        def handler(request: httpx.Request) -> httpx.Response:  # noqa: F811
            if request.url.path.startswith(
                    settings.PPT_AGENT_RESULT_PATH.replace("/{task_id}", "")):
                # 典型的假接通：返回 HTML 错误页却自称 200
                return httpx.Response(200, text="<html>Internal Error</html>",
                                      headers={"content-type": "text/html"})
            return base(request)

    _install_agent(monkeypatch, handler, total_timeout=20, poll_interval=1)

    template, _trow = svc._resolve_template(None, doc.theme_id or "")
    data, renderer = svc._render_pptx_bytes(doc, doc.outline, template, None)

    assert renderer == "local", f"{mode} 场景应回退本地渲染"
    ok, why = looks_like_pptx(data)
    assert ok, f"{mode} 回退产物必须是合法 pptx：{why}"
    assert _open_slide_count(data) == len(doc.outline["slides"])

    path = svc._render_and_store(doc, doc.outline, user, None)
    assert _open_slide_count(Path(path).read_bytes()) >= 1


def test_c_agent_timeout_falls_back(monkeypatch, ctx):
    """状态长期 running → 整体超时 → 回退本地渲染。"""
    svc, doc, user = ctx
    monkeypatch.setattr(settings, "PPT_AGENT_URL", AGENT_URL)
    _install_agent(monkeypatch,
                   _agent_handler(submit_body={"task_id": "T-300"},
                                  status_body={"status": "running"}),
                   total_timeout=3, submit_timeout=1, poll_interval=1)

    template, _trow = svc._resolve_template(None, doc.theme_id or "")
    data, renderer = svc._render_pptx_bytes(doc, doc.outline, template, None)

    assert renderer == "local"
    assert _open_slide_count(data) == len(doc.outline["slides"])


def test_c_agent_task_failed_status_falls_back(monkeypatch, ctx):
    """任务明确返回 failed → 立即回退，不必等到超时。"""
    svc, doc, _user = ctx
    monkeypatch.setattr(settings, "PPT_AGENT_URL", AGENT_URL)
    _install_agent(monkeypatch,
                   _agent_handler(submit_body={"task_id": "T-400"},
                                  status_body={"status": "failed"}),
                   total_timeout=30, poll_interval=1)

    template, _trow = svc._resolve_template(None, doc.theme_id or "")
    data, renderer = svc._render_pptx_bytes(doc, doc.outline, template, None)
    assert renderer == "local"
    assert looks_like_pptx(data)[0]


def test_c_health_check_failure_falls_back(monkeypatch, ctx):
    """健康探测不通过（如服务 502 下线）→ 回退本地渲染。"""
    svc, doc, _user = ctx
    monkeypatch.setattr(settings, "PPT_AGENT_URL", AGENT_URL)
    _install_agent(monkeypatch,
                   _agent_handler(health_status=502), total_timeout=20)

    template, _trow = svc._resolve_template(None, doc.theme_id or "")
    data, renderer = svc._render_pptx_bytes(doc, doc.outline, template, None)
    assert renderer == "local"
    assert looks_like_pptx(data)[0]


# ============================================================ 纯单元


def test_looks_like_pptx_rejects_common_junk():
    """校验器必须拦住 HTML 错误页 / JSON / 空字节 / 假 zip。"""
    ok, _ = looks_like_pptx(_make_pptx_bytes("REAL"))
    assert ok is True
    for junk in (b"", b"<html>boom</html>", b'{"error":"x"}', b"\x50\x4b\x05\x06xxxxxx"):
        ok, _why = looks_like_pptx(junk)
        assert ok is False


def test_build_outline_markdown_contains_all_pages():
    """大纲 → Markdown：标题、每页标题与要点都不丢失。"""
    md = build_outline_markdown(ppt_engine.normalize_outline(_OUTLINE_SRC))
    assert "AI 赋能司法行政工作" in md
    assert "2026 年试点工作汇报" in md
    for t in ("建设背景", "实施路径", "谢谢聆听，请批评指正"):
        assert t in md
    for p in ("政策要求", "业务需求", "平台搭建", "数据治理"):
        assert p in md


def test_agent_error_is_runtime_error():
    """失败信号类型须为 RuntimeError 子类，方便调用方统一兜底。"""
    assert issubclass(PPTAgentError, RuntimeError)
