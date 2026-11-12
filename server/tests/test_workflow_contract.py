"""工作流程模块契约测试（TC-063~TC-070）。

覆盖 §7.1 里 workflow 模块 9 条此前零测试的端点。

模块特点：所有端点都只要求登录（无 require_admin_or_above），越权防线
全靠 service 层的 _get_instance_checked / _get_node_instance_checked。
这意味着**任何一处漏掉归属判断，都是一个越权口子**，而路由层完全拦不住。
所以本文件的重点不是「接口能不能调通」，而是「别人的流程能不能被碰到」。

归属规则（service 层定义，此处固化）：
- 本人 or 系统管理员 → 可访问
- 同科室的知识管理员 → 可访问
- 其余一律 403
"""
import os
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("AI_PROVIDER", "mock")
os.environ.setdefault("DATA_DIR", f"/tmp/test-wf-{uuid.uuid4().hex[:8]}")
os.environ.setdefault("DATABASE_URL", f"sqlite:////tmp/test-wf-{uuid.uuid4().hex[:8]}.db")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.infrastructure.database import Base, engine  # noqa: E402

Base.metadata.create_all(bind=engine)

BASE = "/api/v1"
DEPT_FUYI = "行政复议科"
DEPT_RENSHI = "人事科"


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

    def reg(username, role, dept, **extra):
        payload = {"username": username, "email": f"{username}@test.local",
                   "password": "Passw0rd!2026", "real_name": username,
                   "department": dept, "role": role}
        payload.update(extra)
        rr = client.post(f"{BASE}/auth/register", json=payload,
                         headers=_hdr(out["developer"]))
        assert rr.status_code == 200, rr.text
        tok = client.post(f"{BASE}/auth/login", json={
            "username": username, "password": "Passw0rd!2026"}).json()["access_token"]
        changed = client.post(f"{BASE}/auth/change-password", json={
            "old_password": "Passw0rd!2026", "new_password": "Changed@2026",
            "confirm_password": "Changed@2026"}, headers=_hdr(tok))
        assert changed.status_code == 200, changed.text
        return tok

    out["user_a"] = reg("wfusera", "user", DEPT_FUYI, department_code="fuyi")
    out["user_b"] = reg("wfuserb", "user", DEPT_RENSHI, department_code="renshi")
    out["deptadmin_a"] = reg("wfdeptadmin", "knowledge_admin",
                             DEPT_FUYI, department_code="fuyi")
    return out


@pytest.fixture(scope="module")
def inst_id(client, users):
    r = client.post(f"{BASE}/workflow/instances", headers=_hdr(users["user_a"]),
                    json={"template_code": "meeting", "title": "季度工作推进会"})
    assert r.status_code == 200, r.text
    return r.json()["id"]


# ------------------------------------------------ TC-063 鉴权：未登录一律 401

@pytest.mark.parametrize("method,path", [
    ("get", "/workflow/templates"),
    ("get", "/workflow/instances"),
    ("post", "/workflow/instances"),
    ("get", "/workflow/instances/whatever"),
    ("put", "/workflow/instances/whatever"),
    ("delete", "/workflow/instances/whatever"),
    ("post", "/workflow/instances/whatever/ai-adjust"),
    ("post", "/workflow/instances/whatever/confirm-context"),
    ("post", "/workflow/instances/whatever/parse-key-value"),
    ("post", "/workflow/instances/whatever/parse-natural-language"),
    ("put", "/workflow/nodes/whatever"),
    ("post", "/workflow/nodes/whatever/generate"),
])
def test_endpoints_require_auth(client, method, path):
    r = getattr(client, method)(f"{BASE}{path}")
    assert r.status_code in (401, 403), r.text


# ------------------------------------------------ TC-064 模板列表

def test_list_templates(client, users):
    r = client.get(f"{BASE}/workflow/templates", headers=_hdr(users["user_a"]))
    assert r.status_code == 200, r.text
    body = r.json()
    assert "templates" in body
    codes = {t["code"] for t in body["templates"]}
    assert "meeting" in codes


# ------------------------------------------------ TC-065 实例归属

def test_owner_can_read_own_instance(client, users, inst_id):
    r = client.get(f"{BASE}/workflow/instances/{inst_id}", headers=_hdr(users["user_a"]))
    assert r.status_code == 200, r.text
    assert r.json()["id"] == inst_id


def test_other_user_cannot_read_instance(client, users, inst_id):
    r = client.get(f"{BASE}/workflow/instances/{inst_id}", headers=_hdr(users["user_b"]))
    assert r.status_code == 403, r.text


def test_other_user_cannot_delete_instance(client, users, inst_id):
    r = client.delete(f"{BASE}/workflow/instances/{inst_id}", headers=_hdr(users["user_b"]))
    assert r.status_code == 403, r.text
    assert client.get(f"{BASE}/workflow/instances/{inst_id}",
                      headers=_hdr(users["user_a"])).status_code == 200


def test_other_user_cannot_update_instance(client, users, inst_id):
    r = client.put(f"{BASE}/workflow/instances/{inst_id}", headers=_hdr(users["user_b"]),
                   json={"title": "被改掉的标题"})
    assert r.status_code == 403, r.text


def test_same_department_admin_can_read_instance(client, users, inst_id):
    """同科室知识管理员可见——这是有意放开的，别当成越权修掉。"""
    r = client.get(f"{BASE}/workflow/instances/{inst_id}", headers=_hdr(users["deptadmin_a"]))
    assert r.status_code == 200, r.text


def test_instance_list_is_scoped_to_owner(client, users, inst_id):
    mine = client.get(f"{BASE}/workflow/instances", headers=_hdr(users["user_a"]))
    assert mine.status_code == 200, mine.text
    assert any(x["id"] == inst_id for x in mine.json()["instances"])

    theirs = client.get(f"{BASE}/workflow/instances", headers=_hdr(users["user_b"]))
    assert theirs.status_code == 200, theirs.text
    assert all(x["id"] != inst_id for x in theirs.json()["instances"]), \
        "用户 B 的列表里出现了用户 A 的流程"


def test_unknown_instance_is_404(client, users):
    r = client.get(f"{BASE}/workflow/instances/no-such-instance",
                   headers=_hdr(users["user_a"]))
    assert r.status_code == 404


# ------------------------------------------------ TC-066 节点写操作

def _first_node_inst_id(client, users, inst_id):
    r = client.get(f"{BASE}/workflow/instances/{inst_id}", headers=_hdr(users["user_a"]))
    nodes = r.json().get("nodes") or r.json().get("node_instances") or []
    assert nodes, f"实例里没有节点，返回体：{r.text[:300]}"
    return nodes[0]["id"]


def test_update_node_content_moves_status_out_of_pending(client, users, inst_id):
    nid = _first_node_inst_id(client, users, inst_id)
    r = client.put(f"{BASE}/workflow/nodes/{nid}", headers=_hdr(users["user_a"]),
                   json={"content": "会议通知正文"})
    assert r.status_code == 200, r.text
    assert r.json().get("status") != "pending"


def test_other_user_cannot_update_node(client, users, inst_id):
    nid = _first_node_inst_id(client, users, inst_id)
    r = client.put(f"{BASE}/workflow/nodes/{nid}", headers=_hdr(users["user_b"]),
                   json={"content": "越权写入"})
    assert r.status_code in (403, 404), r.text


def test_update_unknown_node_is_404(client, users):
    r = client.put(f"{BASE}/workflow/nodes/no-such-node", headers=_hdr(users["user_a"]),
                   json={"content": "x"})
    assert r.status_code == 404


# ------------------------------------------------ TC-067 创建实例

def test_create_instance_with_unknown_template_code(client, users):
    r = client.post(f"{BASE}/workflow/instances", headers=_hdr(users["user_a"]),
                    json={"template_code": "no-such-code", "title": "x"})
    assert r.status_code in (400, 404), r.text


def test_create_instance_requires_title(client, users):
    r = client.post(f"{BASE}/workflow/instances", headers=_hdr(users["user_a"]),
                    json={"template_code": "meeting"})
    assert r.status_code == 422, r.text


# ------------------------------------------------ TC-068 删除级联

def test_delete_instance_also_removes_its_nodes(client, users):
    created = client.post(f"{BASE}/workflow/instances", headers=_hdr(users["user_a"]),
                          json={"template_code": "activity", "title": "待删除流程"})
    assert created.status_code == 200, created.text
    iid = created.json()["id"]
    nodes = client.get(f"{BASE}/workflow/instances/{iid}",
                       headers=_hdr(users["user_a"])).json()
    assert (nodes.get("nodes") or nodes.get("node_instances")), "新实例应带出节点"

    deleted = client.delete(f"{BASE}/workflow/instances/{iid}", headers=_hdr(users["user_a"]))
    assert deleted.status_code == 200, deleted.text
    assert client.get(f"{BASE}/workflow/instances/{iid}",
                      headers=_hdr(users["user_a"])).status_code == 404


# ------------------------------------------------ 回归：基础信息节点同步到下游生成

def test_generate_node_falls_back_to_basic_info_node_content(client, users):
    """桌面端编辑「基础信息」节点时只写入节点正文（ni.content），并未同步实例级
    basic_info（唯一权威数据源）；生成下游节点（会议通知）时应从「基础信息」节点
    正文回退取数，否则模型拿不到会议核心信息、会输出 ×× 占位。

    复现路径严格模拟桌面端：createInstance 传空 workflow_context，仅通过
    updateNode 把基础信息写入节点正文。
    """
    from fastapi import Depends
    from app.infrastructure.database.session import get_db
    from app.application.workflow.service import WorkflowService
    from app.application.shared.writing_assistant import WritingAssistant
    from app.interfaces.workflow import get_workflow_service

    captured: dict = {}

    class _RecordingGateway:
        def complete(self, messages, temperature=None, max_tokens=None):
            captured["prompt"] = "\n".join(m.get("content", "") for m in messages)
            return "（回归测试桩）下游正文"

    def _override_svc(db=Depends(get_db)):
        return WorkflowService(db, WritingAssistant(_RecordingGateway()))

    prev = app.dependency_overrides.get(get_workflow_service)
    app.dependency_overrides[get_workflow_service] = _override_svc
    try:
        created = client.post(f"{BASE}/workflow/instances", headers=_hdr(users["user_a"]),
                              json={"template_code": "meeting", "title": "回归-会议通知同步"})
        assert created.status_code == 200, created.text
        iid = created.json()["id"]

        detail = client.get(f"{BASE}/workflow/instances/{iid}",
                            headers=_hdr(users["user_a"])).json()
        nodes = detail.get("nodes") or []
        basic = next((n for n in nodes if "基础信息" in n["name"]), None)
        notice = next((n for n in nodes if "会议通知" in n["name"]), None)
        assert basic and notice, f"缺少节点：{[n['name'] for n in nodes]}"

        # 仅通过 updateNode 写入「基础信息」节点正文（桌面端 saveNode 的真实行为）
        basic_content = ("一、会议名称：白云区法律顾问业务专题培训班\n"
                         "二、会议时间：2026年12月1日14:30\n"
                         "三、会议地点：白云区司法局二楼大会议室")
        r = client.put(f"{BASE}/workflow/nodes/{basic['id']}", headers=_hdr(users["user_a"]),
                       json={"content": basic_content})
        assert r.status_code == 200, r.text

        g = client.post(f"{BASE}/workflow/nodes/{notice['id']}/generate",
                        headers=_hdr(users["user_a"]),
                        json={"instruction": "", "save": True})
        assert g.status_code == 200, g.text

        prompt = captured.get("prompt", "")
        assert "白云区法律顾问业务专题培训班" in prompt, \
            "会议通知生成未从「基础信息」节点回退取数，下游会缺失会议核心信息"
    finally:
        if prev is None:
            app.dependency_overrides.pop(get_workflow_service, None)
        else:
            app.dependency_overrides[get_workflow_service] = prev


# ------------------------------------------------ 回归：编辑基础信息节点同步写 basic_info（根治）

def test_update_node_on_basic_info_node_syncs_basic_info(client, users):
    """根治项回归：桌面端编辑「基础信息」节点正文时，后端应把自由文本解析为结构化
    basic_info 写回实例，修复实例列表/详情回显丢失（_instance_to_dict 读 basic_info），
    并让 generate_node 不再依赖节点正文回退。

    复现路径严格模拟桌面端：createInstance 传空 workflow_context，仅通过 updateNode
    把基础信息写入节点正文；断言实例详情的 workflow_context/basic_info 被填充。
    """
    created = client.post(f"{BASE}/workflow/instances", headers=_hdr(users["user_a"]),
                          json={"template_code": "meeting", "title": "根治-基础信息同步回显"})
    assert created.status_code == 200, created.text
    iid = created.json()["id"]

    detail = client.get(f"{BASE}/workflow/instances/{iid}",
                        headers=_hdr(users["user_a"])).json()
    nodes = detail.get("nodes") or []
    basic = next((n for n in nodes if "基础信息" in n["name"]), None)
    assert basic, f"缺少基础信息节点：{[n['name'] for n in nodes]}"

    # 编辑「基础信息」节点正文（结构化「标签：值」格式，桌面端 saveNode 的真实行为）
    content = ("会议名称：白云区司法行政工作会议\n"
               "会议时间：2026-03-15 09:00\n"
               "会议地点：白云区司法局二楼大会议室")
    r = client.put(f"{BASE}/workflow/nodes/{basic['id']}", headers=_hdr(users["user_a"]),
                   json={"content": content})
    assert r.status_code == 200, r.text

    # 实例详情应回显结构化 basic_info（不再是空）
    detail2 = client.get(f"{BASE}/workflow/instances/{iid}",
                         headers=_hdr(users["user_a"])).json()
    ctx = detail2.get("workflow_context") or detail2.get("basic_info") or {}
    assert ctx.get("会议名称") == "白云区司法行政工作会议", ctx
    assert ctx.get("会议时间") == "2026-03-15 09:00", ctx
    assert ctx.get("会议地点") == "白云区司法局二楼大会议室", ctx

    # 反例：非基础信息节点不应触发 basic_info 同步
    notice = next((n for n in nodes if "会议通知" in n["name"]), None)
    assert notice, "缺少会议通知节点"
    before = client.get(f"{BASE}/workflow/instances/{iid}",
                        headers=_hdr(users["user_a"])).json()
    client.put(f"{BASE}/workflow/nodes/{notice['id']}", headers=_hdr(users["user_a"]),
               json={"content": "会议通知正文"})
    after = client.get(f"{BASE}/workflow/instances/{iid}",
                       headers=_hdr(users["user_a"])).json()
    assert (before.get("basic_info") or {}) == (after.get("basic_info") or {}), \
        "非基础信息节点的编辑不应改变实例 basic_info"
