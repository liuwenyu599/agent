from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_health_ready_and_metrics_are_live():
    client = TestClient(create_app())
    assert client.get("/health").status_code == 200
    ready = client.get("/ready")
    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"
    metrics = client.get("/metrics")
    assert metrics.status_code == 200
    assert "judicial_ai_http_requests_total" in metrics.text
    assert "judicial_ai_http_request_duration_seconds" in metrics.text


def test_postcheck_requires_backup_and_restore_evidence():
    text = (REPO_ROOT / "deploy" / "postcheck-production.sh").read_text(encoding="utf-8")
    assert "/ready" in text
    assert "/metrics" in text
    assert "judicial-ai-backup.timer" in text
    assert ".last-restore-drill" in text
    assert "vector_index.tar.gz" in text


def test_daily_timer_is_persistent_and_backup_retention_is_14_days():
    installer = (REPO_ROOT / "deploy" / "install-backup-timer.sh").read_text(encoding="utf-8")
    backup = (REPO_ROOT / "deploy" / "backup-production.sh").read_text(encoding="utf-8")
    assert "OnCalendar=*-*-* 02:30:00" in installer
    assert "Persistent=true" in installer
    assert 'BACKUP_RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"' in backup


def test_prometheus_assets_cover_down_errors_and_latency():
    config = (REPO_ROOT / "deploy" / "prometheus.yml.example").read_text(encoding="utf-8")
    alerts = (REPO_ROOT / "deploy" / "judicial-ai-alerts.yml").read_text(encoding="utf-8")
    assert "metrics_path: /metrics" in config
    assert "JudicialAIAPIDown" in alerts
    assert "JudicialAIHigh5xxRate" in alerts
    assert "JudicialAIHighP95Latency" in alerts
    assert "judicial_ai_http_requests_total" in alerts
    assert "judicial_ai_http_request_duration_seconds_bucket" in alerts
