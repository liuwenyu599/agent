"""ppt_documents 增加 job_stage_detail：生成任务的细粒度阶段明细。

Revision ID: 024_ppt_job_stage_detail
Revises: 023_ppt_font_windows_native

背景：前端生成时只有粗粒度 job_phase（submitting/designing/...），用户
不知道后台在干什么。新增 job_stage_detail 存中文明细（如「正在设计
页面构图（第 2/5 批）」「正在生成页面预览 3/12」），由
app.application.ppt.job_progress 的 contextvar 回报器在渲染链路深处
回写，GET /ppt/jobs/{id}/status 原样透出，前端优先展示。
"""

import sqlalchemy as sa
from alembic import op

revision = "024_ppt_job_stage_detail"
down_revision = "023_ppt_font_windows_native"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {c["name"] for c in inspector.get_columns("ppt_documents")}
    if "job_stage_detail" not in columns:
        op.add_column(
            "ppt_documents",
            sa.Column("job_stage_detail", sa.String(120),
                      nullable=False, server_default=""),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {c["name"] for c in inspector.get_columns("ppt_documents")}
    if "job_stage_detail" in columns:
        op.drop_column("ppt_documents", "job_stage_detail")
