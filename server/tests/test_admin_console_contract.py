"""管理后台：桌面端每个按钮所依赖的接口契约。

桌面端 AdminScreen 的按钮 → 接口 → 解析字段，这条链路里任何一处对不上都会
表现为「点了没反应 / 列表空白 / 列里空一格」。这里用 HTTP 层把全部按钮真打一遍：

| 按钮 | 接口 |
|---|---|
| 数据概览刷新 | GET /knowledge/stats |
| 新建用户 / 编辑 / 禁用·启用 / 重置密码 / 批量导入 | /users/… |
| 新建知识库（仓库已接、界面未接） | POST /knowledge/create |
| 删除知识库 | DELETE /knowledge/{id} |
| 通过 / 驳回 | POST /knowledge/review |
| 归档 | POST /knowledge/documents/{id}/archive |
| 科室下拉 | GET /organization/departments |

断言的是**客户端真正读取的字段**（如 `uploader_name`、`department_code`、
`is_active`），字段名一改这里就红。
"""
import pytest
from fastapi.testclient import TestClient

from app.core.timeutil import now_local  # noqa: F401
from app.domain.identity.entities import (
    ROLE_DEVELOPER,
    ROLE_KNOWLEDGE_ADMIN,
    ROLE_USER,
    User,
)
from app.infrastructure.database.base import Base
from app.infrastructure.database.models.identity import UserModel
from app.infrastructure.database.models.knowledge import (
    DocumentModel,
    KnowledgeBaseModel,
)
from app.infrastructure.database.session import SessionLocal, engine
from app.interfaces.deps import get_current_user
from app.main import app

Base.metadata.create_all(bind=engine)

BASE = "/api/v1"
# 必须是 domain 字典里真实存在的科室 code（服务端按静态字典校验，不认自由输入）
DEPT = "bangongshi"

DEV = User(username="admindev", email="admindev@test.local", hashed_password="x",
           id="u-admin-1", role=ROLE_DEVELOPER, department_code=DEPT)
KA = User(username="deptadmin", email="deptadmin@test.local", hashed_password="x",
          id="u-ka-1", role=ROLE_KNOWLEDGE_ADMIN, department_code=DEPT)
NORMAL = User(username="normalu", email="normalu@test.local", hashed_password="x",
              id="u-n-1", role=ROLE_USER, department_code=DEPT)


def _ensure_user(db, u: User) -> None:
    row = db.get(UserModel, u.id)
    if row is None:
        row = UserModel(id=u.id, username=u.username, email=u.email,
                        hashed_password=u.hashed_password, role=u.role,
                        department_code=u.department_code, is_active=True)
        db.add(row)
    else:
        row.role = u.role
        row.department_code = u.department_code
        row.is_active = True
    db.commit()


def _kb(db, name, dept_code="", kb_type="public"):
    kb = KnowledgeBaseModel(name=name, description="", kb_type=kb_type,
                            department_code=dept_code, owner_id=DEV.id, is_active=True)
    db.add(kb)
    db.commit()
    db.refresh(kb)
    return kb


def _doc(db, kb_id, title, status="pending", uploader=DEV.id):
    d = DocumentModel(kb_id=kb_id, title=title, doc_type="docx", status=status,
                      content="正文内容", uploaded_by=uploader, created_by=uploader,
                      department_code=DEPT)
    db.add(d)
    db.commit()
    db.refresh(d)
    return d


@pytest.fixture()
def env():
    db = SessionLocal()
    try:
        _ensure_user(db, DEV)
        _ensure_user(db, KA)
        _ensure_user(db, NORMAL)
        db.commit()
        yield db
        db.query(DocumentModel).delete()
        db.query(KnowledgeBaseModel).delete()
        db.commit()
    finally:
        db.close()


@pytest.fixture(autouse=True)
def _clear_auth_override():
    """每个用例后必须摘掉鉴权覆盖。

    app.dependency_overrides 是全局的，漏摘会让排在后面的测试模块（如
    test_department_permissions）拿到假的当前用户而成片 ERROR。
    """
    yield
    app.dependency_overrides.pop(get_current_user, None)


def _client(role_user: User):
    app.dependency_overrides[get_current_user] = lambda: role_user
    return TestClient(app)


# ---------------- 数据概览 ----------------

def test_stats_exposes_cards_read_by_desktop(env):
    db = env
    _kb(db, "公共库")
    _doc(db, _kb(db, "第二个库").id, "文档一", status="published")
    with _client(DEV) as c:
        r = c.get(f"{BASE}/knowledge/stats")
    assert r.status_code == 200, r.text
    body = r.json()
    for key in ("user_count", "doc_count", "session_count", "kb_count"):
        assert key in body, f"概览卡片缺字段 {key}"
    assert body["kb_count"] >= 2
    assert body["doc_count"] >= 1


def test_stats_is_developer_only(env):
    """科室管理员拿不到全局统计。

    客户端 AdminScreen 对非 developer 也调用了 vm.loadAll()（操作成功后刷新），
    会把 status 覆盖成 403 —— 见 test_review_then_refresh_keeps_success_message。
    """
    with _client(KA) as c:
        assert c.get(f"{BASE}/knowledge/stats").status_code == 403
        assert c.get(f"{BASE}/users/").status_code == 403


# ---------------- 用户管理 ----------------

def test_user_list_and_lifecycle(env):
    db = env
    with _client(DEV) as c:
        r = c.post(f"{BASE}/users/", json={
            "username": "newbie", "email": "newbie@test.local", "password": "Passw0rd!2026",
            "real_name": "新同事", "department_code": DEPT, "role": "user"})
        assert r.status_code == 200, r.text
        uid = r.json()["id"]

        rows = c.get(f"{BASE}/users/").json()
        row = next(x for x in rows if x["id"] == uid)
        # 桌面端表格逐列读取这些字段
        for key in ("id", "username", "real_name", "email", "department_code",
                    "role", "is_active", "created_at"):
            assert key in row, f"用户列表缺字段 {key}"
        assert row["is_active"] is True

        # 编辑（真实姓名 / 科室 / 角色）
        assert c.put(f"{BASE}/users/{uid}", json={
            "real_name": "改名后", "department_code": DEPT, "role": "knowledge_admin",
        }).status_code == 200
        row = next(x for x in c.get(f"{BASE}/users/").json() if x["id"] == uid)
        assert row["role"] == "knowledge_admin" and row["real_name"] == "改名后"

        # 禁用 → 启用（客户端「禁用 / 启用」按钮只发 is_active）
        assert c.put(f"{BASE}/users/{uid}", json={"is_active": False}).status_code == 200
        assert next(x for x in c.get(f"{BASE}/users/").json()
                    if x["id"] == uid)["is_active"] is False
        assert c.put(f"{BASE}/users/{uid}", json={"is_active": True}).status_code == 200

        # 重置密码
        r = c.post(f"{BASE}/users/{uid}/reset-password", json={"password": "Passw0rd!2027"})
        assert r.status_code == 200 and r.json().get("must_change_password") is True

        # 删除（仓库里已接 deleteUser，界面尚未放按钮）
        assert c.delete(f"{BASE}/users/{uid}").status_code == 200


def test_departments_expose_code_and_name(env):
    """科室下拉只认 code + name（+ short_name 兜底）。"""
    from app.infrastructure.database.models.organization import DepartmentModel

    db = env
    if db.get(DepartmentModel, DEPT) is None:
        db.add(DepartmentModel(code=DEPT, name="办公室", short_name="办公室",
                               sort_order=0, is_active=True))
        db.commit()
    with _client(DEV) as c:
        r = c.get(f"{BASE}/organization/departments")
    assert r.status_code == 200, r.text
    data = r.json()
    rows = data["items"] if isinstance(data, dict) else data
    assert any(d.get("code") == DEPT and d.get("name") for d in rows)


# ---------------- 知识库管理 ----------------

def test_kb_create_and_delete(env):
    db = env
    with _client(DEV) as c:
        r = c.post(f"{BASE}/knowledge/create", json={"name": "后台新建库", "description": ""})
        assert r.status_code == 200, r.text
        kb_id = (r.json() or {}).get("id") or r.json().get("kb_id")
        rows = c.get(f"{BASE}/knowledge/list").json()
        row = next((x for x in rows if x.get("id") == kb_id), None) or \
            next((x for x in rows if x.get("name") == "后台新建库"), None)
        assert row is not None
        # 客户端表格读的字段
        for key in ("id", "name", "type", "doc_count", "created_at", "department_code"):
            assert key in row, f"知识库列表缺字段 {key}"
        target = row["id"]
        assert c.delete(f"{BASE}/knowledge/{target}").status_code == 200


# ---------------- 文档审核 ----------------

def test_pending_and_documents_rows(env):
    db = env
    kb = _kb(db, "科室库", dept_code=DEPT)
    _doc(db, kb.id, "待审文档", status="pending")
    pub = _doc(db, kb.id, "已发布文档", status="published")
    _doc(db, kb.id, "已驳回文档", status="rejected")

    with _client(DEV) as c:
        pend = c.get(f"{BASE}/knowledge/pending").json()
        pend_rows = pend["data"] if isinstance(pend, dict) else pend
        assert any(d["title"] == "待审文档" for d in pend_rows)
        for key in ("id", "title", "doc_type", "kb_name"):
            assert key in pend_rows[0]

        pubs = c.get(f"{BASE}/knowledge/documents", params={"status": "published"}).json()
        rows = pubs["data"] if isinstance(pubs, dict) else pubs
        row = next(x for x in rows if x["id"] == pub.id)
        # 客户端「上传者」列读的是 uploader_name
        assert "uploader_name" in row
        assert row["kb_name"] == "科室库"

        rejected = c.get(f"{BASE}/knowledge/documents", params={"status": "rejected"}).json()
        rrows = rejected["data"] if isinstance(rejected, dict) else rejected
        assert any(d["title"] == "已驳回文档" for d in rrows)


def test_pending_rows_use_same_columns_as_documents(env):
    """待审队列必须与 /knowledge/documents 同构。

    DocsTab 三个子页共用一张表、读的是同一批字段（uploader_name / created_at /
    kb_name）。但 list_pending 只下发 uploaded_by / uploaded_at —— 于是「上传者」
    和「时间」两列在「待审核」页恒为空白，另外两页却正常。同一张表两套字段名，
    用户看到的就是「这块没做完」。
    """
    db = env
    kb = _kb(db, "同构库", dept_code=DEPT)
    _doc(db, kb.id, "待审文档", status="pending")
    _doc(db, kb.id, "已发布文档", status="published")
    with _client(DEV) as c:
        pend = c.get(f"{BASE}/knowledge/pending").json()
        row = next(x for x in pend if x["title"] == "待审文档")
        pub = c.get(f"{BASE}/knowledge/documents",
                    params={"status": "published"}).json()["data"]
    pub_row = next(x for x in pub if x["title"] == "已发布文档")
    for key in ("uploader_name", "created_at", "kb_name", "doc_type", "status"):
        assert key in row, f"待审队列缺字段 {key}"
        assert key in pub_row, f"文档列表缺字段 {key}"


def test_rejected_doc_can_be_re_approved(env):
    """驳回不是终态：服务端允许 rejected → approved。

    界面「已驳回」子页当前没有任何操作按钮，误驳回的文档永远回不来。
    """
    db = env
    kb = _kb(db, "翻案库", dept_code=DEPT)
    doc = _doc(db, kb.id, "误驳回", status="pending")
    with _client(DEV) as c:
        assert c.post(f"{BASE}/knowledge/review", json={
            "doc_id": doc.id, "action": "rejected", "comment": "误操作"}).status_code == 200
        r = c.post(f"{BASE}/knowledge/review", json={
            "doc_id": doc.id, "action": "approved", "comment": "复核通过"})
        assert r.status_code == 200, r.text
    db.expire_all()
    assert db.get(DocumentModel, doc.id).status == "published"


def test_archive_is_reversible_and_archived_docs_are_listable(env):
    """归档必须可逆，归档后的文档也必须还能列出来。

    只归档不恢复 + 三个子页（pending / published / rejected）都不含 archived
    → 归档等于永久消失，用户会以为「归档把数据弄丢了」。
    """
    db = env
    kb = _kb(db, "归档库", dept_code=DEPT)
    doc = _doc(db, kb.id, "待归档", status="published")
    with _client(DEV) as c:
        assert c.post(f"{BASE}/knowledge/documents/{doc.id}/archive",
                      json={}).status_code == 200
        rows = c.get(f"{BASE}/knowledge/documents",
                     params={"status": "archived"}).json()["data"]
        assert any(x["id"] == doc.id for x in rows), "归档后文档在任何列表里都找不到"

        r = c.post(f"{BASE}/knowledge/documents/{doc.id}/unarchive", json={})
        assert r.status_code == 200, r.text

    db.expire_all()
    assert db.get(DocumentModel, doc.id).status == "published"


def test_create_kb_without_type_becomes_personal(env):
    """不显式传 kb_type 会建成个人知识库（仅本人可见）。

    AdminRepository.createKb 只发了 name/description，直接接界面会在管理后台建出
    一个只有操作者自己看得见的私人库 —— 接 UI 时必须显式传 public / department。
    """
    with _client(DEV) as c:
        r = c.post(f"{BASE}/knowledge/create", json={"name": "默认类型库"})
        assert r.status_code == 200, r.text
        assert (r.json() or {}).get("type") == "personal"
        r2 = c.post(f"{BASE}/knowledge/create",
                    json={"name": "公共库", "kb_type": "public"})
        assert r2.status_code == 200, r2.text
        assert r2.json().get("type") == "public"


def test_review_approve_and_reject(env):
    db = env
    kb = _kb(db, "审核库", dept_code=DEPT)
    ok = _doc(db, kb.id, "该通过", status="pending")
    bad = _doc(db, kb.id, "该驳回", status="pending")

    with _client(DEV) as c:
        r = c.post(f"{BASE}/knowledge/review",
                   json={"doc_id": ok.id, "action": "approved", "comment": "审核通过"})
        assert r.status_code == 200, r.text
        r = c.post(f"{BASE}/knowledge/review",
                   json={"doc_id": bad.id, "action": "rejected", "comment": "事实依据不足"})
        assert r.status_code == 200, r.text

    db.expire_all()
    assert db.get(DocumentModel, ok.id).status == "published"
    assert db.get(DocumentModel, bad.id).status == "rejected"


def test_review_then_refresh_keeps_success_message(env):
    """科室管理员审核成功后，客户端 act() 调用的刷新不能把结果刷成 403。

    AdminViewModel.act() 成功后无条件 `loadAll()`，而 loadAll 会打
    /knowledge/stats 与 /users/（均 require_developer）。科室管理员点「通过」
    会先看到「审核完成」，紧接着被这两条 403 覆盖 → 表现为「操作报错」。
    """
    db = env
    kb = _kb(db, "科室库", dept_code=DEPT)
    doc = _doc(db, kb.id, "本科室待审", status="pending")

    with _client(KA) as c:
        assert c.post(f"{BASE}/knowledge/review",
                      json={"doc_id": doc.id, "action": "approved",
                            "comment": "同意"}).status_code == 200
        # 这就是 loadAll() 会打的两个接口
        assert c.get(f"{BASE}/knowledge/stats").status_code == 403
        assert c.get(f"{BASE}/users/").status_code == 403
        # 但其职责范围内的接口必须正常
        assert c.get(f"{BASE}/knowledge/pending").status_code == 200
        assert c.get(f"{BASE}/knowledge/documents",
                     params={"status": "published"}).status_code == 200


def test_knowledge_admin_cannot_review_other_department(env):
    db = env
    other = _kb(db, "别的科室库", dept_code="D99")
    doc = _doc(db, other.id, "别科文档", status="pending")
    with _client(KA) as c:
        r = c.post(f"{BASE}/knowledge/review",
                   json={"doc_id": doc.id, "action": "approved", "comment": "x"})
    assert r.status_code == 403


def test_archive_published_document(env):
    db = env
    kb = _kb(db, "归档库", dept_code=DEPT)
    doc = _doc(db, kb.id, "待归档", status="published")
    with _client(DEV) as c:
        r = c.post(f"{BASE}/knowledge/documents/{doc.id}/archive", json={})
    assert r.status_code == 200, r.text
    db.expire_all()
    archived = db.get(DocumentModel, doc.id)
    assert archived.status == "archived"


def test_normal_user_cannot_open_admin_endpoints(env):
    with _client(NORMAL) as c:
        assert c.get(f"{BASE}/knowledge/stats").status_code == 403
        assert c.get(f"{BASE}/users/").status_code == 403
        assert c.get(f"{BASE}/knowledge/pending").status_code == 403
        assert c.get(f"{BASE}/knowledge/documents",
                     params={"status": "published"}).status_code == 403
