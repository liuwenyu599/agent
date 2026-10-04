"""Add explicit template format profile and ordered body skeleton.

Revision ID: 014_template_format_profile_skeleton
Revises: 013_remove_approval_module
"""
from alembic import op
import sqlalchemy as sa

revision = "014_template_format_profile_skeleton"
down_revision = "013_remove_approval_module"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("writing_templates") as batch:
        batch.add_column(sa.Column("body_skeleton", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("format_profile", sa.String(40), nullable=False,
                                  server_default="GBT_RULES"))

    bind = op.get_bind()
    templates = sa.table(
        "writing_templates",
        sa.column("id", sa.String()),
        sa.column("content_template", sa.Text()),
        sa.column("structure", sa.JSON()),
        sa.column("body_skeleton", sa.JSON()),
    )
    rows = bind.execute(sa.select(
        templates.c.id, templates.c.content_template,
        templates.c.structure, templates.c.body_skeleton,
    )).mappings().all()
    for row in rows:
        if row["body_skeleton"]:
            continue
        skeleton = row["structure"] or []
        if not skeleton:
            skeleton = []
            for line in (row["content_template"] or "").splitlines():
                line = line.strip()
                if line:
                    skeleton.append({
                        "name": line.removeprefix("正文骨架：").strip()[:120],
                        "guide": "",
                    })
        skeleton = [
            item if isinstance(item, dict) else {"name": str(item), "guide": ""}
            for item in skeleton
        ]
        skeleton = [item for item in skeleton if item.get("name")]
        bind.execute(
            templates.update().where(templates.c.id == row["id"])
            .values(body_skeleton=skeleton)
        )


def downgrade() -> None:
    with op.batch_alter_table("writing_templates") as batch:
        batch.drop_column("format_profile")
        batch.drop_column("body_skeleton")
