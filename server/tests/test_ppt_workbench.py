"""PPT 工作台新增服务端端点测试（materials/analyze、documents/import、
outline/stream、ai/slide-action、ai/visual、ai/structure）。

运行方式（在 server/ 目录下）：
    D:/apps/anaconda3/python.exe -m pytest tests/test_ppt_workbench.py -v

测试策略：
- **模型一律打桩**：本地 8001 通用模型与 8003 PPT 专用模型均未启动，测试用
  monkeypatch 替换 `app.infrastructure.ai.get_ppt_gateway` 与
  `app.interfaces.ppt.get_llm_gateway`，返回可控的 FakeGateway。
  本文件**不验证模型输出质量**，只验证不依赖模型的部分：
  参数校验 / 鉴权与越权 / 缺失资源 404 / SSE 事件骨架与顺序 /
  pptx 解析出的大纲结构 / sources(provenance) 字段的存在与结构。
- **数据隔离**：DATA_DIR 与 DATABASE_URL 指向临时目录，绝不写入真实库。
"""
import io
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("AI_PROVIDER", "mock")

_TMPDIR = Path(tempfile.mkdtemp(prefix="test-ppt-"))
os.environ.setdefault("DATA_DIR", str(_TMPDIR))
os.environ.setdefault("DATABASE_URL", f"sqlite:///{(_TMPDIR / 'test.db').as_posix()}")

from fastapi.testclient import TestClient  # noqa: E402

from app.infrastructure.database import Base, engine  # noqa: E402
from app.main import app  # noqa: E402

Base.metadata.create_all(bind=engine)

BASE = "/api/v1"
PWD = "Passw0rd!2026"


# ============================================================ 模型打桩


class FakeGateway:
    """替身模型网关：记录每次调用，按 responder 返回固定文本。

    只实现 WritingAssistant 用到的 complete()，不发任何网络请求。
    """

    def __init__(self, responder=None):
        self.calls = []
        self._responder = responder or (lambda messages: "{}")

    @property
    def model_name(self) -> str:
        return "fake-ppt-model"

    def complete(self, messages, temperature=0.7, max_tokens=4096):
        self.calls.append({"messages": messages,
                           "temperature": temperature,
                           "max_tokens": max_tokens})
        return self._responder(messages)

    @property
    def last_prompt(self) -> str:
        """最近一次调用的 user 消息文本（用于断言 prompt 侧要求是否下发）。"""
        return self.calls[-1]["messages"][-1]["content"]


@pytest.fixture
def fake_llm(monkeypatch):
    """把 PPT 专用网关与主文本网关都换成可控替身。"""
    import app.infrastructure.ai as ai_mod
    import app.interfaces.ppt as ppt_iface

    fake = FakeGateway()
    # PPT 专用网关（服务内 `from app.infrastructure.ai import get_ppt_gateway` 惰性取用）
    monkeypatch.setattr(ai_mod, "get_ppt_gateway", lambda: fake)
    # 主文本网关（接口层 get_ppt_service 注入 WritingAssistant 时使用）
    monkeypatch.setattr(ai_mod, "get_llm_gateway", lambda: fake)
    monkeypatch.setattr(ppt_iface, "get_llm_gateway", lambda: fake)
    # 清掉网关缓存，避免真实 QwenGateway 被构造
    ai_mod.reset_gateway()
    return fake


# ============================================================ 夹具


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _hdr(token):
    return {"Authorization": f"Bearer {token}"}


def _dev_token(client):
    """取得系统管理员令牌（首个用户已被占用时直接为库内管理员签发）。"""
    r = client.post(f"{BASE}/auth/register-first", json={
        "username": "ppt_dev", "email": "ppt_dev@test.local",
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


@pytest.fixture(scope="module")
def accounts(client):
    """系统管理员 + 两个互不相干的普通用户（用于越权断言）。"""
    dev = _dev_token(client)

    def reg(username):
        r = client.post(f"{BASE}/auth/register", json={
            "username": username, "email": f"{username}@test.local",
            "password": PWD, "department": "行政复议科", "role": "user",
        }, headers=_hdr(dev))
        assert r.status_code == 200, r.text
        tok = client.post(f"{BASE}/auth/login", json={
            "username": username, "password": PWD}).json()["access_token"]
        # 管理员代建的账号首登必须改密（真实业务流程）：未改密前业务端点一律 403
        changed = client.post(f"{BASE}/auth/change-password", json={
            "old_password": PWD, "new_password": "Changed@2026",
            "confirm_password": "Changed@2026",
        }, headers=_hdr(tok))
        assert changed.status_code == 200, changed.text
        return tok

    return {"dev": dev, "a": reg("ppt_user_a"), "b": reg("ppt_user_b")}


# ============================================================ 工具


def _make_pptx_bytes(pages):
    """用 python-pptx 生成最小可解析 pptx：[(标题, [要点...]), ...]。"""
    from pptx import Presentation
    from pptx.util import Pt

    prs = Presentation()
    blank = prs.slide_layouts[6]
    for title, bullets in pages:
        slide = prs.slides.add_slide(blank)
        tb = slide.shapes.add_textbox(Pt(50), Pt(40), Pt(600), Pt(70))
        tf = tb.text_frame
        tf.text = title
        if tf.paragraphs[0].runs:
            tf.paragraphs[0].runs[0].font.size = Pt(32)
        if bullets:
            tb2 = slide.shapes.add_textbox(Pt(50), Pt(150), Pt(600), Pt(320))
            tf2 = tb2.text_frame
            for i, b in enumerate(bullets):
                p = tf2.paragraphs[0] if i == 0 else tf2.add_paragraph()
                p.text = b
                if p.runs:
                    p.runs[0].font.size = Pt(18)
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


def _parse_sse(text):
    """解析 SSE 响应体为事件列表。"""
    events = []
    for line in (text or "").splitlines():
        line = line.strip()
        if line.startswith("data:"):
            events.append(json.loads(line[len("data:"):].strip()))
    return events


def _blank_doc(client, token, title="测试PPT"):
    """建一个空白 PPT 文档，返回 doc_id。"""
    r = client.post(f"{BASE}/ppt/blank", json={"title": title}, headers=_hdr(token))
    assert r.status_code == 200, r.text
    return r.json()["doc_id"]


# ============================================================ 1. materials/analyze


def test_analyze_materials_requires_login(client):
    r = client.post(f"{BASE}/ppt/materials/analyze")
    assert r.status_code in (401, 403), r.text


def test_analyze_materials_no_file_rejected(client, accounts):
    r = client.post(f"{BASE}/ppt/materials/analyze", headers=_hdr(accounts["a"]))
    assert r.status_code in (400, 422), r.text


def test_analyze_materials_returns_summary_and_text(client, accounts, fake_llm):
    """上传 txt：返回该份材料的 AI 摘要 + 提取文本，材料不再黑盒。

    v2 起材料分析升级为结构化输出（摘要 + 重点清单 + 数据表数量），
    这里喂合法 JSON 以验证解析链路真的生效，而不是只验证降级兜底。
    """
    fake_llm._responder = lambda m: json.dumps({
        "summary": "工作总结类文档，含一季度案件统计数据。",
        "key_points": ["一季度受理 120 件", "办结 115 件"],
        "tables": 1,
    }, ensure_ascii=False)
    body = "行政复议案件办理情况：一季度受理120件，办结115件。".encode("utf-8")
    r = client.post(
        f"{BASE}/ppt/materials/analyze",
        files=[("files", ("案件材料.txt", body, "text/plain"))],
        headers=_hdr(accounts["a"]))
    assert r.status_code == 200, r.text
    data = r.json()
    # 文案带聚合统计后缀，只校验份数部分
    assert data["message"].startswith("已分析 1 份材料")
    items = data["items"]
    assert len(items) == 1
    assert items[0]["filename"] == "案件材料.txt"
    assert items[0]["chars"] > 0
    assert "受理120件" in items[0]["text"]
    assert items[0]["summary"] == "工作总结类文档，含一季度案件统计数据。"
    # 结构化字段真的解析出来了（不是兜底空值）
    assert items[0]["key_points"] == ["一季度受理 120 件", "办结 115 件"]
    assert items[0]["tables"] == 1
    # 聚合统计与逐份结果一致
    assert data["totals"] == {"materials": 1, "key_points": 2, "tables": 1}
    # 摘要确实走了模型通道（否则这段逻辑等于没接）
    assert len(fake_llm.calls) == 1


def test_analyze_materials_degrades_on_non_json_summary(client, accounts, fake_llm):
    """模型返回非法 JSON（纯文本）时降级：摘要用原文，重点/表数留空，不抛异常。

    这条是兜底路径的护栏——结构化解析绝不能因为没有 JSON 就把整批材料分析打断。
    """
    fake_llm._responder = lambda m: "这不是 JSON，只是一段普通文本摘要"
    r = client.post(
        f"{BASE}/ppt/materials/analyze",
        files=[("files", ("材料.txt", "一季度受理120件".encode("utf-8"), "text/plain"))],
        headers=_hdr(accounts["a"]))
    assert r.status_code == 200, r.text
    item = r.json()["items"][0]
    assert item["summary"] == "这不是 JSON，只是一段普通文本摘要"
    assert item["key_points"] == []
    assert item["tables"] == 0
    # 聚合统计同步降级，不能 KeyError
    assert r.json()["totals"] == {"materials": 1, "key_points": 0, "tables": 0}


def test_analyze_materials_accepts_fenced_json(client, accounts, fake_llm):
    """模型用 ```json 代码围栏包裹、或前后带废话时，也要能解析出结构化字段。"""
    fenced = (
        "好的，分析结果如下：\n"
        "```json\n"
        '{"summary": "一季度案件办理情况表", "key_points": ["受理120件", "办结115件"],'
        ' "tables": 2}\n'
        "```\n"
    )
    fake_llm._responder = lambda m: fenced
    r = client.post(
        f"{BASE}/ppt/materials/analyze",
        files=[("files", ("案件.txt", "受理120件，办结115件".encode("utf-8"), "text/plain"))],
        headers=_hdr(accounts["a"]))
    assert r.status_code == 200, r.text
    item = r.json()["items"][0]
    assert item["summary"] == "一季度案件办理情况表"
    assert item["key_points"] == ["受理120件", "办结115件"]
    assert item["tables"] == 2


def test_analyze_materials_missing_fields_degrade(client, accounts, fake_llm):
    """JSON 里缺字段/类型不对时按类型兜底，不能抛异常或把脏值透给桌面端。"""
    fake_llm._responder = lambda m: json.dumps(
        {"summary": "只有摘要", "key_points": "not-a-list", "tables": "很多"},
        ensure_ascii=False)
    r = client.post(
        f"{BASE}/ppt/materials/analyze",
        files=[("files", ("残缺.txt", "一些内容".encode("utf-8"), "text/plain"))],
        headers=_hdr(accounts["a"]))
    assert r.status_code == 200, r.text
    item = r.json()["items"][0]
    assert item["summary"] == "只有摘要"
    # key_points 必须是数组：字符串按行拆成单条
    assert item["key_points"] == ["not-a-list"]
    # tables 必须是不小于 0 的整数：非数字降级为 0
    assert item["tables"] == 0


def test_analyze_materials_multi_format(client, accounts, fake_llm):
    """txt + csv + pptx 三种通道都能提取出内容。"""
    fake_llm._responder = lambda m: "（替身摘要）"
    pptx_bytes = _make_pptx_bytes([("旧汇报", ["受理120件", "办结115件"])])
    files = [
        ("files", ("概述.txt", "这是纯文本材料内容".encode("utf-8"), "text/plain")),
        ("files", ("数据表.csv", "指标,数值\n案件数,120\n".encode("utf-8"), "text/csv")),
        ("files", ("旧汇报.pptx", pptx_bytes,
                   "application/vnd.openxmlformats-officedocument.presentationml.presentation")),
    ]
    r = client.post(f"{BASE}/ppt/materials/analyze", files=files,
                    headers=_hdr(accounts["a"]))
    assert r.status_code == 200, r.text
    items = {i["filename"]: i for i in r.json()["items"]}
    assert set(items) == {"概述.txt", "数据表.csv", "旧汇报.pptx"}
    assert "这是纯文本材料内容" in items["概述.txt"]["text"]
    assert "案件数" in items["数据表.csv"]["text"] and "120" in items["数据表.csv"]["text"]
    assert "旧汇报" in items["旧汇报.pptx"]["text"]


def test_analyze_materials_unsupported_format_is_400(client, accounts, fake_llm):
    r = client.post(
        f"{BASE}/ppt/materials/analyze",
        files=[("files", ("乱码.bin", b"\x00\x01\x02binary", "application/octet-stream"))],
        headers=_hdr(accounts["a"]))
    assert r.status_code == 400, r.text
    assert "乱码.bin" in r.json()["detail"]


def test_analyze_materials_empty_file_is_400(client, accounts, fake_llm):
    r = client.post(
        f"{BASE}/ppt/materials/analyze",
        files=[("files", ("空文件.txt", b"", "text/plain"))],
        headers=_hdr(accounts["a"]))
    assert r.status_code == 400, r.text
    assert "没有可解析的材料" in r.json()["detail"]


def test_analyze_materials_caps_at_eight_files(client, accounts, fake_llm):
    """一次最多分析 8 份，超出的不处理（防止请求体无限膨胀）。"""
    fake_llm._responder = lambda m: "（替身摘要）"
    files = [("files", (f"材料{i}.txt", f"内容{i}".encode("utf-8"), "text/plain"))
             for i in range(9)]
    r = client.post(f"{BASE}/ppt/materials/analyze", files=files,
                    headers=_hdr(accounts["a"]))
    assert r.status_code == 200, r.text
    assert len(r.json()["items"]) == 8


# ============================================================ 2. documents/import


def test_import_pptx_requires_login(client):
    r = client.post(f"{BASE}/ppt/documents/import")
    assert r.status_code in (401, 403), r.text


def test_import_pptx_rejects_non_pptx(client, accounts):
    r = client.post(
        f"{BASE}/ppt/documents/import",
        files={"file": ("材料.docx", b"PK\x03\x04fake", "application/msword")},
        headers=_hdr(accounts["a"]))
    assert r.status_code == 400, r.text
    assert "仅支持 .pptx 文件" in r.json()["detail"]


def test_import_pptx_rejects_empty_file(client, accounts):
    r = client.post(
        f"{BASE}/ppt/documents/import",
        files={"file": ("空.pptx", b"",
                        "application/vnd.openxmlformats-officedocument.presentationml.presentation")},
        headers=_hdr(accounts["a"]))
    assert r.status_code == 400, r.text
    assert "文件内容为空" in r.json()["detail"]


def test_import_pptx_rejects_corrupt_zip(client, accounts):
    r = client.post(
        f"{BASE}/ppt/documents/import",
        files={"file": ("损坏.pptx", b"this-is-not-a-zip",
                        "application/vnd.openxmlformats-officedocument.presentationml.presentation")},
        headers=_hdr(accounts["a"]))
    assert r.status_code == 400, r.text
    assert "损坏" in r.json()["detail"]


def test_import_pptx_parses_editable_outline(client, accounts, fake_llm):
    """上传已有 pptx → 解析为可编辑大纲（不依赖 LLM）。"""
    data = _make_pptx_bytes([
        ("行政复议工作汇报", []),
        ("一季度案件办理情况", ["受理案件120件", "办结115件", "调解成功率86%"]),
    ])
    r = client.post(
        f"{BASE}/ppt/documents/import",
        files={"file": ("旧汇报.pptx", data,
                        "application/vnd.openxmlformats-officedocument.presentationml.presentation")},
        headers=_hdr(accounts["a"]))
    assert r.status_code == 200, r.text
    body = r.json()
    doc_id = body["doc_id"]
    assert doc_id
    assert "已导入" in body["message"]
    outline = body["outline"]
    slides = outline["slides"]
    # normalize_outline 保证首封面、尾结束页
    assert slides[0]["type"] == "cover"
    assert slides[-1]["type"] == "closing"
    titles = " ".join(s["title"] for s in slides)
    assert "行政复议工作汇报" in titles
    assert "一季度案件办理情况" in titles
    # 正文要点被解析出来
    body_points = " ".join(
        p for s in slides for p in (s.get("points") or []))
    assert "受理案件120件" in body_points
    # 每页都有 sources 字段（可编辑大纲的 provenance 结构齐备）
    for s in slides:
        assert "sources" in s and isinstance(s["sources"], list)
    # 解析走的是规则通道，不调用模型
    assert len(fake_llm.calls) == 0

    # 导入结果已落库，可用同一编辑链路取回
    got = client.get(f"{BASE}/ppt/documents/{doc_id}", headers=_hdr(accounts["a"]))
    assert got.status_code == 200, got.text
    assert len(got.json()["outline"]["slides"]) == len(slides)


def test_imported_pptx_appears_in_my_documents(client, accounts, fake_llm):
    data = _make_pptx_bytes([("清单页", ["要点一", "要点二"])])
    r = client.post(
        f"{BASE}/ppt/documents/import",
        files={"file": ("清单.pptx", data,
                        "application/vnd.openxmlformats-officedocument.presentationml.presentation")},
        headers=_hdr(accounts["a"]))
    doc_id = r.json()["doc_id"]
    lst = client.get(f"{BASE}/ppt/documents", headers=_hdr(accounts["a"])).json()
    assert any(d["id"] == doc_id for d in lst["items"])


# ============================================================ 3. outline/stream


def test_outline_stream_requires_login(client):
    r = client.post(f"{BASE}/ppt/outline/stream", json={"topic": "x"})
    assert r.status_code in (401, 403), r.text


@pytest.fixture
def outline_payload():
    """替身模型返回的大纲：含每页 sources 内容依据。"""
    return {
        "title": "行政复议工作汇报",
        "subtitle": "2026年第一季度",
        "slides": [
            {"type": "cover", "title": "行政复议工作汇报",
             "subtitle": "2026年第一季度", "sources": []},
            {"type": "content", "title": "案件办理情况",
             "points": ["受理案件120件", "办结115件"], "sources": ["材料A.txt"]},
            {"type": "closing", "title": "谢谢聆听，请批评指正", "sources": []},
        ],
    }


def test_outline_stream_event_sequence_and_done(client, accounts, fake_llm,
                                                outline_payload):
    """SSE：先 3 个 stage，最后 done 携带权威大纲（含 sources）。"""
    payload = outline_payload
    fake_llm._responder = lambda m: json.dumps(payload, ensure_ascii=False)

    r = client.post(f"{BASE}/ppt/outline/stream", json={
        "source_type": "topic",
        "topic": "行政复议工作汇报",
        "slide_count": 8,
        "material_names": ["材料A.txt", "材料B.csv"],
    }, headers=_hdr(accounts["a"]))
    assert r.status_code == 200, r.text
    assert "text/event-stream" in r.headers["content-type"]

    events = _parse_sse(r.text)
    assert [e["type"] for e in events] == ["stage", "stage", "stage", "done"], events
    assert events[0]["text"] == "正在理解材料与任务要求…"
    assert events[1]["text"] == "正在梳理汇报结构…"
    assert events[2]["text"] == "大纲已就绪，正在校验与保存…"

    done = events[3]
    assert done["data"]["doc_id"]
    outline = done["data"]["outline"]
    assert outline["title"] == "行政复议工作汇报"
    slides = outline["slides"]
    assert len(slides) == 3
    for s in slides:
        assert "sources" in s and isinstance(s["sources"], list)
    assert slides[1]["sources"] == ["材料A.txt"]

    # 来源标注要求确实下发给了模型（provenance 约束不是摆设）
    assert "【来源标注】" in fake_llm.last_prompt
    assert "材料A.txt" in fake_llm.last_prompt and "材料B.csv" in fake_llm.last_prompt

    # 大纲已落库，后续编辑链路可拿到同一份
    got = client.get(f"{BASE}/ppt/documents/{done['data']['doc_id']}",
                     headers=_hdr(accounts["a"]))
    assert got.status_code == 200
    assert got.json()["outline"]["title"] == "行政复议工作汇报"


def test_outline_stream_emits_error_without_done(client, accounts, fake_llm):
    """模型返回非 JSON：只推 2 个 stage + error，不推 done。

    解析失败会自动重试一次（temperature 降到 0.2 并追加严格格式约束），
    因此模型共被调用 2 次；两次都失败才推 error，且绝不落库。
    """
    fake_llm._responder = lambda m: "抱歉，我无法完成这个请求。"
    r = client.post(f"{BASE}/ppt/outline/stream", json={
        "source_type": "topic", "topic": "随便一个主题",
    }, headers=_hdr(accounts["a"]))
    assert r.status_code == 200, r.text
    events = _parse_sse(r.text)
    assert [e["type"] for e in events] == ["stage", "stage", "error"], events
    assert events[-1]["message"]
    # 错误文案必须对用户可读：说明"没有生成任何文档"，且不带原始异常/英文报错
    message = events[-1]["message"]
    assert "没有生成任何文档" in message
    assert "Expecting" not in message and "JSONDecodeError" not in message
    # 首次失败 + 自动重试一次 = 2 次调用，重试温度降为 0.2
    assert len(fake_llm.calls) == 2, fake_llm.calls
    assert fake_llm.calls[0]["temperature"] == 0.5
    assert fake_llm.calls[1]["temperature"] == 0.2
    # 重试的 prompt 末尾追加了严格格式约束
    assert "只输出一个 JSON 对象" in fake_llm.calls[1]["messages"][-1]["content"]


def test_outline_stream_rescues_malformed_json_without_retry(client, accounts, fake_llm):
    """模型输出带尾随逗号 / 字符串内裸换行 / JSON 后追加说明：宽容解析直接救回。

    这是本次修复的核心场景：旧实现用贪婪正则 `\\{.*\\}` 吃到 JSON 后面的说明
    文字，再被零容错的 json.loads 抛成
    "Expecting property name enclosed in double quotes: ... (char 745)"。
    现在应当一次调用即成功，不产生额外重试开销。
    """
    malformed = (
        '{"title":"行政复议工作汇报","subtitle":"2026年第一季度","slides":['
        '{"type":"cover","title":"封面","subtitle":"副标题"},'
        '{"type":"content","title":"第一行\n第二行","points":["受理案件120件",],},'
        ']} 以上就是本次大纲，请查收。'
    )
    fake_llm._responder = lambda m: malformed
    r = client.post(f"{BASE}/ppt/outline/stream", json={
        "source_type": "topic", "topic": "随便一个主题",
    }, headers=_hdr(accounts["a"]))
    assert r.status_code == 200, r.text
    events = _parse_sse(r.text)
    assert [e["type"] for e in events] == ["stage", "stage", "stage", "done"], events
    assert len(fake_llm.calls) == 1, fake_llm.calls  # 宽容解析救回，无需重试
    outline = events[-1]["data"]["outline"]
    titles = [s["title"] for s in outline["slides"]]
    assert titles[0] == "封面"
    assert "第一行\n第二行" in titles  # 字符串内裸换行被正确还原为换行


def test_outline_stream_slide_count_clamped(client, accounts, fake_llm,
                                            outline_payload):
    """slide_count 越界时按 6~18 夹紧后下发给模型。"""
    fake_llm._responder = lambda m: json.dumps(outline_payload, ensure_ascii=False)
    r = client.post(f"{BASE}/ppt/outline/stream", json={
        "source_type": "topic", "topic": "主题", "slide_count": 99,
    }, headers=_hdr(accounts["a"]))
    assert r.status_code == 200, r.text
    assert _parse_sse(r.text)[-1]["type"] == "done"
    assert "18 页左右" in fake_llm.last_prompt or "18 页" in fake_llm.last_prompt


# ============================================================ 4. ai/slide-action


def test_ai_slide_action_requires_login(client):
    r = client.post(f"{BASE}/ppt/ai/slide-action",
                    json={"action": "rewrite", "slide": {"title": "x"}})
    assert r.status_code in (401, 403), r.text


def test_ai_slide_action_requires_action_and_slide(client, accounts):
    r1 = client.post(f"{BASE}/ppt/ai/slide-action", json={"slide": {"title": "x"}},
                     headers=_hdr(accounts["a"]))
    r2 = client.post(f"{BASE}/ppt/ai/slide-action", json={"action": "rewrite"},
                     headers=_hdr(accounts["a"]))
    assert r1.status_code == 422, r1.text
    assert r2.status_code == 422, r2.text


# ✅ 已修复（BUG-1）: server/app/application/ppt/ppt_engine.py:797
#   原写法 normalize_outline({"slides": [merged]})["slides"][0] 按索引取首屏。
#   normalize_outline() 恒定保证"首屏是 cover、末屏是 closing"，对非 cover 页
#   （编辑器里最常见的正文页）会在 index 0 插入一页合成封面，导致取到
#   title="演示文稿" 的空封面、AI 改写结果被整体丢弃。
#   现改为按 id 取回真正被改写的那一页，并保留 normalize_outline 的字段规范化。
#   下面两条即该缺陷的回归用例（原为 xfail(strict=True)，修复后转为常规断言）。


def test_ai_slide_action_rewrite_keeps_id_and_sources(client, accounts, fake_llm):
    slide = {"id": "abc12345", "type": "content", "title": "案件办理",
             "points": ["原要点"], "blocks": {}, "sources": ["材料A.txt"]}
    fake_llm._responder = lambda m: json.dumps({
        "id": "abc12345", "type": "content", "title": "一季度案件办理情况",
        "points": ["受理案件120件", "办结115件"], "blocks": {},
        "sources": ["材料A.txt"]}, ensure_ascii=False)

    r = client.post(f"{BASE}/ppt/ai/slide-action",
                    json={"action": "rewrite", "slide": slide},
                    headers=_hdr(accounts["a"]))
    assert r.status_code == 200, r.text
    out = r.json()["slide"]
    assert out["id"] == "abc12345", "单页改写必须保留原 id，否则编辑器选中态丢失"
    assert out["title"] == "一季度案件办理情况"
    assert len(out["points"]) == 2
    assert "sources" in out
    assert "整体重写这一页" in fake_llm.last_prompt


def test_ai_slide_action_custom_passes_instruction(client, accounts, fake_llm):
    slide = {"id": "s1", "type": "content", "title": "标题", "points": ["要点"]}
    fake_llm._responder = lambda m: json.dumps(
        {**slide, "title": "更正式的标题"}, ensure_ascii=False)
    r = client.post(f"{BASE}/ppt/ai/slide-action",
                    json={"action": "custom", "slide": slide,
                          "instruction": "把语气改得更正式一些"},
                    headers=_hdr(accounts["a"]))
    assert r.status_code == 200, r.text
    assert r.json()["slide"]["title"] == "更正式的标题"
    assert "把语气改得更正式一些" in fake_llm.last_prompt


def test_ai_slide_action_cover_page_roundtrip(client, accounts, fake_llm):
    """封面页（norm[0].type == cover）不会被插入合成封面，改写结果能正确返回。

    BUG-1 修复前这条也通过，正是它把缺陷范围锁定在「非 cover 页」。
    """
    slide = {"id": "cover1", "type": "cover", "title": "旧封面",
             "subtitle": "旧副标题", "points": [], "sources": []}
    fake_llm._responder = lambda m: json.dumps(
        {**slide, "title": "行政复议工作汇报", "subtitle": "2026年第一季度"},
        ensure_ascii=False)
    r = client.post(f"{BASE}/ppt/ai/slide-action",
                    json={"action": "rewrite", "slide": slide},
                    headers=_hdr(accounts["a"]))
    assert r.status_code == 200, r.text
    out = r.json()["slide"]
    assert out["id"] == "cover1"
    assert out["title"] == "行政复议工作汇报"
    assert out["subtitle"] == "2026年第一季度"


def test_ai_slide_action_content_page_returns_ai_result(fake_llm):
    """BUG-1 最小复现（直接打桩 ppt_engine.ai_slide_action，不经 HTTP）。

    防回归要点：正文页（type=content）经 normalize_outline 后会在 index 0 被
    插入一页合成封面（title="演示文稿"）。若哪天又把实现改回按索引取
    ["slides"][0]，本用例会立刻失败。
    """
    from app.application.ppt import ppt_engine

    slide = {"id": "abc12345", "type": "content", "title": "原标题",
             "points": ["原要点"], "sources": ["材料A.txt"]}
    fake_llm._responder = lambda m: json.dumps({
        "id": "abc12345", "type": "content", "title": "AI改写后的标题",
        "points": ["改写要点一", "改写要点二"], "sources": ["材料A.txt"],
    }, ensure_ascii=False)

    out = ppt_engine.ai_slide_action(fake_llm, "rewrite", slide)

    # 1) 必须是被改写的那一页，不能是 normalize_outline 凭空造的封面/结束页
    assert out["id"] == "abc12345", "正文页改写必须保留原 id"
    assert out["type"] == "content", f"不应返回合成页，实际 type={out['type']}"
    # 2) 内容必须是 AI 的输出，不能被丢弃成空壳
    assert out["title"] == "AI改写后的标题", f"实际 title={out['title']!r}"
    assert out["points"] == ["改写要点一", "改写要点二"], f"实际 points={out['points']!r}"
    assert out["sources"] == ["材料A.txt"], f"实际 sources={out['sources']!r}"
    # 3) 只返回一页的字段，不应混入 closing 页的标题
    assert out["title"] != "谢谢聆听，请批评指正"
    assert out["title"] != "演示文稿"


def test_ai_slide_action_model_garbage_is_502(client, accounts, fake_llm):
    fake_llm._responder = lambda m: "我无法输出 JSON"
    r = client.post(f"{BASE}/ppt/ai/slide-action",
                    json={"action": "rewrite", "slide": {"id": "s", "title": "x"}},
                    headers=_hdr(accounts["a"]))
    assert r.status_code == 502, r.text
    assert r.json()["detail"]


# ============================================================ 5. ai/visual


def test_ai_visual_requires_login(client):
    r = client.post(f"{BASE}/ppt/ai/visual",
                    json={"kind": "chart", "slide": {"title": "x"}})
    assert r.status_code in (401, 403), r.text


def test_ai_visual_requires_kind_and_slide(client, accounts):
    r1 = client.post(f"{BASE}/ppt/ai/visual", json={"slide": {"title": "x"}},
                     headers=_hdr(accounts["a"]))
    r2 = client.post(f"{BASE}/ppt/ai/visual", json={"kind": "chart"},
                     headers=_hdr(accounts["a"]))
    assert r1.status_code == 422, r1.text
    assert r2.status_code == 422, r2.text


def test_ai_visual_chart_writes_blocks(client, accounts, fake_llm):
    slide = {"id": "s1", "type": "content", "title": "案件数据",
             "points": ["受理120件", "办结115件"]}
    fake_llm._responder = lambda m: json.dumps({"blocks": {"chart": {
        "chart_type": "bar",
        "categories": ["受理", "办结"],
        "series": [{"name": "案件数", "values": [120, 115]}]}}}, ensure_ascii=False)
    r = client.post(f"{BASE}/ppt/ai/visual", json={"kind": "chart", "slide": slide},
                    headers=_hdr(accounts["a"]))
    assert r.status_code == 200, r.text
    out = r.json()["slide"]
    assert out["type"] == "chart"
    assert out["blocks"]["chart"]["chart_type"] == "bar"
    assert out["blocks"]["chart"]["series"][0]["values"] == [120, 115]


def test_ai_visual_timeline_sets_type(client, accounts, fake_llm):
    slide = {"id": "s1", "type": "content", "title": "工作进程"}
    fake_llm._responder = lambda m: json.dumps({"blocks": {"timeline": [
        {"time": "1月", "text": "部署动员"}, {"time": "3月", "text": "阶段总结"}]}},
        ensure_ascii=False)
    r = client.post(f"{BASE}/ppt/ai/visual", json={"kind": "timeline", "slide": slide},
                    headers=_hdr(accounts["a"]))
    assert r.status_code == 200, r.text
    out = r.json()["slide"]
    assert out["type"] == "timeline"
    assert len(out["blocks"]["timeline"]) == 2


def test_ai_visual_error_payload_is_502(client, accounts, fake_llm):
    fake_llm._responder = lambda m: json.dumps({"error": "数据不足，无法生成图表"},
                                               ensure_ascii=False)
    r = client.post(f"{BASE}/ppt/ai/visual",
                    json={"kind": "chart", "slide": {"id": "s", "title": "x"}},
                    headers=_hdr(accounts["a"]))
    assert r.status_code == 502, r.text
    assert "数据不足" in r.json()["detail"]


# ============================================================ 6. ai/structure


def test_ai_structure_requires_login(client):
    r = client.post(f"{BASE}/ppt/ai/structure",
                    json={"action": "add", "slides": [], "index": 0})
    assert r.status_code in (401, 403), r.text


def test_ai_structure_requires_fields(client, accounts):
    r = client.post(f"{BASE}/ppt/ai/structure", json={"action": "add"},
                    headers=_hdr(accounts["a"]))
    assert r.status_code == 422, r.text


def _three_slides():
    return [
        {"id": "c1", "type": "cover", "title": "封面", "subtitle": "副标题",
         "points": [], "sources": []},
        {"id": "n1", "type": "content", "title": "正文页",
         "points": ["要点一", "要点二", "要点三", "要点四"], "sources": ["材料A.txt"]},
        {"id": "e1", "type": "closing", "title": "谢谢聆听，请批评指正",
         "points": [], "sources": []},
    ]


def test_ai_structure_add_inserts_after_index(client, accounts, fake_llm):
    fake_llm._responder = lambda m: json.dumps(
        {"type": "content", "title": "新增的一页", "points": ["新增要点"]},
        ensure_ascii=False)
    slides = _three_slides()
    r = client.post(f"{BASE}/ppt/ai/structure",
                    json={"action": "add", "slides": slides, "index": 1},
                    headers=_hdr(accounts["a"]))
    assert r.status_code == 200, r.text
    out = r.json()["slides"]
    assert len(out) == 4
    assert out[2]["title"] == "新增的一页"
    # 新页被 normalize 补齐完整结构
    assert "sources" in out[2] and "id" in out[2]
    assert len(fake_llm.calls) == 1


def test_ai_structure_split_is_deterministic_without_llm(client, accounts, fake_llm):
    """拆分是纯规则逻辑：不调用模型，要点对半分，续页标题带（续）。"""
    slides = _three_slides()
    r = client.post(f"{BASE}/ppt/ai/structure",
                    json={"action": "split", "slides": slides, "index": 1},
                    headers=_hdr(accounts["a"]))
    assert r.status_code == 200, r.text
    out = r.json()["slides"]
    assert len(out) == 4
    assert out[1]["points"] == ["要点一", "要点二"]
    assert out[2]["points"] == ["要点三", "要点四"]
    assert out[2]["title"].endswith("（续）")
    assert len(fake_llm.calls) == 0, "拆分不应调用模型"


def test_ai_structure_merge_combines_points(client, accounts, fake_llm):
    slides = [
        {"id": "c1", "type": "cover", "title": "封面", "points": []},
        {"id": "n1", "type": "content", "title": "页一", "points": ["A", "B"]},
        {"id": "n2", "type": "content", "title": "页二", "points": ["C"]},
        {"id": "e1", "type": "closing", "title": "谢谢聆听，请批评指正", "points": []},
    ]
    r = client.post(f"{BASE}/ppt/ai/structure",
                    json={"action": "merge", "slides": slides, "index": 1},
                    headers=_hdr(accounts["a"]))
    assert r.status_code == 200, r.text
    out = r.json()["slides"]
    assert len(out) == 3
    assert out[1]["points"] == ["A", "B", "C"]
    assert len(fake_llm.calls) == 0, "合并不应调用模型"


def test_ai_structure_out_of_range_index_is_502(client, accounts, fake_llm):
    slides = _three_slides()
    r = client.post(f"{BASE}/ppt/ai/structure",
                    json={"action": "split", "slides": slides, "index": 99},
                    headers=_hdr(accounts["a"]))
    assert r.status_code == 502, r.text
    assert r.json()["detail"]


def test_ai_structure_merge_last_page_is_502(client, accounts, fake_llm):
    slides = _three_slides()
    r = client.post(f"{BASE}/ppt/ai/structure",
                    json={"action": "merge", "slides": slides, "index": 2},
                    headers=_hdr(accounts["a"]))
    assert r.status_code == 502, r.text


def test_ai_structure_unknown_action_is_502(client, accounts, fake_llm):
    r = client.post(f"{BASE}/ppt/ai/structure",
                    json={"action": "teleport", "slides": _three_slides(), "index": 0},
                    headers=_hdr(accounts["a"]))
    assert r.status_code == 502, r.text


# ============================================================ 7. 越权与资源隔离


def test_other_users_document_is_404_not_403(client, accounts):
    """他人的 PPT 文档一律 404（不泄露存在性），而不是 403。"""
    my_doc = _blank_doc(client, accounts["a"], "A的私有PPT")

    got = client.get(f"{BASE}/ppt/documents/{my_doc}", headers=_hdr(accounts["b"]))
    assert got.status_code == 404, got.text

    patch = client.patch(f"{BASE}/ppt/documents/{my_doc}", json={"title": "被改了"},
                         headers=_hdr(accounts["b"]))
    assert patch.status_code == 404, patch.text

    dele = client.delete(f"{BASE}/ppt/documents/{my_doc}", headers=_hdr(accounts["b"]))
    assert dele.status_code == 404, dele.text

    # 本人的仍然正常
    ok = client.get(f"{BASE}/ppt/documents/{my_doc}", headers=_hdr(accounts["a"]))
    assert ok.status_code == 200


def test_document_list_is_per_user(client, accounts):
    my_doc = _blank_doc(client, accounts["a"], "仅A可见")
    lst_b = client.get(f"{BASE}/ppt/documents", headers=_hdr(accounts["b"])).json()
    assert all(d["id"] != my_doc for d in lst_b["items"])


def test_missing_document_is_404(client, accounts):
    r = client.get(f"{BASE}/ppt/documents/no-such-doc-id", headers=_hdr(accounts["a"]))
    assert r.status_code == 404


def test_download_before_generate_is_404(client, accounts):
    doc_id = _blank_doc(client, accounts["a"], "尚未生成")
    r = client.get(f"{BASE}/ppt/documents/{doc_id}/download",
                   headers=_hdr(accounts["a"]))
    assert r.status_code == 404, r.text
