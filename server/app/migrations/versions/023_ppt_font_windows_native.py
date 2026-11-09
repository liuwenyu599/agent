"""PPT 模板字体名改为 Windows 原生的 Microsoft YaHei。

Revision ID: 023_ppt_font_windows_native
Revises: 022_ppt_template_sharing_status

背景：016 把模板字体统一成 Noto Sans CJK SC，理由是「后端容器与国产 OS 都装」。
但漏了 Windows —— 那是演示与分发的主场景，而 Windows 没有这个 family，
PowerPoint 打开下载下来的 pptx 会把整行退回宋体（用户 2026-11-09 反馈
「系统上正常、下载下来不正常」）。

现在改为「分发端原生 + Linux 端做别名」：模板里写 Microsoft YaHei / Times New
Roman，Windows 双击即命中；麒麟/统信与容器由 deploy/fonts/51-ppt-fonts.conf 把
这两个名字映射到思源黑体与 Liberation Serif。两端都不需要装字体。
"""

from alembic import op

revision = "023_ppt_font_windows_native"
down_revision = "022_ppt_template_sharing_status"
branch_labels = None
depends_on = None

# 016 之后可能出现的历史值：Noto 本名、思源黑体别名。
_FROM = ("Noto Sans CJK SC", "Source Han Sans SC", "思源黑体")
_TO = "Microsoft YaHei"


def upgrade() -> None:
    """存量模板的字体名升级为 Microsoft YaHei（幂等，可重复执行）。"""
    for old in _FROM:
        op.execute(
            f"UPDATE ppt_templates SET font = '{_TO}' WHERE font = '{old}'"
        )


def downgrade() -> None:
    """回到 016 的口径（Noto Sans CJK SC）。

    注意：本迁移不做新老值区分，模板中心里显式选了 Microsoft YaHei 的模板
    也会被改回 Noto。回滚只在纯国产环境（Kylin/UOS 为主）下有意义。
    """
    op.execute(
        f"UPDATE ppt_templates SET font = 'Noto Sans CJK SC' WHERE font = '{_TO}'"
    )
