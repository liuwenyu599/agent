"""知识库隔离契约测试（v3.1 三段式可见性：公共 / 科室 / 个人）。

运行方式（在 server/ 目录下）：
    AI_PROVIDER=mock python -m pytest tests/test_knowledge_isolation_contract.py -v

本文件不是把 test_department_permissions 重写一遍，而是补它**没覆盖的三处边界**：

1. 文档自身 department_code 与所属知识库不一致时，列表是否泄漏
   （``list_all_documents`` / ``list_kb_documents`` 只按 kb_id 过滤，
   而 ``can_read_doc`` 还有第二道「文档科室标记」校验——两者若不一致，
   就会出现「列表看得到标题、点开却 403」的半泄漏）。
2. 归档文档是否退出默认列表（归档语义是「退出检索范围」，不能还挂在已发布里）。
3. 个人知识库的文档是否严格不出现在他人可见列表中。

这三处都是「代码读起来没问题、但没人用 HTTP 请求证过」的地方。
"""
import os
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("AI_PROVIDER", "mock")
os.environ.setdefault("DATA_DIR", f"/tmp/test-kbiso-{uuid.uuid4().hex[:8]}")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.infrastructure.database import Base, SessionLocal, engine  # noqa: E402
from app.infrastructure.database.models.knowledge import (  # noqa: E402
    DocumentModel,
    KnowledgeBaseModel,
)

Base.metadata.create_all(bind=engine)

BASE = "/api/v1"
DEPT_FUYI = "行政复议科"
DEPT_RENSHI = "人事科"


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


def _mk_doc(kb_id, title, status="published", department_code="", content="正文内容"):
    db = SessionLocal()
    doc = DocumentModel(kb_id=kb_id, title=title, doc_type="通知", content=content,
                        status=status, department_code=department_code)
    db.add(doc)
    db.commit()
    db.refresh(doc)
    did = doc.id
    db.close()
    return did


def _uid_of(username):
    db = SessionLocal()
    from sqlalchemy import select
    from app.infrastructure.database.models.identity import UserModel
    row = db.scalar(select(UserModel).where(UserModel.username == username))
    uid = row.id
    db.close()
    return uid


@pytest.fixture(scope="module")
def users(client):
    """注册系统管理员 + 两个科室的普通用户 / 知识管理员。"""
    r = client.post(f"{BASE}/auth/login", json={
        "username": "developer", "password": "Passw0rd!2026"})
    assert r.status_code == 200, r.text
    dev_token = r.json()["access_token"]

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
        "fuyiuser": reg("isofuyiuser", "user", DEPT_FUYI),
        "fuyiadmin": reg("isofuyiadmin", "knowledge_admin", DEPT_FUYI),
        "renshiuser": reg("isorenshiuser", "user", DEPT_RENSHI),
        "renshiadmin": reg("isorenshiadmin", "knowledge_admin", DEPT_RENSHI),
    }


@pytest.fixture(scope="module")
def kbs(users):
    return {
        "global": _mk_kb("隔离测试-全局公共库", department_code=""),
        "fuyi": _mk_kb("隔离测试-复议科库", department_code="fuyi"),
        "renshi": _mk_kb("隔离测试-人事科库", department_code="renshi"),
        "personal_fuyi": _mk_kb("隔离测试-复议私人库", kb_type="personal",
                                owner_id=_uid_of("isofuyiuser")),
        "personal_renshi": _mk_kb("隔离测试-人事私人库", kb_type="personal",
                                  owner_id=_uid_of("isorenshiuser")),
    }


# ---------------------------------------------------------------- 1. 文档科室标记 vs 所属知识库


def test_doc_with_foreign_dept_mark_is_hidden_from_listing(users, client, kbs):
    """文档自身标了他人科室，即便躺在全局公共库里，也不该出现在他人列表。

    ``can_read_doc`` 有两道校验：先看所属知识库，再看文档自身 department_code。
    但 ``list_all_documents`` 只按 kb_id 取交集——若文档科室标记与所在库不一致，
    列表会把标题泄漏出去，点进详情才被第二道校验 403。这是「半泄漏」：
    用户看得见标题、打不开正文，且列表与详情的判定口径不一致。
    """
    # 一篇属于全局公共库、却标着人事科科室的文档
    did = _mk_doc(kbs["global"], "标错科室的文档", department_code="renshi")

    # 复议科管理员：全局库可见，但文档标了人事科 → 详情必须 403
    detail = client.get(f"{BASE}/knowledge/documents/{did}",
                        headers=_hdr(users["fuyiadmin"]))
    assert detail.status_code == 403, detail.text

    # 列表同样不该出现（列表与详情必须同口径，否则就是半泄漏）
    data = client.get(f"{BASE}/knowledge/documents?status=all",
                      headers=_hdr(users["fuyiadmin"])).json()
    ids = {d["id"] for d in data["data"]}
    assert did not in ids, "列表泄漏了详情 403 的文档：列表与详情口径不一致"


def test_doc_without_dept_mark_in_global_kb_is_readable(users, client, kbs):
    """对照组：全局公共库里未标科室的文档，所有科室都可读。"""
    did = _mk_doc(kbs["global"], "全局可读文档", department_code="")
    r = client.get(f"{BASE}/knowledge/documents/{did}",
                   headers=_hdr(users["renshiuser"]))
    assert r.status_code == 200, r.text
    assert r.json()["title"] == "全局可读文档"


def test_kb_document_listing_uses_same_rule_as_detail(users, client, kbs):
    """库内文档列表与详情同口径：库内列表也不能漏出他科室标记的文档。"""
    did = _mk_doc(kbs["fuyi"], "复议库里标人事科的文档", department_code="renshi")
    data = client.get(f"{BASE}/knowledge/{kbs['fuyi']}/documents",
                      headers=_hdr(users["fuyiuser"])).json()
    ids = {d["id"] for d in data["data"]}
    assert did not in ids, f"库内列表泄漏：{ids}"

    detail = client.get(f"{BASE}/knowledge/documents/{did}",
                        headers=_hdr(users["fuyiuser"]))
    assert detail.status_code == 403, detail.text


# ---------------------------------------------------------------- 2. 归档语义


def test_archived_doc_drops_out_of_published_listing(users, client, kbs):
    """归档 = 退出检索范围：默认列表（published）不再出现该文档。"""
    did = _mk_doc(kbs["fuyi"], "待归档文档", status="published")
    before = client.get(f"{BASE}/knowledge/{kbs['fuyi']}/documents",
                        headers=_hdr(users["fuyiadmin"])).json()
    assert did in {d["id"] for d in before["data"]}

    ar = client.post(f"{BASE}/knowledge/documents/{did}/archive",
                     headers=_hdr(users["fuyiadmin"]))
    assert ar.status_code == 200, ar.text

    after = client.get(f"{BASE}/knowledge/{kbs['fuyi']}/documents",
                       headers=_hdr(users["fuyiadmin"])).json()
    assert did not in {d["id"] for d in after["data"]}, "归档后仍出现在已发布列表"


def test_archived_doc_is_restorable(users, client, kbs):
    """归档必须可逆：恢复后重新出现在已发布列表且可读。

    归档只改状态不删数据，「只进不出」会让误归档变成永久丢文档。
    """
    did = _mk_doc(kbs["fuyi"], "误归档待恢复", status="published")
    assert client.post(f"{BASE}/knowledge/documents/{did}/archive",
                       headers=_hdr(users["fuyiadmin"])).status_code == 200

    un = client.post(f"{BASE}/knowledge/documents/{did}/unarchive",
                     headers=_hdr(users["fuyiadmin"]))
    assert un.status_code == 200, un.text
    assert un.json()["status"] == "published"

    data = client.get(f"{BASE}/knowledge/{kbs['fuyi']}/documents",
                      headers=_hdr(users["fuyiadmin"])).json()
    assert did in {d["id"] for d in data["data"]}


def test_unarchive_rejects_non_archived_doc(users, client, kbs):
    """恢复归档必须拒绝非归档文档，避免误把状态改乱。"""
    did = _mk_doc(kbs["fuyi"], "本来就是发布态", status="published")
    r = client.post(f"{BASE}/knowledge/documents/{did}/unarchive",
                    headers=_hdr(users["fuyiadmin"]))
    assert r.status_code == 409, r.text


# ---------------------------------------------------------------- 3. 个人知识库


def test_personal_kb_docs_never_appear_to_others(users, client, kbs):
    """个人库文档对非 owner 完全不可见：列表、详情两处都不漏。"""
    did = _mk_doc(kbs["personal_fuyi"], "复议用户私人文档")

    # 人事科用户：列表不可见
    ids = {kb["id"] for kb in client.get(
        f"{BASE}/knowledge/list", headers=_hdr(users["renshiuser"])).json()}
    assert kbs["personal_fuyi"] not in ids

    # 详情 403
    r = client.get(f"{BASE}/knowledge/documents/{did}",
                   headers=_hdr(users["renshiuser"]))
    assert r.status_code == 403, r.text


def test_personal_kb_docs_visible_to_owner(users, client, kbs):
    """对照组：owner 本人可读自己个人库的文档。"""
    did = _mk_doc(kbs["personal_fuyi"], "本人私人文档")
    r = client.get(f"{BASE}/knowledge/documents/{did}",
                   headers=_hdr(users["fuyiuser"]))
    assert r.status_code == 200, r.text
    assert r.json()["title"] == "本人私人文档"


def test_personal_kb_invisible_to_other_dept_admin(users, client, kbs):
    """他人个人库对别的科室的知识管理员同样不可见（不是只有普通用户受限）。

    注意 personal_renshi 的 owner 是 renshiuser，对 renshiadmin 而言同样是
    「他人的个人库」——个人库按 owner 隔离，与科室无关，同科室也不互通。
    """
    admin_ids = {kb["id"] for kb in client.get(
        f"{BASE}/knowledge/list", headers=_hdr(users["renshiadmin"])).json()}
    assert kbs["personal_fuyi"] not in admin_ids
    assert kbs["personal_renshi"] not in admin_ids, "他人个人库不应因同科室而可见"

    # 对照组：owner 本人可见自己的个人库
    owner_ids = {kb["id"] for kb in client.get(
        f"{BASE}/knowledge/list", headers=_hdr(users["renshiuser"])).json()}
    assert kbs["personal_renshi"] in owner_ids
    assert kbs["personal_fuyi"] not in owner_ids


# ---------------------------------------------------------------- 4. 客户端参数不能扩大权限


def test_client_cannot_escalate_via_foreign_kb_id(users, client, kbs):
    """客户端强行传他人科室 kb_id 请求库内文档，一律 403。"""
    for who in ("fuyiuser", "fuyiadmin"):
        r = client.get(f"{BASE}/knowledge/{kbs['renshi']}/documents",
                       headers=_hdr(users[who]))
        assert r.status_code == 403, who


def test_cross_dept_kb_search_forbidden(users, client, kbs):
    """库内搜索同样受隔离约束，不能成为列表的旁路。"""
    r = client.get(f"{BASE}/knowledge/{kbs['renshi']}/documents/search?q=文档",
                   headers=_hdr(users["fuyiadmin"]))
    assert r.status_code == 403, r.text


def test_own_kb_search_works(users, client, kbs):
    """对照组：本科室库内搜索可用。"""
    _mk_doc(kbs["fuyi"], "本科室可搜文档", content="关键词在正文里")
    r = client.get(f"{BASE}/knowledge/{kbs['fuyi']}/documents/search?q=关键词",
                   headers=_hdr(users["fuyiadmin"]))
    assert r.status_code == 200, r.text
    assert r.json()["total"] >= 1
