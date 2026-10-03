"""Operational monitoring primitives used by the root /metrics and /ready endpoints."""
from __future__ import annotations

import time
from pathlib import Path

from fastapi import Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

from app.core.config import settings
from app.infrastructure.database import engine

HTTP_REQUESTS = Counter(
    "judicial_ai_http_requests_total",
    "HTTP requests handled by the API",
    ("method", "status"),
)
HTTP_LATENCY = Histogram(
    "judicial_ai_http_request_duration_seconds",
    "HTTP request duration in seconds",
    ("method",),
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 180, 300),
)


async def prometheus_middleware(request: Request, call_next):
    started = time.monotonic()
    status = "500"
    try:
        response = await call_next(request)
        status = str(response.status_code)
        return response
    finally:
        # Avoid self-scrape feedback inflating the service request counters.
        if request.url.path != "/metrics":
            HTTP_REQUESTS.labels(request.method, status).inc()
            HTTP_LATENCY.labels(request.method).observe(time.monotonic() - started)


def metrics_response() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


def readiness() -> tuple[bool, dict]:
    checks: dict[str, dict] = {}
    ok = True

    try:
        with engine.connect() as conn:
            conn.exec_driver_sql("SELECT 1")
        checks["database"] = {"ok": True}
    except Exception as exc:  # pragma: no cover - depends on external DB state
        ok = False
        checks["database"] = {"ok": False, "error": str(exc)[:200]}

    vector_dir = Path(settings.vector_index_dir)
    index_file = vector_dir / "index.faiss"
    meta_file = vector_dir / "metadata.pkl"
    pair_consistent = index_file.exists() == meta_file.exists()
    if not pair_consistent:
        ok = False
    checks["vector_index"] = {
        "ok": pair_consistent,
        "present": index_file.exists() and meta_file.exists(),
    }

    return ok, checks
