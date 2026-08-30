"""写作参考材料领域实体。

两类材料与知识库 Document 严格分离：
- TemplateReference：模板固定参考材料（风格范式学习用，不入知识库）
- TaskReference：当前任务佐证材料（事实依据，仅归属用户可见，不进 RAG）
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

REF_TYPES = ("file", "text", "url")


@dataclass
class TemplateReference:
    template_id: str
    name: str
    ref_type: str
    id: Optional[str] = None
    file_path: Optional[str] = None
    file_size: Optional[int] = None
    source_url: Optional[str] = None
    text_content: Optional[str] = None
    char_count: int = 0
    parse_status: str = "ok"
    parse_note: Optional[str] = None
    created_by: Optional[str] = None
    is_active: bool = True
    created_at: Optional[datetime] = None


@dataclass
class TaskReference:
    user_id: str
    name: str
    ref_type: str
    id: Optional[str] = None
    template_id: Optional[str] = None
    session_id: Optional[str] = None
    file_path: Optional[str] = None
    file_size: Optional[int] = None
    source_url: Optional[str] = None
    text_content: Optional[str] = None
    char_count: int = 0
    parse_status: str = "ok"
    parse_note: Optional[str] = None
    promoted_doc_id: Optional[str] = None
    created_at: Optional[datetime] = None
