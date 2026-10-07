"""Record the Alembic version-column capacity required by revision 014.

Revision ID: 015_widen_alembic_version
Revises: 014_template_format_profile_skeleton
"""
from alembic import op
from sqlalchemy import inspect

revision = "015_widen_alembic_version"
down_revision = "014_template_format_profile_skeleton"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    if connection.dialect.name != "postgresql":
        return
    version_col = next((column for column in inspect(connection).get_columns("alembic_version")
                        if column["name"] == "version_num"), None)
    length = getattr(version_col["type"], "length", None) if version_col else None
    if length is not None and length < 255:
        op.execute("ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(255)")


def downgrade() -> None:
    # 014 needs more than 32 characters, so shrinking would break the version table.
    pass
