"""Public, licensed PPT image library.

Revision ID: 021_ppt_library_images
Revises: 020_writing_scoped_memory
"""
from alembic import op
import sqlalchemy as sa

revision = "021_ppt_library_images"
down_revision = "020_writing_scoped_memory"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ppt_templates", sa.Column("license_note", sa.String(500),
                                             nullable=False, server_default=""))
    op.create_table(
        "ppt_library_images",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("caption", sa.String(500), nullable=False),
        sa.Column("category", sa.String(50), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("file_path", sa.String(500), nullable=False),
        sa.Column("thumb_path", sa.String(500), nullable=False),
        sa.Column("file_size", sa.BigInteger(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("mime_type", sa.String(100), nullable=False),
        sa.Column("source", sa.String(200), nullable=False),
        sa.Column("license_note", sa.String(500), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_ppt_library_images_category", "ppt_library_images", ["category"])


def downgrade() -> None:
    op.drop_index("ix_ppt_library_images_category", table_name="ppt_library_images")
    op.drop_table("ppt_library_images")
    op.drop_column("ppt_templates", "license_note")
