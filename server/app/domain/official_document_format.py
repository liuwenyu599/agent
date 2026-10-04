"""党政机关公文共享格式定义（无框架依赖）。"""
from typing import Dict, List

# ---------------- 党政机关公文格式 GB/T 9704-2012 ----------------
# target 取值：page / title / body / heading1 / heading2 / signature / date / general
# severity：error=错误（必须改） / warning=警告（建议改） / info=提示
GBT_RULESET = "gb9704"

GBT_RULES: List[Dict] = [
    # 页面设置（GB/T 9704-2012 6.1 用纸与页边距）
    {"name": "页面上边距 37mm", "target": "page",
     "checks": {"top_margin_cm": 3.7}, "severity": "error",
     "remark": "GB/T 9704-2012 6.1：上白边（天头）37mm±1mm"},
    {"name": "页面下边距 35mm", "target": "page",
     "checks": {"bottom_margin_cm": 3.5}, "severity": "error",
     "remark": "GB/T 9704-2012 6.1：下白边（地脚）35mm±1mm"},
    {"name": "页面左边距 28mm", "target": "page",
     "checks": {"left_margin_cm": 2.8}, "severity": "error",
     "remark": "GB/T 9704-2012 6.1：左白边（订口）28mm±1mm"},
    {"name": "页面右边距 26mm", "target": "page",
     "checks": {"right_margin_cm": 2.6}, "severity": "error",
     "remark": "GB/T 9704-2012 6.1：右白边（翻口）26mm±1mm"},

    # 标题（7.3.1 二号小标宋体字，编排于红色分隔线下空二行，分一行或多行居中排布）
    {"name": "标题字号二号（22磅）", "target": "title",
     "checks": {"font_size_pt": 22}, "severity": "error",
     "remark": "GB/T 9704-2012 7.3.1：标题用 2 号小标宋体字"},
    {"name": "标题居中排布", "target": "title",
     "checks": {"alignment": "center"}, "severity": "error",
     "remark": "GB/T 9704-2012 7.3.1：标题分一行或多行居中排布"},
    {"name": "标题字体小标宋", "target": "title",
     "checks": {"font_name": "方正小标宋简体"}, "severity": "warning",
     "remark": "GB/T 9704-2012 7.3.1：小标宋体字；部分单位以黑体替代，故定为警告"},
    {"name": "标题不加粗", "target": "title",
     "checks": {"bold": False}, "severity": "warning",
     "remark": "小标宋为自带字形，不应再加粗"},
    {"name": "标题段后间距 0", "target": "title",
     "checks": {"space_after_pt": 0}, "severity": "info",
     "remark": "标题与正文之间不应有多余间距"},

    # 正文（7.3.3 三号仿宋_GB2312，每自然段左空二字，回行顶格）
    {"name": "正文字号三号（16磅）", "target": "body",
     "checks": {"font_size_pt": 16, "font_name": "仿宋_GB2312"}, "severity": "error",
     "remark": "GB/T 9704-2012 7.3.3：正文用 3 号仿宋_GB2312 字"},
    {"name": "正文首行缩进 2 字符", "target": "body",
     "checks": {"first_line_indent_chars": 2}, "severity": "error",
     "remark": "GB/T 9704-2012 7.3.3：每自然段左空二字，回行顶格"},
    {"name": "正文行距固定值 28.8 磅", "target": "body",
     "checks": {"line_spacing_pt": 28.8}, "severity": "warning",
     "remark": "GB/T 9704-2012 7.3.3：一般每面排 22 行、每行 28 字（约固定值 28.8 磅）"},
    {"name": "正文段前段后间距 0", "target": "body",
     "checks": {"space_before_pt": 0, "space_after_pt": 0}, "severity": "info",
     "remark": "自然段之间不另设间距"},

    # 层次序号（7.3.3：一、用黑体；（一）用楷体_GB2312；1. 用仿宋加粗）
    {"name": "一级标题「一、」字号三号", "target": "heading1",
     "checks": {"font_size_pt": 16}, "severity": "warning",
     "remark": "GB/T 9704-2012 7.3.3：第一层「一、」用 3 号字"},
    {"name": "一级标题「一、」黑体", "target": "heading1",
     "checks": {"font_name": "黑体"}, "severity": "warning",
     "remark": "GB/T 9704-2012 7.3.3：第一层用黑体字"},
    {"name": "二级标题「（一）」字号三号", "target": "heading2",
     "checks": {"font_size_pt": 16}, "severity": "warning",
     "remark": "GB/T 9704-2012 7.3.3：第二层用 3 号字"},
    {"name": "二级标题「（一）」楷体", "target": "heading2",
     "checks": {"font_name": "楷体_GB2312"}, "severity": "warning",
     "remark": "GB/T 9704-2012 7.3.3：第二层用楷体_GB2312 字"},

    # 落款与成文日期（7.3.5 发文机关署名、7.3.6 成文日期右空四字）
    {"name": "发文机关署名右对齐", "target": "signature",
     "checks": {"alignment": "right", "right_indent_chars": 4}, "severity": "warning",
     "remark": "GB/T 9704-2012 7.3.5：发文机关署名居右排布"},
    {"name": "成文日期右对齐", "target": "date",
     "checks": {"alignment": "right", "right_indent_chars": 4}, "severity": "warning",
     "remark": "GB/T 9704-2012 7.3.6：成文日期右空四字编排"},

    # 全文通用
    {"name": "无连续多余空行", "target": "general",
     "checks": {"no_extra_blank_lines": True}, "severity": "warning",
     "remark": "段落间距应通过段前/段后设置实现，不应使用回车空行"},
    {"name": "无行尾空格", "target": "general",
     "checks": {"no_trailing_spaces": True}, "severity": "warning",
     "remark": "段末不应有多余空格，避免排版错位"},
]


def format_checks(target: str) -> dict:
    checks = {}
    if target in {"heading1", "heading2", "signature", "date"}:
        checks.update(format_checks("body"))
    for rule in GBT_RULES:
        if rule["target"] == target:
            checks.update(rule["checks"])
    if target in {"signature", "date"}:
        checks["first_line_indent_chars"] = 0
    return checks
