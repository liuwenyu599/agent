"""PPT 助手领域实体。

内容与版式分离：
- PPTDocument.outline 只存内容（页面类型/标题/要点/数据块/图片名）；
- 视觉样式由 template_id 指向的 PPTTemplate 决定，换模板只换样式不动内容。
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class PPTTemplate:
    """PPT 模板：视觉风格 + 完整页面版式体系。"""
    name: str
    id: Optional[str] = None
    builtin_id: Optional[str] = None
    category: str = "工作汇报"
    description: Optional[str] = None
    is_official: bool = False
    created_by: Optional[str] = None
    colors: Dict[str, Any] = field(default_factory=dict)
    font: str = "微软雅黑"
    layouts: Dict[str, Any] = field(default_factory=dict)
    layout_library: List[Dict[str, Any]] = field(default_factory=list)
    source_file: Optional[str] = None
    use_count: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


@dataclass
class PPTTemplateFavorite:
    user_id: str
    template_id: str
    id: Optional[str] = None
    created_at: Optional[datetime] = None


@dataclass
class PPTMaterial:
    """素材库图片（用户命名，AI 按名称选用）。"""
    user_id: str
    name: str
    file_path: str
    id: Optional[str] = None
    caption: Optional[str] = None
    file_size: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None
    mime_type: str = ""
    created_at: Optional[datetime] = None


@dataclass
class PPTDocument:
    """PPT 文档（我的 PPT）。status: draft=草稿 / generated=已导出。"""
    user_id: str
    title: str
    id: Optional[str] = None
    subtitle: str = ""
    source_content: Optional[str] = None
    template_id: Optional[str] = None
    theme_id: str = "gov_report_red"
    source_type: str = "topic"
    status: str = "draft"
    is_favorite: bool = False
    outline: Optional[Dict[str, Any]] = None
    file_path: Optional[str] = None
    slide_count: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
