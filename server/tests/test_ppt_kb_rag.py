"""PPT 大纲接入知识库 RAG（提交 b1f28fb 等）专项验证测试。

运行方式（在 server/ 目录下）：
    D:/apps/anaconda3/python.exe -m pytest tests/test_ppt_kb_rag.py -v

覆盖目标（逐条对应验收要求）：
- A kb_ids 被真正消费：传了才检索（query=主题），不传绝不碰 RAG；
- B 降级不阻塞：RagService.search 抛异常时仍 200 且出大纲；
- C 检索为空时给明确报错（/outline /outline-from-kb /outline/stream 三条链路）；
- D /ppt/kbs 权限过滤（公开 + 本科室 + 个人，跨部门互不可见）；
- E 命中来源以「知识库《名》」并入 material_names；
- F 800 字/片段、4000 字总量封顶，top_k=8 下传给 RagService。

测试策略：模型与向量检索一律打桩（本地未启动 8001/8003 与向量库），
数据落在临时 sqlite，不写真实库，不起 uvicorn。
"""
import json
import os
import sys
import tempfile
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("AI_PROVIDER", "mock")

_TMPDIR = Path(tempfile.mkdtemp(prefix="test-ppt-kb-"))
os.environ.setdefault("DATA_DIR", str(_TMPDIR))
os.environ.setdefault("DATABASE_URL", f"sqlite:///{(_TMPDIR / 'test.db').as_posix()}")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.application.knowledge.rag_service import RagService  # noqa: E402
from app.core.exceptions import AppError  # noqa: E402
from app.infrastructure.database import Base, SessionLocal, engine  # noqa: E402
from app.infrastructure.database.models.identity import UserModel  # noqa: E402
from app.infrastructure.database.models.knowledge import KnowledgeBaseModel  # noqa: E402
from app.main import app  # noqa: E402

Base.metadata.create_all(bind=engine)

BASE = "/api/v1"
PWD = "Passw0rd!2026"
NEW_PWD = "Changed@2026"


# ============================================================ 打桩


class FakeGateway:
    """替身模型网关：记录每次调用并按 responder 返回。"""

    def __init__(self, responder=None):
        self.calls = []
        self._responder = responder or (lambda m: "{}")

    @property
    def model_name(self):
        return "fake-model"

    def complete(self, messages, temperature=0.7, max_tokens=4096):
        self.calls.append({"messages": messages})
        return self._responder(messages)

    @property
    def last_prompt(self):
        return self.calls[-1]["messages"][-1]["content"]


class FakeRag:
    """记录 RagService.search 的调用参数，返回可控 hits。"""

    def __init__(self, hits=None, exc=None):
        self.calls = []
        self.hits = hits if hits is not None else []
        self.exc = exc

    def __call__(self, query, user_id, top_k=None, kb_ids=None):
        """记录一次检索调用并返回预置 hits。"""
        self.calls.append({"query": query, "user_id": user_id,
                           "top_k": top_k, "kb_ids": kb_ids})
        if self.exc:
            raise self.exc
        return list(self.hits)

    def as_method(self):
        """产出可挂到 ``RagService.search`` 的函数。

        必须是函数（实现描述协议）才会被绑定成实例方法——直接挂对象不会被
        绑 self，参数会整体错位。
        """
        recorder = self

        def _search(rag_self, query, user_id, kb_types=None, top_k=None,
                    min_score=None, kb_ids=None, dept_code=None, scopes=None):
            return recorder(query, user_id, top_k=top_k, kb_ids=kb_ids)
        return _search


class _StubEmbedder:
    """占位 Embedder：只为让 RagService(...) 构造不失败（search 已被替换）。"""

    def encode_queries(self, texts):
        return [[0.0] * 8 for _ in texts]


@pytest.fixture
def fake_llm(monkeypatch):
    import app.infrastructure.ai as ai_mod
    import app.interfaces.ppt as ppt_iface

    fake = FakeGateway()
    monkeypatch.setattr(ai_mod, "get_ppt_gateway", lambda: fake)
    monkeypatch.setattr(ai_mod, "get_llm_gateway", lambda: fake)
    monkeypatch.setattr(ppt_iface, "get_llm_gateway", lambda: fake)
    ai_mod.reset_gateway()
    return fake


@pytest.fixture
def fake_rag(monkeypatch):
    """把 RagService.search 换成可控替身（服务内部为惰性 import，改类方法即可生效）。

    同时必须打桩 embedder / vector_store：测试环境未搭载本地 BGE 模型与向量库时
    ``get_embedder()`` 可能抛异常，而 ``_rag_kb_material`` 用宽 try 吞掉一切异常
    降级为空——不打桩就永远走不到检索那一行，会把「降级」误判成「未接入」。
    """
    import app.infrastructure.rag as rag_mod

    rec = FakeRag()
    monkeypatch.setattr(RagService, "search", rec.as_method())
    monkeypatch.setattr(rag_mod, "get_embedder", lambda: _StubEmbedder())
    monkeypatch.setattr(rag_mod, "get_vector_store", lambda: None)
    return rec


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _hdr(token):
    return {"Authorization": f"Bearer {token}"}


def _mk_kb(name, kb_type="public", dept_code="", owner_id=None):
    db = SessionLocal()
    try:
        kb = KnowledgeBaseModel(name=name, description=f"{name}描述",
                                kb_type=kb_type, department_code=dept_code,
                                owner_id=owner_id, is_active=True)
        db.add(kb)
        db.commit()
        db.refresh(kb)
        return kb.id
    finally:
        db.close()


@pytest.fixture(scope="module")
def accounts(client):
    """系统管理员 + 两个不同科室的普通用户 + 三种可见性的知识库。"""
    r = client.post(f"{BASE}/auth/register-first", json={
        "username": "kbdev", "email": "kbdev@test.local",
        "password": PWD, "real_name": "系统管理员"})
    if r.status_code == 200:
        dev = r.json()["access_token"]
    else:
        from app.core.security import create_access_token
        db = SessionLocal()
        try:
            row = db.scalar(select(UserModel).where(
                UserModel.role.in_(("developer", "admin"))))
            assert row is not None
            dev = create_access_token(
                {"sub": row.id, "username": row.username, "role": row.role})
        finally:
            db.close()

    def reg(username, dept_name, dept_code):
        rr = client.post(f"{BASE}/auth/register", json={
            "username": username, "email": f"{username}@test.local",
            "password": PWD, "department": dept_name, "role": "user",
        }, headers=_hdr(dev))
        assert rr.status_code == 200, rr.text
        uid = rr.json().get("id") or rr.json().get("user", {}).get("id")
        tok = client.post(f"{BASE}/auth/login", json={
            "username": username, "password": PWD}).json()["access_token"]
        ch = client.post(f"{BASE}/auth/change-password", json={
            "old_password": PWD, "new_password": NEW_PWD,
            "confirm_password": NEW_PWD}, headers=_hdr(tok))
        assert ch.status_code == 200, ch.text
        # 落库确认 uid 与 department_code（隔离维度以 code 为准）
        db = SessionLocal()
        try:
            row = db.scalar(select(UserModel).where(UserModel.username == username))
            uid = row.id
            row.department_code = dept_code
            db.commit()
        finally:
            db.close()
        return {"token": tok, "id": uid, "dept": dept_code}

    a = reg("kbusera", "法制与律师管理科", "fazhi")
    b = reg("kbuserb", "行政复议科", "fuyi")

    kbs = {
        "public": _mk_kb("全局公共库", "public", ""),
        "dept_a": _mk_kb("法制科专有库", "department", "fazhi"),
        "dept_b": _mk_kb("复议科专有库", "department", "fuyi"),
        "personal_a": _mk_kb("A的个人库", "personal", "", a["id"]),
        "personal_b": _mk_kb("B的个人库", "personal", "", b["id"]),
    }
    return {"dev": dev, "a": a, "b": b, "kbs": kbs}


@pytest.fixture
def outline_ok(fake_llm):
    """让替身模型恒定返回一份合法大纲。"""
    payload = {
        "title": "行政复议工作汇报", "subtitle": "2026年第一季度",
        "slides": [
            {"type": "cover", "title": "行政复议工作汇报",
             "subtitle": "2026年第一季度", "sources": []},
            {"type": "content", "title": "案件办理情况",
             "points": ["受理120件", "办结115件"], "sources": ["材料A.txt"]},
            {"type": "content", "title": "受理工作", "points": ["按规定受理申请"]},
            {"type": "content", "title": "审理工作", "points": ["依法审查材料"]},
            {"type": "content", "title": "协调机制", "points": ["加强部门衔接"]},
            {"type": "content", "title": "风险提示", "points": ["及时核对事实"]},
            {"type": "content", "title": "后续安排", "points": ["持续完善流程"]},
            {"type": "closing", "title": "谢谢聆听，请批评指正", "sources": []},
        ]}
    fake_llm._responder = lambda m: json.dumps(payload, ensure_ascii=False)
    return payload


def _hit(content="知识库片段正文。", name="XX制度汇编",
         source="某某办法（第3段）"):
    return {"content": content, "source": source, "source_name": name,
            "doc_id": "d1", "score": 0.9, "match_type": "hybrid"}


def _events(text):
    out = []
    for line in (text or "").splitlines():
        line = line.strip()
        if line.startswith("data:"):
            out.append(json.loads(line[len("data:"):].strip()))
    return out


def _svc_and_user(user_id):
    from app.application.ppt.service import PPTService
    from app.application.shared.writing_assistant import WritingAssistant
    from app.infrastructure.repositories.identity import SqlAlchemyUserRepository
    db = SessionLocal()
    try:
        user = SqlAlchemyUserRepository(db).get(user_id)
        return db, PPTService(db, WritingAssistant(FakeGateway())), user
    except Exception:
        db.close()
        raise


# ============================================================ A. kb_ids 被真正消费


def test_a1_outline_with_kb_ids_calls_rag_using_topic(client, accounts,
                                                      fake_llm, fake_rag,
                                                      outline_ok):
    """传 kb_ids → 必须触发检索，且 query 用的是主题词，top_k=8。"""
    fake_rag.hits = [_hit()]
    r = client.post(f"{BASE}/ppt/outline", json={
        "source_type": "topic", "topic": "行政复议规范化建设",
        "slide_count": 8, "material_names": ["材料A.txt"],
        "kb_ids": [accounts["kbs"]["public"]]}, headers=_hdr(accounts["a"]["token"]))
    assert r.status_code == 200, r.text

    assert len(fake_rag.calls) == 1, f"未触发检索：{fake_rag.calls}"
    call = fake_rag.calls[0]
    assert call["query"] == "行政复议规范化建设", call
    assert call["kb_ids"] == [accounts["kbs"]["public"]], call
    assert call["top_k"] == 8, call
    assert call["user_id"] == accounts["a"]["id"], call

    # 命中内容确实进了模型上下文
    assert "【知识库检索材料】" in fake_llm.last_prompt
    assert "知识库片段正文" in fake_llm.last_prompt


def test_a2_no_kb_ids_never_touches_rag(client, accounts, fake_llm,
                                        fake_rag, outline_ok):
    """不传 kb_ids → 绝不触发检索（不能误伤原有流程）。"""
    r = client.post(f"{BASE}/ppt/outline", json={
        "source_type": "topic", "topic": "行政复议规范化建设",
        "slide_count": 8}, headers=_hdr(accounts["a"]["token"]))
    assert r.status_code == 200, r.text
    assert fake_rag.calls == [], f"未选知识库却触发了检索：{fake_rag.calls}"
    assert "【知识库检索材料】" not in fake_llm.last_prompt


def test_a3_empty_kb_ids_list_does_not_trigger(client, accounts, fake_llm,
                                               fake_rag, outline_ok):
    r = client.post(f"{BASE}/ppt/outline", json={
        "source_type": "topic", "topic": "主题词", "kb_ids": []},
        headers=_hdr(accounts["a"]["token"]))
    assert r.status_code == 200, r.text
    assert fake_rag.calls == []


def test_a4_content_used_as_query_when_topic_blank(client, accounts, fake_llm,
                                                   fake_rag, outline_ok):
    """无主题但有材料正文 → 用正文前 200 字当检索词。"""
    fake_rag.hits = [_hit()]
    long_text = "乙" * 500
    r = client.post(f"{BASE}/ppt/outline", json={
        "source_type": "topic", "topic": "", "content": long_text,
        "kb_ids": [accounts["kbs"]["public"]]}, headers=_hdr(accounts["a"]["token"]))
    assert r.status_code == 200, r.text
    assert len(fake_rag.calls) == 1
    assert fake_rag.calls[0]["query"] == long_text[:200]


# ============================================================ B. 检索异常降级不阻塞


def test_b1_search_raises_but_outline_still_200(client, accounts, fake_llm,
                                                fake_rag, outline_ok):
    """RagService.search 抛异常 → 仍 200 且出大纲，只是没有知识库素材。"""
    fake_rag.exc = RuntimeError("chromadb connection refused")
    r = client.post(f"{BASE}/ppt/outline", json={
        "source_type": "topic", "topic": "行政复议规范化建设",
        "kb_ids": [accounts["kbs"]["public"]]}, headers=_hdr(accounts["a"]["token"]))

    assert r.status_code == 200, f"检索异常被冒泡成 {r.status_code}：{r.text}"
    body = r.json()
    assert body["outline"]["title"] == "行政复议工作汇报"
    assert len(body["outline"]["slides"]) == 8
    assert body["outline"]["slides"][0]["type"] == "cover"
    assert body["outline"]["slides"][1]["type"] == "content"
    assert body["outline"]["slides"][-1]["type"] == "closing"
    assert body["doc_id"]
    prompts = [call["messages"][-1]["content"] for call in fake_llm.calls]
    assert all("【知识库检索材料】" not in p for p in prompts)


def test_b2_stream_search_raises_still_emits_done(client, accounts, fake_llm,
                                                  fake_rag, outline_ok):
    """流式链路同样不能被检索异常拖垮：仍以 done 收尾。"""
    fake_rag.exc = TimeoutError("embed timeout")
    r = client.post(f"{BASE}/ppt/outline/stream", json={
        "source_type": "topic", "topic": "行政复议规范化建设",
        "kb_ids": [accounts["kbs"]["public"]], "auto_images": False,
    }, headers=_hdr(accounts["a"]["token"]))
    assert r.status_code == 200, r.text
    ev = _events(r.text)
    assert [e["type"] for e in ev] == [
        "stage", "stage", "stage", "stage", "stage", "done"], ev
    assert ev[1]["text"] == "正在知识库中检索相关材料…"
    assert ev[-1]["data"]["outline"]["title"] == "行政复议工作汇报"


def test_b3_missing_vector_stack_still_ok(client, accounts, fake_llm, outline_ok,
                                          monkeypatch):
    """更真实的降级：get_embedder/get_vector_store 直接炸（向量组件不可用）。"""
    import app.infrastructure.rag as rag_mod

    def boom():
        raise ImportError("faiss not installed")

    monkeypatch.setattr(rag_mod, "get_embedder", boom)
    monkeypatch.setattr(rag_mod, "get_vector_store", boom)
    r = client.post(f"{BASE}/ppt/outline", json={
        "source_type": "topic", "topic": "主题词",
        "kb_ids": [accounts["kbs"]["public"]]}, headers=_hdr(accounts["a"]["token"]))
    assert r.status_code == 200, f"向量组件不可用时返回 {r.status_code}：{r.text}"
    assert r.json()["outline"]["title"] == "行政复议工作汇报"


# ============================================================ C. 检索为空的报错


def test_c1_outline_from_kb_empty_hits_400_with_clear_message(
        client, accounts, fake_llm, fake_rag):
    """/outline-from-kb 检索为空 → 明确 400 文案（不是空大纲、不是 500）。"""
    fake_rag.hits = []
    r = client.post(f"{BASE}/ppt/outline-from-kb", data={
        "kb_ids": accounts["kbs"]["public"], "topic": "完全无关的冷门主题",
        "slide_count": 8}, headers=_hdr(accounts["a"]["token"]))

    assert r.status_code == 400, f"期望 400，实际 {r.status_code}：{r.text}"
    msg = r.json().get("detail", r.text)
    print(f"\n[C1] /outline-from-kb 空检索返回文案 => {msg}")
    assert "知识库" in msg and "检索" in msg
    assert "换个主题" in msg or "已发布文档" in msg
    assert r.text.strip() and "Traceback" not in r.text


def test_c2_outline_source_kb_empty_hits_400(client, accounts, fake_llm, fake_rag):
    """/outline source_type=kb 检索为空 → 同样明确 400。"""
    fake_rag.hits = []
    r = client.post(f"{BASE}/ppt/outline", json={
        "source_type": "kb", "topic": "完全无关的冷门主题",
        "kb_ids": [accounts["kbs"]["public"]]}, headers=_hdr(accounts["a"]["token"]))
    assert r.status_code == 400, r.text
    print(f"\n[C2] /outline(kb) 空检索返回文案 => {r.json().get('detail')}")


def test_c3_stream_source_kb_empty_hits_emits_error(client, accounts,
                                                    fake_llm, fake_rag):
    """流式链路空检索 → error 事件，且绝不推 done。"""
    fake_rag.hits = []
    r = client.post(f"{BASE}/ppt/outline/stream", json={
        "source_type": "kb", "topic": "完全无关的冷门主题",
        "kb_ids": [accounts["kbs"]["public"]]}, headers=_hdr(accounts["a"]["token"]))
    assert r.status_code == 200, r.text
    ev = _events(r.text)
    assert [e["type"] for e in ev] == ["stage", "stage", "error"], ev
    print(f"\n[C3] 流式 error 事件文案 => {ev[-1]['message']}")
    assert "知识库" in ev[-1]["message"]


def test_c4_topic_flow_empty_hits_behaviour_probe(client, accounts, fake_llm,
                                                  fake_rag, outline_ok):
    """探针：source_type=topic + 选了库 + 检索为空的真实行为（留证据）。"""
    fake_rag.hits = []
    r = client.post(f"{BASE}/ppt/outline", json={
        "source_type": "topic", "topic": "行政复议规范化建设",
        "kb_ids": [accounts["kbs"]["public"]]}, headers=_hdr(accounts["a"]["token"]))
    print(f"\n[C4] topic 流程空检索：HTTP {r.status_code}，"
          f"outline.title={r.json().get('outline', {}).get('title')!r}，"
          f"prompt 含知识库材料={'【知识库检索材料】' in fake_llm.last_prompt}")
    assert r.status_code == 200


# ============================================================ D. /ppt/kbs 权限过滤


def test_d1_kbs_only_visible_scope(client, accounts):
    """公开库 + 本科室 + 本人个人库可见，其他科室/他人个人库一律不可见。"""
    ka = {i["id"]: i["name"] for i in
          client.get(f"{BASE}/ppt/kbs", headers=_hdr(accounts["a"]["token"])).json()["items"]}
    kb = {i["id"]: i["name"] for i in
          client.get(f"{BASE}/ppt/kbs", headers=_hdr(accounts["b"]["token"])).json()["items"]}
    print(f"\n[D1] user_a 可见 => {sorted(ka.values())}")
    print(f"[D1] user_b 可见 => {sorted(kb.values())}")
    kbs = accounts["kbs"]

    assert kbs["public"] in ka and kbs["public"] in kb          # 公开库双方可见
    assert kbs["dept_a"] in ka and kbs["dept_a"] not in kb      # A 科室库 B 不可见
    assert kbs["dept_b"] in kb and kbs["dept_b"] not in ka      # B 科室库 A 不可见
    assert kbs["personal_a"] in ka and kbs["personal_a"] not in kb
    assert kbs["personal_b"] in kb and kbs["personal_b"] not in ka


def test_d2_kbs_requires_login(client):
    r = client.get(f"{BASE}/ppt/kbs")
    assert r.status_code in (401, 403), r.status_code


def test_d3_kbs_forbidden_id_not_returned_even_if_asked(client, accounts,
                                                        fake_llm, fake_rag,
                                                        outline_ok):
    """越权探测：传入 B 科室库 id，RagService 交集应把它挡下。

    此处 PPTService 不做交集（交给 RagService），故只断言 _rag_kb_material
    把客户端 kb_ids 原样下传、由 RagService 侧取交集。
    """
    fake_rag.hits = [_hit()]
    r = client.post(f"{BASE}/ppt/outline", json={
        "source_type": "topic", "topic": "主题词",
        "kb_ids": [accounts["kbs"]["dept_b"]]},
        headers=_hdr(accounts["a"]["token"]))
    assert r.status_code == 200, r.text
    assert fake_rag.calls[0]["kb_ids"] == [accounts["kbs"]["dept_b"]]


# ============================================================ E. material_names


def test_e1_hit_sources_join_material_names(client, accounts, fake_llm,
                                            fake_rag, outline_ok):
    """命中来源以「知识库《名》」并入 material_names 并下发给模型。"""
    fake_rag.hits = [_hit(name="复议案件办理规范", source="复议办法（第3段）"),
                     _hit(name="复议案件办理规范", source="复议办法（第7段）"),
                     _hit(name="", source="无主名 gjz新（第1段）")]
    r = client.post(f"{BASE}/ppt/outline", json={
        "source_type": "topic", "topic": "行政复议规范化建设",
        "material_names": ["材料A.txt"],
        "kb_ids": [accounts["kbs"]["public"]]}, headers=_hdr(accounts["a"]["token"]))
    assert r.status_code == 200, r.text
    prompts = [call["messages"][-1]["content"] for call in fake_llm.calls]
    generation_prompt = next(
        p for p in prompts if "知识库《复议案件办理规范》" in p)
    assert "知识库《复议案件办理规范》" in generation_prompt
    # source_name 缺失时，从 source 字段提取干净标题（不再回落「知识库文档」）
    assert "知识库《无主名 gjz新》" in generation_prompt
    # 原文 material_names 不被吞掉
    assert "材料A.txt" in generation_prompt
    # 片段带来源标注《名》（第N段）
    assert "（复议办法（第3段））" in generation_prompt


def test_e2_unit_material_names_and_limit(accounts, fake_rag):
    """单元级：material_names 条目 + 800/4000 字封顶 + 片段结构。"""
    fake_rag.hits = [{"content": "字" * 5000, "source": "某笨办法（第1段）",
                      "source_name": "长文档"}]
    db, svc, user = _svc_and_user(accounts["a"]["id"])
    try:
        content, names = svc._apply_kb_material(
            user, ["kb1"], "主题", "原文", ["材料A.txt"])
        assert names == ["材料A.txt", "知识库《长文档》"], names
        seg = content.split("【知识库检索材料】\n")[1]
        body = seg.split("\n", 1)[1]
        assert seg.startswith("《长文档》（某笨办法（第1段））")
        assert len(body) == 800, f"片段未按 800 字截断：{len(body)}"

        # 6 个 900 字段落的原始总量远超 4000，必须按总量封顶
        fake_rag.hits = [{"content": "丙" * 900, "source": f"文档{i}（第1段）",
                          "source_name": f"文档{i}"} for i in range(6)]
        content2, names2 = svc._apply_kb_material(user, ["kb1"], "主题", "", None)
        material_block = content2.split("【知识库检索材料】\n")[1]
        blob = material_block.replace("\n\n", "")
        assert len(blob) <= 4200, f"总量未封顶：{len(blob)}"
        assert len(names2) < 6, f"封顶后仍收全来源：{names2}"
    finally:
        db.close()


def test_e3_no_query_falls_back_to_whole_kb_concat(accounts, fake_rag, monkeypatch):
    """无检索词（纯选库）→ 回退旧整库拼接，不调 RagService。"""
    # 造一篇已发布文档供拼接
    from app.infrastructure.database.models.knowledge import DocumentModel
    db = SessionLocal()
    try:
        db.add(DocumentModel(kb_id=accounts["kbs"]["public"], title="OldPath文档",
                             status="published", content="旧路径正文内容" * 50,
                             department_code=""))
        db.commit()
    finally:
        db.close()
    db, svc, user = _svc_and_user(accounts["a"]["id"])
    try:
        content, names = svc._apply_kb_material(
            user, [accounts["kbs"]["public"]], "", "", [])
        assert fake_rag.calls == [], f"无检索词却走了 RAG：{fake_rag.calls}"
        assert "OldPath文档" in content
        # BUG-3 修复：纯选库回退整库拼接时，文档标题应进入 material_names
        assert "知识库《OldPath文档》" in names, names
    finally:
        db.close()


# ============================================================ F. 不传时零副作用


def test_f1_outline_from_kb_semantic_path(client, accounts, fake_llm,
                                          fake_rag, outline_ok):
    """/outline-from-kb 有主题时走语义检索而非整库拼接。"""
    fake_rag.hits = [_hit()]
    r = client.post(f"{BASE}/ppt/outline-from-kb", data={
        "kb_ids": accounts["kbs"]["public"], "topic": "行政复议规范化建设",
        "slide_count": 8}, headers=_hdr(accounts["a"]["token"]))
    assert r.status_code == 200, r.text
    assert len(fake_rag.calls) == 1
    assert fake_rag.calls[0]["query"] == "行政复议规范化建设"
    assert "知识库片段正文" in fake_llm.last_prompt


def test_f2_outline_from_kb_no_topic_falls_back(client, accounts, fake_llm,
                                                fake_rag, outline_ok):
    """/outline-from-kb 无主题 → 整库拼接回退，不触发检索且不报错。"""
    from app.infrastructure.database.models.knowledge import DocumentModel
    db = SessionLocal()
    try:
        db.add(DocumentModel(kb_id=accounts["kbs"]["public"], title="回退文档",
                             status="published", content="回退正文", department_code=""))
        db.commit()
    finally:
        db.close()
    r = client.post(f"{BASE}/ppt/outline-from-kb", data={
        "kb_ids": accounts["kbs"]["public"], "topic": "", "slide_count": 8},
        headers=_hdr(accounts["a"]["token"]))
    assert r.status_code == 200, r.text
    assert fake_rag.calls == []
    assert "回退文档" in fake_llm.last_prompt


# ============================================================ G. BUG-1 预检放行纯选库

def test_g1_precheck_kb_only_does_not_raise(client, accounts, fake_rag):
    """BUG-1：仅选了知识库（topic/content 空）时，生成前预检不应 400。

    知识库会提供内容，因此只选库也必须放行；连库都没选才应继续保持 400。
    """
    db, svc, user = _svc_and_user(accounts["a"]["id"])
    try:
        body_kb = types.SimpleNamespace(topic="", content="",
                                        material_names=[],
                                        kb_ids=[accounts["kbs"]["public"]])
        # 仅选库：不应抛 AppError(400)
        result = svc.precheck_outline(body_kb, user)
        assert isinstance(result, dict), result

        # 反例：连库都没选，仍应 400
        body_empty = types.SimpleNamespace(topic="", content="",
                                          material_names=[], kb_ids=[])
        with pytest.raises(AppError):
            svc.precheck_outline(body_empty, user)
    finally:
        db.close()


# ============================================================ H. BUG-2 空知识库报错

def test_h1_kb_only_empty_hits_400_nonstream(client, accounts, fake_llm, fake_rag):
    """BUG-2：纯选库（无主题/无正文）且 KB 整库无内容 → /outline 必须 400。

    用新建的空库，避免被其它用例写入的已发布文档干扰（走整库拼接回退分支）。
    """
    empty_kb = _mk_kb("空库用于空检索测试", "public", "")
    fake_rag.hits = []
    r = client.post(f"{BASE}/ppt/outline", json={
        "source_type": "topic", "topic": "", "content": "",
        "kb_ids": [empty_kb]}, headers=_hdr(accounts["a"]["token"]))
    assert r.status_code == 400, r.text
    msg = r.json().get("detail", r.text)
    assert "知识库" in msg and ("换个主题" in msg or "已发布文档" in msg)


def test_h2_kb_only_empty_hits_error_stream(client, accounts, fake_llm, fake_rag):
    """BUG-2：纯选库（无主题/无正文）且 KB 整库无内容 → /outline/stream 必须发 error 事件。"""
    empty_kb = _mk_kb("空库用于流式空检索测试", "public", "")
    fake_rag.hits = []
    r = client.post(f"{BASE}/ppt/outline/stream", json={
        "source_type": "topic", "topic": "", "content": "",
        "kb_ids": [empty_kb]}, headers=_hdr(accounts["a"]["token"]))
    assert r.status_code == 200, r.text
    ev = _events(r.text)
    assert ev[-1]["type"] == "error", ev
    assert "知识库" in ev[-1]["message"]


# ============================================================ I. DEF-2 来源名提取

def test_i1_source_title_from_source_field(accounts, fake_rag):
    """DEF-2：source_name 为 None 时，来源名应从 source 提取干净标题（去掉「（第N段）」）。"""
    fake_rag.hits = [{"content": "复议相关内容。", "source": "复议办法（第3段）",
                      "source_name": None, "doc_id": "d1", "score": 0.9,
                      "match_type": "hybrid"}]
    db, svc, user = _svc_and_user(accounts["a"]["id"])
    try:
        content, names = svc._apply_kb_material(user, ["kb1"], "复议", "", [])
        assert names == ["知识库《复议办法》"], names
        block = content.split("【知识库检索材料】\n", 1)[1]
        # 片段以干净标题《复议办法》开头
        assert block.startswith("《复议办法》"), block
        # 下游会把 source 的「（第N段）」重新拼回，保留片段出处
        assert "（复议办法（第3段））" in block
    finally:
        db.close()

