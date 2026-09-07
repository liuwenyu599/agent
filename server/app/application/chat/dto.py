"""对话请求/响应模型（与旧系统一致）。"""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    use_rag: bool = True
    system_prompt: Optional[str] = None
    template_category: Optional[str] = None
    source: Optional[str] = "chat"  # chat / template
    attachment_ids: Optional[List[str]] = None
    reference_template_id: Optional[str] = None
    task_reference_ids: Optional[List[str]] = None


class ChatResponse(BaseModel):
    reply: str
    sources: List[dict] = []
    attachments: List[dict] = []
    session_id: str
    # 智能写作流水线产物（仅写作类请求返回）
    document_id: Optional[str] = None
    document_number: Optional[str] = None
    document_date: Optional[str] = None
    quality: Optional[Dict[str, Any]] = None
    content_check: Optional[Dict[str, Any]] = None
    postprocess_events: List[str] = []


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
