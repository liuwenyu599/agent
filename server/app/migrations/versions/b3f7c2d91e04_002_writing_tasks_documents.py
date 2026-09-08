"""002_writing_tasks_documents

新增：写作任务、我的文档与版本、文号序号、训练闭环相关表。

Revision ID: b3f7c2d91e04
Revises: a112a03b86f2
Create Date: 2026-09-08

"""
from alembic import op
import sqlalchemy as sa

revision = 'b3f7c2d91e04'
down_revision = "a112a03b86f2"
branch_labels = None
depends_on = None


def _ts_columns():
    return [
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
    ]


def upgrade() -> None:
    # ---- 文号序号 ----
    op.create_table(
        'doc_number_sequences',
        sa.Column('daizi', sa.String(length=20), nullable=False),
        sa.Column('year', sa.Integer(), nullable=False),
        sa.Column('next_seq', sa.Integer(), nullable=False),
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('daizi', 'year', name='uq_docnum_daizi_year'),
    )

    # ---- 我的文档 + 版本 ----
    op.create_table(
        'my_documents',
        sa.Column('user_id', sa.String(length=36), nullable=False),
        sa.Column('title', sa.String(length=300), nullable=False),
        sa.Column('doc_type', sa.String(length=50), nullable=True),
        sa.Column('document_number', sa.String(length=100), nullable=True),
        sa.Column('document_date', sa.String(length=50), nullable=True),
        sa.Column('current_version', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('session_id', sa.String(length=36), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_my_documents_user_id', 'my_documents', ['user_id'])
    op.create_table(
        'my_document_versions',
        sa.Column('document_id', sa.String(length=36), nullable=False),
        sa.Column('version_no', sa.Integer(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('quality', sa.JSON(), nullable=True),
        sa.Column('content_check', sa.JSON(), nullable=True),
        sa.Column('note', sa.String(length=500), nullable=True),
        sa.Column('created_by', sa.String(length=36), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(['document_id'], ['my_documents.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_my_document_versions_document_id',
                    'my_document_versions', ['document_id'])

    # ---- 写作任务 ----
    op.create_table(
        'writing_tasks',
        sa.Column('user_id', sa.String(length=36), nullable=False),
        sa.Column('session_id', sa.String(length=36), nullable=True),
        sa.Column('document_id', sa.String(length=36), nullable=True),
        sa.Column('context', sa.JSON(), nullable=False),
        sa.Column('current_content', sa.Text(), nullable=False),
        sa.Column('ai_draft', sa.Text(), nullable=False),
        sa.Column('version_no', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_writing_tasks_user_id', 'writing_tasks', ['user_id'])

    # ---- 训练闭环 ----
    op.create_table(
        'data_assets',
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('source_type', sa.String(length=20), nullable=False),
        sa.Column('file_path', sa.String(length=500), nullable=True),
        sa.Column('file_type', sa.String(length=20), nullable=True),
        sa.Column('title', sa.String(length=300), nullable=True),
        sa.Column('doc_type', sa.String(length=50), nullable=True),
        sa.Column('content', sa.Text(), nullable=True),
        sa.Column('char_count', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('sample_generated', sa.Integer(), nullable=False),
        sa.Column('extra', sa.JSON(), nullable=True),
        sa.Column('created_by', sa.String(length=36), nullable=True),
        *_ts_columns(),
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'training_samples',
        sa.Column('instruction', sa.Text(), nullable=False),
        sa.Column('input', sa.Text(), nullable=True),
        sa.Column('output', sa.Text(), nullable=False),
        sa.Column('draft', sa.Text(), nullable=True),
        sa.Column('source', sa.String(length=30), nullable=False),
        sa.Column('asset_id', sa.String(length=36), nullable=True),
        sa.Column('session_id', sa.String(length=36), nullable=True),
        sa.Column('biz_type', sa.String(length=50), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('reviewed_by', sa.String(length=36), nullable=True),
        sa.Column('created_by', sa.String(length=36), nullable=True),
        *_ts_columns(),
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'datasets',
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_by', sa.String(length=36), nullable=True),
        *_ts_columns(),
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'dataset_versions',
        sa.Column('dataset_id', sa.String(length=36), nullable=False),
        sa.Column('version', sa.String(length=50), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('stats', sa.JSON(), nullable=True),
        sa.Column('check_report', sa.JSON(), nullable=True),
        sa.Column('sample_ids', sa.JSON(), nullable=True),
        sa.Column('train_jsonl', sa.String(length=500), nullable=True),
        sa.Column('val_jsonl', sa.String(length=500), nullable=True),
        sa.Column('created_by', sa.String(length=36), nullable=True),
        *_ts_columns(),
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'training_jobs',
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('dataset_version_id', sa.String(length=36), nullable=True),
        sa.Column('base_model', sa.String(length=200), nullable=True),
        sa.Column('method', sa.String(length=20), nullable=False),
        sa.Column('params', sa.JSON(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('pid', sa.Integer(), nullable=True),
        sa.Column('log_path', sa.String(length=500), nullable=True),
        sa.Column('output_dir', sa.String(length=500), nullable=True),
        sa.Column('resume_from', sa.String(length=500), nullable=True),
        sa.Column('train_loss', sa.Float(), nullable=True),
        sa.Column('val_loss', sa.Float(), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('model_version_id', sa.String(length=36), nullable=True),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('finished_at', sa.DateTime(), nullable=True),
        sa.Column('created_by', sa.String(length=36), nullable=True),
        *_ts_columns(),
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'trained_model_versions',
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('base_model', sa.String(length=200), nullable=True),
        sa.Column('job_id', sa.String(length=36), nullable=True),
        sa.Column('parent_id', sa.String(length=36), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('adapter_path', sa.String(length=500), nullable=True),
        sa.Column('metrics', sa.JSON(), nullable=True),
        *_ts_columns(),
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    for t in ('trained_model_versions', 'training_jobs', 'dataset_versions',
              'datasets', 'training_samples', 'data_assets',
              'writing_tasks', 'my_document_versions', 'my_documents',
              'doc_number_sequences'):
        op.drop_table(t)
