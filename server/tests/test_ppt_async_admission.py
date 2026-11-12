"""Regression tests for PPT async admission, queue fairness and optional composition parallelism.

Measured on the production 35B endpoint (2026-11-12): two long PPT composition
requests in flight degrade interactive writing TTFT from 2.47s to 9.39s. These
tests lock in the guard rails that keep that from happening.
"""
import json
import threading
import time
from types import SimpleNamespace

import pytest

from app.application.ppt import agent_job
from app.application.ppt import page_authoring
from app.application.ppt import ppt_admission
from app.core.config import settings
from app.core.exceptions import ConflictError


# ---------------------------------------------------------------------------
# 模型侧准入闸门
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_gate():
    ppt_admission.configure()
    yield
    ppt_admission.configure()


def test_ppt_model_slot_bounds_inflight_requests(_reset_gate, monkeypatch):
    monkeypatch.setattr(settings, "MODEL_MAX_CONCURRENCY", 4)
    monkeypatch.setattr(settings, "PPT_MODEL_MAX_CONCURRENCY", 2)
    assert ppt_admission.configure() == 2

    lock = threading.Lock()
    state = {"active": 0, "peak": 0}

    def worker():
        with ppt_admission.ppt_model_slot():
            with lock:
                state["active"] += 1
                state["peak"] = max(state["peak"], state["active"])
            time.sleep(0.08)
            with lock:
                state["active"] -= 1

    threads = [threading.Thread(target=worker) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert state["peak"] == 2
    snap = ppt_admission.stats()
    assert snap["limit"] == 2 and snap["inflight"] == 0
    assert snap["total_waits"] == 6 and snap["avg_wait_seconds"] > 0


def test_ppt_gate_always_leaves_one_model_slot_for_writing(_reset_gate, monkeypatch):
    monkeypatch.setattr(settings, "MODEL_MAX_CONCURRENCY", 3)
    monkeypatch.setattr(settings, "PPT_MODEL_MAX_CONCURRENCY", 9)
    assert ppt_admission.configure() == 2

    monkeypatch.setattr(settings, "MODEL_MAX_CONCURRENCY", 1)
    assert ppt_admission.configure() == 1


def test_composition_parallel_defaults_to_serial_and_is_capped(_reset_gate, monkeypatch):
    monkeypatch.setattr(settings, "MODEL_MAX_CONCURRENCY", 4)
    monkeypatch.setattr(settings, "PPT_MODEL_MAX_CONCURRENCY", 2)
    ppt_admission.configure()
    monkeypatch.setattr(settings, "PPT_COMPOSITION_PARALLEL", 1)
    assert ppt_admission.composition_parallel() == 1
    monkeypatch.setattr(settings, "PPT_COMPOSITION_PARALLEL", 8)
    # 永远不超过闸门总量，避免并行构图反过来吃满模型池。
    assert ppt_admission.composition_parallel() == 2


def test_ppt_model_slot_timeout_raises_clear_error(_reset_gate, monkeypatch):
    monkeypatch.setattr(settings, "PPT_MODEL_MAX_CONCURRENCY", 1)
    ppt_admission.configure(1)
    with ppt_admission.ppt_model_slot():
        with pytest.raises(Exception) as exc:
            with ppt_admission.ppt_model_slot(timeout=0.05):
                pass
        assert "排队超时" in str(exc.value)


# ---------------------------------------------------------------------------
# 首轮构图：默认串行 / 显式开启并行
# ---------------------------------------------------------------------------

class _ConcurrentAssistant:
    """Thread-safe assistant that records how many calls overlap."""

    def __init__(self, pages=12):
        self.pages = pages
        self.lock = threading.Lock()
        self.active = 0
        self.peak = 0
        self.calls = 0

    def complete(self, messages, **kwargs):
        with self.lock:
            self.active += 1
            self.calls += 1
            self.peak = max(self.peak, self.active)
        try:
            time.sleep(0.06)
            regions = [
                {"ref": "title", "x": .08, "y": .05, "w": .84, "h": .12},
                {"ref": "point:0", "x": .08, "y": .25, "w": .38, "h": .50},
                {"ref": "point:1", "x": .54, "y": .25, "w": .38, "h": .50},
            ]
            payload = {"pages": [
                {"page": i, "regions": regions, "visuals": []}
                for i in range(1, self.pages + 1)
            ]}
            return json.dumps(payload, ensure_ascii=False)
        finally:
            with self.lock:
                self.active -= 1


def _twelve_content_pages():
    return {"title": "并发测试", "slides": [
        {"type": "content", "title": f"第{i}页", "points": ["要点一", "要点二"]}
        for i in range(1, 13)
    ]}


def test_composition_is_serial_by_default(_reset_gate, monkeypatch):
    monkeypatch.setattr(settings, "PPT_COMPOSITION_PARALLEL", 1)
    assistant = _ConcurrentAssistant()
    page_authoring.author_pages(_twelve_content_pages(), {}, assistant)
    assert assistant.peak == 1
    assert assistant.calls >= 3  # 12 页 / 每批 4 页 = 3 批


def test_composition_parallel_is_opt_in_and_stays_ordered(_reset_gate, monkeypatch):
    monkeypatch.setattr(settings, "PPT_COMPOSITION_PARALLEL", 2)
    ppt_admission.configure(2)
    assistant = _ConcurrentAssistant()
    result = page_authoring.author_pages(_twelve_content_pages(), {}, assistant)
    assert assistant.peak >= 2
    assert len(result["slides"]) == 12
    assert all("title" in slide for slide in result["slides"])


# ---------------------------------------------------------------------------
# FIFO 队列：上限 / 超时 / 等待估算
# ---------------------------------------------------------------------------

@pytest.fixture
def _isolated(monkeypatch):
    with agent_job._QUEUE_LOCK:
        agent_job._QUEUE.clear()
        agent_job._ACTIVE_DOCS.clear()
        agent_job._USER_JOBS.clear()
        agent_job._DURATIONS.clear()
        agent_job._STARTED_AT.clear()
        # 0 个槽位 => 所有提交都直接进 FIFO，不启动后台线程。
        agent_job._SLOTS = threading.BoundedSemaphore(0)
    monkeypatch.setattr(agent_job, "_update_job", lambda *a, **k: None)
    monkeypatch.setattr(agent_job, "_ensure_reaper", lambda: None)
    monkeypatch.setattr(agent_job._core, "uses_local_renderer", lambda _id: False)
    monkeypatch.setattr(settings, "PPT_QUEUE_MAX", 3)
    monkeypatch.setattr(settings, "PPT_QUEUE_TIMEOUT", 1800)
    yield
    with agent_job._QUEUE_LOCK:
        agent_job._QUEUE.clear()
        agent_job._ACTIVE_DOCS.clear()
        agent_job._USER_JOBS.clear()
        agent_job._DURATIONS.clear()
        agent_job._STARTED_AT.clear()
        agent_job._SLOTS = threading.BoundedSemaphore(2)


def test_queue_rejects_overflow_instead_of_accumulating_forever(_isolated):
    for i in range(3):
        row = agent_job.submit_job(f"doc-{i}", f"user-{i}")
        assert row["queue_position"] == i + 1
    with pytest.raises(ConflictError) as exc:
        agent_job.submit_job("doc-overflow", "user-overflow")
    assert "上限 3" in exc.value.detail
    assert "user-overflow" not in agent_job._USER_JOBS
    assert len(agent_job._QUEUE) == 3


def test_stale_queued_jobs_expire_without_leaking_user_ownership(
        _isolated, monkeypatch):
    monkeypatch.setattr(settings, "PPT_QUEUE_TIMEOUT", 60)
    agent_job.submit_job("doc-old", "user-old")
    with agent_job._QUEUE_LOCK:
        agent_job._QUEUE[0].enqueued_at = time.monotonic() - 120
        expired = agent_job._expire_queued_locked()
    assert [item.doc_id for item in expired] == ["doc-old"]
    assert not agent_job._QUEUE
    assert "user-old" not in agent_job._USER_JOBS


def test_queue_stats_and_wait_estimate_use_measured_duration(
        _isolated, monkeypatch):
    agent_job.submit_job("doc-a", "user-a")
    agent_job.submit_job("doc-b", "user-b")
    agent_job.submit_job("doc-c", "user-c")
    with agent_job._QUEUE_LOCK:
        agent_job._DURATIONS.extend([300.0, 300.0])
    monkeypatch.setattr(agent_job._core, "job_status", lambda doc: {"status": "pending"})

    snap = agent_job.queue_stats()
    assert snap["queued_jobs"] == 3 and snap["queue_limit"] == 3
    assert snap["avg_job_seconds"] == 300.0

    status = agent_job.job_status(SimpleNamespace(id="doc-c"))
    assert status["queue_position"] == 3
    assert status["queue_depth"] == 3
    # 2 个并发槽位：位置 3 在第 2 波，约 2 × 300s。
    assert status["estimated_wait_seconds"] == 600.0


def test_gateway_failure_still_short_circuits_remaining_batches(
        _reset_gate, monkeypatch):
    """并行开关关闭时，历史「首批失败不再逐批等超时」语义不能丢。"""
    monkeypatch.setattr(settings, "PPT_COMPOSITION_PARALLEL", 1)

    class Dead:
        def __init__(self):
            self.calls = 0

        def complete(self, *_args, **_kwargs):
            self.calls += 1
            raise TimeoutError("model unavailable")

    assistant = Dead()
    warnings = []
    page_authoring.author_pages(_twelve_content_pages(), {}, assistant, warnings)
    assert assistant.calls == 1
    assert warnings and "模型构图未通过检查" in warnings[0]
