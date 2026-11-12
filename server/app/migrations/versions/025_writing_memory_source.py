"""writing_memories 增加 source 列：区分人工维护与自动风格蒸馏沉淀。

Revision ID: 025_writing_memory_source
Revises: 024_ppt_job_stage_detail

背景：风格自学习（app.application.writing.style_learning）会把蒸馏出的
用户风格画像写进 writing_memories（scope=personal）。加 source 列区分
manual（用户手工创建）/ auto（系统自动沉淀），自动条目同文种仅一条、
每次蒸馏覆盖更新；用户可在记忆管理中编辑、禁用或删除。
"""

import sqlalchemy as sa
from alembic import op

revision = "025_writing_memory_source"
down_revision = "024_ppt_job_stage_detail"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {c["name"] for c in inspector.get_columns("writing_memories")}
    if "source" in columns:
        return
    op.add_column("writing_memories",
                  sa.Column("source", sa.String(length=12),
                            nullable=False, server_default="manual"))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {c["name"] for c in inspector.get_columns("writing_memories")}
    if "source" not in columns:
        return
    op.drop_column("writing_memories", "source")
