
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


# =====================================================================
# 内置模板数据 —— 四个一级分类：法定公文 / 工作材料 / 宣传材料 / 其他材料
# 说明：
# - 请示、报告为两个独立模板，互相严格排斥：请示强调"一文一事、请求批准"，
#   结尾"妥否，请批示"；报告只汇报不请求，结尾"特此报告"，均禁止写成"请示报告"。
# - 宣传材料以真实外宣稿（"白云政法""广州司法行政"公众号）为样：标题鲜活、
#   故事化开头、提炼"三步""三心"式工作法，公众号推文不落款、不写成文日期。
# - 请示的第一个字段是"请示标题"（关于××的请示），"请求批准事项"单独
#   作为多行字段——"请示事项"本身就是标题的概括，不再混用。
# =====================================================================
BUILTIN_TEMPLATES = BUILTIN_TEMPLATES = [{'name': '请示', 'category': '法定公文', 'base_type': '请示', 'icon': 'MessageBox', 'description': '用于向上级机关请求指示、批准或解决具体事项，一文一事。', 'writing_style': '正式公文', 'word_count': 1000, 'need_red_header': False, 'need_signature': True, 'need_date': True, 'need_doc_number': False, 'params_schema': [{'name': 'title', 'label': '请示标题', 'type': 'input', 'required': True, 'placeholder': '如：关于申请社区矫正专项工作经费的请示', 'rows': 3, 'options': None}, {'name': 'recipient', 'label': '主送机关', 'type': 'input', 'required': True, 'placeholder': '如：市司法局', 'rows': 3, 'options': None}, {'name': 'reason', 'label': '请示理由', 'type': 'textarea', 'required': True, 'placeholder': '请简述请示的背景、原因和必要性', 'rows': 4, 'options': None}, {'name': 'basis', 'label': '请示依据', 'type': 'textarea', 'required': False, 'placeholder': '相关政策文件或法律依据（如有）', 'rows': 3, 'options': None}, {'name': 'matter', 'label': '请求批准事项', 'type': 'textarea', 'required': True, 'placeholder': '请详细说明需要上级批准或解决的具体事项、金额、时间等', 'rows': 4, 'options': None}, {'name': 'suggestion', 'label': '拟办意见', 'type': 'textarea', 'required': False, 'placeholder': '拟采取的方案或建议（如有）', 'rows': 3, 'options': None}], 'content_template': '请示通常包含：标题（关于××的请示）、主送机关、请示理由、请示依据、请求批准事项、拟办意见、结尾（妥否，请批示）、落款和成文日期。', 'system_prompt': "你是资深的司法行政公文写作专家，只写请示。要求：1.坚持一文一事，一篇请示只请求批准一个事项；2.理由充分、依据明确、引用规范；3.请求事项具体明确，可批复、可执行；4.标题采用'关于××的请示'，结尾规范使用'妥否，请批示'（或'以上请示，请批复'）；5.严格区分请示与报告：全文不得出现'特此报告'等报告结语，文种只称'请示'，严禁写成'请示报告'；6.不得在请示中汇报与请求事项无关的工作情况。请根据用户提供的要素生成规范正文，不要简单填空，未填写的要素不要虚构内容。"}, {'name': '报告', 'category': '法定公文', 'base_type': '报告', 'icon': 'Document', 'description': '用于向上级机关汇报工作、反映情况、回复询问，不得夹带请示事项。', 'writing_style': '正式公文', 'word_count': 1200, 'need_red_header': False, 'need_signature': True, 'need_date': True, 'need_doc_number': False, 'params_schema': [{'name': 'title', 'label': '报告标题', 'type': 'input', 'required': True, 'placeholder': '如：关于2026年上半年社区矫正工作情况的报告', 'rows': 3, 'options': None}, {'name': 'recipient', 'label': '报送对象', 'type': 'input', 'required': True, 'placeholder': '如：市司法局', 'rows': 3, 'options': None}, {'name': 'work', 'label': '工作情况', 'type': 'textarea', 'required': True, 'placeholder': '请简述工作开展情况、主要做法', 'rows': 4, 'options': None}, {'name': 'results', 'label': '取得成效', 'type': 'textarea', 'required': True, 'placeholder': '请简述工作成效、亮点和数据', 'rows': 4, 'options': None}, {'name': 'problems', 'label': '存在问题', 'type': 'textarea', 'required': False, 'placeholder': '请简述存在的问题和不足', 'rows': 3, 'options': None}, {'name': 'next', 'label': '下一步安排', 'type': 'textarea', 'required': True, 'placeholder': '请简述下一步工作安排', 'rows': 3, 'options': None}], 'content_template': '报告通常包含：标题（关于××的报告）、主送机关、工作情况、取得成效、存在问题、下一步安排、结尾（特此报告）、落款和成文日期。', 'system_prompt': "你是资深的司法行政公文写作专家，只写报告。要求：1.重点体现工作情况、取得成效、存在问题、下一步安排；2.报告只用于汇报工作、反映情况、回复询问，不得出现请求批准、请求解决、请予拨付等任何请示性表述；3.标题采用'关于××的报告'，结尾规范使用'特此报告'；4.严格区分报告与请示：全文不得出现'妥否，请批示''请批复'等请示用语，文种只称'报告'，严禁写成'请示报告'；5.数据和成效要具体，问题分析客观。请根据用户提供的要素生成规范正文，不要简单填空，未填写的要素不要虚构内容。"}, {'name': '通知', 'category': '法定公文', 'base_type': '通知', 'icon': 'Bell', 'description': '用于印发工作安排、部署任务、告知事项。', 'writing_style': '正式公文', 'word_count': 800, 'need_red_header': False, 'need_signature': True, 'need_date': True, 'need_doc_number': True, 'params_schema': [{'name': 'title', 'label': '通知标题', 'type': 'input', 'required': True, 'placeholder': '如：关于开展社区矫正专项排查的通知', 'rows': 3, 'options': None}, {'name': 'recipient', 'label': '通知对象', 'type': 'input', 'required': True, 'placeholder': '如：各区县司法局、各司法所', 'rows': 3, 'options': None}, {'name': 'purpose', 'label': '发文目的', 'type': 'textarea', 'required': True, 'placeholder': '请简述发文目的和政策依据', 'rows': 3, 'options': None}, {'name': 'content', 'label': '具体事项', 'type': 'textarea', 'required': True, 'placeholder': '请详细说明通知的具体内容、工作安排和要求', 'rows': 5, 'options': None}, {'name': 'requirements', 'label': '工作要求', 'type': 'textarea', 'required': True, 'placeholder': '请简述工作要求、时间节点和责任人', 'rows': 3, 'options': None}, {'name': 'contact', 'label': '联系人', 'type': 'input', 'required': False, 'placeholder': '如：张三', 'rows': 3, 'options': None}, {'name': 'phone', 'label': '联系电话', 'type': 'input', 'required': False, 'placeholder': '如：020-12345678', 'rows': 3, 'options': None}], 'content_template': '通知类公文通常包含：标题、主送机关、发文目的、具体事项、工作要求、联系人及电话、落款和成文日期。', 'system_prompt': '你是资深的司法行政公文写作专家，擅长撰写政务通知。要求：1.语言正式严谨；2.目的明确、内容具体、要求清晰；3.结构完整。请根据用户提供的要素生成规范正文，不要简单填空，未填写的要素不要虚构内容。'}, {'name': '函', 'category': '法定公文', 'base_type': '函', 'icon': 'Promotion', 'description': '用于不相隶属机关之间商洽工作、询问答复、请求批准事项。', 'writing_style': '正式公文', 'word_count': 800, 'need_red_header': False, 'need_signature': True, 'need_date': True, 'need_doc_number': False, 'params_schema': [{'name': 'title', 'label': '函的标题', 'type': 'input', 'required': True, 'placeholder': '如：关于商请协助开展人民调解员培训的函', 'rows': 3, 'options': None}, {'name': 'recipient', 'label': '主送单位', 'type': 'input', 'required': True, 'placeholder': '如：××区人力资源和社会保障局', 'rows': 3, 'options': None}, {'name': 'reason', 'label': '发函事由', 'type': 'textarea', 'required': True, 'placeholder': '请简述发函的背景和事由', 'rows': 3, 'options': None}, {'name': 'matter', 'label': '商洽/告知事项', 'type': 'textarea', 'required': True, 'placeholder': '请详细说明商洽、询问或告知的具体事项', 'rows': 4, 'options': None}, {'name': 'requirement', 'label': '希望对方配合事项', 'type': 'textarea', 'required': False, 'placeholder': '请说明希望对方办理或回复的事项及时间要求', 'rows': 3, 'options': None}], 'content_template': '函通常包含：标题、主送单位、发函事由、商洽或告知事项、希望对方配合事项、结尾（特此函达/特此函商）、落款和成文日期。', 'system_prompt': "你是资深的司法行政公文写作专家，擅长撰写函。要求：1.行文谦和得体，符合平行文规范；2.事项具体、要求明确；3.结尾规范使用'特此函达'或'特此函商，盼复'。请根据用户提供的要素生成规范正文，不要简单填空，未填写的要素不要虚构内容。"}, {'name': '纪要', 'category': '法定公文', 'base_type': '纪要', 'icon': 'Notebook', 'description': '用于记载会议主要情况和议定事项。', 'writing_style': '正式公文', 'word_count': 800, 'need_red_header': False, 'need_signature': True, 'need_date': True, 'need_doc_number': False, 'params_schema': [{'name': 'meeting_name', 'label': '会议名称', 'type': 'input', 'required': True, 'placeholder': '如：社区矫正工作推进会', 'rows': 3, 'options': None}, {'name': 'time', 'label': '会议时间', 'type': 'input', 'required': True, 'placeholder': '如：2026年7月23日上午9:00', 'rows': 3, 'options': None}, {'name': 'location', 'label': '会议地点', 'type': 'input', 'required': True, 'placeholder': '如：局三楼会议室', 'rows': 3, 'options': None}, {'name': 'host', 'label': '主持人', 'type': 'input', 'required': True, 'placeholder': '如：张局长', 'rows': 3, 'options': None}, {'name': 'attendees', 'label': '参会人员', 'type': 'textarea', 'required': True, 'placeholder': '请列出参会人员', 'rows': 2, 'options': None}, {'name': 'content', 'label': '会议内容', 'type': 'textarea', 'required': True, 'placeholder': '请简述会议主要内容和讨论事项', 'rows': 5, 'options': None}, {'name': 'decisions', 'label': '议定事项', 'type': 'textarea', 'required': True, 'placeholder': '请列出会议议定事项、工作安排和责任人', 'rows': 3, 'options': None}], 'content_template': '会议纪要通常包含：标题、会议基本情况（时间、地点、主持人、参会人员）、会议内容、议定事项、工作要求。', 'system_prompt': '你是资深的司法行政公文写作专家，擅长撰写会议纪要。要求：1.内容真实准确；2.条理清晰、重点突出；3.议定事项明确可执行；4.符合纪要规范表述习惯。请根据用户提供的要素生成规范正文，不要简单填空，未填写的要素不要虚构内容。'}, {'name': '工作计划', 'category': '工作材料', 'base_type': '工作计划', 'icon': 'Calendar', 'description': '用于部署年度、阶段或专项工作的目标、任务和措施。', 'writing_style': '正式公文', 'word_count': 1200, 'need_red_header': False, 'need_signature': True, 'need_date': True, 'need_doc_number': False, 'params_schema': [{'name': 'title', 'label': '计划标题', 'type': 'input', 'required': True, 'placeholder': '如：社区矫正科2026年下半年工作计划', 'rows': 3, 'options': None}, {'name': 'department', 'label': '部门/单位', 'type': 'input', 'required': True, 'placeholder': '如：社区矫正科', 'rows': 3, 'options': None}, {'name': 'period', 'label': '时间范围', 'type': 'input', 'required': True, 'placeholder': '如：2026年下半年', 'rows': 3, 'options': None}, {'name': 'background', 'label': '工作背景', 'type': 'textarea', 'required': False, 'placeholder': '上级要求和总体思路', 'rows': 3, 'options': None}, {'name': 'goals', 'label': '工作目标', 'type': 'textarea', 'required': True, 'placeholder': '请简述阶段工作目标', 'rows': 3, 'options': None}, {'name': 'key_work', 'label': '重点任务', 'type': 'textarea', 'required': True, 'placeholder': '请列出重点工作任务', 'rows': 4, 'options': None}, {'name': 'measures', 'label': '措施安排', 'type': 'textarea', 'required': True, 'placeholder': '请简述落实措施、步骤和时间节点', 'rows': 4, 'options': None}], 'content_template': '工作计划通常包含：标题、工作背景与总体思路、工作目标、重点任务、措施安排、工作要求。', 'system_prompt': '你是资深的司法行政公文写作专家，擅长撰写工作计划。要求：1.目标明确、任务具体、措施可行；2.时间节点清晰、责任明确；3.结构层次分明。请根据用户提供的要素生成规范正文，不要简单填空，未填写的要素不要虚构内容。'}, {'name': '工作总结', 'category': '工作材料', 'base_type': '工作总结', 'icon': 'DocumentChecked', 'description': '用于总结阶段性工作、主要成效、存在问题及下一步安排。', 'writing_style': '正式公文', 'word_count': 1500, 'need_red_header': False, 'need_signature': True, 'need_date': True, 'need_doc_number': False, 'params_schema': [{'name': 'title', 'label': '总结标题', 'type': 'input', 'required': True, 'placeholder': '如：2026年上半年司法行政工作总结', 'rows': 3, 'options': None}, {'name': 'department', 'label': '部门/单位', 'type': 'input', 'required': True, 'placeholder': '如：普法与依法治理科', 'rows': 3, 'options': None}, {'name': 'period', 'label': '时间范围', 'type': 'input', 'required': True, 'placeholder': '如：2026年上半年', 'rows': 3, 'options': None}, {'name': 'completion', 'label': '工作完成情况', 'type': 'textarea', 'required': True, 'placeholder': '请简述各项工作完成情况', 'rows': 4, 'options': None}, {'name': 'achievements', 'label': '主要成效', 'type': 'textarea', 'required': True, 'placeholder': '请简述工作成效、亮点和相关数据', 'rows': 4, 'options': None}, {'name': 'problems', 'label': '存在问题', 'type': 'textarea', 'required': True, 'placeholder': '请简述存在的问题和不足', 'rows': 3, 'options': None}, {'name': 'next_plan', 'label': '下一步工作', 'type': 'textarea', 'required': True, 'placeholder': '请简述下一步工作打算', 'rows': 3, 'options': None}], 'content_template': '工作总结通常包含：标题、工作完成情况、主要成效（数据支撑）、存在问题、下一步工作安排。', 'system_prompt': '你是资深的司法行政公文写作专家，擅长撰写工作总结。要求：1.以完成情况和成效为主体，数据具体；2.问题分析客观；3.下一步安排切实可行。请根据用户提供的要素生成规范正文，不要简单填空，未填写的要素不要虚构内容。'}, {'name': '情况汇报', 'category': '工作材料', 'base_type': '情况汇报', 'icon': 'InfoFilled', 'description': '用于向上级或领导汇报某项工作、某个事件的具体情况。', 'writing_style': '正式公文', 'word_count': 1000, 'need_red_header': False, 'need_signature': True, 'need_date': True, 'need_doc_number': False, 'params_schema': [{'name': 'title', 'label': '汇报标题', 'type': 'input', 'required': True, 'placeholder': '如：关于社区矫正对象脱管情况的汇报', 'rows': 3, 'options': None}, {'name': 'recipient', 'label': '汇报对象', 'type': 'input', 'required': True, 'placeholder': '如：局领导', 'rows': 3, 'options': None}, {'name': 'situation', 'label': '情况说明', 'type': 'textarea', 'required': True, 'placeholder': '请详细说明情况、背景和数据', 'rows': 5, 'options': None}, {'name': 'measures', 'label': '已采取措施', 'type': 'textarea', 'required': True, 'placeholder': '请简述已采取的措施和成效', 'rows': 3, 'options': None}, {'name': 'suggestions', 'label': '工作建议', 'type': 'textarea', 'required': False, 'placeholder': '请简述下一步建议', 'rows': 3, 'options': None}], 'content_template': '情况汇报通常包含：标题、汇报对象、情况说明、已采取措施、工作建议、结尾（特此汇报）。', 'system_prompt': '你是资深的司法行政公文写作专家，擅长撰写情况汇报。要求：1.情况清楚、数据准确；2.措施具体；3.建议可行。请根据用户提供的要素生成规范正文，不要简单填空，未填写的要素不要虚构内容。'}, {'name': '调研报告', 'category': '工作材料', 'base_type': '调研报告', 'icon': 'DataAnalysis', 'description': '用于反映调研成果：基本情况、问题分析、对策建议。', 'writing_style': '正式公文', 'word_count': 2000, 'need_red_header': False, 'need_signature': True, 'need_date': True, 'need_doc_number': False, 'params_schema': [{'name': 'title', 'label': '调研主题', 'type': 'input', 'required': True, 'placeholder': '如：社区矫正工作现状调研报告', 'rows': 3, 'options': None}, {'name': 'department', 'label': '调研部门', 'type': 'input', 'required': True, 'placeholder': '如：社区矫正科', 'rows': 3, 'options': None}, {'name': 'background', 'label': '调研背景', 'type': 'textarea', 'required': True, 'placeholder': '请简述调研背景和目的', 'rows': 3, 'options': None}, {'name': 'method', 'label': '调研方法', 'type': 'textarea', 'required': True, 'placeholder': '请简述调研方法和过程', 'rows': 3, 'options': None}, {'name': 'findings', 'label': '调研发现', 'type': 'textarea', 'required': True, 'placeholder': '请简述调研发现的主要情况和数据', 'rows': 5, 'options': None}, {'name': 'problems', 'label': '存在问题', 'type': 'textarea', 'required': True, 'placeholder': '请简述发现的问题', 'rows': 3, 'options': None}, {'name': 'suggestions', 'label': '对策建议', 'type': 'textarea', 'required': True, 'placeholder': '请提出针对性的对策建议', 'rows': 4, 'options': None}], 'content_template': '调研报告通常包含：标题、调研背景、调研方法、基本情况、存在问题、原因分析、对策建议。', 'system_prompt': '你是资深的司法行政调研报告写作专家。要求：1.数据真实、分析深入；2.问题准确、建议可行；3.结构完整、逻辑清晰。请根据用户提供的要素生成规范正文，不要简单填空，未填写的要素不要虚构内容。'}, {'name': '工作简报', 'category': '工作材料', 'base_type': '工作简报', 'icon': 'Tickets', 'description': '用于编发工作动态简报，简明扼要反映工作进展。', 'writing_style': '正式公文', 'word_count': 800, 'need_red_header': False, 'need_signature': True, 'need_date': True, 'need_doc_number': False, 'params_schema': [{'name': 'title', 'label': '简报标题', 'type': 'input', 'required': True, 'placeholder': '如：我局扎实开展法律援助惠民生活动', 'rows': 3, 'options': None}, {'name': 'department', 'label': '编发单位', 'type': 'input', 'required': True, 'placeholder': '如：局办公室', 'rows': 3, 'options': None}, {'name': 'main_work', 'label': '主要工作', 'type': 'textarea', 'required': True, 'placeholder': '请简述本期简报反映的主要工作和动态', 'rows': 5, 'options': None}, {'name': 'results', 'label': '工作成效', 'type': 'textarea', 'required': False, 'placeholder': '请简述成效和数据', 'rows': 3, 'options': None}, {'name': 'next', 'label': '下步打算', 'type': 'textarea', 'required': False, 'placeholder': '请简述下一步安排', 'rows': 3, 'options': None}], 'content_template': '工作简报通常包含：标题、编发单位、主要工作动态、工作成效、下步打算，篇幅短小精悍。', 'system_prompt': '你是资深的司法行政机关简报写作专家。要求：1.一事一报或一类一报，主题集中；2.篇幅精炼，一般在800字以内；3.表述客观、数据准确。请根据用户提供的要素生成规范正文，不要简单填空，未填写的要素不要虚构内容。'}, {'name': '信息材料', 'category': '工作材料', 'base_type': '信息材料', 'icon': 'Document', 'description': '用于向上级报送政务信息：做法、成效、问题建议类信息。', 'writing_style': '正式公文', 'word_count': 600, 'need_red_header': False, 'need_signature': True, 'need_date': True, 'need_doc_number': False, 'params_schema': [{'name': 'title', 'label': '信息标题', 'type': 'input', 'required': True, 'placeholder': '如：××区司法局三举措提升社区矫正质效', 'rows': 3, 'options': None}, {'name': 'theme', 'label': '信息主题', 'type': 'textarea', 'required': True, 'placeholder': '请简述信息反映的核心内容', 'rows': 4, 'options': None}, {'name': 'data', 'label': '数据成效', 'type': 'textarea', 'required': False, 'placeholder': '相关数据和成效', 'rows': 3, 'options': None}, {'name': 'note', 'label': '补充说明', 'type': 'textarea', 'required': False, 'placeholder': '其他需要说明的情况', 'rows': 3, 'options': None}], 'content_template': '政务信息通常包含：标题（概括做法或成效）、导语、主体内容、数据成效，篇幅短小。', 'system_prompt': '你是资深的政务信息写作专家。要求：1.标题即观点，概括做法或成效；2.篇幅短小精炼；3.数据和事例具体。请根据用户提供的要素生成规范正文，不要简单填空，未填写的要素不要虚构内容。'}, {'name': '外宣信息', 'category': '宣传材料', 'base_type': '外宣信息', 'icon': 'Promotion', 'description': '用于在“白云政法”“广州司法行政”等公众号刊发的宣传信息（推文），标题鲜活、以事带法。', 'writing_style': '公众号推文', 'word_count': 800, 'need_red_header': False, 'need_signature': False, 'need_date': False, 'need_doc_number': False, 'params_schema': [{'name': 'theme', 'label': '宣传主题', 'type': 'input', 'required': True, 'placeholder': '如：司法所化解预付充值消费纠纷 / 宪法宣传进校园', 'rows': 3, 'options': None}, {'name': 'unit', 'label': '供稿单位', 'type': 'input', 'required': True, 'placeholder': '如：鹤龙司法所', 'rows': 3, 'options': None}, {'name': 'story', 'label': '事例或现场', 'type': 'textarea', 'required': True, 'placeholder': '请简述一件具体事例、纠纷经过或活动现场情景（外宣稿用它开头讲故事）', 'rows': 4, 'options': None}, {'name': 'practices', 'label': '做法亮点', 'type': 'textarea', 'required': True, 'placeholder': "请简述主要做法和特色，如可提炼为'三步''三心''三链'等工作法更好", 'rows': 4, 'options': None}, {'name': 'data', 'label': '数据成效', 'type': 'textarea', 'required': False, 'placeholder': '如：调解成功率、参与人数、挽回损失金额等', 'rows': 3, 'options': None}], 'content_template': '外宣信息（公众号推文）通常包含：吸睛标题（疑问式/感叹式/引号提炼式）、事例或现场开头、做法与亮点（可提炼工作法）、数据成效、简短结尾（理念或下一步）。不出现主送机关、落款和成文日期。', 'system_prompt': "你是资深政法新媒体编辑，为司法局公众号撰写外宣推文。要求：1.标题必须鲜活吸睛，优先采用疑问式（如'卡充了，用不了？鹤龙司法所高效化解预付充值消费纠纷'）、感叹式（如'法治护航广交会！三元里司法所将法律服务送到客商家门口'）或引号提炼式（如'“四阶”赋能打造法治化营商环境''“三步”矫正工作法铺就新生路'），可恰当用谐音（如'精彩呈“宪”'），标题即看点；2.正文用一件具体事例、一场纠纷或一个现场开头讲故事，再自然带出做法与成效，不要公文式导语；3.做法能提炼就提炼为'三步''三心''三链''四阶'式工作法并加引号；4.语言鲜活有温度、段落短小，可用问号感叹号，严禁'一、（一）、1.'式公文分条和'现将有关情况报告如下'式套话；5.数据真实准确，用户未提供的数据不要编造，用定性表述；6.结尾一两句话点出理念或下一步打算；全文不出现主送机关、发文机关署名和成文日期。请根据用户提供的要素生成推文正文，不要简单填空，未填写的要素不要虚构内容。", 'keywords': '公众号推文；标题吸睛；故事化开头；提炼工作法；无落款无成文日期'}, {'name': '新闻稿', 'category': '宣传材料', 'base_type': '新闻稿', 'icon': 'Postcard', 'description': '用于向媒体、政务网站供稿的工作动态消息，突出新闻性和亮点。', 'writing_style': '媒体通讯', 'word_count': 800, 'need_red_header': False, 'need_signature': False, 'need_date': False, 'need_doc_number': False, 'params_schema': [{'name': 'title', 'label': '新闻稿标题', 'type': 'input', 'required': True, 'placeholder': '如：白云区成立首个驻拘留所调解工作室 / 200余个岗位精准对接法学英才', 'rows': 3, 'options': None}, {'name': 'event', 'label': '事件/活动', 'type': 'textarea', 'required': True, 'placeholder': '请简述新闻事件或活动的基本情况（谁、何时、何地、做了什么）', 'rows': 4, 'options': None}, {'name': 'when_where', 'label': '时间地点', 'type': 'input', 'required': False, 'placeholder': '如：8月20日，局三楼会议室', 'rows': 3, 'options': None}, {'name': 'highlights', 'label': '重点亮点', 'type': 'textarea', 'required': False, 'placeholder': '请简述值得宣传的重点、亮点', 'rows': 3, 'options': None}, {'name': 'results', 'label': '成果成效', 'type': 'textarea', 'required': False, 'placeholder': '请简述取得的成果和下一步安排', 'rows': 3, 'options': None}], 'content_template': '新闻稿通常包含：标题、导语（时间地点事件）、主体（过程、亮点、成果）、结尾（下一步或意义）。', 'system_prompt': "你是资深政法新闻记者。要求：1.标题突出新闻点和亮点，可直陈也可带感叹语气，如'拘调衔接止纷争，多元共治护平安！白云区成立首个驻拘留所调解工作室'；2.导语一段说清何时何地何事及意义；3.主体写清做法、现场和反响，数据具体；4.语言准确积极、有现场感，不用公文分条；5.不写主送机关、落款和成文日期。请根据用户提供的要素生成规范正文，不要简单填空，未填写的要素不要虚构内容。"}, {'name': '活动报道', 'category': '宣传材料', 'base_type': '活动报道', 'icon': 'Flag', 'description': '用于公众号刊发普法宣传、法律援助、社区矫正等活动推文，现场感强、有温度。', 'writing_style': '公众号推文', 'word_count': 700, 'need_red_header': False, 'need_signature': False, 'need_date': False, 'need_doc_number': False, 'params_schema': [{'name': 'title', 'label': '报道标题', 'type': 'input', 'required': True, 'placeholder': "如：上好'开学第一课'，点亮'平安新学期' / 法治启蒙，安全'童'行", 'rows': 3, 'options': None}, {'name': 'activity', 'label': '活动名称', 'type': 'input', 'required': True, 'placeholder': '如：民法典进社区普法宣传活动', 'rows': 3, 'options': None}, {'name': 'time', 'label': '活动时间地点', 'type': 'input', 'required': False, 'placeholder': '如：8月15日，××社区文化广场', 'rows': 3, 'options': None}, {'name': 'content', 'label': '活动内容', 'type': 'textarea', 'required': True, 'placeholder': '请简述活动过程、形式、参与人员和现场细节（互动的问答、群众的反应）', 'rows': 4, 'options': None}, {'name': 'effect', 'label': '活动效果', 'type': 'textarea', 'required': False, 'placeholder': '请简述活动效果和群众反响', 'rows': 3, 'options': None}], 'content_template': '活动报道通常包含：标题、活动时间地点、活动内容和形式、参与情况、活动效果。', 'system_prompt': "你是资深政法新媒体编辑，撰写活动报道推文。要求：1.标题活泼，可对仗、谐音或感叹（如'当非遗箫声遇上法治教育！这堂特殊课程入脑更入心'）；2.以现场画面或群众互动开头，再写活动内容和参与情况；3.突出实效和群众反响，可引用参与者一两句原话（用户提供才有）；4.语言生动、段落短小，严禁公文腔；5.不写主送机关、落款和成文日期。请根据用户提供的要素生成规范正文，不要简单填空，未填写的要素不要虚构内容。"}, {'name': '经验做法', 'category': '宣传材料', 'base_type': '经验做法', 'icon': 'Star', 'description': "用于提炼本单位特色做法、创新机制的信息，提炼'三步''三心''三链'式工作法。", 'writing_style': '正式公文', 'word_count': 1200, 'need_red_header': False, 'need_signature': True, 'need_date': True, 'need_doc_number': False, 'params_schema': [{'name': 'title', 'label': '经验材料标题', 'type': 'input', 'required': True, 'placeholder': "如：'四阶'赋能打造皮具商圈法治化营商环境 / '三源治理'破解矛盾困局", 'rows': 3, 'options': None}, {'name': 'background', 'label': '工作背景', 'type': 'textarea', 'required': False, 'placeholder': '请简述该项工作的背景和针对的问题', 'rows': 3, 'options': None}, {'name': 'practices', 'label': '主要做法', 'type': 'textarea', 'required': True, 'placeholder': '请分条列出主要做法，每条尽量用一句话概括（如：第一步摸排建档、第二步分类施策）', 'rows': 5, 'options': None}, {'name': 'results', 'label': '取得成效', 'type': 'textarea', 'required': True, 'placeholder': '请简述成效，最好有数据支撑', 'rows': 3, 'options': None}], 'content_template': '经验做法材料通常包含：标题（概括特色做法）、背景与问题、主要做法（分条）、取得成效（数据支撑）、启示。', 'system_prompt': "你是资深的司法行政经验材料写作专家。要求：1.标题概括特色做法，优先提炼并命名工作法（如'四阶'赋能、'三链'协同、'五心'服务、'三源治理'），加引号使用；2.做法分条提炼、每条有小标题式概括，可复制可推广；3.成效有数据支撑；4.语言凝练，对仗工整但不堆砌。请根据用户提供的要素生成规范正文，不要简单填空，未填写的要素不要虚构内容。"}, {'name': '典型案例宣传', 'category': '宣传材料', 'base_type': '典型案例', 'icon': 'Collection', 'description': '用于宣传调解、援助、矫正等典型案例，故事化叙述、以案释法。', 'writing_style': '公众号推文', 'word_count': 1000, 'need_red_header': False, 'need_signature': False, 'need_date': False, 'need_doc_number': False, 'params_schema': [{'name': 'title', 'label': '案例标题', 'type': 'input', 'required': True, 'placeholder': "如：合同纠纷僵持多日无果？'人民调解+司法确认'帮大忙 / 一天调解追回三年欠款", 'rows': 3, 'options': None}, {'name': 'case_bg', 'label': '案例背景', 'type': 'textarea', 'required': True, 'placeholder': '请简述纠纷起因和当事人情况（隐去真实姓名）', 'rows': 3, 'options': None}, {'name': 'process', 'label': '办理经过', 'type': 'textarea', 'required': True, 'placeholder': '请简述调解/办理经过、转折点和关键环节', 'rows': 4, 'options': None}, {'name': 'result', 'label': '处理结果与启示', 'type': 'textarea', 'required': True, 'placeholder': '请简述处理结果、社会效果和启示', 'rows': 3, 'options': None}], 'content_template': '典型案例宣传通常包含：标题、案例背景、办理经过、处理结果、典型意义/启示。', 'system_prompt': "你是资深的法治宣传写作专家，撰写故事化案例推文。要求：1.标题用疑问式或悬念式勾起阅读欲（如'要么随迁要么离职？综治中心一站式速解劳动合同纠纷'）；2.按'纠纷起因—调解经过—圆满化解'讲故事，有细节、有转折；3.自然带出'人民调解+司法确认'等机制的作用，结尾一句话以案释法；4.隐去当事人真实姓名（用××或化名）；5.语言鲜活、段落短小，不用公文分条；6.不写主送机关、落款和成文日期。请根据用户提供的要素生成规范正文，不要简单填空，未填写的要素不要虚构内容。"}, {'name': '讲话稿', 'category': '其他材料', 'base_type': '讲话稿', 'icon': 'Microphone', 'description': '用于领导在会议、活动上的讲话。', 'writing_style': '领导讲话', 'word_count': 1500, 'need_red_header': False, 'need_signature': True, 'need_date': True, 'need_doc_number': False, 'params_schema': [{'name': 'title', 'label': '讲话稿标题', 'type': 'input', 'required': True, 'placeholder': '如：在全局上半年工作总结会议上的讲话', 'rows': 3, 'options': None}, {'name': 'occasion', 'label': '讲话场合', 'type': 'input', 'required': True, 'placeholder': '如：全局上半年工作总结会议', 'rows': 3, 'options': None}, {'name': 'speaker', 'label': '讲话人职务', 'type': 'input', 'required': False, 'placeholder': '如：局党组书记、局长', 'rows': 3, 'options': None}, {'name': 'topic', 'label': '讲话主题', 'type': 'textarea', 'required': True, 'placeholder': '请简述讲话要围绕的主题', 'rows': 3, 'options': None}, {'name': 'points', 'label': '讲话要点', 'type': 'textarea', 'required': True, 'placeholder': '请列出要讲的主要内容要点', 'rows': 5, 'options': None}], 'content_template': '讲话稿通常包含：标题、称谓、开场白、主体（分部分阐述）、结尾（提出要求或希望）。', 'system_prompt': "你是资深的领导讲话稿写作专家。要求：1.符合领导讲话口吻，有号召力；2.层次分明，常用'一、二、三'式结构；3.语言庄重凝练。请根据用户提供的要素生成规范正文，不要简单填空，未填写的要素不要虚构内容。"}, {'name': '主持词', 'category': '其他材料', 'base_type': '主持词', 'icon': 'Guide', 'description': '用于会议主持：开场白、议程串联、结束语。', 'writing_style': '正式公文', 'word_count': 800, 'need_red_header': False, 'need_signature': True, 'need_date': True, 'need_doc_number': False, 'params_schema': [{'name': 'meeting_name', 'label': '会议名称', 'type': 'input', 'required': True, 'placeholder': '如：2026年上半年工作总结会议', 'rows': 3, 'options': None}, {'name': 'time', 'label': '会议时间', 'type': 'input', 'required': False, 'placeholder': '如：8月20日上午', 'rows': 3, 'options': None}, {'name': 'host', 'label': '主持人职务', 'type': 'input', 'required': False, 'placeholder': '如：副局长', 'rows': 3, 'options': None}, {'name': 'agenda', 'label': '会议议程', 'type': 'textarea', 'required': True, 'placeholder': '请列出会议各环节安排', 'rows': 5, 'options': None}], 'content_template': '主持词通常包含：开场白（宣布开会、介绍参会情况）、议程串联词、结束语（贯彻要求）。', 'system_prompt': '你是资深的会议主持词写作专家。要求：1.开场庄重、串联自然、收尾有力；2.符合领导讲话习惯；3.各环节衔接紧凑。请根据用户提供的要素生成规范正文，不要简单填空，未填写的要素不要虚构内容。'}, {'name': '发言稿', 'category': '其他材料', 'base_type': '发言稿', 'icon': 'ChatLineSquare', 'description': '用于座谈、交流、表态等场合的个人或单位发言。', 'writing_style': '正式公文', 'word_count': 1000, 'need_red_header': False, 'need_signature': True, 'need_date': True, 'need_doc_number': False, 'params_schema': [{'name': 'title', 'label': '发言标题', 'type': 'input', 'required': True, 'placeholder': '如：在全市司法行政工作座谈会上的发言', 'rows': 3, 'options': None}, {'name': 'occasion', 'label': '发言场合', 'type': 'input', 'required': True, 'placeholder': '如：全市司法行政工作座谈会', 'rows': 3, 'options': None}, {'name': 'topic', 'label': '发言主题', 'type': 'textarea', 'required': True, 'placeholder': '请简述发言主题', 'rows': 3, 'options': None}, {'name': 'points', 'label': '发言要点', 'type': 'textarea', 'required': True, 'placeholder': '请列出主要内容和观点', 'rows': 4, 'options': None}], 'content_template': '发言稿通常包含：标题、称谓、开场、主体内容、结尾表态。', 'system_prompt': '你是资深的发言材料写作专家。要求：1.紧扣主题、观点鲜明；2.语言朴实得体；3.篇幅适中。请根据用户提供的要素生成规范正文，不要简单填空，未填写的要素不要虚构内容。'}, {'name': '工作方案', 'category': '其他材料', 'base_type': '工作方案', 'icon': 'SetUp', 'description': '用于部署专项工作：目标、内容、分工、保障措施。', 'writing_style': '正式公文', 'word_count': 1200, 'need_red_header': False, 'need_signature': True, 'need_date': True, 'need_doc_number': False, 'params_schema': [{'name': 'title', 'label': '方案标题', 'type': 'input', 'required': True, 'placeholder': '如：社区矫正专项排查整治工作方案', 'rows': 3, 'options': None}, {'name': 'background', 'label': '背景目的', 'type': 'textarea', 'required': True, 'placeholder': '请简述制定方案的背景和目的', 'rows': 3, 'options': None}, {'name': 'content', 'label': '工作内容', 'type': 'textarea', 'required': True, 'placeholder': '请简述主要工作内容和时间安排', 'rows': 4, 'options': None}, {'name': 'division', 'label': '组织分工', 'type': 'textarea', 'required': True, 'placeholder': '请简述组织架构和责任分工', 'rows': 3, 'options': None}, {'name': 'guarantee', 'label': '保障措施', 'type': 'textarea', 'required': False, 'placeholder': '请简述保障措施和工作要求', 'rows': 3, 'options': None}], 'content_template': '工作方案通常包含：标题、指导思想/背景目的、工作目标、主要内容和步骤、组织分工、保障措施。', 'system_prompt': '你是资深的司法行政方案写作专家。要求：1.目标明确、步骤清晰；2.分工具体、责任到人；3.措施可操作。请根据用户提供的要素生成规范正文，不要简单填空，未填写的要素不要虚构内容。'}, {'name': '活动方案', 'category': '其他材料', 'base_type': '活动方案', 'icon': 'Flag', 'description': '用于策划普法宣传、志愿服务等具体活动。', 'writing_style': '正式公文', 'word_count': 1000, 'need_red_header': False, 'need_signature': True, 'need_date': True, 'need_doc_number': False, 'params_schema': [{'name': 'title', 'label': '方案标题', 'type': 'input', 'required': True, 'placeholder': "如：'宪法宣传周'系列活动方案", 'rows': 3, 'options': None}, {'name': 'activity', 'label': '活动名称', 'type': 'input', 'required': True, 'placeholder': '如：宪法宣传周系列活动', 'rows': 3, 'options': None}, {'name': 'time', 'label': '时间地点', 'type': 'input', 'required': False, 'placeholder': '如：12月1日至7日，各司法所辖区', 'rows': 3, 'options': None}, {'name': 'content', 'label': '活动安排', 'type': 'textarea', 'required': True, 'placeholder': '请简述活动内容、形式和日程', 'rows': 4, 'options': None}, {'name': 'division', 'label': '分工保障', 'type': 'textarea', 'required': False, 'placeholder': '请简述责任分工和保障措施', 'rows': 3, 'options': None}], 'content_template': '活动方案通常包含：标题、活动目的、时间地点、参与对象、内容安排、责任分工、保障措施。', 'system_prompt': '你是资深的活动方案写作专家。要求：1.安排具体、可落地；2.分工明确；3.考虑安全等保障因素。请根据用户提供的要素生成规范正文，不要简单填空，未填写的要素不要虚构内容。'}, {'name': '汇报提纲', 'category': '其他材料', 'base_type': '汇报提纲', 'icon': 'List', 'description': '用于口头汇报前搭建框架：要点式提纲。', 'writing_style': '正式公文', 'word_count': 600, 'need_red_header': False, 'need_signature': True, 'need_date': True, 'need_doc_number': False, 'params_schema': [{'name': 'title', 'label': '汇报主题', 'type': 'input', 'required': True, 'placeholder': '如：上半年社区矫正工作汇报', 'rows': 3, 'options': None}, {'name': 'recipient', 'label': '汇报对象', 'type': 'input', 'required': False, 'placeholder': '如：局党组会', 'rows': 3, 'options': None}, {'name': 'points', 'label': '汇报要点', 'type': 'textarea', 'required': True, 'placeholder': '请列出要汇报的主要内容要点', 'rows': 5, 'options': None}], 'content_template': '汇报提纲通常包含：汇报主题、总体情况、重点工作进展、存在问题、下一步打算，以要点式呈现。', 'system_prompt': '你是资深的机关汇报材料写作专家。要求：1.要点式呈现，每条一句话概括+简要展开；2.逻辑清晰、详略得当。请根据用户提供的要素生成规范正文，不要简单填空，未填写的要素不要虚构内容。'}, {'name': '执法文书', 'category': '其他材料', 'base_type': '执法文书', 'icon': 'DocumentCopy', 'description': '用于行政执法过程中的笔录、告知、决定等文书。', 'writing_style': '正式公文', 'word_count': 800, 'need_red_header': False, 'need_signature': True, 'need_date': True, 'need_doc_number': False, 'params_schema': [{'name': 'doc_type', 'label': '文书类型', 'type': 'select', 'required': True, 'placeholder': '', 'rows': 3, 'options': [{'label': '调查笔录', 'value': '调查笔录'}, {'label': '告知书', 'value': '告知书'}, {'label': '决定书', 'value': '决定书'}, {'label': '通知书', 'value': '通知书'}]}, {'name': 'party', 'label': '当事人', 'type': 'input', 'required': True, 'placeholder': '如：王某某', 'rows': 3, 'options': None}, {'name': 'id_number', 'label': '身份证号', 'type': 'input', 'required': False, 'placeholder': '如：440XXXXXXXXXXXXXXX', 'rows': 3, 'options': None}, {'name': 'facts', 'label': '事实经过', 'type': 'textarea', 'required': True, 'placeholder': '请简述事实经过', 'rows': 4, 'options': None}, {'name': 'basis', 'label': '法律依据', 'type': 'textarea', 'required': True, 'placeholder': '请列出法律依据', 'rows': 3, 'options': None}, {'name': 'decision', 'label': '处理决定', 'type': 'textarea', 'required': True, 'placeholder': '请说明处理决定', 'rows': 3, 'options': None}], 'content_template': '执法文书通常包含：标题、当事人信息、事实经过、法律依据、处理决定、签名栏和日期。', 'system_prompt': '你是资深的司法行政执法文书写作专家。要求：1.事实清楚、证据确凿；2.依据准确、引用规范；3.程序合法、格式规范。请根据用户提供的要素生成规范正文，不要简单填空，未填写的要素不要虚构内容。'}]


BUILTIN_CATEGORIES = [
    {"name": "法定公文", "code": "statutory", "icon": "Stamp", "sort_order": 1},
    {"name": "工作材料", "code": "work", "icon": "DocumentChecked", "sort_order": 2},
    {"name": "宣传材料", "code": "publicity", "icon": "Promotion", "sort_order": 3},
    {"name": "其他材料", "code": "other", "icon": "Folder", "sort_order": 4},
]

# 旧分类 code（/init 时自动停用）
_DEPRECATED_CATEGORY_CODES = [
    "plan_summary", "request_report", "notice", "research", "meeting",
    "report", "legal_doc", "work_summary", "work_plan",
]
# 旧内置模板（按旧分类名下的内置模板整批停用，不影响新分类下的同名新模板和用户自建模板）
_DEPRECATED_CATEGORY_NAMES = [
    "计划总结", "请示报告", "通知公告", "调研报告", "会议纪要", "情况汇报", "执法文书",
]
_DEPRECATED_BUILTIN_NAMES = ["年度工作总结", "工作计划", "请示报告"]  # 合并前的历史遗留名称（含“请示报告”混用文种）

# ========== Pydantic 模型 ==========

class TemplateParam(BaseModel):
    name: str
    label: str
    type: str  # input, textarea, select, date
    required: bool = False
    placeholder: str = ""
    options: Optional[List[Dict[str, str]]] = None
    rows: int = 2

class StructureItem(BaseModel):
    name: str                      # 结构项名称，如"请示理由"
    guide: Optional[str] = ""      # 该部分的写作要求（选填）

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
    # —— 新版新建模板设计 ——
    template_kind: Optional[str] = "official_doc"   # official_doc=公文模板(有固定结构) / writing_ref=写作参考模板(无固定结构)
    tags: Optional[List[str]] = []                  # 模板标签
    scene: Optional[str] = ""                       # 适用场景
    writing_guide: Optional[str] = ""               # 写作要点与注意事项
    structure: Optional[List[StructureItem]] = []   # 结构设置（仅公文模板）
    kb_ids: Optional[List[str]] = []                # 关联知识库
    visibility: Optional[str] = "official"          # official=官方模板 / personal=个人模板
    share_scope: Optional[str] = "all"              # all=全平台共享 / department=指定部门 / role=指定角色
    share_departments: Optional[List[str]] = []
    share_roles: Optional[List[str]] = []
    is_draft: Optional[bool] = False                # 保存草稿

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
    # —— 新版新建模板设计 ——
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
    """初始化/同步内置模板（仅管理员）

    幂等：可重复调用。
    - 新内置模板不存在则创建；
    - 已存在的内置模板按代码中的最新定义整体更新（保留 id 与使用统计）；
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

    # 停用旧分类下的内置模板（只影响 is_builtin=True 的，不动用户自建模板）
    db.query(WritingTemplate).filter(
        WritingTemplate.category.in_(_DEPRECATED_CATEGORY_NAMES + _DEPRECATED_BUILTIN_NAMES),
        WritingTemplate.is_builtin == True
    ).update({"is_active": False}, synchronize_session=False)
    db.commit()

    # 初始化/同步模板：不存在则创建；已存在则按最新内置定义整体更新
    # （保证后端代码里改过的字段、提示词、占位示例能落到数据库，无需手工清库）
    count = 0
    updated = 0
    for tmpl in BUILTIN_TEMPLATES:
        existing = db.query(WritingTemplate).filter(
            WritingTemplate.name == tmpl["name"],
            WritingTemplate.is_builtin == True
        ).first()
        if existing:
            existing.category = tmpl["category"]
            existing.base_type = tmpl.get("base_type", "公文")
            existing.description = tmpl.get("description", "")
            existing.icon = tmpl["icon"]
            existing.params_schema = tmpl["params_schema"]
            existing.content_template = tmpl["content_template"]
            existing.system_prompt = tmpl.get("system_prompt", "")
            existing.writing_style = tmpl.get("writing_style", "正式公文")
            existing.word_count = tmpl.get("word_count", 1000)
            existing.need_red_header = tmpl.get("need_red_header", False)
            existing.need_signature = tmpl.get("need_signature", True)
            existing.need_date = tmpl.get("need_date", True)
            existing.need_doc_number = tmpl.get("need_doc_number", False)
            existing.keywords = tmpl.get("keywords", None)
            updated += 1
            continue
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

    return {"message": f"Initialized {count} builtin templates, updated {updated}"}

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
    """获取模板列表（含可见性过滤，需求：模板权限与共享）

    - 官方模板：按共享范围过滤（全平台 / 指定部门 / 指定角色）；
    - 个人模板：仅创建者本人可见；
    - 草稿：仅创建者和管理员可见；
    - 管理员可见全部。
    """
    query = db.query(WritingTemplate).filter(WritingTemplate.is_active == True)
    if category:
        query = query.filter(WritingTemplate.category == category)

    templates = query.order_by(WritingTemplate.sort_order, WritingTemplate.created_at.desc()).all()

    is_admin = user.role in ["developer", "knowledge_admin", "admin"]

    def _visible(t) -> bool:
        if is_admin:
            return True
        if getattr(t, "is_draft", False):
            return t.created_by == user.id
        visibility = getattr(t, "visibility", "official") or "official"
        if visibility == "personal":
            return t.created_by == user.id
        scope = getattr(t, "share_scope", "all") or "all"
        if scope == "all":
            return True
        if scope == "department":
            return bool(user.department) and user.department in (getattr(t, "share_departments", None) or [])
        if scope == "role":
            return user.role in (getattr(t, "share_roles", None) or [])
        return True

    templates = [t for t in templates if _visible(t)]

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
            "template_kind": getattr(t, "template_kind", "official_doc"),
            "tags": getattr(t, "tags", None) or [],
            "scene": getattr(t, "scene", "") or "",
            "writing_guide": getattr(t, "writing_guide", "") or "",
            "structure": getattr(t, "structure", None) or [],
            "kb_ids": getattr(t, "kb_ids", None) or [],
            "visibility": getattr(t, "visibility", "official") or "official",
            "share_scope": getattr(t, "share_scope", "all") or "all",
            "share_departments": getattr(t, "share_departments", None) or [],
            "share_roles": getattr(t, "share_roles", None) or [],
            "is_draft": bool(getattr(t, "is_draft", False)),
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
    admin: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """创建模板。

    权限（新版设计）：
    - 官方模板（visibility=official）：仅管理员/知识管理员可建；
    - 个人模板（visibility=personal）：任何登录用户可建，仅自己可见可用。
    """
    visibility = req.visibility or "official"
    if visibility == "official" and admin.role not in ["developer", "knowledge_admin", "admin"]:
        raise HTTPException(status_code=403, detail="官方模板仅管理员可创建，请选择'个人模板'")
    if req.is_draft is None:
        req.is_draft = False
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
    # —— 新版字段（写入 doc 式扩展属性，模型列由 main.py 自动迁移补齐）——
    tmpl.template_kind = req.template_kind or "official_doc"
    tmpl.tags = req.tags or []
    tmpl.scene = req.scene or ""
    tmpl.writing_guide = req.writing_guide or ""
    tmpl.structure = [s.dict() for s in (req.structure or [])]
    tmpl.kb_ids = req.kb_ids or []
    tmpl.visibility = visibility
    tmpl.share_scope = req.share_scope or "all"
    tmpl.share_departments = req.share_departments or []
    tmpl.share_roles = req.share_roles or []
    tmpl.is_draft = bool(req.is_draft)
    # 写作参考模板：无固定结构，生成 content_template 兜底，写作要点并入 system_prompt
    if tmpl.template_kind == "writing_ref":
        tmpl.params_schema = tmpl.params_schema or []
        if not tmpl.content_template:
            tmpl.content_template = req.writing_guide or req.description or "自由结构：AI 根据任务灵活组织文章"
        if req.writing_guide and req.writing_guide not in (tmpl.system_prompt or ""):
            tmpl.system_prompt = ((tmpl.system_prompt or "") + "\n写作要点与注意事项：" + req.writing_guide).strip()
    db.add(tmpl)
    db.commit()
    db.refresh(tmpl)
    return {"id": tmpl.id, "message": "Template created", "is_draft": tmpl.is_draft}

@router.put("/{template_id}")
async def update_template(
    template_id: str,
    req: TemplateUpdateRequest,
    admin: User = Depends(require_admin_or_above),
    db: Session = Depends(get_db)
):
    """更新模板。官方/内置模板仅管理员；个人模板创建者本人可改。"""
    tmpl = db.query(WritingTemplate).filter(WritingTemplate.id == template_id).first()
    if not tmpl:
        raise HTTPException(status_code=404, detail="Template not found")

    # 内置模板只能修改部分字段
    if tmpl.is_builtin and admin.role != "developer":
        raise HTTPException(status_code=403, detail="Builtin templates can only be modified by system admin")
    is_owner_personal = (getattr(tmpl, "visibility", "official") == "personal"
                         and tmpl.created_by == admin.id)
    if admin.role not in ["developer", "knowledge_admin", "admin"] and not is_owner_personal:
        raise HTTPException(status_code=403, detail="无权修改该模板")

    if req.name is not None: tmpl.name = req.name
    if req.category is not None: tmpl.category = req.category
    if req.description is not None: tmpl.description = req.description
    if req.icon is not None: tmpl.icon = req.icon
    if req.params_schema is not None: tmpl.params_schema = [p.dict() for p in req.params_schema]
    if req.content_template is not None: tmpl.content_template = req.content_template
    if req.system_prompt is not None: tmpl.system_prompt = req.system_prompt
    if req.is_active is not None: tmpl.is_active = req.is_active
    if req.sort_order is not None: tmpl.sort_order = req.sort_order
    # —— 新版字段 ——
    if req.template_kind is not None: tmpl.template_kind = req.template_kind
    if req.tags is not None: tmpl.tags = req.tags
    if req.scene is not None: tmpl.scene = req.scene
    if req.writing_guide is not None:
        tmpl.writing_guide = req.writing_guide
        if getattr(tmpl, "template_kind", "official_doc") == "writing_ref" \
                and req.writing_guide not in (tmpl.system_prompt or ""):
            tmpl.system_prompt = ((tmpl.system_prompt or "") + "\n写作要点与注意事项：" + req.writing_guide).strip()
    if req.structure is not None: tmpl.structure = [s.dict() for s in req.structure]
    if req.kb_ids is not None: tmpl.kb_ids = req.kb_ids
    if req.visibility is not None:
        if req.visibility == "official" and admin.role not in ["developer", "knowledge_admin", "admin"]:
            raise HTTPException(status_code=403, detail="官方模板仅管理员可设置")
        tmpl.visibility = req.visibility
    if req.share_scope is not None: tmpl.share_scope = req.share_scope
    if req.share_departments is not None: tmpl.share_departments = req.share_departments
    if req.share_roles is not None: tmpl.share_roles = req.share_roles
    if req.is_draft is not None: tmpl.is_draft = req.is_draft

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
