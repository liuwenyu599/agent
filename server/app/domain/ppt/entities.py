"""PPT 助手领域实体。

内容与版式分离：
- PPTDocument.outline 只存内容（页面类型/标题/要点/数据块/图片名）；
- 视觉样式由 template_id 指向的 PPTTemplate 决定，换模板只换样式不动内容。
"""
from dataclasses import dataclass, field
from app.core.fonts import DEFAULT_CJK_FONT
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
    font: str = DEFAULT_CJK_FONT
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

    # ================= 异步生成任务（PPTAgent job）=================
    # 复用本表承载 job，避免新建表；job_status 为空串表示「不是 job」。
    # 取值：pending / running / awaiting_clarification / succeeded /
    #       failed / cancelled
    job_status: str = ""
    # 进度阶段：submitting / researching / outlining / designing /
    #           finalizing / succeeded / failed
    job_phase: str = ""
    job_total_pages: int = 0
    job_current_page: int = 0
    job_error: str = ""
    # PPTAgent 信息不足时的追问文本（R1），非空即等待用户回答
    job_question: str = ""
    job_renderer: str = ""          # 最终产物来源：pptagent / local
    job_event_id: str = ""          # Gradio 事件流句柄，便于日志串联
    job_cancel_requested: bool = False
    job_started_at: Optional[datetime] = None
    job_finished_at: Optional[datetime] = None
    # 最近一次"有进展"的时刻，用于 30 分钟无进展判失败
    job_progress_at: Optional[datetime] = None
