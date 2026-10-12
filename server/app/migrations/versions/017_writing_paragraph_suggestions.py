"""Persist isolated paragraph suggestions and their audit trail.

Revision ID: 017_writing_paragraph_suggestions
Revises: 016_cjk_font_platform_neutral
"""
from alembic import op
import sqlalchemy as sa

revision = "017_writing_paragraph_suggestions"
down_revision = "016_cjk_font_platform_neutral"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "writing_suggestions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("task_id", sa.String(36), sa.ForeignKey("writing_tasks.id"), nullable=False),
        sa.Column("paragraph_id", sa.String(64), nullable=False),
        sa.Column("line_index", sa.Integer(), nullable=False),
        sa.Column("document_type", sa.String(100), nullable=False),
        sa.Column("base_version", sa.Integer(), nullable=False),
        sa.Column("base_content_hash", sa.String(64), nullable=False),
        sa.Column("original_content", sa.Text(), nullable=False),
        sa.Column("proposed_content", sa.Text(), nullable=False),
        sa.Column("final_content", sa.Text()),
        sa.Column("instruction", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    for column in ("user_id", "task_id", "paragraph_id"):
        op.create_index(f"ix_writing_suggestions_{column}", "writing_suggestions", [column])
    op.create_index("ix_writing_suggestions_lookup", "writing_suggestions",
                    ["user_id", "task_id", "status", "line_index", "created_at"])
    op.create_table(
        "writing_suggestion_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("task_id", sa.String(36), sa.ForeignKey("writing_tasks.id"), nullable=False),
        sa.Column("suggestion_id", sa.String(36), sa.ForeignKey("writing_suggestions.id"), nullable=False),
        sa.Column("paragraph_id", sa.String(64), nullable=False),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("original_content", sa.Text(), nullable=False),
        sa.Column("final_content", sa.Text()),
        sa.Column("diff_text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    for column in ("user_id", "task_id", "suggestion_id"):
        op.create_index(f"ix_writing_suggestion_events_{column}", "writing_suggestion_events", [column])


def downgrade() -> None:
    op.drop_table("writing_suggestion_events")
    op.drop_table("writing_suggestions")
