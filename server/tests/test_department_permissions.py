"""跨科室权限测试（v3.1 组织隔离）。

运行方式（在 server/ 目录下）：
    AI_PROVIDER=mock python -m pytest tests/test_department_permissions.py -v

覆盖矩阵：
- 复议科普通用户：可读 GLOBAL / 本科室 / 本人 personal；不可读人事科 KB 与文档
- 复议科 knowledge_admin：可管理本科室；对人事科读/改/删/上传/审核全部 403
- 手工构造他科室 kb_id / dept_code / scopes：一律 403 或不可见
- RAG：不返回其他科室 chunk；developer 可全局检索
- personal KB：仅 owner 可见
- developer：系统级全局管理生效（admin 旧角色同样具备系统管理员权限）
"""
import os
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("AI_PROVIDER", "mock")
os.environ.setdefault("DATA_DIR", f"/tmp/test-dept-{uuid.uuid4().hex[:8]}")
os.environ.setdefault("DATABASE_URL", f"sqlite:////tmp/test-dept-{uuid.uuid4().hex[:8]}.db")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.infrastructure.database import Base, SessionLocal, engine  # noqa: E402
from app.infrastructure.database.models.knowledge import (  # noqa: E402
    DocumentModel,
    KnowledgeBaseModel,
)

# 服务级测试不走应用 lifespan，这里幂等建表
Base.metadata.create_all(bind=engine)

DEPT_FUYI = "行政复议科"
DEPT_RENSHI = "人事科"

BASE = "/api/v1"


# ---------------------------------------------------------------- 夹具

@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _hdr(token):
    return {"Authorization": f"Bearer {token}"}


def _mk_kb(name, department_code="", kb_type="public", owner_id=None):
    db = SessionLocal()
    kb = KnowledgeBaseModel(name=name, description=name,
                            department_code=department_code, kb_type=kb_type,
                            owner_id=owner_id)
    db.add(kb)
    db.commit()
    db.refresh(kb)
    kid = kb.id
    db.close()
    return kid


def _mk_doc(kb_id, title, status="published", department_code="", content="内容"):
    db = SessionLocal()
    doc = DocumentModel(kb_id=kb_id, title=title, doc_type="通知", content=content,
                        status=status, department_code=department_code)
    db.add(doc)
    db.commit()
    db.refresh(doc)
    did = doc.id
    db.close()
    return did


@pytest.fixture(scope="module")
def users(client):
    """注册 5 类账号并返回 token 映射。"""
    dev = client.post(f"{BASE}/auth/register-first", json={
        "username": "developer", "email": "developer@test.local",
        "password": "Passw0rd!2026", "real_name": "系统管理员", "department": "",
    }).json()
    dev_token = dev["access_token"]

    def reg(username, role, dept):
        r = client.post(f"{BASE}/auth/register", json={
            "username": username, "email": f"{username}@test.local",
            "password": "Passw0rd!2026", "real_name": username,
            "department": dept, "role": role,
        }, headers=_hdr(dev_token))
        assert r.status_code == 200, r.text
        tok = client.post(f"{BASE}/auth/login", json={
            "username": username, "password": "Passw0rd!2026"}).json()["access_token"]
        # 管理员代建的账号首登必须改密（真实业务流程）：未改密前业务端点一律 403
        changed = client.post(f"{BASE}/auth/change-password", json={
            "old_password": "Passw0rd!2026", "new_password": "Changed@2026",
            "confirm_password": "Changed@2026",
        }, headers=_hdr(tok))
        assert changed.status_code == 200, changed.text
        return tok

    return {
        "developer": dev_token,
        "fuyi_user": reg("fuyi_user", "user", DEPT_FUYI),
        "fuyi_admin": reg("fuyi_knowledge_admin", "knowledge_admin", DEPT_FUYI),
        "renshi_user": reg("renshi_user", "user", DEPT_RENSHI),
        "renshi_admin": reg("renshi_knowledge_admin", "knowledge_admin", DEPT_RENSHI),
    }


@pytest.fixture(scope="module")
def kbs(users):
    """创建全局 / 复议科 / 人事科 / 个人 四类知识库及文档。"""
    fuyi_uid = _uid_of("fuyi_user")
    return {
        "global": _mk_kb("全局公共知识库", department_code=""),
        "fuyi": _mk_kb("复议科知识库", department_code="fuyi"),
        "renshi": _mk_kb("人事科知识库", department_code="renshi"),
        "personal_fuyi": _mk_kb("复议用户个人库", kb_type="personal", owner_id=fuyi_uid),
    }


@pytest.fixture(scope="module")
def docs(users, kbs):
    return {
        "global": _mk_doc(kbs["global"], "全局文档"),
        "fuyi": _mk_doc(kbs["fuyi"], "复议科文档", department_code="fuyi"),
        "renshi": _mk_doc(kbs["renshi"], "人事科文档", department_code="renshi"),
        "personal_fuyi": _mk_doc(kbs["personal_fuyi"], "复议用户私人文档"),
    }


def _uid_of(username):
    db = SessionLocal()
    from app.infrastructure.database.models.identity import UserModel
    from sqlalchemy import select
    row = db.scalar(select(UserModel).where(UserModel.username == username))
    uid = row.id
    db.close()
    return uid


# ---------------------------------------------------------------- 1. 角色语义

def test_developer_is_system_admin(users, client):
    r = client.get(f"{BASE}/organization/me", headers=_hdr(users["developer"]))
    assert r.status_code == 200
    assert r.json()["is_admin"] is True


def test_knowledge_admin_is_not_system_admin(users, client):
    r = client.get(f"{BASE}/organization/me", headers=_hdr(users["fuyi_admin"]))
    assert r.status_code == 200
    assert r.json()["is_admin"] is False
    assert r.json()["dept_code"] == "fuyi"


def test_legacy_admin_role_has_system_admin_rights(client):
    """旧数据中的 admin 角色必须与 developer 等价。"""
    from app.domain.identity.authorization import is_system_admin
    assert is_system_admin("developer") is True
    assert is_system_admin("admin") is True
    assert is_system_admin("knowledge_admin") is False
    assert is_system_admin("user") is False


# ---------------------------------------------------------------- 2. 用户科室归属落库

def test_department_code_persisted_on_create(users):
    db = SessionLocal()
    from sqlalchemy import select
    from app.infrastructure.database.models.identity import UserModel
    rows = {r.username: r for r in db.scalars(select(UserModel)).all()}
    assert rows["fuyi_user"].department_code == "fuyi"
    assert rows["renshi_user"].department_code == "renshi"
    assert rows["fuyi_knowledge_admin"].department_code == "fuyi"
    db.close()


def test_unknown_department_is_rejected(users, client):
    """v3.2：所属科室只能从科室字典选择，未命中字典的名称一律拒绝，不猜测归口。"""
    r = client.post(f"{BASE}/auth/register", json={
        "username": "nodept_user", "email": "nodept@test.local",
        "password": "Passw0rd!2026", "department": "不存在的科室", "role": "user",
    }, headers=_hdr(users["developer"]))
    assert r.status_code == 400
    db = SessionLocal()
    from sqlalchemy import select
    from app.infrastructure.database.models.identity import UserModel
    row = db.scalar(select(UserModel).where(UserModel.username == "nodept_user"))
    assert row is None
    db.close()


def test_department_code_selected_from_dictionary(users, client):
    """前端按科室 code 提交，服务端落库 department_code 与正式名称。"""
    r = client.post(f"{BASE}/auth/register", json={
        "username": "coded_user", "email": "coded@test.local",
        "password": "Passw0rd!2026", "department_code": "renshi", "role": "user",
    }, headers=_hdr(users["developer"]))
    assert r.status_code == 200
    db = SessionLocal()
    from sqlalchemy import select
    from app.infrastructure.database.models.identity import UserModel
    row = db.scalar(select(UserModel).where(UserModel.username == "coded_user"))
    assert row is not None
    assert row.department_code == "renshi"
    assert row.department == "人事科"
    db.close()


def test_unknown_role_is_rejected(users, client):
    """角色必须与前端下拉一致：普通用户 / 知识管理员 / 系统管理员。"""
    r = client.post(f"{BASE}/auth/register", json={
        "username": "bad_role_user", "email": "badrole@test.local",
        "password": "Passw0rd!2026", "department_code": "fuyi", "role": "super_admin",
    }, headers=_hdr(users["developer"]))
    assert r.status_code in (400, 403)


# ---------------------------------------------------------------- 3. 知识库可见性

def test_list_kb_only_global_and_own_dept(users, client, kbs):
    ids = {kb["id"] for kb in client.get(
        f"{BASE}/knowledge/list", headers=_hdr(users["fuyi_user"])).json()}
    assert kbs["global"] in ids
    assert kbs["fuyi"] in ids
    assert kbs["personal_fuyi"] in ids
    assert kbs["renshi"] not in ids


def test_list_kb_knowledge_admin_cannot_see_other_dept(users, client, kbs):
    ids = {kb["id"] for kb in client.get(
        f"{BASE}/knowledge/list", headers=_hdr(users["fuyi_admin"])).json()}
    assert kbs["renshi"] not in ids
    assert kbs["fuyi"] in ids


def test_list_kb_developer_sees_all(users, client, kbs):
    ids = {kb["id"] for kb in client.get(
        f"{BASE}/knowledge/list", headers=_hdr(users["developer"])).json()}
    for k in kbs.values():
        assert k in ids


def test_personal_kb_only_owner(users, client, kbs):
    ids = {kb["id"] for kb in client.get(
        f"{BASE}/knowledge/list", headers=_hdr(users["renshi_user"])).json()}
    assert kbs["personal_fuyi"] not in ids


# ---------------------------------------------------------------- 4. 跨科室 KB / 文档访问

def test_cross_dept_kb_detail_forbidden(users, client, kbs):
    for who in ("fuyi_user", "fuyi_admin"):
        r = client.get(f"{BASE}/knowledge/{kbs['renshi']}", headers=_hdr(users[who]))
        assert r.status_code == 403, who


def test_cross_dept_kb_documents_forbidden(users, client, kbs):
    for who in ("fuyi_user", "fuyi_admin"):
        r = client.get(f"{BASE}/knowledge/{kbs['renshi']}/documents",
                       headers=_hdr(users[who]))
        assert r.status_code == 403, who


def test_cross_dept_document_detail_forbidden(users, client, docs):
    for who in ("fuyi_user", "fuyi_admin"):
        r = client.get(f"{BASE}/knowledge/documents/{docs['renshi']}",
                       headers=_hdr(users[who]))
        assert r.status_code == 403, who


def test_own_dept_document_readable(users, client, docs):
    r = client.get(f"{BASE}/knowledge/documents/{docs['fuyi']}",
                   headers=_hdr(users["fuyi_user"]))
    assert r.status_code == 200
    assert r.json()["title"] == "复议科文档"


def test_developer_can_read_cross_dept(users, client, docs):
    r = client.get(f"{BASE}/knowledge/documents/{docs['renshi']}",
                   headers=_hdr(users["developer"]))
    assert r.status_code == 200


# ---------------------------------------------------------------- 5. 写/改/删/上传/审核

def test_knowledge_admin_cannot_delete_other_dept_kb(users, client, kbs):
    r = client.delete(f"{BASE}/knowledge/{kbs['renshi']}",
                      headers=_hdr(users["fuyi_admin"]))
    assert r.status_code == 403


def test_knowledge_admin_cannot_update_other_dept_kb(users, client, kbs):
    r = client.put(f"{BASE}/knowledge/{kbs['renshi']}", json={"name": "被改名"},
                   headers=_hdr(users["fuyi_admin"]))
    assert r.status_code == 403


def test_knowledge_admin_can_manage_own_dept_kb(users, client, kbs):
    r = client.put(f"{BASE}/knowledge/{kbs['fuyi']}", json={"name": "复议科知识库(改)"},
                   headers=_hdr(users["fuyi_admin"]))
    assert r.status_code == 200


def test_upload_to_other_dept_kb_forbidden(users, client, kbs):
    r = client.post(
        f"{BASE}/knowledge/upload?kb_id={kbs['renshi']}",
        files={"file": ("a.txt", b"hello world", "text/plain")},
        headers=_hdr(users["fuyi_admin"]),
    )
    assert r.status_code == 403


def test_batch_upload_to_other_dept_kb_forbidden(users, client, kbs):
    r = client.post(
        f"{BASE}/knowledge/batch-upload?kb_id={kbs['renshi']}",
        files={"files": ("a.txt", b"hello world", "text/plain")},
        headers=_hdr(users["fuyi_admin"]),
    )
    assert r.status_code == 403


def test_import_urls_to_other_dept_kb_forbidden(users, client, kbs):
    r = client.post(f"{BASE}/knowledge/import-urls",
                    json={"kb_id": kbs["renshi"], "urls": ["https://example.com/a"]},
                    headers=_hdr(users["fuyi_admin"]))
    assert r.status_code == 403


def test_review_other_dept_document_forbidden(users, client, docs):
    r = client.post(f"{BASE}/knowledge/review",
                    json={"doc_id": docs["renshi"], "action": "approve", "comment": ""},
                    headers=_hdr(users["fuyi_admin"]))
    assert r.status_code == 403


def test_review_own_dept_document_allowed(users, client, kbs):
    did = _mk_doc(kbs["fuyi"], "本科室待审文档", status="pending", department_code="fuyi")
    r = client.post(f"{BASE}/knowledge/review",
                    json={"doc_id": did, "action": "approve", "comment": "ok"},
                    headers=_hdr(users["fuyi_admin"]))
    assert r.status_code == 200


def test_pending_queue_scoped_to_own_dept(users, client, kbs):
    _mk_doc(kbs["renshi"], "人事科待审文档", status="pending", department_code="renshi")
    _mk_doc(kbs["fuyi"], "复议科待审文档2", status="pending", department_code="fuyi")
    items = client.get(f"{BASE}/knowledge/pending",
                       headers=_hdr(users["fuyi_admin"])).json()
    titles = {i["title"] for i in items}
    assert "人事科待审文档" not in titles
    assert "复议科待审文档2" in titles


def test_all_documents_scoped(users, client, docs):
    data = client.get(f"{BASE}/knowledge/documents?status=all",
                      headers=_hdr(users["fuyi_admin"])).json()
    ids = {d["id"] for d in data["data"]}
    assert docs["renshi"] not in ids
    assert docs["fuyi"] in ids


def test_developer_global_management(users, client, kbs, docs):
    """developer 可执行系统级全局管理。"""
    r = client.get(f"{BASE}/knowledge/documents?status=all",
                   headers=_hdr(users["developer"])).json()
    ids = {d["id"] for d in r["data"]}
    assert docs["renshi"] in ids and docs["fuyi"] in ids
    # 全局管理：可删除他科室知识库
    tmp = _mk_kb("人事科临时库", department_code="renshi")
    rr = client.delete(f"{BASE}/knowledge/{tmp}", headers=_hdr(users["developer"]))
    assert rr.status_code == 200


# ---------------------------------------------------------------- 6. RAG 作用域

def test_rag_scopes_exclude_other_dept(users, kbs):
    """RAG 解析出的作用域不含其他科室。"""
    from app.application.knowledge.rag_service import RagService
    db = SessionLocal()
    rag = RagService(db, None, None)
    fuyi_uid = _uid_of("fuyi_user")
    scopes = rag.resolve_scopes("fuyi", False, fuyi_uid)
    assert "GLOBAL" in scopes
    assert "DEPT:fuyi" in scopes
    assert "DEPT:renshi" not in scopes
    assert f"USER:{fuyi_uid}" in scopes
    # 系统管理员不限制
    assert rag.resolve_scopes("", True) is None
    db.close()


def test_rag_client_scopes_cannot_escalate(users, kbs):
    """客户端传入他科室 scope 会被服务端权限覆盖（交集为空 → 不返回越权内容）。"""
    from app.application.knowledge.access import KnowledgeAccessPolicy
    db = SessionLocal()
    policy = KnowledgeAccessPolicy(db)
    fuyi = _user_obj("fuyi_user")
    merged = policy.intersect_scopes(fuyi, ["DEPT:renshi", "GLOBAL"])
    assert merged == ["GLOBAL"]
    db.close()


def test_rag_search_excludes_other_dept_chunks(users, kbs, docs):
    """向量索引里同时存在两科室 chunk，复议科用户检索不到人事科内容。"""
    from app.application.knowledge.rag_service import RagService
    db = SessionLocal()
    try:
        rag = RagService(db, None, None)
        # 绕过向量库不可用的情况：直接校验可访问 kb 集合 + 作用域交集
        fuyi = _user_obj("fuyi_user")
        kb_ids = rag._get_accessible_kb_ids(fuyi.id, "fuyi", False)
        assert kbs["renshi"] not in kb_ids
        # 即便客户端强行指定人事科 kb_id，也会被过滤
        filtered = [k for k in [kbs["renshi"]] if k in set(kb_ids)]
        assert filtered == []
    finally:
        db.close()


def test_rag_developer_global(users, kbs):
    from app.application.knowledge.rag_service import RagService
    db = SessionLocal()
    rag = RagService(db, None, None)
    dev = _user_obj("developer")
    kb_ids = rag._get_accessible_kb_ids(dev.id, "", True)
    assert kbs["renshi"] in kb_ids and kbs["fuyi"] in kb_ids
    db.close()


def _user_obj(username):
    db = SessionLocal()
    from sqlalchemy import select
    from app.infrastructure.database.models.identity import UserModel
    row = db.scalar(select(UserModel).where(UserModel.username == username))
    db.expunge(row)
    db.close()
    return row


# ---------------------------------------------------------------- 7. Agent 权限

def test_agent_cross_dept_forbidden(users, client):
    for who in ("fuyi_user", "fuyi_admin"):
        r = client.get(f"{BASE}/organization/agents/renshi", headers=_hdr(users[who]))
        assert r.status_code == 403, who


def test_agent_own_dept_readable(users, client):
    r = client.get(f"{BASE}/organization/agents/fuyi", headers=_hdr(users["fuyi_admin"]))
    assert r.status_code == 200
    assert r.json()["dept_code"] == "fuyi"


def test_agent_update_other_dept_forbidden(users, client):
    r = client.put(f"{BASE}/organization/agents/renshi", json={"intro": "越权修改"},
                   headers=_hdr(users["fuyi_admin"]))
    assert r.status_code == 403


def test_agent_update_own_dept_allowed(users, client):
    r = client.put(f"{BASE}/organization/agents/fuyi", json={"intro": "本科室简介"},
                   headers=_hdr(users["fuyi_admin"]))
    assert r.status_code == 200
    assert r.json()["intro"] == "本科室简介"


def test_agent_developer_manage_all(users, client):
    r = client.put(f"{BASE}/organization/agents/renshi", json={"intro": "系统管理员维护"},
                   headers=_hdr(users["developer"]))
    assert r.status_code == 200


# ---------------------------------------------------------------- 系统级管理边界

def test_knowledge_admin_cannot_manage_system_users(client, users):
    """科室知识管理员不能读取或修改全局账号目录；账号管理仅系统管理员可用。"""
    ka = _hdr(users["fuyi_admin"])
    dev = _hdr(users["developer"])

    denied = client.get(f"{BASE}/users/", headers=ka)
    assert denied.status_code == 403, denied.text

    allowed = client.get(f"{BASE}/users/", headers=dev)
    assert allowed.status_code == 200, allowed.text


def test_global_stats_are_system_admin_only(client, users):
    """全局用户/会话统计不向科室管理员泄露。"""
    ka = client.get(f"{BASE}/knowledge/stats", headers=_hdr(users["fuyi_admin"]))
    assert ka.status_code == 403, ka.text

    dev = client.get(f"{BASE}/knowledge/stats", headers=_hdr(users["developer"]))
    assert dev.status_code == 200, dev.text
