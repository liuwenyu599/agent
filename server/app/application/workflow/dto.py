"""工作流 DTO。"""
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class CreateInstanceRequest(BaseModel):
    template_code: str
    title: str
    workflow_context: Dict[str, Any] = Field(default_factory=dict)


class UpdateInstanceRequest(BaseModel):
    title: Optional[str] = None
    status: Optional[str] = None
    basic_info: Optional[Dict[str, Any]] = None
    workflow_context: Optional[Dict[str, Any]] = None


class UpdateNodeRequest(BaseModel):
    content: Optional[str] = None
    status: Optional[str] = None


class GenerateNodeRequest(BaseModel):
    instruction: str = ""
    save: bool = True


class ParseNaturalLanguageRequest(BaseModel):
    text: str


class ParseKeyValueRequest(BaseModel):
    text: str


class ConfirmContextRequest(BaseModel):
    workflow_context: Dict[str, Any]
    confirm_overrides: Optional[Dict[str, bool]] = Field(default_factory=dict)
