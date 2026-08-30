"""PPT 助手 DTO。"""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class TemplateIn(BaseModel):
    name: str
    category: str = "其他"
    description: str = ""
    colors: Optional[dict] = None
    font: str = "微软雅黑"
    layouts: Optional[dict] = None


class ImportUrlIn(BaseModel):
    url: str
    name: str = ""
    category: str = "其他"


class DraftIn(BaseModel):
    title: Optional[str] = None
    subtitle: Optional[str] = None
    outline: Optional[dict] = None
    template_id: Optional[str] = None


class OutlineIn(BaseModel):
    source_type: str = "topic"          # topic / text / document / kb
    topic: str = ""
    content: str = ""
    slide_count: int = 10
    audience: str = ""
    scene: str = ""


class GenerateIn(BaseModel):
    doc_id: str
    template_id: Optional[str] = None
    outline: Optional[dict] = None


class BlankIn(BaseModel):
    title: str = "未命名PPT"
    subtitle: str = ""
    template_id: Optional[str] = None


class SlideActionIn(BaseModel):
    action: str                    # rewrite / expand / condense / custom
    slide: dict
    instruction: str = ""


class VisualIn(BaseModel):
    kind: str                      # chart / timeline / process / data
    slide: dict
    instruction: str = ""


class StructureIn(BaseModel):
    action: str                    # add / split / merge
    slides: List[dict]
    index: int
    instruction: str = ""


class CloudCfgIn(BaseModel):
    enabled: bool = False
    api_key: str = ""
    base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    mode: str = "general"
    template_id: str = "summary_01"


class CloudGenIn(BaseModel):
    doc_id: str
    mode: str = ""
    template_id: str = ""
