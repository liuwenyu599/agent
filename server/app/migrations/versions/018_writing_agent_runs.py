"""Persist bounded writing-agent executions.

Revision ID: 018_writing_agent_runs
Revises: 017_writing_paragraph_suggestions
"""
from alembic import op
import sqlalchemy as sa


revision = "018_writing_agent_runs"
down_revision = "017_writing_paragraph_suggestions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "writing_agent_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("task_id", sa.String(36), sa.ForeignKey("writing_tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("graph_version", sa.String(32), nullable=False),
        sa.Column("route", sa.String(16), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("current_node", sa.String(40), nullable=False),
        sa.Column("active_key", sa.String(80), unique=True),
        sa.Column("base_version", sa.Integer(), nullable=False),
        sa.Column("base_content_hash", sa.String(64), nullable=False),
        sa.Column("state_json", sa.JSON(), nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(80)),
        sa.Column("error_message", sa.Text()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime()),
        sa.Column("completed_at", sa.DateTime()),
    )
    for column in ("task_id", "user_id", "status"):
        op.create_index(f"ix_writing_agent_runs_{column}", "writing_agent_runs", [column])

    op.create_table(
        "writing_agent_steps",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("writing_agent_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("node_name", sa.String(40), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("input_digest", sa.String(64), nullable=False),
        sa.Column("output_summary", sa.Text(), nullable=False),
        sa.Column("output_json", sa.JSON(), nullable=False),
        sa.Column("duration_seconds", sa.Float(), nullable=False),
        sa.Column("error_message", sa.Text()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("run_id", "node_name", "attempt", name="uq_writing_agent_step"),
    )
    op.create_index("ix_writing_agent_steps_run_id", "writing_agent_steps", ["run_id"])

    op.create_table(
        "writing_agent_tool_calls",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("writing_agent_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("step_id", sa.String(36), sa.ForeignKey("writing_agent_steps.id", ondelete="SET NULL")),
        sa.Column("agent_name", sa.String(40), nullable=False),
        sa.Column("tool_name", sa.String(80), nullable=False),
        sa.Column("arguments_summary", sa.Text(), nullable=False),
        sa.Column("result_summary", sa.Text(), nullable=False),
        sa.Column("source_ids", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("duration_seconds", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_writing_agent_tool_calls_run_id", "writing_agent_tool_calls", ["run_id"])
    op.create_index("ix_writing_agent_tool_calls_step_id", "writing_agent_tool_calls", ["step_id"])


def downgrade() -> None:
    op.drop_table("writing_agent_tool_calls")
    op.drop_table("writing_agent_steps")
    op.drop_table("writing_agent_runs")
