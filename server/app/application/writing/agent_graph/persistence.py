"""Application-owned persistence and idempotency for writing-agent runs."""
from __future__ import annotations

import hashlib
import json
import time
from datetime import timedelta
from typing import Any, Optional

from fastapi import HTTPException
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError

from app.core.timeutil import now_local
from app.infrastructure.database.models.writing_agent import (
    WritingAgentRunModel,
    WritingAgentStepModel,
    WritingAgentToolCallModel,
)


ACTIVE_STATUSES = ("queued", "running", "interrupted")
TERMINAL_STATUSES = ("completed", "failed", "cancelled")
_LAST_CLEANUP_AT = 0.0


def content_digest(content: str) -> str:
    return hashlib.sha256((content or "").encode("utf-8")).hexdigest()


def json_digest(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class AgentRunStore:
    def __init__(self, db):
        self.db = db

    @staticmethod
    def _active_key(task_id: str, user_id: str) -> str:
        return f"{user_id}:{task_id}"

    def recover_stale_running(self, run_id: Optional[str] = None) -> int:
        """Release runs whose worker disappeared without updating terminal state."""
        from app.core.config import settings

        cutoff = now_local() - timedelta(
            seconds=settings.WRITING_AGENT_RUN_TIMEOUT_SECONDS)
        conditions = [
            WritingAgentRunModel.status == "running",
            WritingAgentRunModel.updated_at < cutoff,
        ]
        if run_id:
            conditions.append(WritingAgentRunModel.id == run_id)
        result = self.db.execute(update(WritingAgentRunModel).where(
            *conditions,
        ).values(
            status="interrupted",
            error_code="STALE_WORKER_RECOVERED",
            error_message="上一次生成进程已中断，系统将从最近完成阶段恢复",
            updated_at=now_local(),
        ))
        self.db.commit()
        return int(result.rowcount or 0)

    def get_or_create(self, *, task_id: str, user_id: str, route: str,
                      base_version: int, base_content: str,
                      initial_state: dict[str, Any]) -> tuple[WritingAgentRunModel, bool]:
        self.cleanup_expired_traces()
        self.recover_stale_running()
        key = self._active_key(task_id, user_id)
        active = self.db.scalars(select(WritingAgentRunModel).where(
            WritingAgentRunModel.active_key == key,
            WritingAgentRunModel.status.in_(ACTIVE_STATUSES),
        )).first()
        if active:
            return active, False
        run = WritingAgentRunModel(
            task_id=task_id,
            user_id=user_id,
            route=route,
            status="queued",
            active_key=key,
            base_version=base_version,
            base_content_hash=content_digest(base_content),
            state_json=dict(initial_state),
        )
        self.db.add(run)
        try:
            self.db.commit()
            self.db.refresh(run)
            return run, True
        except IntegrityError:
            self.db.rollback()
            active = self.db.scalars(select(WritingAgentRunModel).where(
                WritingAgentRunModel.active_key == key,
                WritingAgentRunModel.status.in_(ACTIVE_STATUSES),
            )).first()
            if active:
                return active, False
            raise

    def cleanup_expired_traces(self) -> None:
        """Prune detailed step/tool traces lazily; run summaries follow task lifecycle."""
        global _LAST_CLEANUP_AT
        now = time.monotonic()
        if now - _LAST_CLEANUP_AT < 3600:
            return
        _LAST_CLEANUP_AT = now
        from app.core.config import settings

        cutoff = now_local() - timedelta(days=settings.WRITING_AGENT_TRACE_RETENTION_DAYS)
        old_runs = self.db.scalars(select(WritingAgentRunModel).where(
            WritingAgentRunModel.status.in_(TERMINAL_STATUSES),
            WritingAgentRunModel.completed_at.is_not(None),
            WritingAgentRunModel.completed_at < cutoff,
        )).all()
        ids = [run.id for run in old_runs]
        if not ids:
            return
        self.db.execute(delete(WritingAgentToolCallModel).where(
            WritingAgentToolCallModel.run_id.in_(ids)))
        self.db.execute(delete(WritingAgentStepModel).where(
            WritingAgentStepModel.run_id.in_(ids)))
        for run in old_runs:
            state = dict(run.state_json or {})
            result = dict(state.get("result") or {})
            run.state_json = {
                "result": {
                    key: result.get(key)
                    for key in (
                        "task_id", "document_id", "version_no", "generation_mode",
                        "agent_run_id", "repair_rounds",
                    )
                    if result.get(key) is not None
                },
                "quality_level": state.get("quality_level"),
                "issue_count": len(state.get("quality_issues") or []),
                "repair_round": state.get("repair_round") or 0,
            }
        self.db.commit()

    def get_owned(self, run_id: str, task_id: str, user_id: str) -> WritingAgentRunModel:
        run = self.db.scalars(select(WritingAgentRunModel).where(
            WritingAgentRunModel.id == run_id,
            WritingAgentRunModel.task_id == task_id,
            WritingAgentRunModel.user_id == user_id,
        )).first()
        if not run:
            raise HTTPException(status_code=404, detail="写作智能体运行不存在")
        return run

    def active_for_task(self, task_id: str, user_id: str) -> Optional[WritingAgentRunModel]:
        return self.db.scalars(select(WritingAgentRunModel).where(
            WritingAgentRunModel.task_id == task_id,
            WritingAgentRunModel.user_id == user_id,
            WritingAgentRunModel.status.in_(ACTIVE_STATUSES),
        ).order_by(WritingAgentRunModel.created_at.desc())).first()

    def start(self, run: WritingAgentRunModel) -> None:
        if run.status == "cancelled":
            raise HTTPException(status_code=409, detail="该运行已取消")
        run.status = "running"
        run.error_code = None
        run.error_message = None
        run.started_at = run.started_at or now_local()
        run.updated_at = now_local()
        self.db.commit()

    def claim(self, run: WritingAgentRunModel) -> bool:
        """Atomically claim a queued/interrupted run across workers."""
        self.recover_stale_running(run.id)
        result = self.db.execute(update(WritingAgentRunModel).where(
            WritingAgentRunModel.id == run.id,
            WritingAgentRunModel.status.in_(("queued", "interrupted")),
        ).values(
            status="running", error_code=None, error_message=None,
            started_at=run.started_at or now_local(), updated_at=now_local(),
        ))
        self.db.commit()
        self.db.refresh(run)
        return result.rowcount == 1

    def completed_step(self, run_id: str, node_name: str,
                       attempt: int) -> Optional[WritingAgentStepModel]:
        return self.db.scalars(select(WritingAgentStepModel).where(
            WritingAgentStepModel.run_id == run_id,
            WritingAgentStepModel.node_name == node_name,
            WritingAgentStepModel.attempt == attempt,
            WritingAgentStepModel.status == "completed",
        )).first()

    def step(self, run_id: str, node_name: str,
             attempt: int) -> Optional[WritingAgentStepModel]:
        return self.db.scalars(select(WritingAgentStepModel).where(
            WritingAgentStepModel.run_id == run_id,
            WritingAgentStepModel.node_name == node_name,
            WritingAgentStepModel.attempt == attempt,
        )).first()

    def begin_step(self, run: WritingAgentRunModel, node_name: str, attempt: int,
                   state: dict[str, Any]) -> WritingAgentStepModel:
        row = self.db.scalars(select(WritingAgentStepModel).where(
            WritingAgentStepModel.run_id == run.id,
            WritingAgentStepModel.node_name == node_name,
            WritingAgentStepModel.attempt == attempt,
        )).first()
        if not row:
            row = WritingAgentStepModel(
                run_id=run.id, node_name=node_name, attempt=attempt,
                status="running", input_digest=json_digest(state),
            )
            self.db.add(row)
        else:
            row.status = "running"
            row.error_message = None
        run.current_node = node_name
        run.status = "running"
        self.db.commit()
        self.db.refresh(row)
        return row

    def complete_step(self, run: WritingAgentRunModel, node_name: str, attempt: int,
                      output: dict[str, Any], duration_seconds: float) -> WritingAgentStepModel:
        row = self.db.scalars(select(WritingAgentStepModel).where(
            WritingAgentStepModel.run_id == run.id,
            WritingAgentStepModel.node_name == node_name,
            WritingAgentStepModel.attempt == attempt,
        )).first()
        if not row:
            row = WritingAgentStepModel(
                run_id=run.id, node_name=node_name, attempt=attempt,
                input_digest="",
            )
            self.db.add(row)
        row.status = "completed"
        row.output_json = dict(output)
        row.output_summary = self._summary(output)
        row.duration_seconds = max(0.0, float(duration_seconds))
        row.error_message = None
        state = dict(run.state_json or {})
        state.update(output)
        run.state_json = state
        run.current_node = node_name
        run.updated_at = now_local()
        self.db.commit()
        self.db.refresh(row)
        return row

    def fail_step(self, run: WritingAgentRunModel, node_name: str, attempt: int,
                  message: str, *, recoverable: bool = True) -> None:
        row = self.db.scalars(select(WritingAgentStepModel).where(
            WritingAgentStepModel.run_id == run.id,
            WritingAgentStepModel.node_name == node_name,
            WritingAgentStepModel.attempt == attempt,
        )).first()
        if row:
            row.status = "failed"
            row.error_message = message[:2000]
        run.status = "interrupted" if recoverable else "failed"
        run.error_message = message[:2000]
        if not recoverable:
            run.active_key = None
            run.completed_at = now_local()
        self.db.commit()

    def record_tool_call(self, *, run_id: str, step_id: Optional[str], agent_name: str,
                         tool_name: str, arguments_summary: str, result_summary: str,
                         source_ids: list[str], status: str = "completed",
                         duration_seconds: float = 0.0) -> None:
        self.db.add(WritingAgentToolCallModel(
            run_id=run_id, step_id=step_id, agent_name=agent_name,
            tool_name=tool_name,
            arguments_summary=arguments_summary[:1000],
            result_summary=result_summary[:2000],
            source_ids=source_ids[:50], status=status,
            duration_seconds=max(0.0, float(duration_seconds)),
        ))
        self.db.commit()

    def finish(self, run: WritingAgentRunModel, result: dict[str, Any]) -> None:
        state = dict(run.state_json or {})
        state["result"] = result
        run.state_json = state
        run.status = "completed"
        run.current_node = "finalize"
        run.active_key = None
        run.error_code = None
        run.error_message = None
        run.completed_at = now_local()
        self.db.commit()

    def cancel(self, run: WritingAgentRunModel) -> None:
        if run.status == "completed":
            raise HTTPException(status_code=409, detail="该运行已完成，不能取消")
        run.status = "cancelled"
        run.active_key = None
        run.error_code = "CANCELLED"
        run.error_message = "用户已取消生成"
        run.completed_at = now_local()
        self.db.commit()

    def fail_run(self, run: WritingAgentRunModel, code: str, message: str,
                 *, recoverable: bool) -> None:
        run.status = "interrupted" if recoverable else "failed"
        run.error_code = code[:80]
        run.error_message = message[:2000]
        run.updated_at = now_local()
        if not recoverable:
            run.active_key = None
            run.completed_at = now_local()
        self.db.commit()

    @staticmethod
    def _summary(output: dict[str, Any]) -> str:
        safe: dict[str, Any] = {}
        for key, value in output.items():
            if isinstance(value, str):
                safe[key] = f"{len(value)} chars"
            elif isinstance(value, list):
                safe[key] = f"{len(value)} items"
            elif isinstance(value, dict):
                if key == "context":
                    safe[key] = {"fields": sorted(value.keys())}
                elif key in {"quality", "content_check"}:
                    safe[key] = {
                        "level": value.get("level"),
                        "issue_count": len(value.get("issues") or []),
                    }
                else:
                    safe[key] = {"fields": sorted(value.keys())}
            else:
                safe[key] = value
        return json.dumps(safe, ensure_ascii=False, default=str)[:2000]

    @staticmethod
    def public_dict(run: WritingAgentRunModel) -> dict[str, Any]:
        state = run.state_json or {}
        return {
            "id": run.id,
            "task_id": run.task_id,
            "route": run.route,
            "status": run.status,
            "current_node": run.current_node,
            "retry_count": run.retry_count,
            "quality_level": state.get("quality_level"),
            "issue_count": len(state.get("quality_issues") or []),
            "error_code": run.error_code,
            "error_message": run.error_message,
            "created_at": run.created_at.isoformat() if run.created_at else None,
            "updated_at": run.updated_at.isoformat() if run.updated_at else None,
        }
