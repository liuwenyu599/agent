"""PPT 细粒度阶段进度（stage_detail）的单测。

覆盖三层：
1. ``job_progress`` 回报器：绑定/解绑、未绑定 no-op、回报器异常不外抛、超长截断；
2. ``agent_job.job_status``：透出 stage_detail，且缺字段的老对象不炸（后端兼容）；
3. ``queued_agent_job.job_status``：排队态把位次写进 stage_detail。
"""
from types import SimpleNamespace

import pytest

from app.application.ppt import job_progress


# ---------------- job_progress ----------------

def test_report_is_noop_when_unbound():
    # 非 job 场景（同步导出、单测）没有绑定回报器，report 必须静默
    job_progress.report("正在做一件无人监听的事")


def test_bind_collects_and_unbind_stops():
    seen = []
    token = job_progress.bind(seen.append)
    try:
        job_progress.report("正在设计页面构图（第 2/5 批）…")
    finally:
        job_progress.unbind(token)
    job_progress.report("解绑后不应记录")
    assert seen == ["正在设计页面构图（第 2/5 批）…"]


def test_reporter_exception_is_swallowed():
    def boom(_detail: str) -> None:
        raise RuntimeError("数据库抽风")

    token = job_progress.bind(boom)
    try:
        # 回报器异常绝不能把生成主链路拖垮
        job_progress.report("正在排版渲染页面…")
    finally:
        job_progress.unbind(token)


def test_report_truncates_to_column_width():
    seen = []
    token = job_progress.bind(seen.append)
    try:
        job_progress.report("很" * 300)
    finally:
        job_progress.unbind(token)
    assert len(seen) == 1 and len(seen[0]) == 120


def test_empty_detail_is_ignored():
    seen = []
    token = job_progress.bind(seen.append)
    try:
        job_progress.report("")
    finally:
        job_progress.unbind(token)
    assert seen == []


# ---------------- agent_job.job_status ----------------

def _doc(**overrides):
    base = dict(
        id="doc-1", job_status="running", job_phase="designing",
        job_stage_detail="正在设计页面构图（第 2/5 批）…",
        job_total_pages=12, job_current_page=3,
        job_started_at=None, job_progress_at=None,
        job_error="", job_question="", job_renderer="local",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_job_status_exposes_stage_detail():
    from app.application.ppt import agent_job

    result = agent_job.job_status(_doc())
    assert result["stage_detail"] == "正在设计页面构图（第 2/5 批）…"
    assert result["phase"] == "designing"


def test_job_status_tolerates_missing_stage_field():
    """老对象/其它构造路径没有 job_stage_detail 时不能 AttributeError。"""
    from app.application.ppt import agent_job

    doc = _doc()
    del doc.job_stage_detail
    result = agent_job.job_status(doc)
    assert result["stage_detail"] == ""


# ---------------- queued_agent_job.job_status ----------------

@pytest.mark.parametrize("wait_seconds,expect", [
    (None, "第 2 位"),
    (185.0, "预计等待约 3 分钟"),
])
def test_queued_status_detail_reports_position(monkeypatch, wait_seconds, expect):
    from app.application.ppt import queued_agent_job

    doc = _doc(job_status="pending", job_phase="queued", job_stage_detail="任务已提交…")
    monkeypatch.setattr(queued_agent_job, "_queue_position_locked", lambda _doc_id: 2)
    # 直接控制均值来源：有样本时才会给出预计等待
    monkeypatch.setattr(queued_agent_job, "_DURATIONS",
                        [wait_seconds] if wait_seconds else [])
    monkeypatch.setattr(queued_agent_job, "_ACTIVE_DOCS", set())
    monkeypatch.setattr(queued_agent_job, "_QUEUE", [])

    result = queued_agent_job.job_status(doc)
    assert result["status"] == "pending"
    assert result["phase"] == "queued"
    assert "排队中" in result["stage_detail"]
    assert expect in result["stage_detail"]
