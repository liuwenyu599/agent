"""知识库领域实体。"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

KB_TYPE_PUBLIC = "public"
KB_TYPE_PERSONAL = "personal"

DOC_STATUS_PENDING = "pending"
DOC_STATUS_PUBLISHED = "published"
DOC_STATUS_REJECTED = "rejected"
DOC_STATUS_ARCHIVED = "archived"


@dataclass
class KnowledgeBase:
    name: str
    id: Optional[str] = None
    description: str = ""
    kb_type: str = KB_TYPE_PUBLIC
    owner_id: Optional[str] = None
    is_active: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


@dataclass
class KnowledgeDocument:
    kb_id: str
    title: str
    id: Optional[str] = None
    doc_type: Optional[str] = None
    department: Optional[str] = None
    issue_date: Optional[datetime] = None
    doc_number: Optional[str] = None
    file_path: Optional[str] = None
    file_size: Optional[int] = None
    page_count: Optional[int] = None
    content: Optional[str] = None
    status: str = DOC_STATUS_PENDING
    uploaded_by: Optional[str] = None
    created_by: Optional[str] = None
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    review_comment: Optional[str] = None
    version: int = 1
    doc_metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


@dataclass
class DocumentChunk:
    doc_id: str
    chunk_index: int
    content: str
    id: Optional[str] = None
    chunk_type: Optional[str] = None
    title: Optional[str] = None
    char_count: int = 0
    word_count: int = 0
    embedding_model: Optional[str] = None
    chunk_metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: Optional[datetime] = None
