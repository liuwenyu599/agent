# -*- coding: utf-8 -*-
"""PPT 助手数据模型（覆盖 backend/database/models_ppt.py）

三张表：
- PPTTemplate：PPT 模板。官方模板（is_official=True，只能用不能删）/
  个人模板（可编辑可删除）。模板保存完整版式体系（layouts JSON：
  封面/目录/章节/正文/数据/图表/案例/总结/结束 各页型的版式变体），
  不止封面颜色。
- PPTMaterial：素材库图片（不变）。
- PPTDocument：PPT 文档。内容与版式分离：
  outline JSON 只存"内容 + 页面类型 + 版式变体 + 数据块"，
  视觉样式由 template_id 指向的模板决定——换模板只换样式，不动内容。

PPTDocument.status：draft（草稿/编辑中）/ generated（已导出过 PPTX）
"""
import uuid
from datetime import datetime

from sqlalchemy import Column, String, DateTime, Boolean, ForeignKey, Text, BigInteger, Integer, JSON

from backend.database.models import Base


def _uuid():
    return str(uuid.uuid4())


# ================= PPT 模板 =================

class PPTTemplate(Base):
    """PPT 模板：视觉风格 + 完整页面版式体系"""
    __tablename__ = "ppt_templates"

    id = Column(String(36), primary_key=True, default=_uuid)
    name = Column(String(100), nullable=False)
    builtin_id = Column(String(50), unique=True, nullable=True, comment="内置官方模板的固定标识，用于种子同步")
    category = Column(String(50), default="工作汇报", comment="工作汇报/政策解读/培训课件/经验交流/总结汇报/宣传展示/其他")
    description = Column(String(300))
    is_official = Column(Boolean, default=False, comment="官方模板只可使用，不可删改")
    created_by = Column(String(36), ForeignKey("users.id"), nullable=True)

    # —— 视觉风格 ——
    colors = Column(JSON, comment='{"primary":"C00000","accent":"E8B54D","light":"FDF2F2","dark":"7A0000"}')
    font = Column(String(50), default="微软雅黑")

    # —— 版式体系：每种页型一个版式变体名 ——
    # 页型：cover/toc/section/content/data/chart/case/timeline/process/summary/closing
    layouts = Column(JSON, comment='{"cover":"band_bottom","toc":"numbered_list",...}')

    # —— 模板学习版式库（上传模板自动分析生成）——
    # [{id,name,detected_type,source_slide_index,slide_size,background,
    #   element_schema,placeholders,text_regions,image_regions,chart_regions,shape_regions,preview}]
    layout_library = Column(JSON, comment="模板学习得到的版式库，识别出几种存几种")

    source_file = Column(String(500), comment="上传的 pptx 模板原始文件（如有）")
    use_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PPTTemplateFavorite(Base):
    """模板收藏（按用户）"""
    __tablename__ = "ppt_template_favorites"

    id = Column(String(36), primary_key=True, default=_uuid)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    template_id = Column(String(36), ForeignKey("ppt_templates.id"), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)


# ================= 素材库 =================

class PPTMaterial(Base):
    """PPT 素材库图片（用户命名，AI 按名称选用）"""
    __tablename__ = "ppt_materials"

    id = Column(String(36), primary_key=True, default=_uuid)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String(200), nullable=False, comment="图片名称（AI 按此选用）")
    caption = Column(String(500), comment="图片说明/内容描述，帮助 AI 判断插入位置")
    file_path = Column(String(500), nullable=False)
    file_size = Column(BigInteger)
    width = Column(Integer)
    height = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)


# ================= PPT 文档 =================

class PPTDocument(Base):
    """PPT 文档（我的 PPT）。

    内容与版式分离（需求 6）：
    - outline：页面数组，每页 = {id, type(页面类型), layout(版式变体，可选覆盖模板),
                title, subtitle, points[], blocks(数据块/图表/时间轴等结构化数据),
                image_name, image_hint, note} —— 只含内容，不含颜色样式；
    - template_id：视觉样式来源，切换模板不影响 outline；
    - status：draft / generated。
    """
    __tablename__ = "ppt_documents"

    id = Column(String(36), primary_key=True, default=_uuid)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String(200), nullable=False)
    subtitle = Column(String(300), default="")
    source_content = Column(Text, comment="生成来源内容（主题/粘贴文本，留存备查）")
    template_id = Column(String(36), ForeignKey("ppt_templates.id"), nullable=True)
    theme_id = Column(String(50), default="gov_report_red", comment="旧字段，兼容用")
    source_type = Column(String(20), default="topic", comment="topic / document / paste / blank")
    status = Column(String(20), default="draft", comment="draft=草稿 / generated=已导出")
    is_favorite = Column(Boolean, default=False, comment="收藏")
    outline = Column(JSON, comment="页面内容结构（与样式分离）")
    file_path = Column(String(500), comment="最近导出的 pptx 路径")
    slide_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)