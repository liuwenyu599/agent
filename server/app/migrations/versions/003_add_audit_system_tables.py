"""003_add_audit_system_tables

补齐三张「有 ORM 模型、数据库里却没有实体表」的表：

* audit_logs      —— 审计日志（app.infrastructure.database.models.audit.AuditLogModel）
* model_versions  —— 模型版本（app.infrastructure.database.models.system.ModelVersionModel）
* system_configs  —— 系统配置（app.infrastructure.database.models.system.SystemConfigModel）

背景：这三个模型此前没有被 models/__init__.py / main.py 导入，
create_all 与 alembic autogenerate 都看不见它们，导致 repositories/audit.py
等调用时报 "no such table"。本次同时补齐了模型注册与本迁移脚本。

兼容性：
* 字段类型与 ORM 模型严格对齐，SQLite / PostgreSQL 均可执行；
* 幂等：建表与建索引前先通过 inspector 检查是否已存在，已存在则跳过
  （部分环境可能已经由 Base.metadata.create_all 建过）。

Revision ID: 003_add_audit_system_tables
Revises: b3f7c2d91e04
Create Date: 2026-09-16

"""
from alembic import op
import sqlalchemy as sa


revision = '003_add_audit_system_tables'
down_revision = 'b3f7c2d91e04'
branch_labels = None
depends_on = None


_TABLES = ('audit_logs', 'model_versions', 'system_configs')
_AUDIT_INDEXES = (
    ('ix_audit_logs_action', ['action']),
    ('ix_audit_logs_created_at', ['created_at']),
    ('ix_audit_logs_resource_id', ['resource_id']),
    ('ix_audit_logs_resource_type', ['resource_type']),
    ('ix_audit_logs_user_id', ['user_id']),
)


def _inspector():
    """获取当前连接上的 inspector；不可用时返回 None（退化为全部尝试创建）。"""
    try:
        return sa.inspect(op.get_bind())
    except Exception:  # noqa: BLE001
        return None


def _existing_tables() -> set:
    """返回当前库中已存在的目标表名集合（SQLite / PostgreSQL 通用）。"""
    insp = _inspector()
    if insp is None:
        return set()
    try:
        names = set(insp.get_table_names())
    except Exception:  # noqa: BLE001
        return set()
    return {t for t in _TABLES if t in names}


def _existing_indexes(table: str) -> set:
    """返回指定表上已存在的索引名集合。"""
    insp = _inspector()
    if insp is None:
        return set()
    try:
        return {ix.get('name') for ix in insp.get_indexes(table)}
    except Exception:  # noqa: BLE001
        return set()


def upgrade() -> None:
    existing = _existing_tables()

    # ---- 审计日志 ----
    if 'audit_logs' not in existing:
        op.create_table(
            'audit_logs',
            sa.Column('user_id', sa.String(length=36), nullable=True),
            sa.Column('action', sa.String(length=100), nullable=False),
            sa.Column('resource_type', sa.String(length=50), nullable=False),
            sa.Column('resource_id', sa.String(length=36), nullable=True),
            sa.Column('detail', sa.JSON(), nullable=True),
            sa.Column('result', sa.String(length=20), nullable=False),
            sa.Column('ip_address', sa.String(length=50), nullable=True),
            sa.Column('user_agent', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(),
                      server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
            sa.Column('id', sa.String(length=36), nullable=False),
            sa.PrimaryKeyConstraint('id'),
        )
    audit_indexes = _existing_indexes('audit_logs')
    todo_indexes = [(n, c) for n, c in _AUDIT_INDEXES if n not in audit_indexes]
    if todo_indexes:
        with op.batch_alter_table('audit_logs', schema=None) as batch_op:
            for name, cols in todo_indexes:
                batch_op.create_index(name, cols, unique=False)

    # ---- 模型版本 ----
    if 'model_versions' not in existing:
        op.create_table(
            'model_versions',
            sa.Column('name', sa.String(length=100), nullable=False),
            sa.Column('version', sa.String(length=50), nullable=False),
            sa.Column('provider', sa.String(length=50), nullable=False),
            sa.Column('endpoint', sa.String(length=500), nullable=True),
            sa.Column('capabilities', sa.JSON(), nullable=True),
            sa.Column('status', sa.String(length=20), nullable=False),
            sa.Column('is_active', sa.Boolean(), nullable=False),
            sa.Column('created_at', sa.DateTime(),
                      server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
            sa.Column('activated_at', sa.DateTime(), nullable=True),
            sa.Column('id', sa.String(length=36), nullable=False),
            sa.PrimaryKeyConstraint('id'),
        )

    # ---- 系统配置 ----
    if 'system_configs' not in existing:
        op.create_table(
            'system_configs',
            sa.Column('key', sa.String(length=100), nullable=False),
            sa.Column('value', sa.Text(), nullable=True),
            sa.Column('category', sa.String(length=50), nullable=False),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('updated_by', sa.String(length=36), nullable=True),
            sa.Column('updated_at', sa.DateTime(),
                      server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
            sa.Column('id', sa.String(length=36), nullable=False),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('key', name='uq_system_configs_key'),
        )


def downgrade() -> None:
    existing = _existing_tables()
    audit_indexes = _existing_indexes('audit_logs')
    todo_indexes = [n for n, _ in _AUDIT_INDEXES if n in audit_indexes]
    if todo_indexes:
        with op.batch_alter_table('audit_logs', schema=None) as batch_op:
            for name in todo_indexes:
                batch_op.drop_index(name)
    for t in ('system_configs', 'model_versions', 'audit_logs'):
        if t in existing:
            op.drop_table(t)
