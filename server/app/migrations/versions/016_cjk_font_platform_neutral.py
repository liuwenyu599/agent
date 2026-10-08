"""把 PPT 模板里已存的「微软雅黑」改为跨平台可用的 SimHei（黑体）。

Revision ID: 016_cjk_font_platform_neutral
Revises: 015_widen_alembic_version
"""

from alembic import op

revision = "016_cjk_font_platform_neutral"
down_revision = "015_widen_alembic_version"
branch_labels = None
depends_on = None

# 已废弃的字体名 -> 替换值。左侧是历史硬编码写入的值。
_LEGACY_FONTS = ("微软雅黑",)


def upgrade() -> None:
    """存量模板记录里的字体名换成 SimHei。

    只改数据不改表结构，因此没有 dialect 分支；重复执行结果一致（幂等）。
    """
    for legacy in _LEGACY_FONTS:
        op.execute(
            "UPDATE ppt_templates SET font = 'SimHei' "
            f"WHERE font = '{legacy}'"
        )


def downgrade() -> None:
    """回滚不恢复原字体名。

    「微软雅黑」在麒麟/统信上不存在，恢复它等于把缺陷装回去；
    且升级前的值本就来自硬编码默认值，语义上不构成有效回滚目标。
    因此这里只打印提示，不做数据变更。
    """
    print(
        "[016] 字体名不回滚：'微软雅黑' 在国产 OS 上不存在，"
        "恢复会导致 PPT 字体回退。如确需恢复请手工执行："
        "UPDATE ppt_templates SET font = '微软雅黑' WHERE font = 'SimHei';"
    )
