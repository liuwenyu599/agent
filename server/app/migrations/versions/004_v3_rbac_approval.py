"""v3.0 核心：RBAC 三表 + 审核流两表 + 用户角色/数据范围扩展列

安全约束：
- 只新增表和列，不删除任何存量表或列，不删除任何存量业务数据。
- 新增列一律 nullable 或带 server_default（SQLite 批量建表要求）。
- downgrade 完整可逆；users.role 的改写通过 role_legacy 列保留原值，可精确反推。

Revision ID: 004_v3_rbac_approval
Revises: 003_add_audit_system_tables
"""
from alembic import op
import sqlalchemy as sa

revision = "004_v3_rbac_approval"
down_revision = "003_add_audit_system_tables"
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

    # ---------- 1. RBAC 三表 ----------
    if not _has_table(inspector, "roles"):
        op.create_table(
            "roles",
            sa.Column("code", sa.String(30), primary_key=True),
            sa.Column("name", sa.String(60), nullable=False),
            sa.Column("description", sa.String(300), server_default=""),
            sa.Column("is_system", sa.Boolean, server_default=sa.text("1")),
            sa.Column("sort_order", sa.Integer, server_default="0"),
            sa.Column("created_at", sa.DateTime, server_default=sa.text("CURRENT_TIMESTAMP")),
        )
    if not _has_table(inspector, "permissions"):
        op.create_table(
            "permissions",
            sa.Column("code", sa.String(60), primary_key=True),
            sa.Column("name", sa.String(100), nullable=False),
            sa.Column("module", sa.String(30), server_default=""),
            sa.Column("sort_order", sa.Integer, server_default="0"),
            sa.Column("created_at", sa.DateTime, server_default=sa.text("CURRENT_TIMESTAMP")),
        )
    if not _has_table(inspector, "role_permissions"):
        op.create_table(
            "role_permissions",
            sa.Column("role_code", sa.String(30), nullable=False),
            sa.Column("permission_code", sa.String(60), nullable=False),
            sa.Column("created_at", sa.DateTime, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.PrimaryKeyConstraint("role_code", "permission_code"),
        )

    # ---------- 2. 审核流两表 ----------
    if not _has_table(inspector, "approval_instances"):
        op.create_table(
            "approval_instances",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("document_id", sa.String(36), sa.ForeignKey("my_documents.id"), nullable=True),
            sa.Column("title", sa.String(300), nullable=False),
            sa.Column("submitter_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("submitter_name", sa.String(100), server_default=""),
            sa.Column("department", sa.String(100), server_default=""),
            sa.Column("current_status", sa.String(30), server_default="PENDING_DEPT"),
            sa.Column("current_step", sa.String(30), server_default="dept"),
            sa.Column("flow", sa.JSON, nullable=True),
            sa.Column("doc_number", sa.String(80), nullable=True),
            sa.Column("urgency", sa.String(10), server_default="normal"),
            sa.Column("created_at", sa.DateTime, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime, server_default=sa.text("CURRENT_TIMESTAMP")),
        )
        op.create_index("ix_approval_instances_submitter", "approval_instances", ["submitter_id"])
        op.create_index("ix_approval_instances_status", "approval_instances", ["current_status"])

    if not _has_table(inspector, "approval_actions"):
        op.create_table(
            "approval_actions",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("instance_id", sa.String(36), sa.ForeignKey("approval_instances.id"), nullable=False),
            sa.Column("action", sa.String(30), nullable=False),
            sa.Column("from_status", sa.String(30), server_default=""),
            sa.Column("to_status", sa.String(30), server_default=""),
            sa.Column("comment", sa.Text, nullable=True),
            sa.Column("actor_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("actor_name", sa.String(100), server_default=""),
            sa.Column("actor_role", sa.String(30), server_default=""),
            sa.Column("created_at", sa.DateTime, server_default=sa.text("CURRENT_TIMESTAMP")),
        )
        op.create_index("ix_approval_actions_instance", "approval_actions", ["instance_id"])

    # ---------- 3. users 扩展列 ----------
    inspector = sa.inspect(bind)
    if not _has_column(inspector, "users", "role_legacy"):
        op.add_column("users", sa.Column("role_legacy", sa.String(20), nullable=True))
        # 保留迁移前的原始角色值，保证 downgrade 可精确还原
        op.execute("UPDATE users SET role_legacy = role WHERE role_legacy IS NULL")

    inspector = sa.inspect(bind)
    if not _has_column(inspector, "users", "data_scope"):
        op.add_column("users", sa.Column("data_scope", sa.String(10),
                                         nullable=True, server_default="self"))
        op.execute("UPDATE users SET data_scope = 'self' WHERE data_scope IS NULL")

    # ---------- 4. format_rules 规则集列 ----------
    inspector = sa.inspect(bind)
    if _has_table(inspector, "format_rules") and not _has_column(inspector, "format_rules", "ruleset"):
        op.add_column("format_rules", sa.Column("ruleset", sa.String(30),
                                                nullable=True, server_default="gb9704"))
        op.execute("UPDATE format_rules SET ruleset = 'gb9704' WHERE ruleset IS NULL")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_table(inspector, "approval_actions"):
        op.drop_index("ix_approval_actions_instance", table_name="approval_actions")
        op.drop_table("approval_actions")
    if _has_table(inspector, "approval_instances"):
        op.drop_index("ix_approval_instances_status", table_name="approval_instances")
        op.drop_index("ix_approval_instances_submitter", table_name="approval_instances")
        op.drop_table("approval_instances")
    if _has_table(inspector, "role_permissions"):
        op.drop_table("role_permissions")
    if _has_table(inspector, "permissions"):
        op.drop_table("permissions")
    if _has_table(inspector, "roles"):
        op.drop_table("roles")

    # users：先用 role_legacy 还原角色，再删列
    inspector = sa.inspect(bind)
    if _has_column(inspector, "users", "role_legacy"):
        op.execute("UPDATE users SET role = role_legacy WHERE role_legacy IS NOT NULL")
    if _has_column(inspector, "users", "role_legacy"):
        op.drop_column("users", "role_legacy")
    if _has_column(inspector, "users", "data_scope"):
        op.drop_column("users", "data_scope")
    inspector = sa.inspect(bind)
    if _has_table(inspector, "format_rules") and _has_column(inspector, "format_rules", "ruleset"):
        op.drop_column("format_rules", "ruleset")
