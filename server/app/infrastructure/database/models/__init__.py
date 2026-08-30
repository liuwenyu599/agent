"""ORM 模型注册表：main.py / 迁移通过 import 本包完成全部表注册。"""
from app.infrastructure.database.models import (  # noqa: F401
    chat,
    format_check,
    identity,
    knowledge,
    ppt,
    references,
    templates,
    workflow,
)
