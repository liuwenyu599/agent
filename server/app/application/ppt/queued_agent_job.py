"""Single-process admission queue for PPTAgent jobs.

The core :mod:`agent_job` module owns one long-running generation. This wrapper adds
server-side admission control without changing that runner: at most two generations
run at once, overflow is FIFO, and one user may own at most one active/queued job.

This queue is intentionally process-local. Cross-process coordination belongs to the
multi-instance deployment layer; pretending an in-memory semaphore is distributed
would be incorrect.
"""
from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass
from typing import Any, Deque, Dict, List, Optional

from app.application.ppt import agent_job as _core
from app.core.exceptions import ConflictError
from app.core.timeutil import now_local

logger = _core.logger
settings = _core.settings

# Item 7 acceptance contract: one application process may drive at most two expensive
# PPTAgent generations concurrently. Extra jobs stay in a strict FIFO queue.
_MAX_CONCURRENT_JOBS = 2
_SLOTS = threading.BoundedSemaphore(_MAX_CONCURRENT_JOBS)
_QUEUE_LOCK = threading.RLock()


@dataclass
class _QueuedJob:
    doc_id: str
    user_id: str
    message: str
    history: Optional[List[Any]]


_QUEUE: Deque[_QueuedJob] = deque()
_ACTIVE_DOCS: set[str] = set()
# Includes both active and queued ownership. It is the atomic guard for the
# "same user max one active/queued job" rule.
_USER_JOBS: Dict[str, str] = {}

# Compatibility exports used by existing routes/tests.
_RUNNING = _core._RUNNING
_RUNNING_LOCK = _core._RUNNING_LOCK
_TERMINAL = _core._TERMINAL
_open = _core._open
_update_job = _core._update_job
_is_active = _core._is_active
list_previews = _core.list_previews
resolve_preview = _core.resolve_preview


def _queue_position_locked(doc_id: str) -> Optional[int]:
    """Return 1-based FIFO position, 0 for active, None when not admitted."""
    if doc_id in _ACTIVE_DOCS:
        return 0
    for index, item in enumerate(_QUEUE, start=1):
        if item.doc_id == doc_id:
            return index
    return None


def _start_locked(item: _QueuedJob) -> None:
    """Start one job after a semaphore slot has already been acquired."""
    _ACTIVE_DOCS.add(item.doc_id)
    _update_job(
        item.doc_id,
        job_status="pending",
        job_phase="submitting",
        job_error="",
        job_question="",
        job_current_page=0,
        job_total_pages=0,
        job_cancel_requested=False,
        job_started_at=now_local(),
        job_progress_at=now_local(),
        job_finished_at=None,
    )
    runner = PPTAgentJobRunner(
        item.doc_id, item.user_id, item.message, history=item.history
    )
    thread = threading.Thread(
        target=runner.run,
        name=f"ppt-job-{item.doc_id[:8]}",
        daemon=True,
    )
    with _RUNNING_LOCK:
        _RUNNING[item.doc_id] = thread
    try:
        thread.start()
    except Exception:
        with _RUNNING_LOCK:
            _RUNNING.pop(item.doc_id, None)
        _ACTIVE_DOCS.discard(item.doc_id)
        if _USER_JOBS.get(item.user_id) == item.doc_id:
            _USER_JOBS.pop(item.user_id, None)
        _SLOTS.release()
        _update_job(
            item.doc_id,
            status="failed",
            job_status="failed",
            job_phase="failed",
            job_error="后台生成线程启动失败",
            job_finished_at=now_local(),
        )
        raise
    logger.info("PPT job 开始执行：job_id=%s", item.doc_id)


def _dispatch_locked() -> None:
    """Fill every free slot from the FIFO queue."""
    while _QUEUE and _SLOTS.acquire(blocking=False):
        item = _QUEUE.popleft()
        try:
            _start_locked(item)
        except Exception:  # slot was restored by _start_locked
            logger.exception("PPT 排队任务启动失败：job_id=%s", item.doc_id)
            # Another queued job must not be blocked by one bad thread start.
            continue


def _on_runner_finished(doc_id: str, user_id: str) -> None:
    """Release capacity/user ownership and immediately admit the next FIFO job."""
    with _QUEUE_LOCK:
        if doc_id not in _ACTIVE_DOCS:
            return
        _ACTIVE_DOCS.discard(doc_id)
        if _USER_JOBS.get(user_id) == doc_id:
            _USER_JOBS.pop(user_id, None)
        _SLOTS.release()
        _dispatch_locked()


class PPTAgentJobRunner(_core.PPTAgentJobRunner):
    """Core runner plus queue-slot release/dispatch in a guaranteed finally block."""

    def run(self) -> None:
        try:
            super().run()
        finally:
            _on_runner_finished(self.doc_id, self.user_id)


def submit_job(
    doc_id: str,
    user_id: str,
    message: str = "",
    history: Optional[List[Any]] = None,
) -> Dict[str, Any]:
    """Admit immediately when capacity exists; otherwise enqueue in FIFO order."""
    # 无 PPTAgent 时走本地严格套模板渲染：秒级确定性任务，不占用排队名额，
    # 因此直接交给 core 的同一条异步 job 链路，不再以「不可用」拒绝。
    if not (settings.PPT_AGENT_URL or "").strip():
        result = _core.submit_job(doc_id, user_id, message, history)
        result.setdefault("queue_position", None)
        return result

    with _QUEUE_LOCK:
        position = _queue_position_locked(doc_id)
        if position is not None:
            phase = "queued" if position > 0 else "submitting"
            return {
                "job_id": doc_id,
                "status": "pending" if position > 0 else "running",
                "phase": phase,
                "queue_position": position,
                "message": "已有进行中的任务",
            }

        existing = _USER_JOBS.get(user_id)
        if existing and existing != doc_id:
            raise ConflictError(
                "同一用户同时只能有 1 个 PPT 生成任务（含排队任务），"
                f"请等待任务 {existing} 完成或取消后再提交。"
            )

        item = _QueuedJob(doc_id, user_id, message or "", history)
        _USER_JOBS[user_id] = doc_id

        # Reset stale state before either starting or queueing this document.
        _update_job(
            doc_id,
            job_status="pending",
            job_phase="queued",
            job_error="",
            job_question="",
            job_current_page=0,
            job_total_pages=0,
            job_cancel_requested=False,
            job_started_at=None,
            job_progress_at=now_local(),
            job_finished_at=None,
        )

        if _SLOTS.acquire(blocking=False):
            try:
                _start_locked(item)
            except Exception:
                # _start_locked already restores the slot and ownership on failure.
                raise
            return {
                "job_id": doc_id,
                "status": "pending",
                "phase": "submitting",
                "queue_position": 0,
            }

        _QUEUE.append(item)
        position = len(_QUEUE)
        logger.info("PPT job 进入 FIFO 队列：job_id=%s position=%d", doc_id, position)
        return {
            "job_id": doc_id,
            "status": "pending",
            "phase": "queued",
            "queue_position": position,
        }


def cancel_job(doc_id: str) -> Dict[str, Any]:
    """Cancel queued jobs immediately; active jobs retain the core cooperative cancel."""
    with _QUEUE_LOCK:
        queued: Optional[_QueuedJob] = None
        for item in _QUEUE:
            if item.doc_id == doc_id:
                queued = item
                break
        if queued is not None:
            _QUEUE.remove(queued)
            if _USER_JOBS.get(queued.user_id) == doc_id:
                _USER_JOBS.pop(queued.user_id, None)
            _update_job(
                doc_id,
                job_cancel_requested=True,
                job_status="cancelled",
                job_phase="cancelled",
                job_finished_at=now_local(),
                job_progress_at=now_local(),
            )
            return {
                "job_id": doc_id,
                "status": "cancelled",
                "queue_position": None,
                "message": "已取消排队任务",
            }
    return _core.cancel_job(doc_id)


def answer_clarification(
    doc_id: str, user_id: str, answer: str
) -> Dict[str, Any]:
    """Legacy clarification resume path, routed through the same admission queue."""
    doc = _open(doc_id)
    if not doc:
        return {"job_id": doc_id, "status": "failed", "message": "任务不存在"}
    if doc.job_status != "awaiting_clarification":
        return {
            "job_id": doc_id,
            "status": doc.job_status or "unknown",
            "message": "该任务当前不在等待回答状态",
        }
    final_answer = (answer or "").strip()
    if not final_answer:
        final_answer = "我不额外补充，请你按自己的专业判断直接生成完整 PPT。"
    history = [
        {"role": "assistant", "content": doc.job_question or ""},
        {"role": "user", "content": final_answer},
    ]
    return submit_job(
        doc_id, user_id, message=final_answer, history=history
    )


def job_status(doc) -> Dict[str, Any]:
    """Core persisted status plus current process-local FIFO position."""
    with _QUEUE_LOCK:
        position = _queue_position_locked(doc.id)
    result = _core.job_status(doc)
    result["queue_position"] = position
    if position is not None and position > 0:
        # A queued job has not started, so the core stall timer must not age it out.
        result["status"] = "pending"
        result["phase"] = "queued"
        result["elapsed_seconds"] = 0.0
        result["estimated_remaining"] = None
    return result


def __getattr__(name: str):
    """Keep the wrapper drop-in compatible with the core module."""
    return getattr(_core, name)
