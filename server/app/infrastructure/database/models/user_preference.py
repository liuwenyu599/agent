"""用户个人偏好 ORM 模型（v3.3，Prompt 分层第 5 层）。

设计要点（权限隔离的物理约束）：
- 本表**只保存表达风格类偏好**（助手称呼 / 工作偏好 / 写作偏好 / 默认行为开关），
  刻意不含 `department_code`、`scope`、`role`、`theme` 或任何权限位；
- 权限与检索范围的解析链路（RagService / OrganizationService）一律不读本表，
  偏好仅作为 Prompt 文本层参与生成，不改变任何服务端判定；
- 与 users 主表 1:1（user_id 即主键），用户清空偏好 / 注销时删除整行即可。
"""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base


class UserPreferenceModel(Base):
    __tablename__ = "user_preferences"

    # 主键即用户 id：天然保证一个用户只有一条偏好，且无法跨用户寻址
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), primary_key=True)

    # 1) 助手称呼：用户对 AI 助手的称呼（≤20 字，不接受换行）
    assistant_name: Mapped[str] = mapped_column(String(30), default="")
    # 2) 我的工作偏好：多行文本（常处理业务 / 习惯 / 希望如何协助，≤600 字）
    work_preference: Mapped[str] = mapped_column(Text, default="")
    # 3) 写作偏好枚举："" | concise_formal | rigorous_detailed | custom
    writing_style: Mapped[str] = mapped_column(String(20), default="")
    #    写作偏好=custom 时的补充说明（≤200 字）
    writing_style_custom: Mapped[str] = mapped_column(Text, default="")
    # 4) 默认行为开关（JSON，键白名单：cite_sources / confirm_structure）
    behaviors_json: Mapped[str] = mapped_column(Text, default="{}")

    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now())
