"""视觉原语样稿：按 design.relationship 渲染五种页面语言 + 同步 SVG 线框。

不依赖 35B 与数据库，纯确定性渲染，用于开发机目视复核：
    D:/apps/anaconda3/python.exe deliverables/_render_visual_primitives.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))

from app.application.ppt import page_scene as P  # noqa: E402
from app.application.ppt import ppt_engine as E  # noqa: E402

OUT = ROOT / "deliverables" / "_visual_samples"
OUT.mkdir(parents=True, exist_ok=True)


def content(title: str, relationship: str, points: list[str], layout: str) -> dict:
    return {"type": "content", "title": title, "points": points,
            "layout": layout, "design": {"relationship": relationship,
                                         "job": "读者应理解本页的核心结论"}}


def outline() -> dict:
    return {
        "title": "2026年司法行政工作回顾与展望",
        "subtitle": "白云区司法局",
        "slides": [
            {"type": "cover", "title": "2026年司法行政工作回顾与展望",
             "subtitle": "白云区司法局", "points": [], "layout": "minimal"},
            {"type": "toc", "title": "目录", "layout": "cards",
             "points": ["年度总体情况", "重点任务成效", "数据指标分析", "下一步安排"]},
            content("总体判断：稳中有进", "none",
                    ["全年各项工作稳中有进，主要指标均按序时进度完成",
                     "公共法律服务覆盖面持续扩大，街道站点实现全覆盖",
                     "基层治理法治化水平稳步提升，纠纷化解成功率 97.3%",
                     "行政复议体制改革持续深化，按期办结率保持 100%"],
                    "bullets"),
            content("两条主线的对照", "comparison",
                    ["法治政府建设：完善重大行政决策合法性审查机制，全年审查规范性文件 42 件",
                     "普惠法律服务：建成区级公共法律服务中心，街道站点实现全覆盖"],
                    "symmetric"),
            content("四项重点工作协同推进", "parallel",
                    ["行政复议体制改革持续深化，受理案件按期办结率 100%",
                     "普法宣传走进社区与企业，全年开展专题活动 86 场",
                     "人民调解组织网络进一步健全，纠纷化解成功率 97.3%",
                     "社区矫正对象监管帮扶规范有序，无重大重新犯罪"],
                    "icon_grid"),
            content("分类推进的三组任务", "grouped",
                    ["制度建设：完成规范性文件清理与合法性审查流程再造",
                     "服务供给：区级中心与街道站点一体化运行",
                     "队伍建设：组织业务培训 12 期，覆盖 480 人次",
                     "监督评估：建立季度通报与问题销号机制"],
                    "two_col"),
            content("核心结论", "takeaway",
                    ["制度基础更加扎实、服务供给更加均衡，数据化与规范化水平明显提升，"
                     "基层法治阵地作用进一步发挥，全年工作实现稳中有进"],
                    "statement"),
            {"type": "closing", "title": "谢谢聆听", "points": [], "layout": "center"},
        ],
    }


def main() -> None:
    for name in ("publicity_cyan", "summary_brown"):
        spec = copy.deepcopy(next(t for t in E.BUILTIN_TEMPLATES if t["id"] == name))
        data = outline()
        payload = E.render_pptx(data, spec, adaptive=True)
        target = OUT / f"{name}_primitives.pptx"
        target.write_bytes(payload)
        for idx, slide in enumerate(data["slides"], 1):
            scene = slide.get("scene")
            if scene:
                (OUT / f"{name}_p{idx:02d}.svg").write_text(
                    P.wireframe(scene, slide), encoding="utf-8")
        print(f"{target}  {len(payload)} bytes  pages={len(data['slides'])}")


if __name__ == "__main__":
    main()
