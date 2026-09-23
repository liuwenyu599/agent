"""PPT 助手 DTO。"""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


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


class DocRenameIn(BaseModel):
    """重命名 PPT 文档：只改标题，不改变内容与状态。"""

    title: str = Field(min_length=1, max_length=200)


class OutlineIn(BaseModel):
    source_type: str = "topic"          # topic / text / document / kb
    topic: str = ""
    content: str = ""
    slide_count: int = 10
    audience: str = ""
    scene: str = ""
    # 本次参与生成的材料文件名清单（材料分析步骤返回），
    # 用于要求模型为每页标注 sources 内容依据（provenance）
    material_names: List[str] = Field(default_factory=list)


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
