"""v3.5 时间语义统一：历史 UTC 时间批量 +8 小时，改为东八区本地时间。

背景（为什么必须迁数据）
------------------------
v3.5 之前，后端混用了三种"取当前时间"的方式，但**没有一处做时区转换**：

1. ``default=datetime.utcnow``      -> Python 侧 UTC（带微秒）
2. ``server_default=func.now()``    -> SQLite ``CURRENT_TIMESTAMP``，UTC（无微秒）
3. ``datetime.now()``               -> 进程本地时间（仅 task_queue 写 JSON，未落库）

因此**库里所有时间列存的都是 UTC**，东八区用户看到的上传时间比真实时间慢 8 小时。
v3.5 代码侧已统一为 ``app.core.timeutil.now_local()``（显式东八区，不依赖容器 TZ），
新写入的数据从这一版开始就是本地时间；本迁移负责把**存量数据**一并对齐，
否则会出现"新数据对、老数据差 8 小时"的新旧混用。

存量数据为什么确定是 UTC（不是猜的，有三条硬证据）
--------------------------------------------------
1. **上传文件与数据库行按 UUID/标题一一对应，mtime 差正好 8 小时**
   - ``documents.id=935d4ec2`` 存 ``2026-09-22 12:02:39``；
     磁盘产物 ``server/data/tmp/knowledge-upload/64cc1da1_【函】广州市白云区司法局
     关于拨付2026年白云区村（社区）兼职人民调解员工作补贴的函.docx``
     的 mtime 是 ``2026-09-22 20:02:38``（操作系统时钟 = 东八区，即真实本地时间）。
     差 1 秒（应用解析文件耗时），即 DB 值 +8h = 真实本地时间。
   - ``format_check_records.id=2cccffee-2cbb-493c-ab1f-8d7dd28aa0d9``
     存 ``2026-09-22 09:55:27``；同名产物
     ``server/data/format-check/2cccffee-....docx`` mtime ``2026-09-22 17:55:25``。
2. **没有任何一条记录是"未来时间"**：全库 471 条时间值，max 值
   ``2026-09-23 01:46:31``（writing_tasks）远早于当时 UTC 时刻，排除本地时间写入。
3. **写入路径穷举**：改前全仓 ``grep`` 只有 UTC 两种来源落库（见上），
   唯一用本地时间的 ``task_queue.py`` 写的是 ``DATA_DIR/tasks/*.json``，不进库。

安全性约束（本脚本的写法）
--------------------------
- 只改**墙钟时间列**（列名以 ``_at`` 结尾，外加 ``last_accessed``）。
  ``document_date``（成文日期，业务语义字符串）、``issue_date``（发文日期）、
  ``need_date``（布尔）、``updated_by``（操作人）一律不动。
- 用 inspector 防御：表不存在 / 列不存在直接跳过，绝不因某张表结构不同让迁移挂掉。
- 时间值在 **Python 里做加减再写回**，不用 SQL ``datetime(col, '+8 hours')``——
  SQLite 3.41 的 ``datetime()`` 会把 ``12:02:39.029728`` 截断成 ``12:02:39``，
  丢掉微秒；Python 侧运算保留微秒，并统一按 ORM 写入格式（空格分隔）输出，
  顺带修掉库里个别 ``T`` 分隔的历史值（详见 ``_render`` 注释）。
- 无法解析的值（空串 / 非 ISO 格式）跳过，不报错、不改写。
- 主键缺失的表回退用 ``rowid`` 定位行。
- ``downgrade()`` 完整回退（-8 小时），与 upgrade 完全对称。

执行方式（由部署脚本触发，本文件不自行执行）
--------------------------------------------
::

    cd server && python -m app.migrations.migrator upgrade
    # 等价于 alembic upgrade head

Revision ID: 010_v35_local_time_migration
Revises: 009_v34_format_check_workbench
"""
import logging
from datetime import datetime, timedelta

import sqlalchemy as sa
from alembic import op

revision = "010_v35_local_time_migration"
down_revision = "009_v34_format_check_workbench"
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic.runtime.migration")

# ---------------------------------------------------------------- 列识别规则

#: 墙钟时间列的后缀。只认这类列，避免误伤业务日期字符串
#: （``document_date`` / ``issue_date`` 是业务日期，``need_date`` 是布尔，都不匹配）。
_TIME_SUFFIXES = ("_at", "_time")
#: 不以 _at 结尾但确实是墙钟时间的列（历史遗留命名）。
_EXTRA_TIME_COLUMNS = ("last_accessed",)
#: 长得像时间列其实不是的例外（updated_by 是操作人 id）。
_EXCLUDED_COLUMNS = ("updated_by",)

#: 东八区相对 UTC 的固定偏移。中国大陆自 1991 年起不使用夏令时，恒为 +8。
_OFFSET = timedelta(hours=8)


def _is_time_column(column_name: str) -> bool:
    """判断列名是否是墙钟时间列。

    Args:
        column_name: 数据库列名。

    Returns:
        True 表示该列存的是墙钟时间，需要参与 +8/-8 迁移。
    """
    if column_name in _EXCLUDED_COLUMNS:
        return False
    if column_name in _EXTRA_TIME_COLUMNS:
        return True
    return column_name.endswith(_TIME_SUFFIXES)


def _has_table(inspector, table: str) -> bool:
    """表存在性检查（失败一律视为不存在，保证迁移不中断）。"""
    try:
        return table in set(inspector.get_table_names())
    except Exception:
        return False


def _has_column(inspector, table: str, column: str) -> bool:
    """列存在性检查。"""
    try:
        return column in {c["name"] for c in inspector.get_columns(table)}
    except Exception:
        return False


def _primary_key(inspector, table: str) -> str:
    """取主键列名；无主键时回退 rowid（SQLite 隐式主键）。"""
    try:
        pk = inspector.get_pk_constraint(table)
        cols = (pk or {}).get("constrained_columns") or []
        if cols:
            return cols[0]
    except Exception:
        pass
    return "rowid"


def _parse(value) -> datetime | None:
    """把库里的字符串解析成 datetime；解析不了返回 None（调用方跳过）。"""
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "").strip())
    except ValueError:
        return None


def _render(new_dt: datetime, original: str = "") -> str:
    """按 SQLAlchemy/SQLite 的 DATETIME 规范格式回写。

    统一用空格分隔 + 微秒（无微秒时自动省略），原因：
    1. 与 ORM 自身写入的格式完全一致，避免同一列里混着 ``T`` 与空格两种
       分隔符——SQLite 按 TEXT 做字典序排序，混用会让 ``ORDER BY 时间列``
       的结果错乱（库里 ``users.updated_at`` 就存在这样一条 ``T`` 分隔的历史值）；
    2. ``isoformat`` 在微秒为 0 时自动省略小数部分，
       因此 ``CURRENT_TIMESTAMP`` 写入的 ``09:55:27`` 不会被画蛇添足成
       ``09:55:27.000000``。
    """
    return new_dt.isoformat(sep=" ")


def _shift_table(conn, table: str, column: str, key: str, hours: int) -> int:
    """对单张表的单个时间列做 +/- N 小时平移。

    Args:
        conn: 数据库连接。
        table: 表名。
        column: 时间列名。
        key: 用于定位行的主键列名。
        hours: 平移小时数（upgrade 传 +8，downgrade 传 -8）。

    Returns:
        实际更新的行数。
    """
    delta = _OFFSET if hours > 0 else -_OFFSET
    rows = conn.execute(sa.text(
        f'SELECT "{key}" AS _k, "{column}" AS _v FROM "{table}" '
        f'WHERE "{column}" IS NOT NULL'
    )).fetchall()

    updated = 0
    for row in rows:
        old = _parse(row._v)
        if old is None:
            continue
        new_text = _render(old + delta)
        conn.execute(
            sa.text(f'UPDATE "{table}" SET "{column}" = :v WHERE "{key}" = :k'),
            {"v": new_text, "k": row._k},
        )
        updated += 1
    return updated


def _shift_all(hours: int) -> None:
    """遍历全库所有墙钟时间列做平移。

    Args:
        hours: +8 表示 UTC -> 东八区（upgrade），-8 表示回退（downgrade）。
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    total_tables = 0
    total_rows = 0
    for table in inspector.get_table_names():
        if table.startswith("sqlite_") or table == "alembic_version":
            continue
        columns = [c["name"] for c in inspector.get_columns(table)]
        time_cols = [c for c in columns if _is_time_column(c)]
        if not time_cols:
            continue
        key = _primary_key(inspector, table)
        for column in time_cols:
            n = _shift_table(bind, table, column, key, hours)
            if n:
                total_tables += 1
                logger.info("[v35 time] %s.%s %+dh -> %d rows",
                            table, column, hours, n)
            total_rows += n
    logger.info("[v35 time] done: %d columns touched, %d rows shifted by %+dh",
                total_tables, total_rows, hours)


def upgrade() -> None:
    """存量 UTC 时间 +8 小时，对齐东八区本地时间语义。"""
    _shift_all(+8)


def downgrade() -> None:
    """回退：东八区本地时间 -8 小时，恢复到 UTC 存储语义。"""
    _shift_all(-8)
