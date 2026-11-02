"""知识库请求模型。"""
from typing import List, Optional

from pydantic import BaseModel, Field


class KBCreateRequest(BaseModel):
    name: str
    description: str = ""
    kb_type: Optional[str] = None


class KBUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    # 类型调整（public / department / personal），权限在服务端按角色校验
    kb_type: Optional[str] = None


class ReviewRequest(BaseModel):
    doc_id: str
    action: str
    comment: str = ""


class DocUpdateRequest(BaseModel):
    title: Optional[str] = None
    doc_type: Optional[str] = Field(default=None, min_length=1, max_length=50)
    status: Optional[str] = None
    department: Optional[str] = None
    doc_number: Optional[str] = None
    # 正文在线编辑：传入时重新分块并重建该文档的向量索引
    content: Optional[str] = None


class UrlImportRequest(BaseModel):
    kb_id: str
    urls: List[str]


class UrlTextImportRequest(BaseModel):
    """批量粘贴文本（每行一个或多个链接）"""
    kb_id: str
    text: str


class KnowledgeAskRequest(BaseModel):
    """科室空间知识问答：检索范围由服务端按登录用户强制解析。"""
    message: str
    session_id: Optional[str] = None
    attachment_ids: List[str] = Field(default_factory=list)
