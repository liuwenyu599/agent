from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
import uuid
import json

from backend.database.postgres import get_db
from backend.database.models import WritingTemplate, TemplateCategory, User
from backend.auth.permission import get_current_user, require_admin_or_above

router = APIRouter(prefix="/templates", tags=["写作模板"])

# ========== 内置模板数据 ==========
BUILTIN_TEMPLATES = [
    {
        "name": "工作通知",
        "category": "通知公告",
        "base_type": "通知",
        "icon": "Bell",
        "writing_style": "正式公文",
        "word_count": 800,
        "need_red_header": False,
        "need_signature": True,
        "need_date": True,
        "need_doc_number": True,
        "params_schema": [
            {"name": "title", "label": "通知标题", "type": "input", "required": True, "placeholder": "如：关于开展社区矫正专项排查的通知"},
            {"name": "recipient", "label": "通知对象", "type": "input", "required": True, "placeholder": "如：各区县司法局、各司法所"},
            {"name": "purpose", "label": "发文目的", "type": "textarea", "required": True, "placeholder": "请简述发文目的和政策依据", "rows": 3},
            {"name": "content", "label": "具体事项", "type": "textarea", "required": True, "placeholder": "请详细说明通知的具体内容、工作安排和要求", "rows": 5},
            {"name": "requirements", "label": "工作要求", "type": "textarea", "required": True, "placeholder": "请简述工作要求、时间节点和责任人", "rows": 3},
            {"name": "contact", "label": "联系人", "type": "input", "required": False, "placeholder": "如：张三"},
            {"name": "phone", "label": "联系电话", "type": "input", "required": False, "placeholder": "如：0531-12345678"}
        ],
        "content_template": "通知类公文，通常包含：标题、主送机关、发文目的、具体事项、工作要求、联系人及电话、落款和成文日期。请根据用户提供的要素生成规范的通知。",
        "system_prompt": "你是一位资深的司法行政公文写作专家，擅长撰写各类政务通知。请根据用户提供的要素生成规范的工作通知。要求：1.语言正式、严谨，符合党政机关公文规范；2.目的明确、内容具体、要求清晰；3.包含完整的标题、主送机关、正文、落款和成文日期；4.不要简单填空，要根据要素展开成完整的公文正文。"
    },
    {
        # ===== 合并后的"工作计划与总结"模板 =====
        # 由原来的"年度工作总结"和"工作计划"两个内置模板合并而来。
        # 字段覆盖计划与总结两类要素，用户只需填写实际涉及的部分，
        # 由 AI 根据已填写的要素判断：偏计划（目标/措施为主）还是偏总结（完成情况/成效为主），
        # 或两者兼有（如"上半年总结暨下半年计划"），并组织成合适的公文结构。
        "name": "工作计划与总结",
        "category": "计划总结",
        "base_type": "计划与总结",
        "icon": "DocumentChecked",
        "writing_style": "正式公文",
        "word_count": 1500,
        "need_red_header": False,
        "need_signature": True,
        "need_date": True,
        "need_doc_number": False,
        "params_schema": [
            {"name": "title", "label": "标题", "type": "input", "required": True, "placeholder": "如：社区矫正科2026年上半年工作总结暨下半年工作计划"},
            {"name": "department", "label": "部门/单位", "type": "input", "required": True, "placeholder": "如：社区矫正科"},
            {"name": "period", "label": "时间范围", "type": "input", "required": True, "placeholder": "如：2026年全年 / 2026年上半年"},
            {"name": "background", "label": "工作背景", "type": "textarea", "required": False, "placeholder": "请简述工作背景、上级要求和政策依据", "rows": 3},
            {"name": "goals", "label": "工作目标", "type": "textarea", "required": False, "placeholder": "请简述年度/阶段工作目标和总体思路", "rows": 3},
            {"name": "key_work", "label": "重点工作", "type": "textarea", "required": False, "placeholder": "请列出重点工作任务和主要举措", "rows": 4},
            {"name": "measures", "label": "具体措施", "type": "textarea", "required": False, "placeholder": "请简述落实工作的具体措施、步骤和时间安排", "rows": 4},
            {"name": "completion", "label": "完成情况", "type": "textarea", "required": False, "placeholder": "请简述各项工作完成情况（写总结时填写）", "rows": 4},
            {"name": "achievements", "label": "取得成效", "type": "textarea", "required": False, "placeholder": "请简述工作成效、亮点和相关数据（写总结时填写）", "rows": 4},
            {"name": "problems", "label": "存在问题", "type": "textarea", "required": False, "placeholder": "请简述工作中存在的问题和不足", "rows": 3},
            {"name": "next_plan", "label": "下一步工作", "type": "textarea", "required": False, "placeholder": "请简述下一步工作计划、目标和安排", "rows": 3}
        ],
        "content_template": "工作计划与总结类公文，可包含：标题、工作背景、工作目标、重点工作、具体措施、完成情况、取得成效、存在问题、下一步工作、落款和成文日期。用户可能只写计划、只写总结、或两者兼有，请根据用户实际填写的要素判断并组织成合适的公文结构，未填写的要素不要凭空编造。",
        "system_prompt": "你是一位资深的司法行政公文写作专家，擅长撰写工作计划与工作总结。请根据用户提供的要素生成规范的公文。要求：1.先判断用户意图：以目标、措施为主的按工作计划写；以完成情况、成效为主的按工作总结写；两者都有的按「总结暨计划」的复合结构写；2.语言正式、严谨，符合党政机关公文规范；3.结构清晰，层次分明，数据和成效要具体；4.问题分析客观，计划切实可行；5.用户未填写的要素不要虚构内容；6.不要简单填空，要根据要素展开成完整的公文正文。"
    },
    {
        "name": "请示报告",
        "category": "请示报告",
        "base_type": "请示",
        "icon": "MessageBox",
        "writing_style": "正式公文",
        "word_count": 1000,
        "need_red_header": False,
        "need_signature": True,
        "need_date": True,
        "need_doc_number": False,
        "params_schema": [
            {"name": "title", "label": "请示事项", "type": "input", "required": True, "placeholder": "如：关于申请社区矫正工作经费的请示"},
            {"name": "reason", "label": "请示理由", "type": "textarea", "required": True, "placeholder": "请简述请示的背景、原因和政策依据", "rows": 4},
            {"name": "content", "label": "申请内容", "type": "textarea", "required": True, "placeholder": "请详细说明申请的具体内容、金额或事项", "rows": 4},
            {"name": "basis", "label": "政策依据", "type": "textarea", "required": True, "placeholder": "请列出相关政策文件或法律依据", "rows": 3},
            {"name": "suggestion", "label": "拟办意见", "type": "textarea", "required": True, "placeholder": "请简述拟办意见或建议方案", "rows": 3}
        ],
        "content_template": "请示报告通常包含：标题、主送机关、请示理由、申请内容、政策依据、拟办意见、结尾（妥否，请批示）、落款和成文日期。请根据用户提供的要素生成规范的请示报告。",
        "system_prompt": "你是一位资深的司法行政公文写作专家，擅长撰写请示报告。请根据用户提供的要素生成规范的请示。要求：1.一事一请，理由充分；2.依据明确，引用规范；3.内容具体，方案可行；4.结尾规范使用'妥否，请批示'；5.不要简单填空，要根据要素展开成完整的公文正文。"
    },
    {
        "name": "调研报告",
        "category": "调研报告",
        "base_type": "调研报告",
        "icon": "DataAnalysis",
        "writing_style": "正式公文",
        "word_count": 2000,
        "need_red_header": False,
        "need_signature": True,
        "need_date": True,
        "need_doc_number": False,
        "params_schema": [
            {"name": "title", "label": "调研主题", "type": "input", "required": True, "placeholder": "如：社区矫正工作现状调研报告"},
            {"name": "department", "label": "调研部门", "type": "input", "required": True, "placeholder": "如：社区矫正科"},
            {"name": "background", "label": "调研背景", "type": "textarea", "required": True, "placeholder": "请简述调研背景和目的", "rows": 3},
            {"name": "method", "label": "调研方法", "type": "textarea", "required": True, "placeholder": "请简述调研方法和过程", "rows": 3},
            {"name": "findings", "label": "调研发现", "type": "textarea", "required": True, "placeholder": "请简述调研发现的主要情况和数据", "rows": 5},
            {"name": "problems", "label": "存在问题", "type": "textarea", "required": True, "placeholder": "请简述发现的问题和不足", "rows": 3},
            {"name": "suggestions", "label": "对策建议", "type": "textarea", "required": True, "placeholder": "请提出针对性的对策建议", "rows": 4}
        ],
        "content_template": "调研报告通常包含：标题、调研背景、调研方法、调研发现、存在问题、对策建议、落款和成文日期。请根据用户提供的要素生成规范的调研报告。",
        "system_prompt": "你是一位资深的司法行政调研报告写作专家。请根据用户提供的要素生成规范的调研报告。要求：1.数据真实、分析深入；2.问题准确、建议可行；3.结构完整、逻辑清晰；4.符合党政机关调研报告写作规范；5.不要简单填空，要根据要素展开成完整的公文正文。"
    },
    {
        "name": "会议纪要",
        "category": "会议纪要",
        "base_type": "会议纪要",
        "icon": "Notebook",
        "writing_style": "正式公文",
        "word_count": 800,
        "need_red_header": False,
        "need_signature": True,
        "need_date": True,
        "need_doc_number": False,
        "params_schema": [
            {"name": "meeting_name", "label": "会议名称", "type": "input", "required": True, "placeholder": "如：社区矫正工作推进会"},
            {"name": "time", "label": "会议时间", "type": "input", "required": True, "placeholder": "如：2026年7月23日 上午9:00"},
            {"name": "location", "label": "会议地点", "type": "input", "required": True, "placeholder": "如：局三楼会议室"},
            {"name": "host", "label": "主持人", "type": "input", "required": True, "placeholder": "如：张局长"},
            {"name": "attendees", "label": "参会人员", "type": "textarea", "required": True, "placeholder": "请列出参会人员", "rows": 2},
            {"name": "content", "label": "会议内容", "type": "textarea", "required": True, "placeholder": "请简述会议主要内容和讨论事项", "rows": 5},
            {"name": "decisions", "label": "会议决议", "type": "textarea", "required": True, "placeholder": "请列出会议决议、工作安排和责任人", "rows": 3}
        ],
        "content_template": "会议纪要通常包含：标题、会议基本信息（时间、地点、主持人、参会人员）、会议内容、会议决议、工作要求、记录人和日期。请根据用户提供的要素生成规范的会议纪要。",
        "system_prompt": "你是一位资深的司法行政公文写作专家，擅长撰写会议纪要。请根据用户提供的要素生成规范的会议纪要。要求：1.内容真实、准确；2.条理清晰、重点突出；3.决议明确、可执行；4.符合党政机关会议纪要写作规范；5.不要简单填空，要根据要素展开成完整的公文正文。"
    },
    {
        "name": "情况汇报",
        "category": "情况汇报",
        "base_type": "汇报",
        "icon": "InfoFilled",
        "writing_style": "正式公文",
        "word_count": 1000,
        "need_red_header": False,
        "need_signature": True,
        "need_date": True,
        "need_doc_number": False,
        "params_schema": [
            {"name": "title", "label": "汇报标题", "type": "input", "required": True, "placeholder": "如：关于社区矫正对象脱管情况的汇报"},
            {"name": "recipient", "label": "汇报对象", "type": "input", "required": True, "placeholder": "如：局领导"},
            {"name": "situation", "label": "情况说明", "type": "textarea", "required": True, "placeholder": "请详细说明情况、背景和数据", "rows": 5},
            {"name": "measures", "label": "已采取措施", "type": "textarea", "required": True, "placeholder": "请简述已采取的措施和成效", "rows": 3},
            {"name": "suggestions", "label": "建议", "type": "textarea", "required": False, "placeholder": "请简述建议或请求", "rows": 3}
        ],
        "content_template": "情况汇报通常包含：标题、汇报对象、情况说明、已采取措施、建议、结尾（特此汇报）、落款和成文日期。请根据用户提供的要素生成规范的情况汇报。",
        "system_prompt": "你是一位资深的司法行政公文写作专家，擅长撰写情况汇报。请根据用户提供的要素生成规范的情况汇报。要求：1.情况清楚、数据准确；2.措施具体、成效明显；3.建议可行；4.符合党政机关公文写作规范；5.不要简单填空，要根据要素展开成完整的公文正文。"
    },
    {
        "name": "执法文书",
        "category": "执法文书",
        "base_type": "执法文书",
        "icon": "DocumentCopy",
        "writing_style": "正式公文",
        "word_count": 800,
        "need_red_header": False,
        "need_signature": True,
        "need_date": True,
        "need_doc_number": False,
        "params_schema": [
            {"name": "doc_type", "label": "文书类型", "type": "select", "required": True, "options": [
                {"label": "调查笔录", "value": "调查笔录"},
                {"label": "告知书", "value": "告知书"},
                {"label": "决定书", "value": "决定书"},
                {"label": "通知书", "value": "通知书"}
            ]},
            {"name": "party", "label": "当事人", "type": "input", "required": True, "placeholder": "如：王某某"},
            {"name": "id_number", "label": "身份证号", "type": "input", "required": False, "placeholder": "如：370XXXXXXXXXXXXXXX"},
            {"name": "facts", "label": "事实经过", "type": "textarea", "required": True, "placeholder": "请简述事实经过", "rows": 4},
            {"name": "basis", "label": "法律依据", "type": "textarea", "required": True, "placeholder": "请列出法律依据", "rows": 3},
            {"name": "decision", "label": "处理决定", "type": "textarea", "required": True, "placeholder": "请说明处理决定", "rows": 3}
        ],
        "content_template": "执法文书通常包含：标题、当事人信息、事实经过、法律依据、处理决定、签名栏和日期。请根据用户提供的要素生成规范的执法文书。",
        "system_prompt": "你是一位资深的司法行政执法文书写作专家。请根据用户提供的要素生成规范的执法文书。要求：1.事实清楚、证据确凿；2.依据准确、引用规范；3.程序合法、格式规范；4.符合行政执法文书写作规范；5.不要简单填空，要根据要素展开成完整的公文正文。"
    }
]

BUILTIN_CATEGORIES = [
    {"name": "计划总结", "code": "plan_summary", "icon": "DocumentChecked", "sort_order": 1},
    {"name": "请示报告", "code": "request_report", "icon": "MessageBox", "sort_order": 3},
    {"name": "通知公告", "code": "notice", "icon": "Bell", "sort_order": 4},
    {"name": "调研报告", "code": "research", "icon": "DataAnalysis", "sort_order": 5},
    {"name": "会议纪要", "code": "meeting", "icon": "Notebook", "sort_order": 6},
    {"name": "情况汇报", "code": "report", "icon": "InfoFilled", "sort_order": 7},
    {"name": "执法文书", "code": "legal_doc", "icon": "DocumentCopy", "sort_order": 8}
]

# 计划/总结合并前的旧内置模板名（用于 /init 时自动停用）
_DEPRECATED_BUILTIN_NAMES = ["年度工作总结", "工作计划"]
# 合并前的旧分类 code（用于 /init 时自动停用）
_DEPRECATED_CATEGORY_CODES = ["work_summary", "work_plan"]

# ========== Pydantic 模型 ==========

class TemplateParam(BaseModel):
    name: str
    label: str
    type: str  # input, textarea, select, date
    required: bool = False
    placeholder: str = ""
    options: Optional[List[Dict[str, str]]] = None
    rows: int = 2

class TemplateCreateRequest(BaseModel):
    name: str
    category: str
    base_type: Optional[str] = "公文"
    description: Optional[str] = ""
    icon: str = "Document"
    params_schema: List[TemplateParam]
    content_template: str
    system_prompt: Optional[str] = ""
    writing_style: Optional[str] = "正式公文"
    word_count: Optional[int] = 1000
    need_red_header: Optional[bool] = False
    need_signature: Optional[bool] = True
    need_date: Optional[bool] = True
    need_doc_number: Optional[bool] = False
    keywords: Optional[str] = None
    sort_order: int = 0

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

class TemplateGenerateRequest(BaseModel):
    template_id: str
    params: Dict[str, Any]
    use_rag: bool = True

class CategoryCreateRequest(BaseModel):
    name: str
    code: str
    description: Optional[str] = ""
    icon: str = "Folder"
    sort_order: int = 0

# ========== API 路由 ==========

@router.post("/init")
async def init_builtin_templates(
    admin: User = Depends(require_admin_or_above),
    db: Session = Depends(get_db)
):
    """初始化内置模板（仅管理员）

    幂等：可重复调用。
    - 新内置模板不存在则创建；
    - 计划/总结合并前的旧内置模板（年度工作总结、工作计划）自动停用（is_active=False），
      不删除，保留使用统计和历史数据；
    - 旧分类（work_summary、work_plan）自动停用。
    """
    # 初始化分类
    for cat in BUILTIN_CATEGORIES:
        existing = db.query(TemplateCategory).filter(TemplateCategory.code == cat["code"]).first()
        if not existing:
            new_cat = TemplateCategory(**cat)
            db.add(new_cat)
    db.commit()

    # 停用旧分类
    db.query(TemplateCategory).filter(
        TemplateCategory.code.in_(_DEPRECATED_CATEGORY_CODES)
    ).update({"is_active": False}, synchronize_session=False)

    # 停用合并前的旧内置模板（只影响 is_builtin=True 的，不动用户自建模板）
    db.query(WritingTemplate).filter(
        WritingTemplate.name.in_(_DEPRECATED_BUILTIN_NAMES),
        WritingTemplate.is_builtin == True
    ).update({"is_active": False}, synchronize_session=False)
    db.commit()

    # 初始化模板
    count = 0
    for tmpl in BUILTIN_TEMPLATES:
        existing = db.query(WritingTemplate).filter(
            WritingTemplate.name == tmpl["name"],
            WritingTemplate.is_builtin == True
        ).first()
        if not existing:
            new_tmpl = WritingTemplate(
                id=str(uuid.uuid4()),
                name=tmpl["name"],
                category=tmpl["category"],
                base_type=tmpl.get("base_type", "公文"),
                icon=tmpl["icon"],
                params_schema=tmpl["params_schema"],
                content_template=tmpl["content_template"],
                system_prompt=tmpl.get("system_prompt", ""),
                writing_style=tmpl.get("writing_style", "正式公文"),
                word_count=tmpl.get("word_count", 1000),
                need_red_header=tmpl.get("need_red_header", False),
                need_signature=tmpl.get("need_signature", True),
                need_date=tmpl.get("need_date", True),
                need_doc_number=tmpl.get("need_doc_number", False),
                keywords=tmpl.get("keywords", None),
                is_builtin=True,
                is_active=True,
                created_by=admin.id,
                sort_order=0
            )
            db.add(new_tmpl)
            count += 1
        elif not existing.is_active:
            # 合并后的新模板若曾被误停用，重新启用
            existing.is_active = True
            db.commit()
    db.commit()

    return {"message": f"Initialized {count} builtin templates"}

@router.get("/categories")
async def list_categories(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取模板分类列表"""
    cats = db.query(TemplateCategory).filter(TemplateCategory.is_active == True).order_by(TemplateCategory.sort_order).all()
    return [{"id": c.id, "name": c.name, "code": c.code, "icon": c.icon, "description": c.description} for c in cats]

@router.post("/categories")
async def create_category(
    req: CategoryCreateRequest,
    admin: User = Depends(require_admin_or_above),
    db: Session = Depends(get_db)
):
    """创建模板分类（仅管理员）"""
    existing = db.query(TemplateCategory).filter(TemplateCategory.code == req.code).first()
    if existing:
        raise HTTPException(status_code=400, detail="Category code already exists")

    cat = TemplateCategory(
        id=str(uuid.uuid4()),
        name=req.name,
        code=req.code,
        description=req.description,
        icon=req.icon,
        sort_order=req.sort_order
    )
    db.add(cat)
    db.commit()
    db.refresh(cat)
    return {"id": cat.id, "message": "Category created"}

@router.get("/")
async def list_templates(
    category: Optional[str] = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取模板列表"""
    query = db.query(WritingTemplate).filter(WritingTemplate.is_active == True)
    if category:
        query = query.filter(WritingTemplate.category == category)

    templates = query.order_by(WritingTemplate.sort_order, WritingTemplate.created_at.desc()).all()

    result = []
    for t in templates:
        creator = db.query(User).filter(User.id == t.created_by).first()
        result.append({
            "id": t.id,
            "name": t.name,
            "category": t.category,
            "base_type": t.base_type,
            "description": t.description,
            "icon": t.icon,
            "params_schema": t.params_schema,
            "is_builtin": t.is_builtin,
            "use_count": t.use_count,
            "writing_style": t.writing_style,
            "word_count": t.word_count,
            "need_red_header": t.need_red_header,
            "need_signature": t.need_signature,
            "need_date": t.need_date,
            "need_doc_number": t.need_doc_number,
            "keywords": t.keywords,
            "created_by_name": creator.real_name or creator.username if creator else '系统',
            "created_at": t.created_at.isoformat() if t.created_at else None
        })
    return result

@router.get("/{template_id}")
async def get_template(
    template_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取模板详情"""
    tmpl = db.query(WritingTemplate).filter(WritingTemplate.id == template_id).first()
    if not tmpl:
        raise HTTPException(status_code=404, detail="Template not found")

    return {
        "id": tmpl.id,
        "name": tmpl.name,
        "category": tmpl.category,
        "base_type": tmpl.base_type,
        "description": tmpl.description,
        "icon": tmpl.icon,
        "params_schema": tmpl.params_schema,
        "content_template": tmpl.content_template,
        "system_prompt": tmpl.system_prompt,
        "writing_style": tmpl.writing_style,
        "word_count": tmpl.word_count,
        "need_red_header": tmpl.need_red_header,
        "need_signature": tmpl.need_signature,
        "need_date": tmpl.need_date,
        "need_doc_number": tmpl.need_doc_number,
        "is_builtin": tmpl.is_builtin,
        "is_active": tmpl.is_active,
        "use_count": tmpl.use_count
    }

@router.post("/")
async def create_template(
    req: TemplateCreateRequest,
    admin: User = Depends(require_admin_or_above),
    db: Session = Depends(get_db)
):
    """创建模板（仅管理员/知识管理员）"""
    tmpl = WritingTemplate(
        id=str(uuid.uuid4()),
        name=req.name,
        category=req.category,
        base_type=req.base_type or "公文",
        description=req.description,
        icon=req.icon,
        params_schema=[p.dict() for p in req.params_schema],
        content_template=req.content_template,
        system_prompt=req.system_prompt,
        writing_style=req.writing_style or "正式公文",
        word_count=req.word_count or 1000,
        need_red_header=req.need_red_header if req.need_red_header is not None else False,
        need_signature=req.need_signature if req.need_signature is not None else True,
        need_date=req.need_date if req.need_date is not None else True,
        need_doc_number=req.need_doc_number if req.need_doc_number is not None else False,
        keywords=req.keywords,
        is_builtin=False,
        is_active=True,
        created_by=admin.id,
        sort_order=req.sort_order
    )
    db.add(tmpl)
    db.commit()
    db.refresh(tmpl)
    return {"id": tmpl.id, "message": "Template created"}

@router.put("/{template_id}")
async def update_template(
    template_id: str,
    req: TemplateUpdateRequest,
    admin: User = Depends(require_admin_or_above),
    db: Session = Depends(get_db)
):
    """更新模板（仅管理员/知识管理员）"""
    tmpl = db.query(WritingTemplate).filter(WritingTemplate.id == template_id).first()
    if not tmpl:
        raise HTTPException(status_code=404, detail="Template not found")

    # 内置模板只能修改部分字段
    if tmpl.is_builtin and admin.role != "developer":
        raise HTTPException(status_code=403, detail="Builtin templates can only be modified by system admin")

    if req.name is not None: tmpl.name = req.name
    if req.category is not None: tmpl.category = req.category
    if req.description is not None: tmpl.description = req.description
    if req.icon is not None: tmpl.icon = req.icon
    if req.params_schema is not None: tmpl.params_schema = [p.dict() for p in req.params_schema]
    if req.content_template is not None: tmpl.content_template = req.content_template
    if req.system_prompt is not None: tmpl.system_prompt = req.system_prompt
    if req.is_active is not None: tmpl.is_active = req.is_active
    if req.sort_order is not None: tmpl.sort_order = req.sort_order

    db.commit()
    return {"message": "Template updated"}

@router.delete("/{template_id}")
async def delete_template(
    template_id: str,
    admin: User = Depends(require_admin_or_above),
    db: Session = Depends(get_db)
):
    """删除模板（仅管理员/知识管理员）"""
    tmpl = db.query(WritingTemplate).filter(WritingTemplate.id == template_id).first()
    if not tmpl:
        raise HTTPException(status_code=404, detail="Template not found")

    if tmpl.is_builtin and admin.role != "developer":
        raise HTTPException(status_code=403, detail="Builtin templates can only be deleted by system admin")

    db.delete(tmpl)
    db.commit()
    return {"message": "Template deleted"}

@router.post("/{template_id}/use")
async def use_template(
    template_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """记录模板使用次数"""
    tmpl = db.query(WritingTemplate).filter(WritingTemplate.id == template_id).first()
    if tmpl:
        tmpl.use_count += 1
        db.commit()
    return {"message": "Template use recorded"}
