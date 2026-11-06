"""内置自适应排版样稿：验证「居中正文 / 左右对称」新版式的真实观感。

不依赖 35B 与数据库，纯确定性渲染，用于开发机目视复核：
    D:/apps/anaconda3/python.exe deliverables/_render_adaptive_samples.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))

from app.application.ppt import ppt_engine as E  # noqa: E402

OUT = ROOT / "deliverables" / "_adaptive_samples"
OUT.mkdir(parents=True, exist_ok=True)


def slide(kind: str, title: str, points=None, layout=None, blocks=None,
          subtitle=None) -> dict:
    item = {"type": kind, "title": title, "points": points or [],
            "blocks": blocks or {}}
    if layout:
        item["layout"] = layout
    if subtitle is not None:
        item["subtitle"] = subtitle
    return item


def outline() -> dict:
    return {
        "title": "2026年司法行政工作回顾与展望",
        "subtitle": "白云区司法局",
        "slides": [
            slide("cover", "2026年司法行政工作回顾与展望",
                  subtitle="白云区司法局", layout="minimal"),
            slide("toc", "目录", ["年度工作总体情况", "重点任务推进成效",
                                 "数据指标分析", "下一步工作安排"], layout="cards"),
            slide("section", "一、年度工作总体情况", layout="center"),
            slide("content", "总体判断",
                  ["全年各项工作稳中有进", "公共法律服务覆盖面持续扩大",
                   "基层治理法治化水平稳步提升"], layout="center"),
            slide("content", "两条主线协同推进",
                  ["法治政府建设：完善重大行政决策合法性审查机制，"
                   "全年审查规范性文件 42 件",
                   "普惠法律服务：建成区级公共法律服务中心，"
                   "街道站点实现全覆盖"], layout="symmetric"),
            slide("content", "四项重点工作",
                  ["行政复议体制改革持续深化，受理案件按期办结率 100%",
                   "普法宣传走进社区与企业，全年开展专题活动 86 场",
                   "人民调解组织网络进一步健全，纠纷化解成功率 97.3%",
                   "社区矫正对象监管帮扶规范有序，无重大重新犯罪"],
                  layout="bullets"),
            slide("chart", "近三年法律咨询受理量",
                  points=["2026 年同比增长 18%", "线上渠道占比首次过半"],
                  blocks={"chart": {"chart_type": "line",
                                    "categories": ["2024", "2025", "2026"],
                                    "series": [{"name": "咨询量",
                                                "values": [1820, 2160, 2550]}]}},
                  layout="split"),
            slide("chart", "纠纷类型构成",
                  points=["邻里纠纷仍占首位", "劳动争议占比上升"],
                  blocks={"chart": {"chart_type": "pie",
                                    "categories": ["邻里", "劳动争议", "合同", "其他"],
                                    "series": [{"name": "占比",
                                                "values": [38, 27, 21, 14]}]}},
                  layout="split"),
            slide("data", "年度关键指标", points=["数据截至 2026 年 10 月"],
                  blocks={"cards": [{"value": "86", "label": "普法活动（场）"},
                                    {"value": "97.3%", "label": "调解成功率"},
                                    {"value": "42", "label": "文件审查（件）"},
                                    {"value": "100%", "label": "按期办结率"}]},
                  layout="kpi"),
            slide("timeline", "阶段安排",
                  blocks={"timeline": [
                      {"time": "第一阶段", "text": "摸底梳理，形成任务清单"},
                      {"time": "第二阶段", "text": "集中攻坚，逐项销号落实"},
                      {"time": "第三阶段", "text": "总结评估，固化长效机制"}]},
                  layout="horizontal"),
            slide("summary", "工作小结",
                  ["制度基础更加扎实，服务供给更加均衡",
                   "数据化、规范化水平明显提升",
                   "基层法治阵地作用进一步发挥"], layout="list"),
            slide("closing", "谢谢聆听", layout="center"),
        ],
    }


def main() -> None:
    data = outline()
    for name in ("publicity_cyan", "summary_brown"):
        spec = next(t for t in E.BUILTIN_TEMPLATES if t["id"] == name)
        payload = E.render_pptx(data, dict(spec), adaptive=True)
        target = OUT / f"{name}_adaptive.pptx"
        target.write_bytes(payload)
        print(f"{target}  {len(payload)} bytes  pages={len(data['slides'])}")


if __name__ == "__main__":
    main()
