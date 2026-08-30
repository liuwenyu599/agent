"""对话领域实体。"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class ChatSession:
    user_id: str
    id: Optional[str] = None
    title: str = ""
    created_at: Optional[datetime] = None


@dataclass
class ChatMessage:
    session_id: str
    role: str
    content: str
    id: Optional[str] = None
    source: str = "chat"  # chat / template
    sources: List[Any] = field(default_factory=list)
    attachments: List[Dict] = field(default_factory=list)
    tool_calls: Optional[list] = None
    tokens_used: Optional[int] = None
    latency_ms: Optional[int] = None
    created_at: Optional[datetime] = None


@dataclass
class ChatAttachment:
    """对话附件：只服务于对话，不进知识库、不需要审核。"""
    user_id: str
    filename: str
    kind: str  # doc / image
    id: Optional[str] = None
    session_id: Optional[str] = None
    file_path: Optional[str] = None
    file_size: Optional[int] = None
    text_content: Optional[str] = None
    parse_status: str = "ok"  # ok / partial / failed
    parse_note: Optional[str] = None
    created_at: Optional[datetime] = None


@dataclass
class SessionSummary:
    session_id: str
    summary: str
    id: Optional[str] = None
    key_points: List[str] = field(default_factory=list)
    message_count: int = 0
    created_at: Optional[datetime] = None


@dataclass
class UserMemory:
    user_id: str
    memory_type: str
    content: str
    id: Optional[str] = None
    importance: float = 0.5
    source: str = "inferred"
    last_accessed: Optional[datetime] = None
    access_count: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
