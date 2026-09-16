"""全功能详细验收测试套件（司法局智能写作 App）。

运行方式（在 server/ 目录下）：
    AI_PROVIDER=mock python3 -m pytest tests/test_full_acceptance.py -v

覆盖范围：
A. 任务解析器（确定性层）：文种/主题/文号/日期语义/字数/收件人
B. LLM 意图解释器：JSON 健壮性（fence/多余文本/畸形/缺字段/未知意图/schema 标记）
C. 写作任务全链路（API 级）：创建→对话→绑定模板/知识库→起草→修改→版本→导出
D. 日期语义专项：内容时间 vs 落款日期
E. 模板/知识库关联专项：模板进提示词、kb_ids 限定检索
F. 版本 docx 导出：可编辑、带格式、内容正确
G. 格式校验：规则 CRUD、无规则 AI 校验、权限、跨用户隔离
H. 写作任务隔离与边界：404、空草稿修改冲突、训练样本
"""
import io
import json
import os
import sys
import uuid
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("AI_PROVIDER", "mock")
os.environ.setdefault("DATA_DIR", f"/tmp/test-data-{uuid.uuid4().hex[:8]}")
os.environ.setdefault("DATABASE_URL", f"sqlite:////tmp/test-db-{uuid.uuid4().hex[:8]}.db")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.infrastructure.database import Base, engine  # noqa: E402

# 服务级测试不走应用 lifespan，这里幂等建表（create_all 对已有表无副作用）
Base.metadata.create_all(bind=engine)
from app.application.writing import task_parser  # noqa: E402
from app.application.writing.intent_interpreter import (  # noqa: E402
    WritingIntentInterpreter,
    _extract_json,
    _sanitize,
)


# ---------------------------------------------------------------- 工具

class ScriptedAssistant:
    """可编程的 LLM 替身：按队列返回预置回复，记录所有调用。"""

    def __init__(self, replies=None):
        self.replies = list(replies or [])
        self.calls = []

    def complete(self, messages, temperature=0.7, max_tokens=4096):
        self.calls.append(messages)
        if self.replies:
            return self.replies.pop(0)
        return "（Stub）默认回复"

    def chat(self, message, history=None, sources=None, user_role="user",
             system_prompt=None, attachment_context=None):
        self.calls.append([{"role": "system", "content": system_prompt or ""},
                           {"role": "user", "content": message}])
        if self.replies:
            return self.replies.pop(0)
        return "（Stub）起草正文：一、主要工作。二、下一步安排。"


def intent_json(**kw):
    base = {"_schema": "writing_intent_v1", "intent": "update_context",
            "reply": "好的。"}
    base.update(kw)
    return json.dumps(base, ensure_ascii=False)


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def auth_headers(client, email, name="测试用户", admin=False):
    username = email.split("@")[0]
    body = {"username": username, "email": email, "password": "pass1234",
            "real_name": name}
    # 首个用户走 register-first（公开），其后用户由管理员接口创建——
    # 测试环境直接在库中插入，避免依赖管理员会话
    r = client.post("/api/v1/auth/register-first", json=body)
    if r.status_code not in (200, 201):
        from app.infrastructure.database import SessionLocal
        from app.infrastructure.database.models.identity import UserModel
        db = SessionLocal()
        if not db.query(UserModel).filter(UserModel.username == username).first():
            make_db_user(db, username=username)
        db.close()
    if admin:
        from app.infrastructure.database import SessionLocal
        from app.infrastructure.database.models.identity import UserModel
        db = SessionLocal()
        u = db.query(UserModel).filter(UserModel.username == username).first()
        u.role = "admin"
        db.commit()
        db.close()
    r = client.post("/api/v1/auth/login",
                    json={"username": username, "password": "pass1234"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def make_docx_bytes(paragraphs):
    from docx import Document
    doc = Document()
    for p in paragraphs:
        doc.add_paragraph(p)
    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf.read()


def docx_text(data: bytes) -> str:
    from docx import Document
    return "\n".join(p.text for p in Document(io.BytesIO(data)).paragraphs)


# ---------------------------------------------------------------- A. 解析器

class TestParser:
    def test_doctype_long_first(self):
        assert task_parser.parse_message("写一份工作总结")["document_type"] == "工作总结"

    def test_topic_extraction(self):
        upd = task_parser.parse_message("帮我写一份2026年度司法行政工作总结")
        assert upd["topic"] == "司法行政"
        assert upd["time_range"] == "2026年度"

    def test_docnum_verbatim(self):
        upd = task_parser.parse_message("文号用司发〔2026〕12号")
        assert upd["document_number_enabled"] is True
        assert upd["document_number"] == "司发〔2026〕12号"

    def test_docnum_off(self):
        upd = task_parser.parse_message("不要文号")
        assert upd["document_number_enabled"] is False

    def test_word_count(self):
        assert task_parser.parse_message("写3000字左右")["word_count_target"] == 3000

    def test_word_count_section_guard(self):
        assert "word_count_target" not in task_parser.parse_message("第三部分写300字")

    def test_recipient(self):
        assert "市司法局" in task_parser.parse_message("主送：市司法局")["recipient"]

    # ---- 日期语义（本次重点）----
    def test_content_period_not_signoff_date(self):
        """下半年的工作计划：不得占用落款日期"""
        upd = task_parser.parse_message("帮我写下半年的工作计划")
        assert "document_date" not in upd

    def test_explicit_time_is_signoff_date(self):
        upd = task_parser.parse_message("标题重写一下，时间是2026年10月15日")
        assert upd["document_date"] == "2026年10月15日"
        assert "time_range" not in upd  # 落款日期的年份不占用时间范围

    def test_luokuan_cue(self):
        assert task_parser.parse_message("落款日期是2026年7月1日")["document_date"] == "2026年7月1日"

    def test_chengwen_cue(self):
        assert task_parser.parse_message("成文日期：2026年3月5日")["document_date"] == "2026年3月5日"

    def test_today_date(self):
        upd = task_parser.parse_message("用今天的日期")
        assert "document_date" in upd and "年" in upd["document_date"]

    def test_bare_date_no_cue_ignored(self):
        """孤立日期且无落款线索：不占落款日期（可能是内容时间）"""
        upd = task_parser.parse_message("2026年7月1日前完成社区矫正排查")
        assert "document_date" not in upd

    def test_empty_context_has_binding_fields(self):
        ctx = task_parser.empty_context()
        assert ctx["template_id"] is None
        assert ctx["kb_ids"] == []
        assert ctx["document_number_enabled"] is False


# ---------------------------------------------------------------- B. 意图解释器

class TestInterpreterRobustness:
    def test_plain_json(self):
        assert _extract_json('{"a": 1}') == {"a": 1}

    def test_fenced_json(self):
        assert _extract_json('```json\n{"a": 1}\n```') == {"a": 1}

    def test_extra_text_around(self):
        assert _extract_json('好的，结果如下：{"a": 1} 请查收') == {"a": 1}

    def test_malformed_returns_none(self):
        assert _extract_json('{"a": 1') is None

    def test_no_json_returns_none(self):
        assert _extract_json("我完全无法理解") is None

    def test_brace_inside_string(self):
        assert _extract_json('{"a": "这里有}花括号"}') == {"a": "这里有}花括号"}

    def test_sanitize_unknown_intent(self):
        out = _sanitize({"intent": "fly_to_moon"})
        assert out["intent"] == "answer"

    def test_sanitize_key_facts_string_to_list(self):
        out = _sanitize({"intent": "draft", "key_facts": "法治宣传"})
        assert out["key_facts"] == ["法治宣传"]

    def test_schema_marker_required(self):
        """无 schema 标记的 JSON（如 Mock 回显）不得被当作意图"""
        interp = WritingIntentInterpreter(ScriptedAssistant(['{"intent": "draft"}']))
        assert interp.interpret("起草吧") is None

    def test_valid_interpretation(self):
        interp = WritingIntentInterpreter(ScriptedAssistant(
            [intent_json(intent="update_context", document_type="报告", topic="晋升")]))
        out = interp.interpret("写一个晋升报告")
        assert out["intent"] == "update_context"
        assert out["topic"] == "晋升"

    def test_llm_exception_returns_none(self):
        class Boom:
            def complete(self, *a, **k):
                raise ConnectionError("vllm down")
        assert WritingIntentInterpreter(Boom()).interpret("hi") is None

    def test_llm_none_assistant(self):
        assert WritingIntentInterpreter(None).interpret("hi") is None


# ---------------------------------------------------------------- C. 写作任务全链路

@pytest.fixture(scope="module")
def user_a(client):
    return auth_headers(client, f"a-{uuid.uuid4().hex[:6]}@t.cn")


@pytest.fixture(scope="module")
def admin(client):
    return auth_headers(client, f"admin-{uuid.uuid4().hex[:6]}@t.cn", admin=True)


class TestWritingTaskFlow:
    def test_create_and_reply(self, client, user_a):
        r = client.post("/api/v1/writing/tasks", headers=user_a,
                        json={"message": "帮我写一份2026年度司法行政工作总结"})
        assert r.status_code == 201, r.text
        d = r.json()
        assert d["task_id"]
        ctx = d["task_context"]
        assert ctx["document_type"] == "工作总结"
        assert ctx["topic"] == "司法行政"
        assert ctx["document_number_enabled"] is False
        assert d["reply"]

    def test_chat_updates_context(self, client, user_a):
        tid = client.post("/api/v1/writing/tasks", headers=user_a,
                          json={"message": "写一份通知"}).json()["task_id"]
        r = client.post(f"/api/v1/writing/tasks/{tid}/chat", headers=user_a,
                        json={"message": "主送：各司法所"})
        assert r.status_code == 200
        assert "各司法所" in r.json()["task_context"]["recipient"]

    def test_patch_binding_template_kb(self, client, user_a):
        tid = client.post("/api/v1/writing/tasks", headers=user_a,
                          json={"message": "写一份通知"}).json()["task_id"]
        r = client.put(f"/api/v1/writing/tasks/{tid}", headers=user_a,
                       json={"context": {"template_id": "not-exist", "kb_ids": ["kb1"]}})
        ctx = r.json()["task_context"]
        assert ctx["template_id"] is None       # 不存在的模板自动解绑，不阻塞
        assert ctx["kb_ids"] == ["kb1"]

    def test_revise_without_draft_409(self, client, user_a):
        tid = client.post("/api/v1/writing/tasks", headers=user_a,
                          json={"message": "写一份通知"}).json()["task_id"]
        r = client.post(f"/api/v1/writing/tasks/{tid}/revise", headers=user_a,
                        json={"instruction": "扩写"})
        assert r.status_code == 409

    def test_draft_version_export_flow(self, client, user_a):
        """起草→版本→当前导出→版本导出，全部真实 docx"""
        tid = client.post("/api/v1/writing/tasks", headers=user_a,
                          json={"message": "帮我写一份2026年度司法行政工作总结"}).json()["task_id"]
        r = client.post(f"/api/v1/writing/tasks/{tid}/draft", headers=user_a,
                        json={"outline_only": False})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["content_changed"] is True
        assert d["version_no"] == 1
        assert len(d["current_content"]) > 10

        # 修改（自然语言指令，mock 模式下走规则回退 revise）
        r = client.post(f"/api/v1/writing/tasks/{tid}/revise", headers=user_a,
                        json={"instruction": "润色全文", "mode": "polish"})
        assert r.status_code == 200
        assert r.json()["version_no"] == 2

        # 版本列表
        r = client.get(f"/api/v1/writing/tasks/{tid}/versions", headers=user_a)
        assert r.status_code == 200
        assert [v["version_no"] for v in r.json()["items"]] == [1, 2]

        # 当前内容导出 docx
        r = client.get(f"/api/v1/writing/tasks/{tid}/export", headers=user_a)
        assert r.status_code == 200
        assert r.content[:2] == b"PK"  # 真实 docx（zip）
        text = docx_text(r.content)
        assert "司法行政" in text or "工作总结" in text

        # 历史版本导出 docx（v1 与 v2 均可）
        for no in (1, 2):
            r = client.get(f"/api/v1/writing/tasks/{tid}/versions/{no}/export",
                           headers=user_a)
            assert r.status_code == 200, f"v{no} 导出失败"
            assert r.content[:2] == b"PK"
            assert len(docx_text(r.content)) > 5

    def test_save_manual_version(self, client, user_a):
        tid = client.post("/api/v1/writing/tasks", headers=user_a,
                          json={"message": "写一份通知"}).json()["task_id"]
        client.post(f"/api/v1/writing/tasks/{tid}/draft", headers=user_a, json={})
        r = client.post(f"/api/v1/writing/tasks/{tid}/versions", headers=user_a,
                        json={"content": "人工修改后的全文。", "note": "手动"})
        assert r.status_code == 200
        assert r.json()["version_no"] == 2

    def test_training_sample(self, client, user_a):
        tid = client.post("/api/v1/writing/tasks", headers=user_a,
                          json={"message": "写一份通知"}).json()["task_id"]
        client.post(f"/api/v1/writing/tasks/{tid}/draft", headers=user_a, json={})
        r = client.post(f"/api/v1/writing/tasks/{tid}/training-sample", headers=user_a,
                        json={"final_content": "最终定稿内容"})
        assert r.status_code == 200
        assert r.json()["status"] == "pending_review"

    def test_cross_user_isolation(self, client, user_a):
        other = auth_headers(client, f"b-{uuid.uuid4().hex[:6]}@t.cn")
        tid = client.post("/api/v1/writing/tasks", headers=user_a,
                          json={"message": "写一份通知"}).json()["task_id"]
        for method, url in (
            ("get", f"/api/v1/writing/tasks/{tid}"),
            ("put", f"/api/v1/writing/tasks/{tid}"),
            ("post", f"/api/v1/writing/tasks/{tid}/chat"),
            ("post", f"/api/v1/writing/tasks/{tid}/draft"),
        ):
            kwargs = {"headers": other}
            if method != "get":
                kwargs["json"] = {"message": "x", "context": {}}
            r = getattr(client, method)(url, **kwargs)
            assert r.status_code == 404, f"{method} {url} 越权成功！"


# ---------------------------------------------------------------- D/E. 服务级：模板进提示词 + KB 限定 + 日期仲裁

def make_db_user(db, role="user", username=None):
    """在测试库中创建真实用户（外键约束要求 user_id 必须存在）。"""
    from app.core.security import get_password_hash
    from app.infrastructure.database.models.identity import UserModel
    uname = username or f"svc-{uuid.uuid4().hex[:8]}"
    u = UserModel(username=uname, email=f"{uname}@t.cn",
                  hashed_password=get_password_hash("pass1234"),
                  real_name="服务级测试", role=role)
    db.add(u)
    db.commit()
    return u


class TestServiceLevel:
    def _service(self, replies):
        from app.infrastructure.database import SessionLocal
        from app.application.writing.task_service import WritingTaskService
        db = SessionLocal()
        assistant = ScriptedAssistant(replies)
        return db, WritingTaskService(db, assistant=assistant), assistant

    def test_llm_date_cannot_override_user(self):
        """LLM 想改日期，但 parser 裁定的用户指定值获胜"""
        db, svc, _ = self._service([intent_json(
            intent="update_context", topic="晋升")])
        uid = make_db_user(db).id
        t = svc.create_task(uid, "写一个晋升报告")
        tid = t["task_id"]
        svc.interpreter = WritingIntentInterpreter(ScriptedAssistant([intent_json(
            intent="update_context", reply="好的")]))
        r = svc.chat(tid, uid, "时间是2026年10月15日")
        assert r["task_context"]["document_date"] == "2026年10月15日"
        db.close()

    def test_template_in_draft_prompt(self):
        """绑定模板后，起草指令包含模板名与模板结构"""
        db, svc, assistant = self._service(None)
        uid = make_db_user(db).id
        t = svc.create_task(uid, "帮我写一份2026年度司法行政工作总结")
        ctx = dict(t["task_context"])
        template = {"id": "t1", "name": "年度总结标准模板", "is_active": True,
                    "writing_style": "庄重", "word_count": 2500,
                    "content_template": "一、工作回顾\n二、存在问题\n三、下一步",
                    "system_prompt": "必须使用三段式结构"}
        instruction = svc._build_draft_instruction(ctx, False, template)
        assert "年度总结标准模板" in instruction
        assert "一、工作回顾" in instruction
        assert "2500" in instruction
        db.close()

    def test_template_system_prompt_merged(self):
        db, svc, assistant = self._service(["（Stub）正文"])
        template = {"system_prompt": "必须使用三段式结构"}
        svc._llm_draft("起草通知", [], None, "u1", template=template)
        sys_prompt = assistant.calls[-1][0]["content"]
        assert "不要编造文号" in sys_prompt       # 通用起草规则仍在
        assert "三段式" in sys_prompt             # 模板附加要求并入
        db.close()

    def test_kb_restriction_passed_to_rag(self):
        """关联知识库时检索被限定在指定库"""
        captured = {}

        class FakeRag:
            def search(self, query, user_id, kb_ids=None, **kw):
                captured["kb_ids"] = kb_ids
                return []

        from app.infrastructure.database import SessionLocal
        from app.application.writing.task_service import WritingTaskService
        db = SessionLocal()
        svc = WritingTaskService(db, assistant=ScriptedAssistant(), rag=FakeRag())
        svc._retrieve({"title": "总结", "kb_ids": ["kb-a", "kb-b"]}, "u1")
        assert captured["kb_ids"] == ["kb-a", "kb-b"]
        svc._retrieve({"title": "总结", "kb_ids": []}, "u1")
        assert captured["kb_ids"] is None  # 空列表 = 不限定
        db.close()

    def test_rag_service_kb_intersection(self):
        """RagService.search 与可访问库取交集，越权库被剔除"""
        from app.infrastructure.database import SessionLocal
        from app.application.knowledge.rag_service import RagService
        from app.infrastructure.database.models.knowledge import KnowledgeBaseModel
        db = SessionLocal()
        ux = make_db_user(db)
        uy = make_db_user(db)
        mine = KnowledgeBaseModel(name="我的库", kb_type="personal", owner_id=ux.id)
        other = KnowledgeBaseModel(name="别人的库", kb_type="personal", owner_id=uy.id)
        db.add_all([mine, other])
        db.commit()

        class FakeEmbedder:
            def encode_queries(self, qs):
                return [[0.1] * 8]

        class FakeStore:
            def search(self, vec, kb_ids, top_k=20):
                FakeStore.seen = kb_ids
                return []

        RagService(db, FakeEmbedder(), FakeStore()).search(
            query="测试", user_id=ux.id, kb_ids=[mine.id, other.id])
        assert mine.id in FakeStore.seen
        assert other.id not in FakeStore.seen  # 越权库被交集剔除
        db.close()


# ---------------------------------------------------------------- G. 格式校验

class TestFormatCheck:
    def test_rules_crud_and_permission(self, client, admin, user_a):
        # 普通用户（非首个开发者账号）不能建规则
        plain = auth_headers(client, f"plain-{uuid.uuid4().hex[:6]}@t.cn")
        r = client.post("/api/v1/format-check/rules", headers=plain, json={
            "name": "正文字体", "target": "body", "checks": {"font_size_pt": 16}})
        assert r.status_code in (401, 403)
        # 管理员 CRUD
        r = client.post("/api/v1/format-check/rules", headers=admin, json={
            "name": "正文字号", "target": "body",
            "checks": {"font_size_pt": 16}, "severity": "error"})
        assert r.status_code == 200, r.text
        rid = r.json()["id"]
        r = client.get("/api/v1/format-check/rules", headers=user_a)
        assert any(x["id"] == rid for x in r.json())
        r = client.put(f"/api/v1/format-check/rules/{rid}", headers=admin, json={
            "name": "正文字号(改)", "target": "body",
            "checks": {"font_size_pt": 15}, "severity": "warning"})
        assert r.status_code == 200
        r = client.delete(f"/api/v1/format-check/rules/{rid}", headers=admin)
        assert r.status_code == 200
        assert not any(x["id"] == rid for x in
                       client.get("/api/v1/format-check/rules", headers=user_a).json())

    def test_rule_based_check(self, client, admin, user_a):
        client.post("/api/v1/format-check/rules", headers=admin, json={
            "name": "标题居中", "target": "title",
            "checks": {"alignment": "center"}, "severity": "error"})
        data = make_docx_bytes(["关于社区矫正工作的通知", "各司法所：", "请抓好落实。"])
        r = client.post("/api/v1/format-check/check?use_ai=false", headers=user_a,
                        files={"file": ("通知.docx", data)})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["check_mode"] == "rule"
        assert any(i["element"] == "对齐方式" for i in d["issues"])
        assert d["rules_used"]

    def test_ai_only_when_no_rules(self, client, user_a):
        """无规则时不再报 400，降级为 AI 校验模式"""
        # 保证规则表为空（前面用例已删除各自规则；此处防御性清理）
        from app.infrastructure.database import SessionLocal
        from app.infrastructure.database.models.format_check import FormatRuleModel
        db = SessionLocal()
        db.query(FormatRuleModel).delete()
        db.commit()
        db.close()

        data = make_docx_bytes(["关于人民调解工作的报告", "现将有关情况报告如下。"])
        r = client.post("/api/v1/format-check/check", headers=user_a,
                        files={"file": ("报告.docx", data)})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["check_mode"] == "ai_only"
        assert d["rules_used"] == []
        assert d["ai_used"] is True  # mock 网关返回最小 JSON → AI 路径生效

    def test_record_isolation(self, client, admin, user_a):
        other = auth_headers(client, f"c-{uuid.uuid4().hex[:6]}@t.cn")
        data = make_docx_bytes(["标题", "正文"])
        r = client.post("/api/v1/format-check/check", headers=user_a,
                        files={"file": ("a.docx", data)})
        rid = r.json()["record_id"]
        r = client.get(f"/api/v1/format-check/records/{rid}", headers=other)
        assert r.status_code in (403, 404)

    def test_fix_flow(self, client, admin, user_a):
        client.post("/api/v1/format-check/rules", headers=admin, json={
            "name": "标题居中2", "target": "title",
            "checks": {"alignment": "center"}, "severity": "error"})
        data = make_docx_bytes(["社区矫正工作方案", "一、总体要求"])
        r = client.post("/api/v1/format-check/check?use_ai=false", headers=user_a,
                        files={"file": ("方案.docx", data)})
        d = r.json()
        idx = [i for i, x in enumerate(d["issues"]) if x["element"] == "对齐方式"]
        assert idx
        r = client.post("/api/v1/format-check/fix", headers=user_a,
                        json={"record_id": d["record_id"], "accepted_indices": idx})
        assert r.status_code == 200
        assert r.content[:2] == b"PK"
        from docx import Document
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        doc = Document(io.BytesIO(r.content))
        assert doc.paragraphs[0].alignment == WD_ALIGN_PARAGRAPH.CENTER


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", "--tb=short"]))
