"""v3.1 密码策略：users.must_change_password

安全约束：
- 只新增列，不改动 005 已建对象与既有业务数据语义。
- 新列带 server_default，保证 SQLite 存量表可直接加列。
- downgrade 仅移除本列。

Revision ID: 006_v31_password_policy
Revises: 005_v31_department_scope
"""
from alembic import op
import sqlalchemy as sa

revision = "006_v31_password_policy"
down_revision = "005_v31_department_scope"
branch_labels = None
depends_on = None


def _has_column(inspector, table: str, column: str) -> bool:
    try:
        return column in {c["name"] for c in inspector.get_columns(table)}
    except Exception:
        return False


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not _has_column(inspector, "users", "must_change_password"):
        op.add_column(
            "users",
            sa.Column("must_change_password", sa.Boolean(),
                      nullable=False, server_default=sa.false()),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _has_column(inspector, "users", "must_change_password"):
        op.drop_column("users", "must_change_password")
