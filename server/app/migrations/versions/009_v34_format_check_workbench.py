"""v3.4 公文格式审校工作台：format_check_records 增加已应用/已修正 issue 集合

安全约束：
- 只给 format_check_records 加 2 个 TEXT 列（applied_ids / resolved_ids，
  内容为 JSON 整数数组），不改动既有列与业务数据语义。
- 沿用 005–008 的 inspector 守卫写法：列不存在才 ADD COLUMN，保证 SQLite 存量库
  可安全升级/回退且幂等（重复执行不报错）。
- 不加 applied_at / ignored_ids / revoked_ids 等本轮 UI 不消费的死列。
- downgrade 完整回退：两列都在时才删除。

Revision ID: 009_v34_format_check_workbench
Revises: 008_v33_user_preferences
"""
from alembic import op
import sqlalchemy as sa

revision = "009_v34_format_check_workbench"
down_revision = "008_v33_user_preferences"
branch_labels = None
depends_on = None

_TABLE = "format_check_records"
_NEW_COLUMNS = ["applied_ids", "resolved_ids"]


def _has_table(inspector, table: str) -> bool:
    try:
        return table in set(inspector.get_table_names())
    except Exception:
        return False


def _has_column(inspector, table: str, column: str) -> bool:
    try:
        return column in {c["name"] for c in inspector.get_columns(table)}
    except Exception:
        return False


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_table(inspector, _TABLE):
        return
    for name in _NEW_COLUMNS:
        if not _has_column(inspector, _TABLE, name):
            op.add_column(_TABLE, sa.Column(name, sa.Text(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_table(inspector, _TABLE):
        return
    # SQLite 不支持直接 DROP COLUMN 的批量语法差异由 render_as_batch 兜底
    for name in reversed(_NEW_COLUMNS):
        if _has_column(inspector, _TABLE, name):
            op.drop_column(_TABLE, name)
