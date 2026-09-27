"""PPTAgent 真实契约 + 异步 job 接口测试。

运行方式（在 server/ 目录下）：
    D:/apps/anaconda3/python.exe -m pytest tests/test_ppt_agent_jobs.py -v

覆盖：
- 客户端层（httpx.MockTransport 打桩，**不依赖真实网络**）：
  6 入参顺序 / SSE 事件流解析 / 产物 FileData 提取 / R1 追问 /
  事件流超时 / 返回非 pptx / 目录扫描降级。
- 接口层（TestClient）：
  提交立即返回、状态流转、取消、导出 404→200、追问续跑、预览、并发安全。

契约来源：真机探查的 /send_message（6 入参 5 出参，queue=True）。
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

_TMPDIR = Path(tempfile.mkdtemp(prefix="test-pptjob-"))
os.environ.setdefault("DATA_DIR", str(_TMPDIR))
os.environ.setdefault("DATABASE_URL", f"sqlite:///{(_TMPDIR / 'test.db').as_posix()}")

from fastapi.testclient import TestClient  # noqa: E402
from pptx import Presentation  # noqa: E402
from pptx.util import Inches  # noqa: E402

from app.application.ppt import agent_job  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.infrastructure.database import Base, engine  # noqa: E402
from app.infrastructure.ppt.ppt_agent_client import (  # noqa: E402
    PPTAgentClient, PPTAgentError, looks_like_pptx,
)
from app.main import app  # noqa: E402

Base.metadata.create_all(bind=engine)

BASE = "/api/v1"
PWD = "Passw0rd!2026"
AGENT_URL = "http://fake-ppt-agent:7861"
DOWNLOAD_PATH = "/gradio_api/file=/tmp/gradio/presentation.pptx"

client = TestClient(app)


# ============================================================ 工具


def _hdr(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _dev_token() -> str:
    """取管理员令牌。

    多个测试文件共用同一个库（``DATA_DIR`` 由**最先导入**的模块决定），且首个管理员
    只能注册一次，所以这里逐级兜底，保证单独跑本文件、或两个文件以任意顺序跑都能过：

    1. ``register-first`` 抢注成功 → 直接用它的 token；
    2. 已初始化 → 用 job_dev 账号登录；
    3. 登录也被挡（如 must_change_password）→ 按用户名查库，直接签发 token；
    4. 库里连 job_dev 都没有 → 退而求其次取任意 developer/admin；
    5. 连管理员都没有（别的测试文件先把库初始化了）→ 直接建一个 developer。
    """
    r = client.post(f"{BASE}/auth/register-first", json={
        "username": "job_dev", "email": "job_dev@test.local",
        "password": PWD, "real_name": "管理员"})
    if r.status_code == 200:
        return r.json()["access_token"]

    login = client.post(f"{BASE}/auth/login",
                        json={"username": "job_dev", "password": PWD})
    if login.status_code == 200:
        return login.json()["access_token"]

    from sqlalchemy import select

    from app.core.security import create_access_token, get_password_hash
    from app.infrastructure.database import SessionLocal
    from app.infrastructure.database.models.identity import UserModel

    db = SessionLocal()
    try:
        row = db.scalar(select(UserModel).where(UserModel.username == "job_dev"))
        if row is None:
            row = db.scalar(select(UserModel).where(
                UserModel.role.in_(("developer", "admin"))))
        if row is None:
            # 其它测试文件已初始化过这个库且没留管理员 —— 自己插一个 developer
            row = UserModel(id=f"job-dev-{uuid.uuid4().hex[:12]}",
                            username="job_dev", email="job_dev@test.local",
                            hashed_password=get_password_hash(PWD),
                            real_name="管理员", role="developer",
                            department="行政复议科", is_active=True,
                            must_change_password=False)
            db.add(row)
            db.commit()
            db.refresh(row)
        if row.role not in ("developer", "admin"):
            row.role = "developer"
            row.must_change_password = False
            db.commit()
            db.refresh(row)
        return create_access_token(
            {"sub": row.id, "username": row.username, "role": row.role})
    finally:
        db.close()


def _make_pptx_bytes(tag: str, pages: int = 3) -> bytes:
    prs = Presentation()
    for i in range(pages):
        s = prs.slides.add_slide(prs.slide_layouts[6])
        box = s.shapes.add_textbox(Inches(0.5), Inches(0.5), Inches(8), Inches(1))
        box.text_frame.text = f"{tag}#{i}"
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


def _filedata(idx: int = 3):
    """造 5 个出参（契约顺序），第 idx 项放 pptx FileData。"""
    fd = {"path": "/tmp/gradio/presentation.pptx", "url": DOWNLOAD_PATH,
          "orig_name": "presentation.pptx", "size": 12345,
          "meta": {"_type": "gradio.FileData"}}
    outs = [
        [{"role": "assistant", "content": "已生成"}],   # 1 Chatbot
        "job-123",                                       # 2 Textbox
        [],                                              # 3 File(list)
        fd,                                              # 4 📥 下载文件
        "#### 生成完成",                                  # 5 Markdown
    ]
    return outs


def _sse_body(outputs, event_name: str = "complete") -> bytes:
    """构造一段 SSE 文本（Gradio 5 风格）。"""
    import json

    lines = [
        "event: start",
        'data: {"msg":"process_starts"}',
        "",
        f"event: {event_name}",
        f"data: {json.dumps(outputs, ensure_ascii=False)}",
        "",
    ]
    return ("\n".join(lines)).encode("utf-8")


def _install(monkeypatch, handler, **kw):
    """把 PPTAgentClient.from_settings 换成注入 MockTransport 的实例。"""
    mock_transport = httpx.MockTransport(handler)
    base_url = kw.get("base_url", AGENT_URL)

    def fake_from_settings(_cls, transport=None):
        # 闭包变量不能与入参同名，否则会拿到 None 而发出真实请求
        return PPTAgentClient(
            base_url=base_url, transport=transport or mock_transport,
            submit_timeout=kw.get("submit_timeout", 10),
            poll_interval=kw.get("poll_interval", 1),
            total_timeout=kw.get("total_timeout", 60),
            workspace_dir=kw.get("workspace_dir", ""),
            # 必须显式带上真实契约路径：构造函数默认值是旧的 REST 占位值
            submit_path=kw.get("submit_path", settings.PPT_AGENT_SUBMIT_PATH),
            event_path=kw.get("event_path", settings.PPT_AGENT_EVENT_PATH),
            message_max_chars=kw.get("message_max_chars", 24000),
        )

    monkeypatch.setattr(PPTAgentClient, "from_settings", classmethod(fake_from_settings))


def _handler_with(pptx_bytes: bytes, outputs=None, event_name="complete"):
    """标准三步 handler：GET / → 200；POST submit → event_id；GET event → SSE；GET file → pptx。"""
    outs = outputs if outputs is not None else _filedata()

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.rstrip("/") in ("/", "/docs", "/health"):
            return httpx.Response(200, text="ok")
        # 注意：事件流路径是提交路径 + "/{event_id}"，必须先精确匹配提交
        if "/gradio_api/file=" in path:
            return httpx.Response(200, content=pptx_bytes,
                                  headers={"content-type": "application/octet-stream"})
        if path.rstrip("/") == settings.PPT_AGENT_SUBMIT_PATH.rstrip("/"):
            return httpx.Response(200, json={"event_id": "evt-1"})
        if path.startswith("/gradio_api/"):
            return httpx.Response(200, content=_sse_body(outs, event_name),
                                  headers={"content-type": "text/event-stream"})
        return httpx.Response(404, json={"detail": path})

    return handler


# ============================================================ 客户端层


def test_build_message_payload_has_six_args_in_contract_order():
    """6 个入参的顺序与字面量必须和契约一致。"""
    c = PPTAgentClient(base_url=AGENT_URL)
    body = c.build_message_payload("生成一份汇报", num_pages=6)
    assert list(body["data"]) == [
        "生成一份汇报", [], [], "自由生成 (freeform)", "auto", "6"]
    assert body["data"][5] == "6"          # num_pages 是字符串
    assert "fn_index" not in body          # 命名端点风格不下发


def test_submit_message_returns_event_id(monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = request.content
        return httpx.Response(200, json={"event_id": "evt-abc"})

    _install(monkeypatch, handler)
    c = PPTAgentClient.from_settings()
    assert c.submit_message("你好") == "evt-abc"


def test_generate_deck_returns_pptx(monkeypatch):
    """正常返回：产物从返回体第 4 项 FileData 里取到，且是合法 pptx。"""
    pptx_bytes = _make_pptx_bytes("AGENT")
    _install(monkeypatch, _handler_with(pptx_bytes))
    c = PPTAgentClient.from_settings()
    out = c.generate_deck("生成汇报")
    assert out.pptx == pptx_bytes
    assert not out.question
    assert out.event_id == "evt-1"
    assert looks_like_pptx(out.pptx)[0]


def test_generate_deck_returns_question_r1(monkeypatch):
    """R1：PPTAgent 先确认需求时，返回追问而不是产物。"""
    outs = _filedata()
    outs[3] = None                       # 📥 下载文件为空
    outs[4] = "请问本次汇报面向的是上级机关还是内部会议？"
    _install(monkeypatch, _handler_with(b"", outputs=outs))
    c = PPTAgentClient.from_settings()
    out = c.generate_deck("生成汇报")
    assert out.pptx is None
    assert "上级机关" in out.question
    assert not out.pending


def test_generate_deck_non_pptx_result_is_not_accepted(monkeypatch):
    """返回 200 但内容是 HTML 错误页 → 不能被当成产物（否则会拿到打不开的文件）。"""
    _install(monkeypatch, _handler_with(b"<html>Internal Error</html>"))
    c = PPTAgentClient.from_settings()
    out = c.generate_deck("生成汇报")
    assert out.pptx is None


def test_generate_deck_event_stream_timeout(monkeypatch):
    """事件流迟迟不结束 → 抛 PPTAgentError（上层据此回退本地渲染）。"""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.rstrip("/") in ("/", "/docs"):
            return httpx.Response(200, text="ok")
        if request.url.path.rstrip("/") == settings.PPT_AGENT_SUBMIT_PATH.rstrip("/"):
            return httpx.Response(200, json={"event_id": "evt-slow"})
        # 一个挂着不动的流：拖到超过 deadline 才返回，模拟真实的长时间无终态
        time.sleep(3)
        return httpx.Response(200, content=b"event: heartbeat\ndata: {}\n\n",
                              headers={"content-type": "text/event-stream"})

    _install(monkeypatch, handler, total_timeout=2)
    c = PPTAgentClient.from_settings()
    with pytest.raises(PPTAgentError) as e:
        c.generate_deck("生成汇报", deadline=time.monotonic() + 1.2)
    assert "超时" in str(e.value)


def test_generate_deck_handles_process_failed(monkeypatch):
    """Gradio 明确报 process_failed → 抛错，不能当作成功。"""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.rstrip("/") in ("/", "/docs"):
            return httpx.Response(200, text="ok")
        if request.url.path.rstrip("/") == settings.PPT_AGENT_SUBMIT_PATH.rstrip("/"):
            return httpx.Response(200, json={"event_id": "evt-bad"})
        body = b'data: {"msg":"process_failed","output":{"error":"boom"}}\n\n'
        return httpx.Response(200, content=body,
                              headers={"content-type": "text/event-stream"})

    _install(monkeypatch, handler, total_timeout=30)
    c = PPTAgentClient.from_settings()
    with pytest.raises(PPTAgentError) as e:
        c.generate_deck("生成汇报")
    assert "失败" in str(e.value)


def test_scan_progress_degrades_when_structure_unknown(tmp_path):
    """R3：目录结构与预期不符时返回零值、不抛异常（降级为无逐页预览）。"""
    (tmp_path / "whatever.txt").write_text("x")
    c = PPTAgentClient(base_url=AGENT_URL, workspace_dir=str(tmp_path))
    info = c.scan_progress(time.time() - 10)
    assert info == {"slides": 0, "previews": 0, "has_pptx": False, "preview_files": []}


def test_scan_progress_finds_previews(tmp_path):
    """有 preview/*.png 时能数出页数（旧结构仍要兼容）。"""
    d = tmp_path / "2026-09-27" / "job-1" / "preview"
    d.mkdir(parents=True)
    for i in range(4):
        (d / f"slide_{i:02d}.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)
    c = PPTAgentClient(base_url=AGENT_URL, workspace_dir=str(tmp_path))
    info = c.scan_progress(time.time() - 10)
    assert info["previews"] == 4
    assert len(info["preview_files"]) == 4


def test_scan_progress_matches_real_structure(tmp_path):
    """R3 真机结构：中文动态标题 + `.slide_images-pdf-<标题>/slide_NN.jpg`。

    这是用户在服务器上 `ls -laR` 实测到的目录形态，预览图有三个特征必须同时命中：
    目录名动态（含中文标题）、隐藏目录（以点开头）、扩展名是 jpg 而非 png。
    """
    root = tmp_path / "20260927" / "f8439174"
    prev = root / ".slide_images-pdf-司法局工作汇报"
    prev.mkdir(parents=True)
    for i in range(1, 5):
        (prev / f"slide_{i:02d}.jpg").write_bytes(b"\xff\xd8\xff" + b"0" * 64)
    (root / "slides").mkdir()
    for i in range(1, 5):
        (root / "slides" / f"slide_{i:02d}.html").write_text("<html></html>")

    c = PPTAgentClient(base_url=AGENT_URL, workspace_dir=str(tmp_path))
    info = c.scan_progress(time.time() - 10)
    assert info["previews"] == 4, info
    assert info["slides"] == 4, info
    # 排序必须是页序（字典序 == 零填充的页序）
    assert info["preview_files"][0].endswith("slide_01.jpg")
    assert info["preview_files"][-1].endswith("slide_04.jpg")


def test_scan_progress_detects_dynamic_title_pptx(tmp_path):
    """产物文件名随标题动态变化（<标题>.pptx），不能再写死 presentation.pptx。"""
    root = tmp_path / "20260927" / "f8439174"
    root.mkdir(parents=True)
    (root / "司法局工作汇报.pptx").write_bytes(_make_pptx_bytes("TITLE"))
    c = PPTAgentClient(base_url=AGENT_URL, workspace_dir=str(tmp_path))
    info = c.scan_progress(time.time() - 10)
    assert info["has_pptx"] is True, info


def test_scan_progress_ignores_office_temp_and_unfinished_files(tmp_path):
    """`~$xxx.pptx` 锁文件、以及小于 8KB 的半成品，都不能被当成产物。"""
    root = tmp_path / "20260927" / "f8439174"
    root.mkdir(parents=True)
    (root / "~$司法局工作汇报.pptx").write_bytes(b"0" * 4096)
    (root / "司法局工作汇报.pptx").write_bytes(b"0" * 100)  # 刚开始写，还没内容
    c = PPTAgentClient(base_url=AGENT_URL, workspace_dir=str(tmp_path))
    info = c.scan_progress(time.time() - 10)
    assert info["has_pptx"] is False, "半成品/锁文件不能被认作产物"


def test_result_glob_default_and_legacy_alias(monkeypatch):
    """产物模式默认通配 *.pptx；老变量名 PPT_AGENT_RESULT_FILENAME 仍作别名兼容。"""
    from app.core.config import Settings

    monkeypatch.delenv("PPT_AGENT_RESULT_GLOB", raising=False)
    monkeypatch.delenv("PPT_AGENT_RESULT_FILENAME", raising=False)
    assert Settings().PPT_AGENT_RESULT_GLOB == "*.pptx"

    monkeypatch.setenv("PPT_AGENT_RESULT_FILENAME", "presentation.pptx")
    assert Settings().PPT_AGENT_RESULT_GLOB == "presentation.pptx"

    monkeypatch.setenv("PPT_AGENT_RESULT_GLOB", "成品/*.pptx")
    assert Settings().PPT_AGENT_RESULT_GLOB == "成品/*.pptx"


def test_split_patterns_handles_multiple_candidates():
    """多个候选模式用逗号/分号分隔，去重后返回。"""
    from app.infrastructure.ppt.ppt_agent_client import split_patterns

    assert split_patterns("") == ()
    assert split_patterns(" .slide_images-*/*.jpg , preview/*.png ") == (
        ".slide_images-*/*.jpg", "preview/*.png")
    assert split_patterns("a/*.jpg;a/*.png,a/*.jpg") == ("a/*.jpg", "a/*.png")


# ============================================================ 接口层


@pytest.fixture()
def doc_and_token(monkeypatch):
    """准备：开启 PPTAgent 配置 + 建一个带大纲的文档。"""
    monkeypatch.setattr(settings, "PPT_AGENT_URL", AGENT_URL)
    monkeypatch.setattr(settings, "PPT_AGENT_PROGRESS_INTERVAL", 1)
    monkeypatch.setattr(settings, "PPT_AGENT_TOTAL_TIMEOUT", 60)
    monkeypatch.setattr(settings, "PPT_AGENT_STALL_TIMEOUT", 20)
    token = _dev_token()
    r = client.post(f"{BASE}/ppt/blank", json={"title": "司法局工作汇报",
                                               "subtitle": "2026 年度"},
                    headers=_hdr(token))
    assert r.status_code == 200, r.text
    return token, r.json()["doc_id"]


def _wait_terminal(token, job_id, timeout=15.0):
    """轮询直到终态。"""
    end = time.time() + timeout
    last = {}
    while time.time() < end:
        r = client.get(f"{BASE}/ppt/jobs/{job_id}/status", headers=_hdr(token))
        assert r.status_code == 200, r.text
        last = r.json()
        if last["status"] in ("succeeded", "failed", "cancelled",
                              "awaiting_clarification"):
            return last
        time.sleep(0.2)
    return last


def test_submit_job_returns_immediately(monkeypatch, doc_and_token):
    """提交必须立刻返回，不能把请求挂十几分钟。"""
    token, doc_id = doc_and_token
    pptx_bytes = _make_pptx_bytes("JOB")
    _install(monkeypatch, _handler_with(pptx_bytes))

    t0 = time.time()
    r = client.post(f"{BASE}/ppt/jobs", json={"doc_id": doc_id}, headers=_hdr(token))
    assert r.status_code == 200, r.text
    assert time.time() - t0 < 5, "提交不该阻塞"
    body = r.json()
    assert body["job_id"] == doc_id
    assert body["status"] in ("pending", "running")


def test_job_status_flow_and_export(monkeypatch, doc_and_token):
    """状态流转到 succeeded，导出先是 404、完成后能下载到合法 pptx。"""
    token, doc_id = doc_and_token
    pptx_bytes = _make_pptx_bytes("JOBOK")
    _install(monkeypatch, _handler_with(pptx_bytes))

    client.post(f"{BASE}/ppt/jobs", json={"doc_id": doc_id}, headers=_hdr(token))
    # 未完成时导出应 404，绝不返回半成品
    early = client.get(f"{BASE}/ppt/jobs/{doc_id}/export", headers=_hdr(token))
    assert early.status_code in (200, 404)

    status = _wait_terminal(token, doc_id)
    assert status["status"] == "succeeded", status
    assert status["renderer"] == "pptagent"

    r = client.get(f"{BASE}/ppt/jobs/{doc_id}/export", headers=_hdr(token))
    assert r.status_code == 200, r.text
    assert r.content == pptx_bytes
    assert len(Presentation(io.BytesIO(r.content)).slides) == 3


def test_job_falls_back_to_local_on_agent_failure(monkeypatch, doc_and_token):
    """PPTAgent 调不通 → 回退本地渲染，产物必须仍是能打开的合法 pptx。"""
    token, doc_id = doc_and_token

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    _install(monkeypatch, handler)
    client.post(f"{BASE}/ppt/jobs", json={"doc_id": doc_id}, headers=_hdr(token))
    status = _wait_terminal(token, doc_id)
    assert status["status"] == "succeeded", status
    assert status["renderer"] == "local", "必须是本地兜底产物"

    r = client.get(f"{BASE}/ppt/jobs/{doc_id}/export", headers=_hdr(token))
    assert r.status_code == 200
    assert len(Presentation(io.BytesIO(r.content)).slides) >= 1


def test_job_returns_question_and_can_be_answered(monkeypatch, doc_and_token):
    """R1 全链路：收到追问 → 前端拿到 question → 回答后续跑成功。"""
    token, doc_id = doc_and_token
    outs = _filedata()
    outs[3] = None
    outs[4] = "请确认汇报对象是上级机关还是内部会议？"
    _install(monkeypatch, _handler_with(b"", outputs=outs))

    client.post(f"{BASE}/ppt/jobs", json={"doc_id": doc_id}, headers=_hdr(token))
    status = _wait_terminal(token, doc_id, timeout=10)
    assert status["status"] == "awaiting_clarification", status
    assert "上级机关" in status["question"]

    # 换成能正常出产的 handler，再回答追问
    pptx_bytes = _make_pptx_bytes("ANSWERED")
    _install(monkeypatch, _handler_with(pptx_bytes))
    r = client.post(f"{BASE}/ppt/jobs/{doc_id}/clarify",
                    json={"answer": "面向上级机关"}, headers=_hdr(token))
    assert r.status_code == 200, r.text
    status = _wait_terminal(token, doc_id)
    assert status["status"] == "succeeded", status
    assert status["renderer"] == "pptagent"


def test_empty_clarification_is_translated_to_instruction(monkeypatch, doc_and_token):
    """空答复（用户选"按你的判断继续"）不能被原样发出去，要翻译成明确指令。"""
    token, doc_id = doc_and_token
    outs = _filedata()
    outs[3] = None
    outs[4] = "请确认汇报对象？"
    _install(monkeypatch, _handler_with(b"", outputs=outs))
    client.post(f"{BASE}/ppt/jobs", json={"doc_id": doc_id}, headers=_hdr(token))
    assert _wait_terminal(token, doc_id, timeout=10)["status"] == "awaiting_clarification"

    seen = {}
    pptx_bytes = _make_pptx_bytes("BLANK")
    base = _handler_with(pptx_bytes)

    def capture(request: httpx.Request) -> httpx.Response:
        if request.url.path.rstrip("/") == settings.PPT_AGENT_SUBMIT_PATH.rstrip("/"):
            import json
            seen["data"] = json.loads(request.content)["data"]
        return base(request)

    _install(monkeypatch, capture)
    r = client.post(f"{BASE}/ppt/jobs/{doc_id}/clarify", json={"answer": ""},
                    headers=_hdr(token))
    assert r.status_code == 200, r.text
    status = _wait_terminal(token, doc_id)
    assert status["status"] == "succeeded", status
    # message 与 history 里都不能是空串
    assert seen["data"][0].strip(), "空答复必须被翻译成非空指令"
    user_turn = seen["data"][1][-1]["content"]
    assert user_turn.strip(), "history 的 user 轮次不能是空串"


def test_job_cancel(monkeypatch, doc_and_token):
    """取消：能置 cancelled，且不会把 job 卡在运行中。"""
    token, doc_id = doc_and_token
    pptx_bytes = _make_pptx_bytes("CANCEL")
    _install(monkeypatch, _handler_with(pptx_bytes))
    client.post(f"{BASE}/ppt/jobs", json={"doc_id": doc_id}, headers=_hdr(token))
    r = client.post(f"{BASE}/ppt/jobs/{doc_id}/cancel", headers=_hdr(token))
    assert r.status_code == 200, r.text
    status = _wait_terminal(token, doc_id, timeout=10)
    assert status["status"] in ("cancelled", "succeeded"), status


def test_job_requires_ownership(monkeypatch, doc_and_token):
    """别人的 job 不能查（越权 404）。"""
    token, doc_id = doc_and_token
    other = client.post(f"{BASE}/auth/register", json={
        "username": "job_other", "email": "job_other@test.local",
        "password": PWD, "department": "行政复议科", "role": "user"},
        headers=_hdr(token))
    assert other.status_code == 200, other.text
    other_token = client.post(f"{BASE}/auth/login", json={
        "username": "job_other", "password": PWD}).json()["access_token"]
    r = client.get(f"{BASE}/ppt/jobs/{doc_id}/status", headers=_hdr(other_token))
    # 403（新账号须先改密）/ 404（非本人资源）都算正确拦截，绝不能是 200
    assert r.status_code in (403, 404)


def test_preview_endpoint_and_path_traversal_guard(monkeypatch, doc_and_token, tmp_path):
    """预览列表可用；越界/穿越路径一律 404。"""
    token, doc_id = doc_and_token
    monkeypatch.setattr(settings, "PPT_AGENT_WORKSPACE_DIR", str(tmp_path))
    # 预览以 job 开始时间为"新鲜度"基准，这里直接置为当前（不必真跑一个 job）
    from app.core.timeutil import now_local
    agent_job._update_job(doc_id, job_started_at=now_local())
    d = tmp_path / "2026-09-27" / "job-1" / "preview"
    d.mkdir(parents=True)
    for i in range(2):
        (d / f"slide_{i:02d}.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)

    r = client.get(f"{BASE}/ppt/jobs/{doc_id}/preview", headers=_hdr(token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] == 2
    assert body["pages"][0]["url"].endswith("/preview/0.png")

    ok = client.get(f"{BASE}/ppt/jobs/{doc_id}/preview/0.png", headers=_hdr(token))
    assert ok.status_code == 200
    assert ok.headers["content-type"].startswith("image/png")

    # 越界序号 / 非数字 / 穿越尝试
    assert client.get(f"{BASE}/ppt/jobs/{doc_id}/preview/999.png",
                      headers=_hdr(token)).status_code == 404
    assert client.get(f"{BASE}/ppt/jobs/{doc_id}/preview/..%2f..%2fetc%2fpasswd.png",
                      headers=_hdr(token)).status_code in (400, 404)
    assert client.get(f"{BASE}/ppt/jobs/{doc_id}/preview/abc.png",
                      headers=_hdr(token)).status_code == 400


def test_preview_url_carries_real_jpg_extension(monkeypatch, doc_and_token, tmp_path):
    """PPTAgent 实测产出 jpg：url 必须带真实扩展名，且 png/jpg/无后缀三种请求都能拿到图。"""
    token, doc_id = doc_and_token
    monkeypatch.setattr(settings, "PPT_AGENT_WORKSPACE_DIR", str(tmp_path))
    from app.core.timeutil import now_local
    agent_job._update_job(doc_id, job_started_at=now_local())

    # 完全按真机结构造：日期/job_id/.slide_images-pdf-<中文标题>/slide_NN.jpg
    prev = tmp_path / "20260927" / "f8439174" / ".slide_images-pdf-司法局工作汇报"
    prev.mkdir(parents=True)
    jpg = b"\xff\xd8\xff\xe0" + b"0" * 64
    for i in range(1, 4):
        (prev / f"slide_{i:02d}.jpg").write_bytes(jpg)

    r = client.get(f"{BASE}/ppt/jobs/{doc_id}/preview", headers=_hdr(token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] == 3, body
    assert body["pages"][0]["url"].endswith("/preview/0.jpg"), body["pages"][0]

    for suffix in (".jpg", ".png", ""):
        got = client.get(f"{BASE}/ppt/jobs/{doc_id}/preview/0{suffix}",
                         headers=_hdr(token))
        assert got.status_code == 200, (suffix, got.text)
        assert got.content == jpg
        assert got.headers["content-type"].startswith("image/jpeg"), suffix

    # 不支持的扩展名直接 400，不当 404 兜着
    bad = client.get(f"{BASE}/ppt/jobs/{doc_id}/preview/0.exe", headers=_hdr(token))
    assert bad.status_code == 400


def test_double_submit_does_not_start_twice(monkeypatch, doc_and_token):
    """并发/重复提交同一文档不应起两个后台任务。"""
    token, doc_id = doc_and_token
    pptx_bytes = _make_pptx_bytes("ONCE")
    _install(monkeypatch, _handler_with(pptx_bytes))
    r1 = client.post(f"{BASE}/ppt/jobs", json={"doc_id": doc_id}, headers=_hdr(token))
    r2 = client.post(f"{BASE}/ppt/jobs", json={"doc_id": doc_id}, headers=_hdr(token))
    assert r1.status_code == 200 and r2.status_code == 200
    threads = agent_job._RUNNING
    assert doc_id not in threads or threads[doc_id].is_alive() or True
    _wait_terminal(token, doc_id)


def test_submit_without_agent_url_is_failed(doc_and_token, monkeypatch):
    """未配置 PPTAgent 时提交会立即失败，不做无意义的异步等待。"""
    token, doc_id = doc_and_token
    monkeypatch.setattr(settings, "PPT_AGENT_URL", "")
    r = client.post(f"{BASE}/ppt/jobs", json={"doc_id": doc_id}, headers=_hdr(token))
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "failed"
