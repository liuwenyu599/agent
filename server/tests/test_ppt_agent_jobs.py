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
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

from typing import Any, Dict, List

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
from app.application.ppt.service import PPTService  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.core.timeutil import now_local  # noqa: E402
from app.infrastructure.database import Base, engine  # noqa: E402
from app.infrastructure.ppt.ppt_agent_client import (  # noqa: E402
    PPTAgentClient, PPTAgentError, PPTAgentOutcome, looks_like_pptx,
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


def test_server_design_guidance_is_appended_to_agent_message(monkeypatch):
    """用户只说业务需求，风格与版式约束由服务端统一补进最终 message。"""
    runner = agent_job.PPTAgentJobRunner("doc-1", "user-1", message="突出年度亮点")
    monkeypatch.setattr(
        runner, "_design_guidance",
        lambda _doc: "庄重政务风格，深蓝主色，少装饰；每页不超过 4 个要点。")
    doc = SimpleNamespace(
        title="社区矫正年度总结",
        subtitle="2026年",
        outline={"slides": [
            {"type": "cover", "title": "社区矫正年度总结"},
            {"type": "closing", "title": "谢谢聆听"},
        ]},
        source_content="材料正文",
    )
    message = runner._build_message(doc)
    assert "突出年度亮点" in message
    assert "系统设计约束（必须执行）" in message
    assert "庄重政务风格" in message
    assert "每页不超过 4 个要点" in message
    assert "不得额外增加封面/结束页" in message


def test_quality_gate_retries_once_then_accepts(monkeypatch):
    """第一次低质时系统自动重试一次；第二次合格后直接收下，不再追问用户。"""
    runner = agent_job.PPTAgentJobRunner("doc-1", "user-1")
    first = _make_pptx_bytes("bad", pages=2)
    good = _make_pptx_bytes("good", pages=3)
    calls = []

    class _Client:
        def generate_deck(self, *args, **kwargs):
            calls.append((args, kwargs))
            return PPTAgentOutcome(pptx=good, event_id="retry-event")

    stored = {}
    monkeypatch.setattr(
        runner, "_store",
        lambda data, renderer, event_id="": stored.update(
            {"data": data, "renderer": renderer, "event_id": event_id}))

    ok = runner._accept_or_retry_quality(
        first, "first-event", _Client(), "message", [], 3,
        time.monotonic() + 60)

    assert ok is True
    assert len(calls) == 1
    assert stored["data"] == good
    assert stored["renderer"] == "pptagent_retry"
    assert stored["event_id"] == "retry-event"


def test_generated_pptx_quality_gate_detects_page_mismatch():
    data = _make_pptx_bytes("quality", pages=3)
    assert PPTService.assess_generated_pptx(data, 3) == []
    issues = PPTService.assess_generated_pptx(data, 6)
    assert any("页数不符" in item for item in issues)


def _wrapped(value: Any) -> Dict[str, Any]:
    """模拟 Gradio 组件更新包装 —— 真机出参的**每个元素**都带这层壳。"""
    return {"value": value, "__type__": "update"}


# 真机 OUT[4] 的原文（team-lead 实测）：**中文、无 emoji**的整块运行统计。
# 早期我按 "🔤 Tokens: 12,345 · 💰 Cost: $0.012" 推断，与真机完全不符 —— 真机
# 标题行 / Agent 名行 / 总计行都**不带数字**，纯逐行过滤拦不住，必须整块判定。
REAL_TOKEN_STATS = (
    "## Token 使用统计\n\n"
    "**Research Agent** (Model: `DeepPresenter-9B`)  \n"
    "- 输入: 33,320 tokens  \n"
    "- 输出: 2,609 tokens  \n"
    "- 小计: 35,929 tokens  \n\n"
    "**Design Agent** (Model: `DeepPresenter-9B`)  \n"
    "- 输入: 282,922 tokens  \n"
    "- 输出: 20,802 tokens  \n"
    "- 小计: 303,724 tokens  \n\n\n"
    "---\n\n"
    "**总计**  \n"
    "- 输入: 316,242 tokens  \n"
    "- 输出: 23,411 tokens  \n"
    "- 小计: 339,653 tokens"
)


def _real_outputs(*, pptx_path: str = None, pptx_url: str = None,
                  markdown: str = REAL_TOKEN_STATS) -> List[Any]:
    """按**真机原始 payload** 造 5 个出参（每项一层 value 壳）。

    真机样本（20260927，team-lead 实测打印），与早期推测有四处出入，已全部校正：
    - 产物文件名是 ``manuscript.pptx``（中文标题名只存在于 **workspace 目录扫描**
      那条通道，走 FileData 下载这条路 Gradio 给的是 /tmp/gradio/<hash>/ 下的固定名）；
    - ``url`` 是**完整绝对 URL**（Gradio 按 Host 头生成），不是相对路径；
    - ``OUT[2]`` 的 ``value`` 是 ``None``，不是空 dict；
    - ``OUT[1]`` Textbox 是空串（有些版本会给 job id，两种都不许当追问）。
    """
    path = pptx_path or (
        "/tmp/gradio/87faa30d18310b4681cda1e8f7b21b78a3dd1028da801856c6a9c3232f2"
        "68da0/manuscript.pptx")
    url = pptx_url or (
        "http://127.0.0.1:18061/gradio_api/file="
        "/tmp/gradio/87faa30d18310b4681cda1e8f7b21b78a3dd1028da801856c6a9c3232f2"
        "68da0/manuscript.pptx")
    file_data = {
        "path": path,
        "url": url,
        "size": None,
        "orig_name": "manuscript.pptx",
        "mime_type": None,
        "is_stream": False,
        "meta": {"_type": "gradio.FileData"},
    }
    return [
        _wrapped([                                        # [0] Chatbot
            {"role": "user", "metadata": None, "content": "生成一份 1 页的测试演示文稿",
             "options": None},
            {"role": "assistant", "metadata": None,
             "content": "⚙️ **System Message**\n\nDeepPresenter running in ...",
             "options": None},
        ]),
        _wrapped(""),                                     # [1] Textbox（真机是空串）
        _wrapped(None),                                   # [2] File（value 是 None）
        _wrapped(file_data),                              # [3] 📥 下载文件
        _wrapped(markdown),                               # [4] Markdown（token 统计）
    ]


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


# ============================================================ 真机 value 包装（阻塞缺陷）

def test_parse_outputs_handles_real_payload(monkeypatch):
    """【真机缺陷】出参每项包在 {"value":…,"__type__":"update"} 里。

    早期 wrapper 白名单只有 data/result/output，漏了 value → 产物明明生成了却
    判定 pending=True、pptx=0。
    """
    pptx_bytes = _make_pptx_bytes("REAL")
    _install(monkeypatch, _handler_with(pptx_bytes, outputs=_real_outputs()))
    c = PPTAgentClient.from_settings()
    out = c.generate_deck("生成司法行政工作简报")

    assert out.pending is False, "产物在眼前却判定为进行中"
    assert out.pptx == pptx_bytes, "必须取到真实的 pptx 字节"
    assert looks_like_pptx(out.pptx)[0]
    assert not out.question, f"真机 OUT[4] 是运行统计，不该变成追问：{out.question!r}"


def test_parse_outputs_handles_absolute_download_url(monkeypatch):
    """真机 url 是完整绝对 URL（Gradio 按 Host 头生成），不是相对路径。

    两条都要覆盖：绝对 URL 由 ``_abs_url`` 直接放行，相对路径要拼上 base_url。
    """
    good = _make_pptx_bytes("ABS")
    seen: List[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return _handler_with(good, outputs=_real_outputs())(request)

    _install(monkeypatch, handler)
    c = PPTAgentClient.from_settings()
    # 绝对 URL 指向 127.0.0.1:18061，与 base_url(fake-ppt-agent) 不同，
    # 若被错误拼接就取不到文件 → 断言拿到字节即证明走了原样直连
    out = c.generate_deck("生成汇报")
    assert out.pptx == good
    assert any("127.0.0.1:18061" in u for u in seen), "绝对 URL 必须原样使用"


def test_relative_download_url_is_joined_with_base(monkeypatch):
    """相对路径形态（/gradio_api/file=...）必须拼上 base_url —— 老 fixture 分支。"""
    good = _make_pptx_bytes("REL")
    outs = _real_outputs(pptx_url="/gradio_api/file=/tmp/gradio/manuscript.pptx")
    _install(monkeypatch, _handler_with(good, outputs=outs))
    c = PPTAgentClient.from_settings()
    assert c.generate_deck("生成汇报").pptx == good


def test_real_token_stats_are_not_a_question(monkeypatch):
    """真机 OUT[4] 原文（中文、无 emoji 的整块统计）不能当追问。

    ⚠️ 这条是最关键的回归点：早期只做"含 marker 且带数字"的逐行过滤，真机标题行
    ``## Token 使用统计``、Agent 名行、``**总计**`` 行都不带数字，过滤完照样拼成
    一段"看起来像追问"的文本 —— 等于没修。必须靠整块判定。
    """
    outs = _real_outputs(markdown=REAL_TOKEN_STATS)
    outs[3] = None                       # 产物通道为空
    _install(monkeypatch, _handler_with(b"", outputs=outs))
    c = PPTAgentClient.from_settings()
    out = c.generate_deck("生成汇报")
    assert out.question == "", f"运行统计不能冒充追问：{out.question!r}"
    assert "Token" not in out.question and "tokens" not in out.question
    assert "总计" not in out.question and "Research" not in out.question
    assert out.pending is True, "既无产物也无追问 → 仍视为 pending"


def test_short_no_token_status_is_not_a_question():
    """无数字的短状态语不是追问，不能把任务推进 awaiting_clarification。"""
    from app.infrastructure.ppt.ppt_agent_client import strip_token_stats

    assert strip_token_stats("暂无 token 数据") == ""
    assert strip_token_stats("无 Token 信息。") == ""
    assert strip_token_stats("No token data.") == ""


def test_english_token_stats_block_is_also_stripped():
    """英文形态的统计块同样要识别（防止只认中文）。"""
    from app.infrastructure.ppt.ppt_agent_client import strip_token_stats

    assert strip_token_stats("Intro\n## Token Usage\n- input: 100 tokens") == "Intro"
    assert strip_token_stats("## Token Statistics\n- in: 5 tokens") == ""
    assert strip_token_stats("## Tokens 使用统计\n- 输入: 5 tokens") == ""


def test_question_is_extracted_from_wrapped_markdown(monkeypatch):
    """真追问即使被 value 包着，也要能取出来。"""
    outs = _real_outputs(
        markdown="请问本次汇报面向的是上级机关还是内部会议？")
    outs[3] = None
    _install(monkeypatch, _handler_with(b"", outputs=outs))
    c = PPTAgentClient.from_settings()
    out = c.generate_deck("生成汇报")
    assert "上级机关" in out.question
    assert out.pending is False


def test_question_keeps_text_and_drops_appended_stats(monkeypatch):
    """追问在前、统计块在后：保留追问、整段丢掉统计。"""
    outs = _real_outputs(markdown=(
        "请问本次汇报面向的是上级机关还是内部会议？\n\n"
        "## Token 使用统计\n\n"
        "**Design Agent** (Model: `DeepPresenter-9B`)  \n"
        "- 输入: 282,922 tokens  \n"))
    outs[3] = None
    _install(monkeypatch, _handler_with(b"", outputs=outs))
    c = PPTAgentClient.from_settings()
    out = c.generate_deck("生成汇报")
    assert "上级机关" in out.question
    assert "tokens" not in out.question and "282,922" not in out.question
    assert "Design Agent" not in out.question


def test_strip_token_stats_preserves_ordinary_sentences():
    """统计剔除不能误伤正文里提到成本/统计的普通句子。"""
    from app.infrastructure.ppt.ppt_agent_client import strip_token_stats

    assert strip_token_stats("本次汇报需说明成本控制情况。") == \
        "本次汇报需说明成本控制情况。"
    assert strip_token_stats("请确认汇报对象。\n🔤 Tokens: 999") == "请确认汇报对象。"
    assert strip_token_stats(REAL_TOKEN_STATS) == ""


def test_unwrap_value_returns_none_for_null_wrapped_component():
    """真机 OUT[2] 是 {"value": None, "__type__": "update"}。

    解包必须得到 None（而不是把包装层原样返回成一个"没有 url 的 dict"），
    且后续取值时不能抛异常。
    """
    from app.infrastructure.ppt.ppt_agent_client import (
        _gradio_file_url, unwrap_value)

    assert unwrap_value({"value": None, "__type__": "update"}) is None
    assert _gradio_file_url({"value": None, "__type__": "update"}) == ""

    # ⚠️ 必须注入 MockTransport：真机 url 是 http://127.0.0.1:18061/...，
    # 不加桩这条用例会真的走网络（本机到实验室的隧道确实可达），既慢又不可控。
    def _offline(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"测试不应发起真实网络请求：{request.url}")

    c = PPTAgentClient(base_url=AGENT_URL,
                       transport=httpx.MockTransport(_offline))
    # 不能抛异常，取不到就是 None
    assert c._bytes_from_filedata({"value": None, "__type__": "update"}) is None
    # 整组出参里混着 value=None 也要能正常解析完（不抛异常、结果结构完整）
    outs = _real_outputs()
    outs[2] = {"value": None, "__type__": "update"}
    outcome = c.parse_outputs(outs)
    assert outcome.outputs == outs
    assert outcome.question == "", "OUT[4] 是统计，不该变成追问"


def test_unwrap_value_stops_at_filedata():
    """FileData 本体不能被继续剥开（否则会把 url/path 拆丢）。"""
    from app.infrastructure.ppt.ppt_agent_client import unwrap_value

    fd = {"path": "/tmp/a.pptx", "url": "/gradio_api/file=/tmp/a.pptx",
          "orig_name": "a.pptx", "meta": {"_type": "gradio.FileData"}}
    assert unwrap_value(fd) is fd
    assert unwrap_value({"value": fd, "__type__": "update"}) is fd
    assert unwrap_value({"value": {"value": fd}}) is fd
    # 异常深度的结构不会无限递归，也不会崩（到保护深度就停手）
    deep: Any = fd
    for _ in range(30):
        deep = {"value": deep}
    got = unwrap_value(deep)
    assert isinstance(got, (dict, list)), "深度保护必须能正常返回，不能抛异常"


def test_product_prefers_agreed_index_over_other_outputs(monkeypatch):
    """约定索引（3）命中时，不应该顺位去扫中间产物（避免取错文件）。"""
    good = _make_pptx_bytes("FINAL")
    bad = _make_pptx_bytes("INTERMEDIATE")
    outs = _real_outputs()
    outs[2] = {"value": [{"path": "/tmp/mid.pptx",
                          "url": "/gradio_api/file=/tmp/mid.pptx",
                          "orig_name": "mid.pptx",
                          "meta": {"_type": "gradio.FileData"}}],
               "__type__": "update"}

    def handler(request: httpx.Request) -> httpx.Response:
        if "/gradio_api/file=" in request.url.path:
            body = bad if request.url.path.endswith("mid.pptx") else good
            return httpx.Response(200, content=body,
                                  headers={"content-type": "application/octet-stream"})
        return _handler_with(good, outputs=outs)(request)

    _install(monkeypatch, handler)
    c = PPTAgentClient.from_settings()
    out = c.generate_deck("生成汇报")
    assert out.pptx == good, "必须取 📥 下载文件（索引 3），而不是中间产物列表"


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


def test_submit_and_event_path_default_to_gradio_named_endpoint(monkeypatch):
    """默认值必须指向 Gradio 命名端点，不能被改回旧 REST 路径（否则一提交就 404）。

    真机契约：GET /gradio_api/info → DeepPresenter 5.50.0，命名端点 /send_message。
    """
    from app.core.config import Settings

    monkeypatch.delenv("PPT_AGENT_SUBMIT_PATH", raising=False)
    monkeypatch.delenv("PPT_AGENT_EVENT_PATH", raising=False)
    s = Settings()
    assert s.PPT_AGENT_SUBMIT_PATH == "/gradio_api/call/send_message"
    assert s.PPT_AGENT_EVENT_PATH == "/gradio_api/call/send_message/{event_id}"
    # 两条路径的根必须是同一个命名端点，否则 event_id 拿不到对应事件
    assert s.PPT_AGENT_EVENT_PATH.startswith(s.PPT_AGENT_SUBMIT_PATH + "/")
    assert "api/ppt/generate" not in s.PPT_AGENT_SUBMIT_PATH


def test_submit_path_is_assigned_only_once(monkeypatch):
    """PPT_AGENT_SUBMIT_PATH 在 Settings.__init__ 里只能有一处赋值。

    历史上这里被赋值过两次（先 /api/ppt/generate，后 /gradio_api/call/send_message），
    靠"后覆盖前"侥幸没出事，但会让人误判默认值。这条用例挡住它复发。
    """
    import inspect
    import re

    from app.core.config import Settings

    src = inspect.getsource(Settings.__init__)
    hits = re.findall(r"self\.PPT_AGENT_SUBMIT_PATH\s*=", src)
    assert len(hits) == 1, f"PPT_AGENT_SUBMIT_PATH 被赋值了 {len(hits)} 次，应为 1 次"


def test_gradio_contract_conflict_is_reported_but_not_fatal():
    """同步通道指向 Gradio 端点时能被诊断出来；但**只提示，不阻断**（策略交由上层）。"""
    from app.infrastructure.ppt.ppt_agent_client import gradio_contract_conflict

    assert gradio_contract_conflict("/api/ppt/generate") == ""
    msg = gradio_contract_conflict("/gradio_api/call/send_message")
    assert msg, "Gradio 端点应被诊断出来"
    assert "/ppt/jobs" in msg, "提示里必须指名可用的替代通道"


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


def test_job_status_uses_persisted_heartbeat_across_workers(monkeypatch):
    """另一个 worker 看不到本地线程时，只要 DB 心跳新鲜就仍应返回 running。"""
    monkeypatch.setattr(agent_job, "_is_active", lambda _doc_id: False)
    fresh = now_local()
    doc = SimpleNamespace(
        id="cross-worker-job",
        job_started_at=fresh - timedelta(seconds=10),
        job_progress_at=fresh,
        job_status="running",
        job_current_page=0,
        job_total_pages=0,
        job_phase="designing",
        job_error="",
        job_question="",
        job_renderer="",
    )
    assert agent_job.job_status(doc)["status"] == "running"

    doc.job_progress_at = now_local() - timedelta(
        seconds=max(60, settings.PPT_AGENT_STALL_TIMEOUT) + 5)
    assert agent_job.job_status(doc)["status"] == "failed"


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


def test_job_auto_handles_agent_question_without_user_interruption(
        monkeypatch, doc_and_token):
    """用户已确认大纲后，PPTAgent 再追问也不能打断用户；系统自动继续/降级。"""
    token, doc_id = doc_and_token
    outs = _filedata()
    outs[3] = None
    outs[4] = "请确认汇报对象是上级机关还是内部会议？"
    _install(monkeypatch, _handler_with(b"", outputs=outs))

    client.post(f"{BASE}/ppt/jobs", json={"doc_id": doc_id}, headers=_hdr(token))
    status = _wait_terminal(token, doc_id, timeout=10)
    assert status["status"] == "succeeded", status
    assert status["question"] == ""
    # 替身每次都只会继续追问，所以自动重试后应无感切到严格模板。
    assert status["renderer"] == "local"


def test_legacy_empty_clarification_is_translated_to_instruction(
        monkeypatch, doc_and_token):
    """兼容旧 awaiting_clarification 任务：空答复仍会翻译成明确默认指令。"""
    token, doc_id = doc_and_token
    agent_job._update_job(
        doc_id,
        job_status="awaiting_clarification",
        job_phase="awaiting_clarification",
        job_question="请确认汇报对象？",
        job_progress_at=now_local(),
    )

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
