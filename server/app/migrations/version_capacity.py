"""Prepare Alembic's own version table before long revision IDs are recorded."""
from sqlalchemy import inspect, text


def ensure_version_capacity(connection) -> bool:
    """Widen PostgreSQL's default VARCHAR(32) before revision 014 runs."""
    if connection.dialect.name != "postgresql":
        return False
    inspector = inspect(connection)
    if not inspector.has_table("alembic_version"):
        # A fresh database has no version table yet. Create it wide before
        # Alembic can create its default VARCHAR(32) during the same upgrade.
        connection.execute(text(
            "CREATE TABLE alembic_version ("
            "version_num VARCHAR(255) NOT NULL, "
            "CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num))"
        ))
        connection.commit()
        return True
    version_col = next(
        (col for col in inspector.get_columns("alembic_version")
         if col["name"] == "version_num"), None,
    )
    length = getattr(version_col["type"], "length", None) if version_col else None
    if length is not None and length < 255:
        connection.execute(text(
            "ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(255)"
        ))
        connection.commit()
        return True
    connection.commit()
    return False
