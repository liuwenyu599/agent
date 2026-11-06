# -*- coding: utf-8 -*-
"""全主题页眉几何差异化验证：11 套内置主题 × 6 页小样，逐套过视觉闸门。

覆盖页型：cover/toc/content/timeline/summary/closing（页眉在 content/summary 等页生效）。
用法：cd server && D:/apps/anaconda3/python.exe ../deliverables/_verify_header_styles.py
"""
import os
import sys

os.environ.setdefault("PPT_AGENT_ENABLED", "false")
os.environ.setdefault("AI_PROVIDER", "mock")
os.environ.setdefault("EMBEDDING_PROVIDER", "mock")

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "server"))

from app.application.ppt import ppt_engine  # noqa: E402
from app.application.ppt.service import PPTService  # noqa: E402

OUTLINE = {
    "slides": [
        {"type": "cover", "title": "2026年度司法行政工作总结",
         "subtitle": "白云区司法局", "points": []},
        {"type": "toc", "title": "目录", "points": ["总体情况", "主要成效", "存在问题", "下一步计划"]},
        {"type": "content", "title": "总体情况：法治建设稳步推进",
         "points": ["公共法律服务体系覆盖率达到 98%，群众满意度稳步提升。",
                    "社区矫正对象再犯率连续三年下降，安置帮教衔接率保持高位。",
                    "普法宣传进社区、进校园、进企业累计开展活动 120 余场。"],
         "blocks": {}},
        {"type": "timeline", "title": "下一阶段工作推进时间表", "points": [],
         "blocks": {"timeline": [
             {"time": "第一阶段：近期（2026年11月—12月）", "text": "聚焦帮扶衔接，明确效能指标。"},
             {"time": "第二阶段：中期（2027年1月—6月）", "text": "形成可复制推广的制度成果。"},
             {"time": "第三阶段：远期（2027年7月—12月）", "text": "深化制度成果，提升法治建设水平。"},
         ]}},
        {"type": "summary", "title": "工作总结与展望", "points": [],
         "blocks": {"cards": [
             {"label": "体系建设", "text": "覆盖更全、响应更快"},
             {"label": "队伍培养", "text": "专业素能与作风双提升"},
             {"label": "数字赋能", "text": "平台建设与数据互通"},
         ]}},
        {"type": "closing", "title": "汇报完毕，敬请指正", "points": []},
    ],
}

OUT_DIR = os.path.join(HERE, "_header_style_samples")
os.makedirs(OUT_DIR, exist_ok=True)

fail = 0
for spec in ppt_engine.BUILTIN_TEMPLATES:
    tid = spec["id"]
    template = ppt_engine.template_to_dict(spec)
    data = ppt_engine.render_pptx(dict(OUTLINE), template, adaptive=True)
    review = PPTService.review_pptx_visuals(data)
    codes = [(i.get("page"), i.get("code")) for i in review.get("issues") or []]
    status = review.get("status")
    mark = "✅" if status == "passed" else "⚠️"
    if status != "passed":
        fail += 1
    print(f"{mark} {tid:22s} header={spec.get('id')} status={status} issues={codes}")
    with open(os.path.join(OUT_DIR, f"{tid}.pptx"), "wb") as f:
        f.write(data)

print(f"\n{'全部通过' if fail == 0 else f'{fail} 套存在问题'}，样稿在 {OUT_DIR}")
sys.exit(1 if fail else 0)
