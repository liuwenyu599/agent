"""参考材料请求模型。"""
from typing import Optional

from pydantic import BaseModel


class TemplateTextRefRequest(BaseModel):
    name: str
    text: str


class TemplateUrlRefRequest(BaseModel):
    url: str
    name: Optional[str] = None


class TaskTextRefRequest(BaseModel):
    text: str
    name: Optional[str] = None
    template_id: Optional[str] = None


class TaskUrlRefRequest(BaseModel):
    url: str
    name: Optional[str] = None
    template_id: Optional[str] = None


class PromoteRequest(BaseModel):
    kb_id: str
