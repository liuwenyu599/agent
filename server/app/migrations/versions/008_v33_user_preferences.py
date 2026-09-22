"""v3.3 用户个人偏好表（Prompt 分层第 5 层）

安全约束：
- 只新增 user_preferences 一张独立表，不改动任何既有表结构与业务数据。
- 表里不含 department_code / scope / role / theme 等任何权限位；
  权限与检索范围解析链路不读该表。
- 沿用 007 的 inspector 守卫写法，保证 SQLite 存量库可安全升级/回退。

Revision ID: 008_v33_user_preferences
Revises: 007_v32_agent_layers
"""
from alembic import op
import sqlalchemy as sa

revision = "008_v33_user_preferences"
down_revision = "007_v32_agent_layers"
branch_labels = None
depends_on = None


def _has_table(inspector, table: str) -> bool:
    try:
        return table in set(inspector.get_table_names())
    except Exception:
        return False


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_table(inspector, "user_preferences"):
        op.create_table(
            "user_preferences",
            sa.Column("user_id", sa.String(36),
                      sa.ForeignKey("users.id"), primary_key=True),
            sa.Column("assistant_name", sa.String(30),
                      nullable=False, server_default=sa.text("''")),
            sa.Column("work_preference", sa.Text(),
                      nullable=False, server_default=sa.text("''")),
            sa.Column("writing_style", sa.String(20),
                      nullable=False, server_default=sa.text("''")),
            sa.Column("writing_style_custom", sa.Text(),
                      nullable=False, server_default=sa.text("''")),
            sa.Column("behaviors_json", sa.Text(),
                      nullable=False, server_default=sa.text("'{}'")),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _has_table(inspector, "user_preferences"):
        op.drop_table("user_preferences")
