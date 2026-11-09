"""Keep PPT template review state independent of editable description.

Revision ID: 022_ppt_template_sharing_status
Revises: 021_ppt_library_images
"""
from alembic import op
import sqlalchemy as sa

revision = "022_ppt_template_sharing_status"
down_revision = "021_ppt_library_images"
branch_labels = None
depends_on = None

# 回填条件单独成常量，便于在有数据的库上做纯 SQL 回归。
# 「待检查的共享模板」是上传共享模板时写入的固定描述；license_note 只是授权说明，
# 个人模板也允许填写，不能据此把私人模板标成待审核共享模板（会跨管理员可见）。
PUBLISHED_BACKFILL_WHERE = "is_official = TRUE"
PENDING_BACKFILL_WHERE = (
    "is_official = FALSE AND description = '待检查的共享模板'")


def upgrade() -> None:
    op.add_column("ppt_templates", sa.Column(
        "sharing_status", sa.String(12), nullable=False, server_default="private"))
    op.execute(sa.text(
        "UPDATE ppt_templates SET sharing_status = 'published' "
        f"WHERE {PUBLISHED_BACKFILL_WHERE}"))
    op.execute(sa.text(
        "UPDATE ppt_templates SET sharing_status = 'pending' "
        f"WHERE {PENDING_BACKFILL_WHERE}"))


def downgrade() -> None:
    op.drop_column("ppt_templates", "sharing_status")
