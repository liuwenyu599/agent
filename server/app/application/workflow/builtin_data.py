"""内置工作流模板定义（与旧系统 BUILTIN_WORKFLOWS 一致）。"""
from typing import Any, Dict, List

BUILTIN_WORKFLOWS: List[Dict[str, Any]] = [
    {
        "code": "meeting", "name": "会议组织", "category": "综合",
        "description": "会议全流程：基础信息、通知、议程、签到、主持稿、纪要、简报、归档",
        "nodes": [
            {"name": "基础信息", "stage": "会前", "write_guide": "维护会议结构化信息：名称、时间、地点、主题、主办部门、参会范围等。此节点不生成独立文本，直接编辑工作流核心数据。"},
            {"name": "会议通知", "stage": "会前", "write_guide": "起草正式会议通知：会议时间地点、参会人员、会议内容、有关要求，符合公文格式。"},
            {"name": "参会人员", "stage": "会前", "write_guide": "整理参会人员名单：姓名、单位、职务，分组排列。"},
            {"name": "会议议程", "stage": "会前", "write_guide": "生成会议详细议程安排：各环节内容、时间、主持人、发言人。"},
            {"name": "签到表", "stage": "会中", "write_guide": "生成签到表：序号、姓名、单位、职务、联系电话、签到栏。"},
            {"name": "主持稿", "stage": "会中", "write_guide": "起草会议主持稿：开场白、议程串联词、结束语，符合领导讲话习惯。"},
            {"name": "会议材料", "stage": "会中", "write_guide": "整理会上印发/汇报使用的会议材料。"},
            {"name": "会议纪要", "stage": "会后", "write_guide": "起草会议纪要：会议基本情况、议定事项、工作要求，符合纪要规范。"},
            {"name": "简报/新闻稿", "stage": "会后", "write_guide": "撰写会议简报或新闻稿，用于政务公开和宣传报道。"},
            {"name": "归档", "stage": "会后", "write_guide": "汇总归档清单：通知、议程、签到表、纪要、简报等材料目录。"},
        ],
    },
    {
        "code": "activity", "name": "活动组织", "category": "综合",
        "description": "活动方案、通知、物料、分工、执行、总结、宣传全流程",
        "nodes": [
            {"name": "基础信息", "stage": "前期", "write_guide": "汇总活动名称、时间、地点、主题、主办单位、参与对象。"},
            {"name": "活动方案", "stage": "前期", "write_guide": "起草活动方案：目的意义、时间地点、内容安排、组织分工、保障措施。"},
            {"name": "活动通知", "stage": "前期", "write_guide": "起草活动通知，符合公文格式。"},
            {"name": "物料清单", "stage": "中期", "write_guide": "列出活动所需物料、数量、责任人。"},
            {"name": "人员分工", "stage": "中期", "write_guide": "明确各工作组及人员职责分工。"},
            {"name": "现场执行记录", "stage": "中期", "write_guide": "记录活动实施过程、到场情况、突发事项处理。"},
            {"name": "活动总结", "stage": "后期", "write_guide": "撰写活动总结：开展情况、取得成效、经验不足、下一步打算。"},
            {"name": "宣传简报", "stage": "后期", "write_guide": "撰写活动宣传简报/新闻稿。"},
        ],
    },
    {
        "code": "research", "name": "调研工作", "category": "业务",
        "description": "调研方案、提纲、记录、分析、报告、成果转化",
        "nodes": [
            {"name": "基础信息", "stage": "前期", "write_guide": "汇总调研课题、时间、地点、参加人员、调研对象。"},
            {"name": "调研方案", "stage": "前期", "write_guide": "起草调研方案：背景目的、内容方式、日程安排、工作要求。"},
            {"name": "调研提纲", "stage": "前期", "write_guide": "列出调研访谈提纲和重点问题清单。"},
            {"name": "调研记录", "stage": "中期", "write_guide": "整理调研过程记录、座谈要点、实地走访情况。"},
            {"name": "数据分析", "stage": "中期", "write_guide": "汇总分析调研数据和反映的主要问题。"},
            {"name": "调研报告", "stage": "后期", "write_guide": "起草调研报告：基本情况、存在问题、原因分析、对策建议。"},
            {"name": "成果转化建议", "stage": "后期", "write_guide": "提出调研成果转化运用的具体建议。"},
        ],
    },
    {
        "code": "report", "name": "汇报材料", "category": "业务",
        "description": "汇报提纲、初稿、修改稿、定稿、PPT 要点",
        "nodes": [
            {"name": "基础信息", "stage": "准备", "write_guide": "汇总汇报主题、汇报对象、汇报人、时间场合、时长要求。"},
            {"name": "汇报提纲", "stage": "准备", "write_guide": "搭建汇报提纲：总体框架、各部分要点。"},
            {"name": "初稿撰写", "stage": "起草", "write_guide": "按提纲撰写汇报材料初稿，内容详实、数据准确。"},
            {"name": "修改完善", "stage": "起草", "write_guide": "根据反馈修改完善，突出亮点、精炼文字。"},
            {"name": "定稿审核", "stage": "审核", "write_guide": "定稿送审版，格式规范、表述严谨。"},
            {"name": "PPT要点", "stage": "审核", "write_guide": "提炼汇报 PPT 要点：每页标题、核心内容、数据图表建议。"},
        ],
    },
]

MEETING_STANDARD_FIELDS = [
    "meeting_name", "meeting_time", "meeting_location",
    "organizer", "host", "participants", "purpose", "topic"
]

FIELD_LABEL_MAP = {
    "meeting_name": "会议名称",
    "meeting_time": "会议时间",
    "meeting_location": "会议地点",
    "organizer": "主办单位",
    "host": "主持人",
    "participants": "参会人员",
    "purpose": "会议目的",
    "topic": "会议主题",
}
