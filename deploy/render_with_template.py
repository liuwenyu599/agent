#!/usr/bin/env python3
"""端到端打通：把（模型生成的）大纲内容填充进「学习模板」，产出真稿并出预览。

这是把 35B 大纲 → 克隆模板 → 填充 这条链路在本地最小可运行版本，不依赖数据库：
  python deploy/render_with_template.py --template 模板.pptx --out 成品.pptx [--model 主题]

  --model 主题   尝试真调 PPT 模型网关生成大纲；不可达时自动回退示例大纲并提示。
  不加 --model   直接用一份与模型输出同构的示例大纲（结构完全一致，仅内容固定）。

产物：成品.pptx + 同目录 previews/pg-*.png（soffice 逐页预览）。
"""
import argparse
import io
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))

from app.application.ppt import ppt_engine as pe  # noqa: E402


# 与 ppt_engine.generate_outline 输出严格同构的示例大纲（仅内容固定）。
# 覆盖 cover / toc / section / content / closing 五类，足以命中模板的全部版式。
SAMPLE_OUTLINE = {
    "title": "2024 年度党建工作汇报",
    "subtitle": "守正创新 提质增效",
    "slides": [
        {"type": "cover", "title": "2024 年度党建工作汇报",
         "subtitle": "中共某某单位委员会", "points": [], "blocks": {}, "image_name": None},
        {"type": "toc", "title": "目录",
         "points": ["主要工作成效", "存在问题与不足", "下一步工作打算"], "blocks": {}, "image_name": None},
        {"type": "section", "title": "一、主要工作成效", "points": [], "blocks": {}, "image_name": None},
        {"type": "content", "title": "强化政治引领，筑牢思想根基",
         "points": [
             "严格落实“第一议题”制度，全年开展中心组学习 24 次、专题研讨 8 次。",
             "扎实开展党纪学习教育，覆盖党员 386 名，撰写心得体会 412 篇。",
             "打造“指尖党课”线上平台，累计推送学习资料 156 期，点击量破 10 万。"],
         "blocks": {}, "image_name": None},
        {"type": "content", "title": "夯实组织基础，激发支部活力",
         "points": [
             "完成 12 个党支部按期换届，软弱涣散党组织整改销号率 100%。",
             "发展党员 28 名，其中高知群体 9 名，队伍结构持续优化。",
             "推行“党员先锋岗”制度，设立示范岗 56 个，群众满意度达 98.2%。"],
         "blocks": {}, "image_name": None},
        {"type": "content", "title": "服务中心大局，彰显党建价值",
         "points": [
             "组建 9 支党员突击队投身重点项目，攻坚节点提前 23 天。",
             "开展“党建+乡村振兴”结对帮扶，协调资金 320 万元落地 11 个项目。",
             "疫情与汛情期间党员冲在一线，累计服务时长超 1.2 万小时。"],
         "blocks": {}, "image_name": None},
        {"type": "section", "title": "二、存在问题与不足", "points": [], "blocks": {}, "image_name": None},
        {"type": "content", "title": "清醒认识短板弱项",
         "points": [
             "部分支部组织生活形式单一，“三会一课”吸引力有待提升。",
             "党建与业务融合不够深，存在“两张皮”现象。",
             "党务干部多为兼职，专业化能力与新时代要求仍有差距。"],
         "blocks": {}, "image_name": None},
        {"type": "section", "title": "三、下一步工作打算", "points": [], "blocks": {}, "image_name": None},
        {"type": "content", "title": "聚焦重点，谋实举措",
         "points": [
             "实施“堡垒提质”行动，年内打造 3 个市级标杆党支部。",
             "深化党建业务双融双促，建立融合成效量化评估机制。",
             "开展党务干部轮训，年内实现持证上岗全覆盖。"],
         "blocks": {}, "image_name": None},
        {"type": "content", "title": "健全机制，压实责任",
         "points": [
             "修订党建工作责任制清单，压实书记第一责任人职责。",
             "用好述职评议“指挥棒”，评议结果与考核任免硬挂钩。",
             "强化经费与阵地保障，新建党群服务中心 2 处。"],
         "blocks": {}, "image_name": None},
        {"type": "closing", "title": "感谢聆听 恳请批评指正",
         "points": [], "blocks": {}, "image_name": None},
    ],
}


def load_template(path: Path):
    data = path.read_bytes()
    learned = pe.analyze_template(data)
    pe.validate_learned_template(learned)
    template = {
        "layout_library": learned["layouts"],
        "colors": learned["colors"],
        "font": learned.get("font") or "思源黑体",
    }
    types = [l.get("detected_type") for l in learned["layouts"]]
    print(f"模板版式：{len(learned['layouts'])} 个，类型分布 = {types}")
    print(f"模板颜色：{learned['colors']}  字体：{template['font']}")
    return data, template


def get_model_outline(topic: str, slide_count: int):
    """尝试真调 PPT 模型网关；不可达返回 None。"""
    try:
        from app.infrastructure.ai import get_ppt_gateway
        from app.application.shared.writing_assistant import WritingAssistant
        gw = get_ppt_gateway()
        if gw is None:
            print("[model] 未配置 PPT 模型网关，回退示例大纲")
            return None
        asst = WritingAssistant(gw)
        outline = pe.generate_outline(asst, "topic", topic, "", [], slide_count=slide_count)
        print(f"[model] 35B 已生成大纲：{len(outline.get('slides') or [])} 页")
        return outline
    except Exception as e:  # 网络/配置不通都回退，不阻断演示
        print(f"[model] 网关调用失败，回退示例大纲：{type(e).__name__}: {e}")
        return None


def render_preview(pptx_path: Path) -> int:
    previews = pptx_path.parent / "previews"
    previews.mkdir(exist_ok=True)
    pdf = previews / (pptx_path.stem + ".pdf")
    subprocess.run(["soffice", "--headless", "--convert-to", "pdf",
                    "--outdir", str(previews), str(pptx_path)],
                   check=True, capture_output=True)
    out = subprocess.run(["pdftoppm", "-r", "90", "-png", str(pdf),
                          str(previews / "pg")], check=True, capture_output=True)
    count = len(list(previews.glob("pg-*.png")))
    pdf.unlink(missing_ok=True)
    print(f"预览已生成：{previews}  共 {count} 页")
    return count


def main() -> int:
    ap = argparse.ArgumentParser(description="大纲 → 学习模板 → 填充真稿")
    ap.add_argument("--template", required=True, help="处理后的模板 pptx")
    ap.add_argument("--out", required=True, help="输出成品 pptx")
    ap.add_argument("--model", default=None, help="用真实模型生成大纲的主题（可选）")
    ap.add_argument("--slides", type=int, default=12, help="模型大纲页数（仅 --model 时）")
    args = ap.parse_args()

    tpl_path = Path(args.template)
    out_path = Path(args.out)
    if not tpl_path.exists():
        print(f"模板不存在：{tpl_path}")
        return 2

    data, template = load_template(tpl_path)

    if args.model:
        outline = get_model_outline(args.model, args.slides)
    else:
        outline = None
    if outline is None:
        outline = SAMPLE_OUTLINE
        print(f"使用示例大纲：{len(outline['slides'])} 页（cover/toc/section/content/closing）")

    warnings = []
    buf = pe.render_pptx(outline, template, base_pptx=data, warnings=warnings)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(buf)
    print(f"已生成成品：{out_path}  ({len(buf)//1024} KB)")
    if warnings:
        print("渲染提示：")
        for w in warnings:
            print(f"  - {w}")

    # 验证：残留 token 扫描
    from pptx import Presentation
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    def walk(shapes, depth=0):
        for sh in shapes:
            yield sh, depth
            try:
                g = sh.shape_type == MSO_SHAPE_TYPE.GROUP
            except Exception:
                g = False
            if g:
                yield from walk(sh.shapes, depth + 1)

    prs = Presentation(io.BytesIO(buf))
    leaked = 0
    for i, slide in enumerate(prs.slides, 1):
        for sh, _ in walk(slide.shapes):
            if getattr(sh, "has_text_frame", False) and "{{" in sh.text_frame.text:
                leaked += 1
                print(f"  ⚠ 第 {i} 页残留 token：{sh.text_frame.text.strip()[:40]}")
    print(f"残留未替换 token：{leaked} 处" + ("  ✅" if leaked == 0 else "  ❌"))

    render_preview(out_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
