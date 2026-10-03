"""Shared pytest lifecycle guards.

PPT interface tests intentionally start daemon background workers. Item 7 added a
per-user admission guard, so allowing one test to end while its worker is still
running can make the next test (same developer token) correctly receive a conflict
and then observe an untouched document with status ``unknown``. That is test leakage,
not product behavior.
"""
from __future__ import annotations

import time

import pytest


@pytest.fixture(autouse=True)
def _drain_ppt_job_threads_between_interface_tests(request):
    yield
    if request.module.__name__ != "test_ppt_agent_jobs":
        return

    from app.application.ppt import agent_job

    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        with agent_job._RUNNING_LOCK:
            threads = [thread for thread in agent_job._RUNNING.values() if thread.is_alive()]
        if not threads:
            return
        for thread in threads:
            thread.join(timeout=0.1)
