"""模板模块请求模型（与旧系统一致）。"""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class TemplateParam(BaseModel):
    name: str
    label: str
    type: str  # input, textarea, select, date
    required: bool = False
    placeholder: str = ""
    options: Optional[List[Dict[str, str]]] = None
    rows: int = 2


class StructureItem(BaseModel):
    name: str
    guide: Optional[str] = ""


class TemplateCreateRequest(BaseModel):
    name: str
    category: str
    base_type: Optional[str] = "公文"
    description: Optional[str] = ""
    icon: str = "Document"
    params_schema: List[TemplateParam] = []
    content_template: str = ""
    system_prompt: Optional[str] = ""
    writing_style: Optional[str] = "正式公文"
    word_count: Optional[int] = 1000
    need_red_header: Optional[bool] = False
    need_signature: Optional[bool] = True
    need_date: Optional[bool] = True
    need_doc_number: Optional[bool] = False
    keywords: Optional[str] = None
    sort_order: int = 0
    template_kind: Optional[str] = "official_doc"
    tags: Optional[List[str]] = []
    scene: Optional[str] = ""
    writing_guide: Optional[str] = ""
    structure: Optional[List[StructureItem]] = []
    kb_ids: Optional[List[str]] = []
    visibility: Optional[str] = "official"
    share_scope: Optional[str] = "all"
    share_departments: Optional[List[str]] = []
    share_roles: Optional[List[str]] = []
    is_draft: Optional[bool] = False


class TemplateUpdateRequest(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    icon: Optional[str] = None
    params_schema: Optional[List[TemplateParam]] = None
    content_template: Optional[str] = None
    system_prompt: Optional[str] = None
    is_active: Optional[bool] = None
    sort_order: Optional[int] = None
    template_kind: Optional[str] = None
    tags: Optional[List[str]] = None
    scene: Optional[str] = None
    writing_guide: Optional[str] = None
    structure: Optional[List[StructureItem]] = None
    kb_ids: Optional[List[str]] = None
    visibility: Optional[str] = None
    share_scope: Optional[str] = None
    share_departments: Optional[List[str]] = None
    share_roles: Optional[List[str]] = None
    is_draft: Optional[bool] = None


class CategoryCreateRequest(BaseModel):
    name: str
    code: str
    description: Optional[str] = ""
    icon: str = "Folder"
    sort_order: int = 0
