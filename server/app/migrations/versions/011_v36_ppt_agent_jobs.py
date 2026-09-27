"""v3.6 PPTAgent 异步生成任务：ppt_documents 增加 job_* 列

背景
----
PPTAgent（Gradio Host :7861）一次生成实测 5~15 分钟，远超同步 HTTP 请求的承受
范围（桌面端请求超时 120s / 反向代理 60s）。因此 PPT 生成为**异步 job**：
提交立即返回、前端轮询状态与逐页预览、完成后再下载。

为什么加列而不是新建表
----------------------
- 一个 job 天然归属一个 PPT 文档，且与文档 1:1（同一文档同时只会有一个进行中
  的 job），新建 jobs 表会引入一套并行的生命周期管理；
- 现有 ``ppt_documents`` 已有 user_id / outline / file_path / status，复用后
  前端"我的 PPT"列表与 job 状态天然一致，无需联表；
- 本次**只新增列**，不改动既有列语义，存量数据不受影响。

安全约束
--------
- 全部新列带 ``server_default`` / ``nullable``，保证 SQLite 存量表可直接加列；
- 用 inspector 防御：表或列不存在直接跳过，绝不因环境差异让迁移挂掉；
- ``job_status`` 默认空串 = "不是 job"，与历史文档（同步生成）自然区分；
- downgrade 完整移除本批列，与 upgrade 对称。

Revision ID: 011_v36_ppt_agent_jobs
Revises: 010_v35_local_time_migration
"""
from alembic import op
import sqlalchemy as sa

revision = "011_v36_ppt_agent_jobs"
down_revision = "010_v35_local_time_migration"
branch_labels = None
depends_on = None

# (列名, Column 定义) —— 与 PPTDocumentModel 的 job_* 字段一一对应
_NEW_COLUMNS = [
    ("job_status", sa.Column("job_status", sa.String(24), nullable=False,
                             server_default="")),
    ("job_phase", sa.Column("job_phase", sa.String(24), nullable=False,
                            server_default="")),
    ("job_total_pages", sa.Column("job_total_pages", sa.Integer(), nullable=False,
                                  server_default="0")),
    ("job_current_page", sa.Column("job_current_page", sa.Integer(), nullable=False,
                                   server_default="0")),
    ("job_error", sa.Column("job_error", sa.Text(), nullable=True)),
    ("job_question", sa.Column("job_question", sa.Text(), nullable=True)),
    ("job_renderer", sa.Column("job_renderer", sa.String(16), nullable=False,
                               server_default="")),
    ("job_event_id", sa.Column("job_event_id", sa.String(64), nullable=False,
                               server_default="")),
    ("job_cancel_requested", sa.Column("job_cancel_requested", sa.Boolean(),
                                       nullable=False, server_default=sa.false())),
    ("job_started_at", sa.Column("job_started_at", sa.DateTime(), nullable=True)),
    ("job_finished_at", sa.Column("job_finished_at", sa.DateTime(), nullable=True)),
    ("job_progress_at", sa.Column("job_progress_at", sa.DateTime(), nullable=True)),
]

_TABLE = "ppt_documents"


def _has_table(inspector, table: str) -> bool:
    try:
        return table in inspector.get_table_names()
    except Exception:
        return False


def _has_column(inspector, table: str, column: str) -> bool:
    try:
        return column in {c["name"] for c in inspector.get_columns(table)}
    except Exception:
        return False


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not _has_table(inspector, _TABLE):
        return
    for name, col in _NEW_COLUMNS:
        if not _has_column(inspector, _TABLE, name):
            op.add_column(_TABLE, col)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not _has_table(inspector, _TABLE):
        return
    for name, _col in reversed(_NEW_COLUMNS):
        if _has_column(inspector, _TABLE, name):
            op.drop_column(_TABLE, name)
