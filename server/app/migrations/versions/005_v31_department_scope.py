"""v3.1 组织隔离：科室表 + 科室 Agent 配置表 + 各业务对象 department_code 列

安全约束：
- 只新增表和列，不删除任何存量表或列，不删除任何存量业务数据。
- 新增列一律带 server_default，保证 SQLite 存量表可加列。
- downgrade 只移除本次新增对象，不触碰业务数据。

Revision ID: 005_v31_department_scope
Revises: 004_v3_rbac_approval
"""
from alembic import op
import sqlalchemy as sa

revision = "005_v31_department_scope"
down_revision = "004_v3_rbac_approval"
branch_labels = None
depends_on = None


def _has_table(inspector, name: str) -> bool:
    try:
        return name in inspector.get_table_names()
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

    # ---------- 1. 科室字典 ----------
    if not _has_table(inspector, "departments"):
        op.create_table(
            "departments",
            sa.Column("code", sa.String(40), primary_key=True),
            sa.Column("name", sa.String(100), nullable=False),
            sa.Column("short_name", sa.String(60), server_default=""),
            sa.Column("sort_order", sa.Integer, server_default="0"),
            sa.Column("is_active", sa.Boolean, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        )

    # ---------- 2. 科室 Agent 配置 ----------
    if not _has_table(inspector, "agent_configs"):
        op.create_table(
            "agent_configs",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("dept_code", sa.String(40), nullable=False, unique=True),
            sa.Column("name", sa.String(60), server_default=""),
            sa.Column("intro", sa.Text, server_default=""),
            sa.Column("model", sa.String(120), server_default=""),
            sa.Column("system_prompt", sa.Text, server_default=""),
            sa.Column("scopes_json", sa.Text, server_default="[]"),
            sa.Column("tasks_json", sa.Text, server_default="[]"),
            sa.Column("templates_json", sa.Text, server_default="[]"),
            sa.Column("manager", sa.String(100), server_default=""),
            sa.Column("updated_at", sa.DateTime, server_default=sa.func.now()),
        )

    # ---------- 3. 业务对象隔离列 ----------
    for table in ("users", "knowledge_bases", "documents",
                  "my_documents", "writing_templates"):
        if _has_table(inspector, table) and not _has_column(inspector, table, "department_code"):
            op.add_column(
                table,
                sa.Column("department_code", sa.String(40),
                          nullable=False, server_default=""),
            )
            op.create_index(f"ix_{table}_department_code", table, ["department_code"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    for table in ("users", "knowledge_bases", "documents",
                  "my_documents", "writing_templates"):
        if _has_table(inspector, table) and _has_column(inspector, table, "department_code"):
            try:
                op.drop_index(f"ix_{table}_department_code", table_name=table)
            except Exception:
                pass
            op.drop_column(table, "department_code")

    if _has_table(inspector, "agent_configs"):
        op.drop_table("agent_configs")
    if _has_table(inspector, "departments"):
        op.drop_table("departments")
