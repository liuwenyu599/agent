"""Regression contract for the retired approval module.

Approval was intentionally removed from the product. These tests prevent a stale
router, permission or ORM import from quietly re-introducing the feature.
"""
from pathlib import Path

from app.domain.identity.roles import ALL_PERMISSIONS
from app.main import create_app


RETIRED_PERMISSIONS = {
    "doc:submit",
    "doc:review_dept",
    "doc:review_office",
    "doc:approve",
    "doc:seal",
    "doc:distribute",
    "doc:terminate",
}


def test_approval_api_is_not_mounted():
    # FastAPI/Starlette may expose internal router wrapper objects without a
    # ``path`` attribute. Only concrete path-bearing routes matter here.
    paths = {
        path
        for route in create_app().routes
        if (path := getattr(route, "path", None)) is not None
    }
    assert not any(path.startswith("/api/v1/approvals") for path in paths)


def test_approval_permissions_are_retired():
    assert RETIRED_PERMISSIONS.isdisjoint(ALL_PERMISSIONS)
    # Independent document capabilities remain available.
    assert {"doc:number", "doc:archive", "doc:export"}.issubset(ALL_PERMISSIONS)


def test_runtime_has_no_approval_packages_or_orm_registration():
    app_root = Path(__file__).parents[1] / "app"
    assert not (app_root / "interfaces" / "approvals.py").exists()
    assert not (app_root / "application" / "approval").exists()
    assert not (app_root / "domain" / "approval").exists()
    assert not (app_root / "infrastructure" / "database" / "models" / "approval.py").exists()

    model_registry = (app_root / "infrastructure" / "database" / "models" / "__init__.py").read_text(
        encoding="utf-8"
    )
    assert "approval" not in model_registry.lower()


def test_dashboard_contains_no_approval_contract():
    app_root = Path(__file__).parents[1] / "app"
    source = (app_root / "interfaces" / "dashboard.py").read_text(encoding="utf-8")
    forbidden = (
        "ApprovalInstanceModel",
        "app.domain.approval",
        "doc_pending",
        "doc_approved",
        "todo_count",
        "doc:review_dept",
        "doc:review_office",
        "doc:approve",
        "doc:seal",
    )
    for token in forbidden:
        assert token not in source


def test_drop_migration_follows_current_head_and_targets_only_approval_tables():
    app_root = Path(__file__).parents[1] / "app"
    migration = app_root / "migrations" / "versions" / "013_remove_approval_module.py"
    source = migration.read_text(encoding="utf-8")
    assert 'down_revision = "012_v37_ai_response_feedback"' in source
    assert '"approval_actions"' in source
    assert '"approval_instances"' in source
    assert 'op.drop_table("approval_actions")' in source
    assert 'op.drop_table("approval_instances")' in source
    assert 'op.drop_table("my_documents")' not in source
    assert 'op.drop_table("doc_numbers")' not in source
