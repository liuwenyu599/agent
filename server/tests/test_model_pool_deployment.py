"""Repository-level acceptance contract for backlog item 8.

Hardware activation is a production operation, but the repo must retain a safe launcher,
explicit endpoint pools and a postcheck that probes every configured replica.
"""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "deploy"


def _text(name: str) -> str:
    return (DEPLOY / name).read_text(encoding="utf-8")


def test_ascend_launcher_is_dry_run_by_default_and_whitelists_known_spares():
    source = _text("ascend-model-pool.sh")
    assert "APPLY=${APPLY:-0}" in source
    assert "KNOWN_SPARE_DEVICES=${KNOWN_SPARE_DEVICES:-0,1,5,6,7}" in source
    assert "contains_only_spares" in source
    assert "check_port_free" in source
    assert 'if [[ "$APPLY" != "1" ]]' in source


def test_launcher_has_separate_same_model_profiles_and_ports():
    source = _text("ascend-model-pool.sh")
    assert "second-14b" in source
    assert "ppt-replica" in source
    assert "TEXT_REPLICA_PORT=${TEXT_REPLICA_PORT:-8005}" in source
    assert "PPT_REPLICA_PORT=${PPT_REPLICA_PORT:-8006}" in source
    assert "Qwen2.5-14B-Instruct" in source
    assert "DeepPresenter-9B" in source


def test_model_pool_env_keeps_models_in_separate_endpoint_pools():
    env = _text("model-pool.env.example")
    assert (
        "MODEL_SERVICE_URLS=http://10.128.85.133:8003/v1,"
        "http://10.128.85.133:8005/v1"
    ) in env
    assert (
        "PPT_MODEL_URLS=http://10.128.85.133:8004/v1,"
        "http://10.128.85.133:8006/v1"
    ) in env
    # The example must never mix the PPT endpoint into the text pool or vice versa.
    model_pool_line = next(x for x in env.splitlines() if x.startswith("MODEL_SERVICE_URLS="))
    ppt_pool_line = next(x for x in env.splitlines() if x.startswith("PPT_MODEL_URLS="))
    assert ":8004/" not in model_pool_line and ":8006/" not in model_pool_line
    assert ":8003/" not in ppt_pool_line and ":8005/" not in ppt_pool_line


def test_postcheck_probes_effective_url_pools_not_only_fixed_ports():
    source = _text("postcheck-production.sh")
    assert "probe_pool MODEL_SERVICE_URLS MODEL_SERVICE_URL" in source
    assert "probe_pool PPT_MODEL_URLS PPT_MODEL_URL" in source
    assert '"${url%/}/models"' in source


def test_runbook_requires_health_before_adding_replica_to_pool():
    doc = _text("MODEL_POOL_DEPLOYMENT.md")
    assert "只有 `/v1/models` 通过后" in doc
    assert "负载/故障切换检查" in doc
    assert "移除新 URL" in doc
