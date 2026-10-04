"""Remove the retired approval module tables.

Revision ID: 013_remove_approval_module
Revises: 012_v37_ai_response_feedback
"""
from alembic import op
import sqlalchemy as sa

revision = "013_remove_approval_module"
down_revision = "012_v37_ai_response_feedback"
branch_labels = None
depends_on = None


def _has_table(inspector, name: str) -> bool:
    try:
        return name in inspector.get_table_names()
    except Exception:
        return False


def _has_index(inspector, table: str, name: str) -> bool:
    try:
        return name in {idx.get("name") for idx in inspector.get_indexes(table)}
    except Exception:
        return False


def upgrade() -> None:
    """Drop approval-only storage; document/RBAC tables remain untouched."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_table(inspector, "approval_actions"):
        if _has_index(inspector, "approval_actions", "ix_approval_actions_instance"):
            op.drop_index("ix_approval_actions_instance", table_name="approval_actions")
        op.drop_table("approval_actions")

    inspector = sa.inspect(bind)
    if _has_table(inspector, "approval_instances"):
        if _has_index(inspector, "approval_instances", "ix_approval_instances_status"):
            op.drop_index("ix_approval_instances_status", table_name="approval_instances")
        if _has_index(inspector, "approval_instances", "ix_approval_instances_submitter"):
            op.drop_index("ix_approval_instances_submitter", table_name="approval_instances")
        op.drop_table("approval_instances")


def downgrade() -> None:
    """Recreate the legacy tables only when rolling back this migration."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

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

    inspector = sa.inspect(bind)
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
