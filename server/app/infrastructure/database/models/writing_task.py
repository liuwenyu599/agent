"""写作任务（Writing Task）ORM 模型。

一个任务 = 一次持续的写作过程：结构化任务上下文 + 当前文档 + 对话历史指针。
版本快照复用 my_documents / my_document_versions。
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base, IdMixin


class WritingTaskModel(Base, IdMixin):
    __tablename__ = "writing_tasks"

    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    session_id: Mapped[Optional[str]] = mapped_column(String(36))   # 关联对话（可选）
    document_id: Mapped[Optional[str]] = mapped_column(String(36))  # 关联"我的文档"
    context: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)  # task_context
    current_content: Mapped[str] = mapped_column(Text, default="")
    ai_draft: Mapped[str] = mapped_column(Text, default="")         # 首版 AI 初稿（训练数据用）
    version_no: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="collecting")  # collecting/drafting/editing/final
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
