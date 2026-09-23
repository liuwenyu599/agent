"""时区一致性回归测试（用户报障：上传文档的时间比真实时间慢 8 小时）。

本文件由 ``test_timezone.py`` 与 ``test_timezone_consistency.py`` 合并而来，
两者覆盖重叠，统一在此维护。

运行方式（在 server/ 目录下）：
    D:/apps/anaconda3/python.exe -m pytest tests/test_timezone.py -v

背景
----
修复前后端混用三种取时间的写法（``datetime.utcnow()`` / ``func.now()`` 即 SQLite
``CURRENT_TIMESTAMP`` / ``datetime.now()``），且服务端与客户端**都不做时区转换**，
于是东八区用户看到的时间比真实时间**慢 8 小时**。

修复后的唯一约定（见 ``app/core/timeutil.py``）：
- 库里存的是**东八区墙钟时间**（naive datetime）；
- 接口返回、客户端展示的都是东八区墙钟时间；
- 取"现在"只能用 ``now_local()``（显式 +08:00，不依赖部署机器/容器的 TZ）；
- **例外**：JWT 的 ``exp`` 必须保持标准 UTC POSIX 语义，否则 token 会多活 8 小时。

本文件的六类守卫：
1. ``now_local()`` 本身确实是东八区；
2. 用户可见时间 == 本地时间（上传链路 / 我的文档 / 批量任务 JSON）；
3. dashboard 时间窗口与存储时间同一时基，不再差 8 小时（含月初边界）；
4. JWT 的 exp 仍是 UTC；
5. 源码里不再出现 UTC / 本地时间混用（AST 扫描 + 正向守卫）；
6. 存量数据迁移脚本的 +8h / downgrade 完全对称，且不误伤业务日期列。
"""
import ast
import importlib.util
import io
import os
import sys
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("AI_PROVIDER", "mock")
os.environ.setdefault("EMBEDDING_PROVIDER", "mock")

_TMPDIR = Path(tempfile.mkdtemp(prefix="test-tz-"))
os.environ.setdefault("DATA_DIR", str(_TMPDIR))
os.environ.setdefault("DATABASE_URL", f"sqlite:///{(_TMPDIR / 'test.db').as_posix()}")

from fastapi.testclient import TestClient  # noqa: E402

from app.core.timeutil import now_local, now_utc  # noqa: E402
from app.infrastructure.database import Base, SessionLocal, engine  # noqa: E402
from app.infrastructure.database.models.document import MyDocumentModel  # noqa: E402
from app.infrastructure.database.models.identity import UserModel  # noqa: E402
from app.main import app  # noqa: E402

Base.metadata.create_all(bind=engine)

BASE = "/api/v1"
PWD = "Passw0rd!2026"

# 「接口时间 == 本地时间」允许的误差：接口调用 + 入库有毫秒级开销，1 分钟足够宽松，
# 但远小于 8 小时，因此能稳定抓住时区偏移。
MAX_DRIFT = timedelta(minutes=1)
# 判定"不是 UTC"的阈值：东八区与 UTC 差 8 小时，>7h 即说明已不是 UTC。
NOT_UTC_THRESHOLD = 7 * 3600

_APP_DIR = Path(__file__).resolve().parent.parent / "app"


# ============================================================ 夹具


class FakeGateway:
    """替身模型网关：只实现 complete()，不发任何网络请求。"""

    def __init__(self):
        self.calls = []

    @property
    def model_name(self) -> str:
        return "fake-llm"

    def complete(self, messages, temperature=0.7, max_tokens=4096):
        self.calls.append(messages)
        return "（替身模型回复）"


@pytest.fixture(autouse=True)
def fake_llm(monkeypatch):
    """模型一律打桩（本地 8001 / 8003 均未启动），保证零网络请求。"""
    import app.infrastructure.ai as ai_mod

    fake = FakeGateway()
    monkeypatch.setattr(ai_mod, "get_llm_gateway", lambda: fake)
    monkeypatch.setattr(ai_mod, "get_ppt_gateway", lambda: fake)
    ai_mod.reset_gateway()
    return fake


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _hdr(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _local_now_naive() -> datetime:
    """测试进程所在机器的本地时间（东八区环境即东八区墙钟时间）。"""
    return datetime.now()


def _dev_token(client: TestClient) -> str:
    """取得系统管理员令牌。

    测试进程内可能与其他测试模块共用同一个库（首用户已被占用），
    此时直接为库中的系统管理员账号签发令牌。
    """
    r = client.post(f"{BASE}/auth/register-first", json={
        "username": "tz_admin", "email": "tz_admin@test.local",
        "password": PWD, "real_name": "时间管理员",
    })
    if r.status_code == 200:
        return r.json()["access_token"]

    from sqlalchemy import select

    from app.core.security import create_access_token

    db = SessionLocal()
    try:
        row = db.scalar(select(UserModel).where(
            UserModel.role.in_(("developer", "admin", "system_admin"))))
        assert row is not None, "库中没有可用的系统管理员账号"
        return create_access_token(
            {"sub": row.id, "username": row.username, "role": row.role})
    finally:
        db.close()


@pytest.fixture(scope="module")
def admin(client):
    """系统管理员令牌 + 其 user_id（用于直接写库造边界数据）。"""
    token = _dev_token(client)
    from sqlalchemy import select

    db = SessionLocal()
    try:
        row = db.scalar(select(UserModel).where(
            UserModel.role.in_(("developer", "admin", "system_admin"))))
        return {"token": token, "user_id": row.id}
    finally:
        db.close()


def _parse_ts(value) -> datetime:
    """解析接口返回的时间字符串（兼容 T / 空格分隔，忽略时区后缀）。"""
    return datetime.fromisoformat(str(value).replace("Z", "").replace("T", " "))


def _assert_local(actual: datetime, before: datetime, after: datetime, what: str):
    """断言时间落在本地时间窗口内（修复前会偏差 8 小时）。"""
    assert before - MAX_DRIFT <= actual <= after + MAX_DRIFT, (
        f"{what}={actual} 不在本地时间区间 [{before}, {after}] 内"
        f"（差值应 < 1 分钟，实际差 "
        f"{(before - actual).total_seconds() / 3600:.1f} 小时）")


def _assert_not_utc(actual: datetime, what: str):
    """反向确认：绝不是 UTC（与 now_utc 差应≈8 小时）。"""
    gap = abs((actual - now_utc()).total_seconds())
    assert gap > NOT_UTC_THRESHOLD, (
        f"{what}={actual} 与 now_utc() 仅差 {gap / 3600:.2f}h，看起来仍是 UTC")


# ============================================================ 1. 工具函数本身


def test_now_local_is_china_standard_time():
    """now_local() 必须是东八区墙钟时间：等于 UTC 现在 +8 小时。"""
    utc_now = datetime.now(timezone.utc)
    got = now_local()
    expected = (utc_now + timedelta(hours=8)).replace(tzinfo=None)
    assert abs((got - expected).total_seconds()) < 5, (
        f"now_local()={got} 与 UTC+8={expected} 不一致")


def test_now_local_matches_machine_local_time():
    """在东八区部署环境，now_local() 应与机器本地时间一致（差值 < 5 秒）。"""
    offset = _local_now_naive().astimezone().utcoffset()
    if offset is None or abs(offset.total_seconds() - 8 * 3600) > 60:
        pytest.skip(f"测试机不在东八区（UTC{offset}），跳过与机器本地时间的比对")
    drift = abs((now_local() - _local_now_naive()).total_seconds())
    assert drift < 5, f"now_local() 与本地时间相差 {drift} 秒"


# ============================================================ 2. 用户可见时间


def test_uploaded_document_created_at_matches_local_time(client, admin):
    """用户报障的核心症状：经知识库上传链路后，列表返回的 created_at == 本地时间。

    这是用户最初报的那条路径，必须走真实的 ``POST /knowledge/upload``，
    不能用直接写库替代——否则证明不了上传链路本身是对的。
    """
    h = _hdr(admin["token"])

    kb = client.post(f"{BASE}/knowledge/create", json={
        "name": "时区测试库", "description": "tz", "kb_type": "public"}, headers=h)
    assert kb.status_code == 200, kb.text
    kb_id = kb.json().get("id") or kb.json().get("kb_id")

    before = _local_now_naive()
    content = "第一条 为了验证时间一致性，制定本办法。\n第二条 本办法自发布之日起施行。"
    up = client.post(
        f"{BASE}/knowledge/upload",
        params={"kb_id": kb_id},
        data={"title": "时区测试文档", "doc_type": "法规"},
        files={"file": ("tz.txt", io.BytesIO(content.encode("utf-8")), "text/plain")},
        headers=h,
    )
    after = _local_now_naive()
    assert up.status_code == 200, up.text

    lst = client.get(f"{BASE}/knowledge/{kb_id}/documents",
                     params={"status": "all"}, headers=h)
    assert lst.status_code == 200, lst.text
    payload = lst.json()
    # 该接口返回分页信封 {"total": n, "data": [...]}，列表在 data 里
    items = payload["data"] if isinstance(payload, dict) else payload
    docs = [d for d in items if d.get("title") == "时区测试文档"]
    assert docs, f"上传的文档没出现在列表里：{payload}"

    created_at = _parse_ts(docs[0]["created_at"])
    _assert_local(created_at, before, after, "上传文档 created_at")
    _assert_not_utc(created_at, "上传文档 created_at")


def test_my_document_created_at_matches_local_time(client, admin):
    """「我的文档」新建后，创建响应与列表接口的 created_at / updated_at 都是本地时间。"""
    h = _hdr(admin["token"])
    before = _local_now_naive()
    r = client.post(f"{BASE}/documents", json={
        "title": "时区测试公文", "doc_type": "通知", "content": "正文内容"}, headers=h)
    after = _local_now_naive()
    assert r.status_code == 201, r.text

    body = r.json()
    for field in ("created_at", "updated_at"):
        got = _parse_ts(body[field])
        _assert_local(got, before, after, f"创建响应 {field}")
        _assert_not_utc(got, f"创建响应 {field}")

    # 列表接口（用户实际看到的那一份数据）也要一致
    items = client.get(f"{BASE}/documents", headers=h).json()["items"]
    row = next(i for i in items if i["title"] == "时区测试公文")
    got = _parse_ts(row["created_at"])
    _assert_local(got, before, after, "列表接口 created_at")
    _assert_not_utc(got, "列表接口 created_at")


def test_batch_import_task_timestamps_are_local():
    """批量导入任务（DATA_DIR/tasks/*.json）的时间戳也必须是本地时间。

    这条路径原先用的是裸 datetime.now()，在 TZ=UTC 的容器里会退化成 UTC。
    它不落库，但语义必须与库内时间一致，否则同一批导入会出现两套时基。
    """
    from app.application.knowledge.task_queue import BatchImportTask

    before = _local_now_naive()
    task = BatchImportTask(kb_id="kb-test", user_id="u-test", total_files=1)
    after = _local_now_naive()

    for name in ("created_at", "updated_at"):
        got = _parse_ts(getattr(task, name))
        _assert_local(got, before, after, f"批量任务 {name}")
        _assert_not_utc(got, f"批量任务 {name}")


# ============================================================ 3. dashboard 时间窗口


def test_dashboard_month_window_counts_recent_document(client, admin):
    """刚创建的文档必须计入「本月新增」。"""
    h = _hdr(admin["token"])
    r = client.post(f"{BASE}/documents", json={
        "title": "本月新增校验", "doc_type": "通知", "content": "正文"}, headers=h)
    assert r.status_code == 201, r.text

    summary = client.get(f"{BASE}/dashboard/summary", headers=h)
    assert summary.status_code == 200, summary.text
    stats = summary.json()["stats"]
    assert stats["doc_total"] >= 1
    assert stats["month_created"] >= 1, "刚创建的文档没有被计入本月新增"


def test_dashboard_month_window_has_no_eight_hour_gap(client, admin):
    """月初 +3 小时边界：本地 00:00–08:00 创建的文档必须计入「本月新增」。

    这是 8 小时偏差最典型的表现：旧实现用本地时间算月初，却拿库里的 UTC 值比较，
    于是本地 00:00–08:00 创建的文档会被算成上个月的（UTC 里确实还是上月末）。
    """
    h = _hdr(admin["token"])
    before = client.get(f"{BASE}/dashboard/summary", headers=h).json()
    n0 = before["stats"]["month_created"]

    month_start = now_local().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    # 取"本地月初 + 3 小时"：这个值在东八区语义下属于本月，
    # 但若把存储退回 UTC，它会被当成上月末而漏统计。
    boundary = month_start + timedelta(hours=3)

    db = SessionLocal()
    try:
        db.add(MyDocumentModel(
            id=uuid.uuid4().hex[:8],
            user_id=admin["user_id"],
            title="月初边界文档",
            doc_type="通知",
            current_version=1,
            status="draft",
            created_at=boundary,
            updated_at=boundary,
        ))
        db.commit()
    finally:
        db.close()

    after = client.get(f"{BASE}/dashboard/summary", headers=h).json()
    assert after["stats"]["month_created"] == n0 + 1, (
        f"本地月初 00:00–08:00 创建的文档被漏统计：before={n0}, "
        f"after={after['stats']['month_created']}")


def test_dashboard_month_window_excludes_previous_months(client, admin):
    """跨月的历史文档不应进入「本月」统计（相对断言，不受共享库数据影响）。"""
    h = _hdr(admin["token"])

    before_stats = client.get(f"{BASE}/dashboard/summary", headers=h).json()["stats"]

    # 直接造两篇跨月的历史文档（上上月、上月），用 ORM 写 created_at
    db = SessionLocal()
    try:
        for title, days_ago in [("前月文档A", 40), ("前月文档B", 70)]:
            stamp = now_local() - timedelta(days=days_ago)
            db.add(MyDocumentModel(
                id=str(uuid.uuid4()), title=title, user_id=admin["user_id"],
                created_at=stamp, updated_at=stamp,
            ))
        db.commit()
    finally:
        db.close()

    after_stats = client.get(f"{BASE}/dashboard/summary", headers=h).json()["stats"]
    # 跨月文档不应进入「本月」统计
    assert after_stats["month_created"] == before_stats["month_created"], (
        f"插入跨月文档后 month_created 由 {before_stats['month_created']} 变为 "
        f"{after_stats['month_created']}，说明时间窗口被 UTC/本地偏移污染")
    # 文档总数应恰好 +2
    assert after_stats["doc_total"] == before_stats["doc_total"] + 2, (
        f"doc_total 应 +2，实际 {before_stats['doc_total']} -> {after_stats['doc_total']}")


# ============================================================ 4. JWT 仍为 UTC


def test_jwt_exp_stays_utc():
    """JWT 的 exp 必须保持标准 UTC POSIX 时间戳，不能跟着 +8 小时。

    如果把 token 过期时间也改成东八区，exp 会被按 UTC 解析，导致 token
    实际多存活 8 小时——这是安全回归，所以这里单独钉死。
    """
    from jose import jwt

    from app.core.config import settings
    from app.core.security import create_access_token, decode_token

    token = create_access_token({"sub": "tz-test"})
    exp = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])["exp"]

    # exp ≈ 签发时刻(UTC) + 有效期
    expected_ts = (datetime.now(timezone.utc).timestamp()
                   + settings.ACCESS_TOKEN_EXPIRE_HOURS * 3600)
    assert abs(exp - expected_ts) < 60, f"exp={exp} 期望≈{expected_ts}"

    # token 本身仍可正常解码往返
    assert decode_token(token)["sub"] == "tz-test"

    # 关键反向：exp 不应是东八区（否则 token 会多活 8 小时）
    exp_dt = datetime.fromtimestamp(exp, tz=timezone.utc).replace(tzinfo=None)
    gap = abs((exp_dt - now_local()).total_seconds())
    assert gap > NOT_UTC_THRESHOLD, (
        f"JWT exp 看起来用的是本地时间（与 now_local 仅差 {gap / 3600:.2f}h），"
        "会导致 token 有效期错 8 小时")


# ============================================================ 5. 源码防回归


def _iter_source_files():
    """遍历 app/ 下的源码；migrations 是历史快照，冻结后再改没有意义，跳过。"""
    for path in sorted(_APP_DIR.rglob("*.py")):
        if "migrations" in path.parts or "__pycache__" in path.parts:
            continue
        yield path


def test_source_has_no_utc_or_naive_local_time():
    """源码里不得再出现 datetime.utcnow() 或裸 datetime.now()。

    - ``datetime.utcnow()``：UTC，会让用户看到的时间慢 8 小时；
    - 裸 ``datetime.now()``：依赖进程 TZ，部署容器默认 TZ=UTC 时同样算错。

    ``app/core/timeutil.py`` 里的 ``datetime.now(CN_TZ)`` 是唯一合法的取时方式
    （显式带时区参数，不受进程 TZ 影响），不算违规。
    """
    violations = []
    scanned = 0
    for path in _iter_source_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - 语法错误应由其他用例暴露
            continue
        scanned += 1
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            if not (isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name)):
                continue
            if fn.value.id != "datetime":
                continue
            if fn.attr == "utcnow":
                violations.append(
                    f"{path.relative_to(_APP_DIR)}:{node.lineno} datetime.utcnow()")
            elif fn.attr == "now" and not node.args and not node.keywords:
                violations.append(
                    f"{path.relative_to(_APP_DIR)}:{node.lineno} datetime.now()")

    assert scanned > 0, "没有扫描到任何源文件，路径可能不对"
    assert not violations, (
        "发现 UTC / 本地时间混用，请改为 app.core.timeutil.now_local()：\n"
        + "\n".join(violations))


def test_models_do_not_use_sql_server_default_now():
    """ORM 时间列不得再用 server_default=func.now()。

    SQLite 的 CURRENT_TIMESTAMP 恒为 UTC，且与容器 TZ 无关地写死 UTC，
    一旦 ORM 没显式赋值就会写进 UTC 值。统一改成 Python 侧 default=now_local。
    """
    violations = []
    for path in _iter_source_files():
        if "server_default=func.now()" in path.read_text(encoding="utf-8"):
            violations.append(str(path.relative_to(_APP_DIR)))
    assert not violations, (
        "这些文件仍在用 server_default=func.now()（UTC）：\n" + "\n".join(violations))


def test_models_default_to_now_local():
    """正向守卫：ORM 时间列必须走 now_local()，否则上面的用例可能被绕过。"""
    models_dir = _APP_DIR / "infrastructure" / "database" / "models"
    base_file = _APP_DIR / "infrastructure" / "database" / "base.py"
    # TimestampMixin 是模型层时间的唯一来源，必须在
    assert "default=now_local" in base_file.read_text(encoding="utf-8"), \
        "TimestampMixin 未使用 now_local"
    hits = 0
    for path in list(models_dir.glob("*.py")) + [base_file]:
        hits += path.read_text(encoding="utf-8").count("now_local")
    assert hits >= 10, f"now_local 在模型层的引用只有 {hits} 处，疑似被回退"


# ============================================================ 6. 存量数据迁移


def _load_migration_module():
    """按文件路径加载 010 迁移模块（文件名以数字开头，不能用普通 import）。"""
    path = (_APP_DIR / "migrations" / "versions"
            / "010_v35_local_time_migration.py")
    spec = importlib.util.spec_from_file_location("v35_local_time_migration", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_migration_touches_only_wall_clock_columns():
    """迁移脚本只能平移墙钟时间列，不得误伤业务日期/操作人等列。"""
    mod = _load_migration_module()
    for col in ("created_at", "updated_at", "last_accessed", "deleted_time"):
        assert mod._is_time_column(col) is True, col
    for col in ("document_date", "issue_date", "need_date", "updated_by", "title"):
        assert mod._is_time_column(col) is False, col


def test_migration_shift_is_symmetric_and_normalizes_format():
    """迁移 +8h 与 downgrade -8h 必须完全对称，且不丢微秒。

    历史数据是 UTC，upgrade 把它 +8 对齐东八区；downgrade 必须能精确还原，
    否则线上回滚会造成不可逆的时间错乱。
    """
    import sqlalchemy as sa
    from sqlalchemy import create_engine

    mod = _load_migration_module()
    db_path = _TMPDIR / "migration_probe.db"
    engine2 = create_engine(f"sqlite:///{db_path.as_posix()}")

    originals = [
        ("a", "2026-09-22 12:02:39.029728"),   # 带微秒
        ("b", "2026-09-22T09:55:27"),          # 历史遗留的 T 分隔
    ]
    with engine2.begin() as conn:
        conn.execute(sa.text(
            "CREATE TABLE t (id TEXT PRIMARY KEY, created_at TEXT, "
            "document_date TEXT)"))
        for k, v in originals:
            conn.execute(sa.text("INSERT INTO t VALUES (:k, :v, '2026-09-22')"),
                         {"k": k, "v": v})

    def _column(conn):
        return [r[0] for r in conn.execute(
            sa.text("SELECT created_at FROM t ORDER BY id")).fetchall()]

    with engine2.connect() as conn:
        assert mod._shift_table(conn, "t", "created_at", "id", +8) == 2
        conn.commit()
        shifted = _column(conn)
        assert mod._shift_table(conn, "t", "created_at", "id", -8) == 2
        conn.commit()
        restored = _column(conn)

    # +8h 结果正确，且顺手把 T 分隔归一成空格分隔（避免字典序排序错乱）
    assert shifted == ["2026-09-22 20:02:39.029728", "2026-09-22 17:55:27"], shifted
    # -8h 后语义完全还原（微秒不丢，格式已归一）
    assert [datetime.fromisoformat(x) for x in restored] == \
        [datetime.fromisoformat(v) for _, v in originals], restored
