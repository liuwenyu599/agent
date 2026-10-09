"""把 PPT 模板里已存的字体名改为后端与国产客户端都有的 Noto Sans CJK SC。

Revision ID: 016_cjk_font_platform_neutral
Revises: 015_widen_alembic_version
"""

from alembic import op

revision = "016_cjk_font_platform_neutral"
down_revision = "015_widen_alembic_version"
branch_labels = None
depends_on = None

# 历史值 -> 目标值
#   微软雅黑：11 处硬编码时代写入的默认值。Windows 有，麒麟与后端容器都没有。
#   SimHei  ：本迁移的初版目标（2026-10-08 已提交）。因后端容器只装了
#              fonts-noto-cjk、没有 SimHei 而作废；一并清理以防万一已执行过初版。
# 目标 Noto Sans CJK SC：deploy/Dockerfile 装了 fonts-noto-cjk，且国产 OS 标配，
#                        是唯一同时满足「后端渲染」与「国产客户端」的字体。
_FROM = ("微软雅黑", "SimHei")
_TO = "Noto Sans CJK SC"


def upgrade() -> None:
    """存量模板记录的字体名统一为 Noto Sans CJK SC。

    只改数据不改表结构，故没有 dialect 分支；重复执行结果一致（幂等）。
    font 为 NULL 或其它值的行不受影响，用户在模板中心自定义的字体被保留。
    """
    for old in _FROM:
        op.execute(
            f"UPDATE ppt_templates SET font = '{_TO}' WHERE font = '{old}'"
        )


def downgrade() -> None:
    """不回滚字体名。

    回滚目标要么「微软雅黑」要么「SimHei」，两者在国产 OS 与后端容器都不存在，
    恢复会导致 LibreOffice 预览渲染回退，等于把缺陷装回去；且升级前的值本就来自
    硬编码默认值，不构成有效回滚目标。因此只打印提示，不做数据变更。
    """
    print(
        "[016] 字体名不回滚：'微软雅黑' 与 'SimHei' 在国产 OS 与后端容器均不存在，"
        "恢复会导致 LibreOffice 预览渲染回退。如确需恢复请手工执行："
        f"UPDATE ppt_templates SET font = '微软雅黑' WHERE font = '{_TO}';"
    )
