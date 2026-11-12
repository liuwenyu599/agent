"""Single-process admission queue for local and PPTAgent generation jobs.

The core :mod:`agent_job` module owns one long-running generation. This wrapper adds
server-side admission control: at most ``PPT_MAX_CONCURRENT_JOBS`` generations run
at once (default 2), overflow is FIFO, and one user may own at most one active/queued
job. The slot count is a startup snapshot shared by ``_SLOTS``, ``queue_stats()`` and
the ETA calculation, so changing it requires a backend restart.

This queue is intentionally process-local. Cross-process coordination belongs to the
multi-instance deployment layer; pretending an in-memory semaphore is distributed
would be incorrect.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional

from app.application.ppt import agent_job as _core
from app.core.exceptions import ConflictError
from app.core.timeutil import now_local

logger = _core.logger
settings = _core.settings

# One application process may drive at most N expensive PPT generations concurrently.
# Extra jobs stay in a strict FIFO queue, including local designed rendering.
# 默认 2 保持历史行为；起独立 35B 副本后可经 PPT_MAX_CONCURRENT_JOBS 调到 4。
# 注意与 PPT_COMPOSITION_PARALLEL 的乘积不要超过 PPT 网关容量池
# (MODEL_MAX_CONCURRENCY)，否则多出来的请求只是在闸门里排队。
def _max_concurrent_jobs() -> int:
    return max(1, int(getattr(settings, "PPT_MAX_CONCURRENT_JOBS", 2)))


_MAX_CONCURRENT_JOBS = _max_concurrent_jobs()
_SLOTS = threading.BoundedSemaphore(_MAX_CONCURRENT_JOBS)
_QUEUE_LOCK = threading.RLock()


def _queue_limit() -> int:
    """排队深度上限：50 人同时提交时不让 FIFO 无限堆积。"""
    return max(1, int(getattr(settings, "PPT_QUEUE_MAX", 50)))


def _queue_timeout() -> float:
    """排队最长等待秒数；0 表示不限制。"""
    return max(0, int(getattr(settings, "PPT_QUEUE_TIMEOUT", 1800)))


# 作业实际耗时（从被准入到释放槽位）的滑动窗口，用于给排队用户估算等待。
_STARTED_AT: Dict[str, float] = {}
_DURATIONS: Deque[float] = deque(maxlen=20)
_REAPER_STARTED = False


@dataclass
class _QueuedJob:
    doc_id: str
    user_id: str
    message: str
    history: Optional[List[Any]]
    local: bool = False
    enqueued_at: float = field(default_factory=time.monotonic)


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
    logger.info("[PPT 任务耗时] 排队=%.1fs job=%s 本地=%s",
                time.monotonic() - item.enqueued_at, item.doc_id, item.local)
    _ACTIVE_DOCS.add(item.doc_id)
    _STARTED_AT[item.doc_id] = time.monotonic()
    _update_job(
        item.doc_id,
        job_status="pending",
        job_phase="submitting",
        job_stage_detail="排队结束，正在初始化生成环境…",
        job_error="",
        job_question="",
        job_current_page=0,
        job_total_pages=0,
        job_cancel_requested=False,
        job_started_at=now_local(),
        job_progress_at=now_local(),
        job_finished_at=None,
    )
    runner = (LocalRenderJobRunner(item.doc_id, item.user_id) if item.local else
              PPTAgentJobRunner(item.doc_id, item.user_id, item.message,
                                history=item.history))
    thread = threading.Thread(
        target=runner.run,
        name=f"ppt-{'local' if item.local else 'job'}-{item.doc_id[:8]}",
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


def _expire_queued_locked() -> list[_QueuedJob]:
    """摘掉等待过久的排队任务（调用方必须持有 _QUEUE_LOCK）。"""
    timeout = _queue_timeout()
    if timeout <= 0:
        return []
    now = time.monotonic()
    expired = [item for item in _QUEUE if now - item.enqueued_at >= timeout]
    for item in expired:
        _QUEUE.remove(item)
        if _USER_JOBS.get(item.user_id) == item.doc_id:
            _USER_JOBS.pop(item.user_id, None)
    return expired


def _reap_loop() -> None:
    while True:
        time.sleep(5)
        try:
            with _QUEUE_LOCK:
                expired = _expire_queued_locked()
            for item in expired:
                waited = time.monotonic() - item.enqueued_at
                _update_job(
                    item.doc_id,
                    job_cancel_requested=True,
                    job_status="cancelled",
                    job_phase="cancelled",
                    job_error="排队等待超时，请稍后重试",
                    job_finished_at=now_local(),
                    job_progress_at=now_local(),
                )
                logger.warning("[PPT 任务耗时] 排队超时取消 job=%s 等待=%.1fs",
                               item.doc_id, waited)
        except Exception:
            logger.exception("PPT 排队超时清理失败")


def _ensure_reaper() -> None:
    """懒启动守护线程；pytest 不提交任务时不会产生额外活动。"""
    global _REAPER_STARTED
    if _REAPER_STARTED:
        return
    with _QUEUE_LOCK:
        if _REAPER_STARTED:
            return
        _REAPER_STARTED = True
    threading.Thread(target=_reap_loop, name="ppt-queue-reaper",
                     daemon=True).start()


def queue_stats() -> Dict[str, Any]:
    """健康检查 / 排障用快照。"""
    with _QUEUE_LOCK:
        durations = list(_DURATIONS)
        return {
            "max_concurrent_jobs": _MAX_CONCURRENT_JOBS,
            "active_jobs": len(_ACTIVE_DOCS),
            "queued_jobs": len(_QUEUE),
            "queue_limit": _queue_limit(),
            "queue_timeout_seconds": _queue_timeout(),
            "avg_job_seconds": (round(sum(durations) / len(durations), 1)
                                if durations else None),
        }


def _on_runner_finished(doc_id: str, user_id: str) -> None:
    """Release capacity/user ownership and immediately admit the next FIFO job."""
    with _QUEUE_LOCK:
        if doc_id not in _ACTIVE_DOCS:
            return
        _ACTIVE_DOCS.discard(doc_id)
        started = _STARTED_AT.pop(doc_id, None)
        if started is not None:
            _DURATIONS.append(time.monotonic() - started)
        if _USER_JOBS.get(user_id) == doc_id:
            _USER_JOBS.pop(user_id, None)
        _SLOTS.release()
        _dispatch_locked()


def _bind_model_user(user_id: str) -> None:
    """把认证用户带进后台线程的模型准入上下文。

    ContextVar 不会跨线程传播；不绑定的话每个 PPT 模型请求都会被
    _ModelCapacity 当成不同的 unscoped 用户，per-user 限流和轮询公平
    对后台 PPT 完全失效，一个作业就能占满全部 background 名额。
    """
    from app.infrastructure.ai.qwen import set_model_request_user
    set_model_request_user(user_id)


class PPTAgentJobRunner(_core.PPTAgentJobRunner):
    """Core runner plus queue-slot release/dispatch in a guaranteed finally block."""

    def run(self) -> None:
        _bind_model_user(self.user_id)
        try:
            super().run()
        finally:
            _on_runner_finished(self.doc_id, self.user_id)


class LocalRenderJobRunner(_core.LocalRenderJobRunner):
    """Local designed rendering shares the same bounded admission queue."""

    def __init__(self, doc_id: str, user_id: str) -> None:
        super().__init__(doc_id)
        self.user_id = user_id

    def run(self) -> None:
        _bind_model_user(self.user_id)
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
        limit = _queue_limit()
        if len(_QUEUE) >= limit:
            # 50 人同时提交时，与其让第 51 个人静默等两小时，不如立即
            # 明确拒绝；位置与预计等待由 job_status / queue_stats 暴露。
            raise ConflictError(
                f"当前已有 {len(_QUEUE)} 个生成任务在排队（上限 {limit}），"
                "请稍后再试"
            )
        _ensure_reaper()

        item = _QueuedJob(doc_id, user_id, message or "", history,
                          local=_core.uses_local_renderer(doc_id))
        _USER_JOBS[user_id] = doc_id

        # Reset stale state before either starting or queueing this document.
        _update_job(
            doc_id,
            job_status="pending",
            job_phase="queued",
            job_stage_detail="任务已提交…",
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
        _update_job(doc_id, job_stage_detail=f"排队中（第 {position} 位）",
                    job_progress_at=now_local())
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
        queue_depth = len(_QUEUE)
        active_jobs = len(_ACTIVE_DOCS)
        durations = list(_DURATIONS)
    result = _core.job_status(doc)
    result["queue_position"] = position
    result["queue_depth"] = queue_depth
    result["active_jobs"] = active_jobs
    # 队列按 _MAX_CONCURRENT_JOBS 个一批放行；每批耗时用最近完成作业的
    # 实测均值。没有历史样本时只暴露位置与人数，不编造等待时间。
    avg = sum(durations) / len(durations) if durations else None
    if position and position > 0 and avg is not None:
        waves = (position - 1) // _MAX_CONCURRENT_JOBS + 1
        result["estimated_wait_seconds"] = round(waves * avg, 1)
    else:
        result["estimated_wait_seconds"] = None
    if position is not None and position > 0:
        # A queued job has not started, so the core stall timer must not age it out.
        result["status"] = "pending"
        result["phase"] = "queued"
        result["elapsed_seconds"] = 0.0
        result["estimated_remaining"] = None
        wait = result.get("estimated_wait_seconds")
        if wait:
            minutes = max(1, round(wait / 60))
            result["stage_detail"] = (f"排队中（第 {position} 位，"
                                      f"预计等待约 {minutes} 分钟）")
        else:
            result["stage_detail"] = f"排队中（第 {position} 位）"
    return result


def __getattr__(name: str):
    """Keep the wrapper drop-in compatible with the core module."""
    return getattr(_core, name)
