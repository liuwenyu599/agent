"""v3.2 科室 Agent 分层配置与版本记录

安全约束：
- 只新增 agent_configs 的 Prompt 分层列与 agent_config_versions 新表，
  不改动 005 / 006 已建对象与既有业务数据语义。
- 新列均带 server_default，保证 SQLite 存量表可直接加列。
- downgrade 仅移除本次新增对象。

Revision ID: 007_v32_agent_layers
Revises: 006_v31_password_policy
"""
from alembic import op
import sqlalchemy as sa

revision = "007_v32_agent_layers"
down_revision = "006_v31_password_policy"
branch_labels = None
depends_on = None

_NEW_COLUMNS = [
    ("safety_prompt", sa.Text()),
    ("business_prompt", sa.Text()),
    ("work_requirements", sa.Text()),
    ("kb_json", sa.Text()),
    ("version", sa.Integer()),
]


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

    if _has_table(inspector, "agent_configs"):
        for name, type_ in _NEW_COLUMNS:
            if not _has_column(inspector, "agent_configs", name):
                default = sa.text("1") if name == "version" else sa.text("''")
                if name == "kb_json":
                    default = sa.text("'[]'")
                op.add_column(
                    "agent_configs",
                    sa.Column(name, type_, nullable=False, server_default=default),
                )

    if not _has_table(inspector, "agent_config_versions"):
        op.create_table(
            "agent_config_versions",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("dept_code", sa.String(40), nullable=False, index=True),
            sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
            sa.Column("operator_id", sa.String(36), nullable=False, server_default=sa.text("''")),
            sa.Column("operator_name", sa.String(100), nullable=False, server_default=sa.text("''")),
            sa.Column("change_note", sa.Text(), nullable=False, server_default=sa.text("''")),
            sa.Column("snapshot_json", sa.Text(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _has_table(inspector, "agent_config_versions"):
        op.drop_table("agent_config_versions")
    if _has_table(inspector, "agent_configs"):
        for name, _ in reversed(_NEW_COLUMNS):
            if _has_column(inspector, "agent_configs", name):
                op.drop_column("agent_configs", name)
