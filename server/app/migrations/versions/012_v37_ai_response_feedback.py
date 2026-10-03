"""v3.7 AI response/text-version feedback.

Revision ID: 012_v37_ai_response_feedback
Revises: 011_v36_ppt_agent_jobs
"""
from alembic import op
import sqlalchemy as sa

revision = "012_v37_ai_response_feedback"
down_revision = "011_v36_ppt_agent_jobs"
branch_labels = None
depends_on = None

_TABLE = "ai_response_feedback"


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _TABLE in inspector.get_table_names():
        return
    op.create_table(
        _TABLE,
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("target_type", sa.String(32), nullable=False),
        sa.Column("target_id", sa.String(36), nullable=False),
        sa.Column("message_id", sa.String(36), sa.ForeignKey("chat_messages.id", ondelete="CASCADE"), nullable=True),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("source_chunk_ids", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("user_id", "target_type", "target_id", name="uq_ai_feedback_user_target"),
    )
    op.create_index("ix_ai_response_feedback_user_id", _TABLE, ["user_id"])
    op.create_index("ix_ai_response_feedback_target_id", _TABLE, ["target_id"])
    op.create_index("ix_ai_response_feedback_message_id", _TABLE, ["message_id"])


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _TABLE not in inspector.get_table_names():
        return
    op.drop_index("ix_ai_response_feedback_message_id", table_name=_TABLE)
    op.drop_index("ix_ai_response_feedback_target_id", table_name=_TABLE)
    op.drop_index("ix_ai_response_feedback_user_id", table_name=_TABLE)
    op.drop_table(_TABLE)
