"""对话请求/响应模型（与旧系统兼容，新字段均为可选扩展）。"""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


class SessionRenameRequest(BaseModel):
    """重命名会话。只改标题，不产生任何新的会话或消息。"""

    title: str = Field(min_length=1, max_length=200)


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    use_rag: bool = True
    system_prompt: Optional[str] = None
    template_category: Optional[str] = None
    source: Optional[str] = "chat"
    attachment_ids: Optional[List[str]] = None
    reference_template_id: Optional[str] = None
    task_reference_ids: Optional[List[str]] = None


class ChatResponse(BaseModel):
    reply: str
    sources: List[dict] = []
    attachments: List[dict] = []
    session_id: str
    message_id: Optional[str] = None
    document_id: Optional[str] = None
    document_number: Optional[str] = None
    document_date: Optional[str] = None
    quality: Optional[Dict[str, Any]] = None
    content_check: Optional[Dict[str, Any]] = None
    postprocess_events: List[str] = []


class FeedbackRequest(BaseModel):
    target_type: str = Field(pattern="^(chat_message|document_version)$")
    target_id: str = Field(min_length=1, max_length=64)
    rating: int
    detail: str = Field(default="", max_length=2000)

    @field_validator("rating")
    @classmethod
    def validate_rating(cls, value: int) -> int:
        if value not in (-1, 1):
            raise ValueError("rating must be 1 or -1")
        return value


class ExportRequest(BaseModel):
    content: str
    title: str = "公文"
    doc_number: str = ""
    recipient: str = ""
    signature: str = ""
    date_text: str = ""
    use_red_header: bool = False


class OfficialExportRequest(BaseModel):
    content: str
    title: str = ""
    doc_number: str = ""
    recipient: str = ""
    signature: str = ""
    date_text: str = ""