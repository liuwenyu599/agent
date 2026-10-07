from types import SimpleNamespace
from unittest.mock import Mock

from app.migrations import version_capacity


def test_postgres_version_column_is_widened_before_long_revision(monkeypatch):
    connection = Mock(dialect=SimpleNamespace(name="postgresql"))
    inspector = Mock()
    inspector.has_table.return_value = True
    inspector.get_columns.return_value = [
        {"name": "version_num", "type": SimpleNamespace(length=32)},
    ]
    monkeypatch.setattr(version_capacity, "inspect", lambda _: inspector)

    assert version_capacity.ensure_version_capacity(connection) is True
    assert "VARCHAR(255)" in str(connection.execute.call_args.args[0])
    connection.commit.assert_called_once()


def test_already_wide_version_column_is_left_unchanged(monkeypatch):
    connection = Mock(dialect=SimpleNamespace(name="postgresql"))
    inspector = Mock()
    inspector.has_table.return_value = True
    inspector.get_columns.return_value = [
        {"name": "version_num", "type": SimpleNamespace(length=255)},
    ]
    monkeypatch.setattr(version_capacity, "inspect", lambda _: inspector)

    assert version_capacity.ensure_version_capacity(connection) is False
    connection.execute.assert_not_called()


def test_new_postgres_database_starts_with_wide_version_column(monkeypatch):
    connection = Mock(dialect=SimpleNamespace(name="postgresql"))
    inspector = Mock()
    inspector.has_table.return_value = False
    monkeypatch.setattr(version_capacity, "inspect", lambda _: inspector)

    assert version_capacity.ensure_version_capacity(connection) is True
    assert "CREATE TABLE alembic_version" in str(connection.execute.call_args.args[0])
    assert "VARCHAR(255)" in str(connection.execute.call_args.args[0])


def test_sqlite_does_not_run_postgres_ddl():
    connection = Mock(dialect=SimpleNamespace(name="sqlite"))
    assert version_capacity.ensure_version_capacity(connection) is False
    connection.execute.assert_not_called()
