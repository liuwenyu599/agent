# -*- coding: utf-8 -*-
"""复现 2026-11-06 实机验收第 8 页时间轴文字重叠（issue: 长标签塞短日期槽）。

用同一渲染器 + 同一视觉闸门跑两轮：
  round A（现状代码）：期望输出 review 的 text_overlap / overflow 情况，验证闸门是否漏报；
  round B（渲染修复后）：期望 review 干净。
用法：
  cd server && D:/apps/anaconda3/python.exe ../deliverables/_repro_timeline.py
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

TIMELINE_SLIDE = {
    "type": "timeline",
    "title": "下一阶段工作推进时间表",
    "points": [],
    "blocks": {"timeline": [
        {"time": "第一阶段：近期（2026年11月—12月）",
         "text": "聚焦社区矫正对象帮扶衔接，明确期效能指标，自评并开展期效能培训。"},
        {"time": "第二阶段：中期（2027年1月—6月）",
         "text": "形成可复制推广的制度成果，优化公共法律服务资源配置。"},
        {"time": "第三阶段：远期（2027年7月—12月）",
         "text": "深化制度成果，提升法治建设水平。"},
    ]},
}

TEMPLATE = ppt_engine.template_to_dict(
    next(t for t in ppt_engine.BUILTIN_TEMPLATES if t["id"] == "summary_brown"))


def run(tag: str) -> None:
    warnings = []
    outline = {"slides": [dict(TIMELINE_SLIDE)]}
    data = ppt_engine.render_pptx(outline, TEMPLATE, warnings=warnings, adaptive=True)
    review = PPTService.review_pptx_visuals(data)
    print(f"== {tag} ==")
    print("render warnings:", warnings or "无")
    issues = review.get("issues") or []
    if not issues:
        print("review issues: 无 ✅")
    for it in issues:
        print(f"review: page={it.get('page')} code={it.get('code')} "
              f"msg={it.get('message')}")
    out = os.path.join(HERE, f"_repro_timeline_{tag}.pptx")
    with open(out, "wb") as f:
        f.write(data)
    print("已写样稿:", out)


if __name__ == "__main__":
    run("after")
