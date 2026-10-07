"""Optional built-in wording checks, separate from GB/T 9704 layout rules."""

CONTENT_DEFAULT_RULES = [
    {"name": "公文常用规范表述", "target": "content",
     "checks": {"preferred_terms": {
         "截止目前": "截至目前", "截止现在": "截至目前",
         "我们局": "我局", "我们单位": "我单位", "咱们": "本单位",
     }}, "severity": "warning", "remark": "常见口语或不规范表述的确定性提示。"},
    {"name": "数字日期写法", "target": "content",
     "checks": {"normalize_numeric_dates": True}, "severity": "warning",
     "remark": "提示将斜杠、点号等数字日期写法改为中文年月日。"},
    {"name": "相对时间提示", "target": "content",
     "checks": {"relative_time_notice": True}, "severity": "info",
     "remark": "提示核实近日、今年等相对时间在归档后的含义。"},
]
