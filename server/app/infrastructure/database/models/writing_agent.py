"""Durable execution records for the internal writing-agent graph."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.timeutil import now_local
from app.infrastructure.database.base import Base, IdMixin


class WritingAgentRunModel(Base, IdMixin):
    __tablename__ = "writing_agent_runs"

    task_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("writing_tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    graph_version: Mapped[str] = mapped_column(String(32), nullable=False, default="writing-v1")
    route: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued", index=True)
    current_node: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    active_key: Mapped[Optional[str]] = mapped_column(String(80), unique=True)
    base_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    base_content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    state_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_code: Mapped[Optional[str]] = mapped_column(String(80))
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now_local)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=now_local, onupdate=now_local)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)


class WritingAgentStepModel(Base, IdMixin):
    __tablename__ = "writing_agent_steps"
    __table_args__ = (
        UniqueConstraint("run_id", "node_name", "attempt", name="uq_writing_agent_step"),
    )

    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("writing_agent_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    node_name: Mapped[str] = mapped_column(String(40), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running")
    input_digest: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    output_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    output_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    duration_seconds: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now_local)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=now_local, onupdate=now_local)


class WritingAgentToolCallModel(Base, IdMixin):
    __tablename__ = "writing_agent_tool_calls"

    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("writing_agent_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    step_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("writing_agent_steps.id", ondelete="SET NULL"), index=True)
    agent_name: Mapped[str] = mapped_column(String(40), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(80), nullable=False)
    arguments_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    result_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="completed")
    duration_seconds: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now_local)
