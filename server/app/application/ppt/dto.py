"""PPT 助手 DTO。"""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field
from app.core.fonts import DEFAULT_CJK_FONT


class TemplateIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    category: str = Field(default="其他", min_length=1, max_length=40)
    description: str = Field(default="", max_length=500)
    colors: Optional[dict] = None
    font: str = Field(default=DEFAULT_CJK_FONT, min_length=1, max_length=80)
    layouts: Optional[dict] = None


class ImportUrlIn(BaseModel):
    url: str = Field(min_length=1, max_length=2048)
    name: str = Field(default="", max_length=100)
    category: str = Field(default="其他", min_length=1, max_length=40)


class DraftIn(BaseModel):
    title: Optional[str] = None
    subtitle: Optional[str] = None
    outline: Optional[dict] = None
    template_id: Optional[str] = None


class DocRenameIn(BaseModel):
    """重命名 PPT 文档：只改标题，不改变内容与状态。"""

    title: str = Field(min_length=1, max_length=200)


class ImageCaptionIn(BaseModel):
    caption: str = Field(max_length=500)


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
    # 手动指定图片时仅使用这些图片；空数组由 auto_images 决定是否自动配图。
    material_ids: Optional[List[str]] = Field(default=None, max_length=30)
    auto_images: bool = True
    theme_id: Optional[str] = Field(default=None, max_length=50)
    # 结合知识库生成：所选知识库 id 列表。服务端按主题做 RAG 语义检索，
    # 命中片段作为大纲内容依据；权限范围由服务端解析（与可访问库取交集），
    # 客户端传值无法扩大检索范围
    kb_ids: List[str] = Field(default_factory=list)


class GenerateIn(BaseModel):
    doc_id: str
    template_id: Optional[str] = None
    outline: Optional[dict] = None


class JobSubmitIn(BaseModel):
    """提交异步生成任务（PPTAgent）。

    doc_id 同时作为 job_id：一个文档同时只允许一个进行中的任务。
    """
    doc_id: str
    message: str = ""


class JobClarifyIn(BaseModel):
    """回答 PPTAgent 的追问（R1）。"""
    answer: str = Field("", description="对追问的答复；空串表示「按你的判断继续」")


class BlankIn(BaseModel):
    title: str = "未命名PPT"
    subtitle: str = ""
    template_id: Optional[str] = None


class SlideActionIn(BaseModel):
    action: str                    # rewrite / expand / condense / custom
    slide: dict
    instruction: str = ""


class VisualIn(BaseModel):
    kind: str                      # chart / timeline / process / data / relationship / organization / architecture
    slide: dict
    instruction: str = ""
    template_id: Optional[str] = None


class StructureIn(BaseModel):
    action: str                    # add / split / merge
    slides: List[dict]
    index: int
    instruction: str = ""


class OutlineAdjustIn(BaseModel):
    """大纲整体调整：一句自然语言指令（如「把目录页改成正文页」），作用于整份大纲。"""

    instruction: str = Field(min_length=1, max_length=500)
    outline: dict


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
