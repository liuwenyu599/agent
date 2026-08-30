"""知识库请求模型。"""
from typing import List, Optional

from pydantic import BaseModel


class KBCreateRequest(BaseModel):
    name: str
    description: str = ""
    kb_type: Optional[str] = None


class KBUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


class ReviewRequest(BaseModel):
    doc_id: str
    action: str
    comment: str = ""


class DocUpdateRequest(BaseModel):
    title: Optional[str] = None
    doc_type: Optional[str] = None
    status: Optional[str] = None
    department: Optional[str] = None
    doc_number: Optional[str] = None


class UrlImportRequest(BaseModel):
    kb_id: str
    urls: List[str]


class UrlTextImportRequest(BaseModel):
    """批量粘贴文本（每行一个或多个链接）"""
    kb_id: str
    text: str
