"""Persist editable document formatting with each immutable version.

Revision ID: 019_document_formatting
Revises: 018_writing_agent_runs
"""
from alembic import op
import sqlalchemy as sa

revision = "019_document_formatting"
down_revision = "018_writing_agent_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("my_document_versions", sa.Column("formatting", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("my_document_versions", "formatting")
