"""Admission-control tests for the single-process PPT generation queue."""
import threading
import time
from collections import defaultdict
from types import SimpleNamespace

import pytest

from app.application.ppt import agent_job
from app.core.exceptions import ConflictError


@pytest.fixture(autouse=True)
def _isolated_queue(monkeypatch):
    """Keep queue tests deterministic and independent from real DB/network work."""
    updates = {}
    events = defaultdict(threading.Event)
    stop = threading.Event()
    with agent_job._QUEUE_LOCK:
        agent_job._QUEUE.clear()
        agent_job._ACTIVE_DOCS.clear()
        agent_job._USER_JOBS.clear()
        agent_job._SLOTS = threading.BoundedSemaphore(2)
    with agent_job._RUNNING_LOCK:
        agent_job._RUNNING.clear()
    monkeypatch.setattr(agent_job.settings, "PPT_AGENT_URL", "http://ppt-agent")

    def record(doc_id, **fields):
        updates.setdefault(doc_id, {}).update(fields)
        return None

    def block_core_runner(self):
        event = events[self.doc_id]
        while not stop.is_set() and not event.wait(timeout=0.05):
            pass

    monkeypatch.setattr(agent_job, "_update_job", record)
    monkeypatch.setattr(agent_job._core.PPTAgentJobRunner, "run", block_core_runner)
    yield {"updates": updates, "events": events}

    stop.set()
    for event in events.values():
        event.set()
    deadline = time.time() + 2
    while time.time() < deadline:
        with agent_job._QUEUE_LOCK:
            if not agent_job._ACTIVE_DOCS:
                break
        time.sleep(0.01)
    with agent_job._QUEUE_LOCK:
        agent_job._QUEUE.clear()
        agent_job._ACTIVE_DOCS.clear()
        agent_job._USER_JOBS.clear()
        agent_job._SLOTS = threading.BoundedSemaphore(2)
    with agent_job._RUNNING_LOCK:
        agent_job._RUNNING.clear()


def _wait_until(predicate, timeout=1.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def test_two_run_and_overflow_is_fifo(_isolated_queue):
    first = agent_job.submit_job("doc-a", "user-a")
    second = agent_job.submit_job("doc-b", "user-b")
    third = agent_job.submit_job("doc-c", "user-c")
    fourth = agent_job.submit_job("doc-d", "user-d")

    assert first["queue_position"] == 0
    assert second["queue_position"] == 0
    assert third["phase"] == "queued" and third["queue_position"] == 1
    assert fourth["phase"] == "queued" and fourth["queue_position"] == 2
    assert agent_job._ACTIVE_DOCS == {"doc-a", "doc-b"}
    assert [item.doc_id for item in agent_job._QUEUE] == ["doc-c", "doc-d"]

    # Finishing A must admit C before D.
    _isolated_queue["events"]["doc-a"].set()
    assert _wait_until(lambda: "doc-c" in agent_job._ACTIVE_DOCS)
    assert agent_job._ACTIVE_DOCS == {"doc-b", "doc-c"}
    assert [item.doc_id for item in agent_job._QUEUE] == ["doc-d"]
    assert agent_job._queue_position_locked("doc-d") == 1


def test_same_user_may_own_only_one_active_or_queued_job():
    agent_job.submit_job("doc-a", "same-user")
    with pytest.raises(ConflictError) as exc:
        agent_job.submit_job("doc-b", "same-user")
    assert exc.value.status_code == 409
    assert "同时只能有 1 个" in exc.value.detail


def test_queued_cancel_releases_user_and_compacts_positions(_isolated_queue):
    agent_job.submit_job("doc-a", "user-a")
    agent_job.submit_job("doc-b", "user-b")
    agent_job.submit_job("doc-c", "user-c")
    agent_job.submit_job("doc-d", "user-d")

    result = agent_job.cancel_job("doc-c")
    assert result["status"] == "cancelled"
    assert result["queue_position"] is None
    assert [item.doc_id for item in agent_job._QUEUE] == ["doc-d"]
    assert agent_job._queue_position_locked("doc-d") == 1
    assert "user-c" not in agent_job._USER_JOBS
    assert _isolated_queue["updates"]["doc-c"]["job_status"] == "cancelled"


def test_status_exposes_queue_position_without_stall_failure():
    agent_job.submit_job("doc-a", "user-a")
    agent_job.submit_job("doc-b", "user-b")
    agent_job.submit_job("doc-c", "user-c")

    doc = SimpleNamespace(
        id="doc-c",
        job_started_at=None,
        job_progress_at=None,
        job_status="pending",
        job_current_page=0,
        job_total_pages=0,
        job_phase="queued",
        job_error="",
        job_question="",
        job_renderer="",
    )
    status = agent_job.job_status(doc)
    assert status["status"] == "pending"
    assert status["phase"] == "queued"
    assert status["queue_position"] == 1
    assert status["elapsed_seconds"] == 0.0
