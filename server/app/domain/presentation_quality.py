"""User-switchable default checks for generated presentations."""

PPT_DEFAULT_RULES = [
    {"name": "PPT 页数与已确认大纲一致", "target": "ppt",
     "checks": {"check_page_count": True}, "severity": "error",
     "remark": "按用户确认的页数交付，不增删页面。"},
    {"name": "PPT 封面元素不越界", "target": "ppt",
     "checks": {"check_cover_overflow": True}, "severity": "error",
     "remark": "封面文本与图形应完整位于画布内。"},
    {"name": "PPT 中文字体兼容", "target": "ppt",
     "checks": {"forbidden_fonts": ["DejaVu"]}, "severity": "error",
     "remark": "避免缺失中文字形的字体。"},
]
