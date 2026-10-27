"""Curated writing memory for public, department and individual scopes.

Revision ID: 020_writing_scoped_memory
Revises: 019_document_formatting
"""
from alembic import op
import sqlalchemy as sa

revision = "020_writing_scoped_memory"
down_revision = "019_document_formatting"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "writing_memories",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("scope", sa.String(12), nullable=False),
        sa.Column("owner_user_id", sa.String(36), sa.ForeignKey("users.id")),
        sa.Column("department_code", sa.String(40), nullable=False, server_default=""),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("document_type", sa.String(100), nullable=False, server_default=""),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("scope IN ('public', 'department', 'personal')",
                           name="ck_writing_memories_scope"),
    )
    op.create_index("ix_writing_memories_scope_owner", "writing_memories",
                    ["scope", "owner_user_id"])
    op.create_index("ix_writing_memories_scope_dept", "writing_memories",
                    ["scope", "department_code"])


def downgrade() -> None:
    op.drop_index("ix_writing_memories_scope_dept", table_name="writing_memories")
    op.drop_index("ix_writing_memories_scope_owner", table_name="writing_memories")
    op.drop_table("writing_memories")
