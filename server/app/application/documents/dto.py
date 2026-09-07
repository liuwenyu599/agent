"""文档版本管理请求/响应模型。"""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class DocumentCreateRequest(BaseModel):
    title: str = "未命名文档"
    content: str
    doc_type: Optional[str] = None
    document_number: Optional[str] = None
    document_date: Optional[str] = None
    session_id: Optional[str] = None
    quality: Optional[Dict[str, Any]] = None
    content_check: Optional[Dict[str, Any]] = None
    note: Optional[str] = None


class DocumentSaveRequest(BaseModel):
    """保存编辑内容 -> 产生一个新版本。"""
    content: str
    title: Optional[str] = None
    note: Optional[str] = None
    status: Optional[str] = Field(default=None, pattern="^(draft|final)$")


class DocumentSummary(BaseModel):
    id: str
    title: str
    doc_type: Optional[str] = None
    document_number: Optional[str] = None
    document_date: Optional[str] = None
    current_version: int
    status: str
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class DocumentVersionItem(BaseModel):
    version_no: int
    note: Optional[str] = None
    created_by: Optional[str] = None
    created_at: Optional[str] = None
    char_count: int = 0


class DocumentDetail(DocumentSummary):
    content: str
    quality: Optional[Dict[str, Any]] = None
    content_check: Optional[Dict[str, Any]] = None
    versions: List[DocumentVersionItem] = []
