# -*- coding: utf-8 -*-
"""临时验证：版式多样性 + 主题自动匹配 + 几何审计。跑完可删。"""
import sys, io
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1] / "server"))

from app.application.ppt import ppt_engine
from app.infrastructure.ai.mock import MockLLMGateway

def mk_outline(topic, style, slides):
    return {"title": topic, "subtitle": "", "style": style, "slides": slides}

def slide(t, title, pts, **kw):
    d = {"type": t, "title": title, "points": pts, "blocks": kw.pop("blocks", {}),
         "note": "", "sources": []}
    d.update(kw)
    return d

# 三份不同语义的 6 页稿：点数刻意覆盖 4/3/2/1 触发不同版式
OUTLINES = [
    mk_outline("全区普法宣传工作情况汇报", "宣传展示", [
        slide("cover", "全区普法宣传工作情况汇报", []),
        slide("content", "普法工作的主要成效", ["全区开展普法活动120场，覆盖群众8万人次",
              "建成法治文化广场12个", "培育法律明白人850名", "新媒体普法作品阅读量突破300万"]),
        slide("content", "法治文化阵地建设", ["区级法治文化公园建成开放", "镇街普法驿站全覆盖",
              "村居法治宣传栏常态化更新"]),
        slide("content", "普法与依法治理有机融合", ["普法融入执法办案全过程",
              "普法融入基层依法治理"]),
        slide("content", "让法治成为全民信仰", ["八五普法规划落地见效是长期工程"]),
        slide("content", "下一阶段工作打算", ["深化精准普法，聚焦重点人群",
              "壮大普法志愿者队伍", "打造白云普法品牌矩阵", "健全普法责任制评估"]),
    ]),
    mk_outline("党风廉政建设和反腐败工作部署", "党建廉政", [
        slide("cover", "党风廉政建设工作部署", []),
        slide("content", "当前党风廉政建设形势", ["全面从严治党向纵深推进",
              "四风问题隐形变异仍存", "基层微权力监督待加强"]),
        slide("content", "重点任务", ["压紧压实两个责任", "深化警示教育常态化",
              "纠治群众身边不正之风"]),
        slide("content", "打铁必须自身硬", ["执纪者必先守纪，律人者必先律己"]),
        slide("content", "监督执纪四种形态", ["让红脸出汗成为常态",
              "及时谈话提醒防微杜渐", "严查违纪问题形成震慑", "用好问责利器倒逼尽责"]),
        slide("closing", "谢谢聆听", []),
    ]),
    mk_outline("公共法律服务体系数据发布", "工作汇报", [
        slide("cover", "公共法律服务体系数据发布", []),
        slide("data", "服务总量", [], blocks={"cards": [
            {"label": "受理咨询", "value": "3.2万件"}, {"label": "法律援助", "value": "1800件"},
            {"label": "人民调解", "value": "5600件"}, {"label": "公证办理", "value": "9200件"}]}),
        slide("chart", "近三年服务量趋势", ["服务量连续三年稳步增长"],
              blocks={"chart": {"chart_type": "bar", "categories": ["2024", "2025", "2026"],
                                "series": [{"name": "服务量", "values": [78000, 85000, 96000]}]}}),
        slide("content", "数字法律服务成效", ["线上服务占比首次过半", "群众满意度达98.6%"]),
        slide("content", "公共法律服务，就在群众身边", ["让每一名群众都获得及时有效的法律帮助"]),
        slide("closing", "谢谢聆听", []),
    ]),
]

print("== pick_builtin_template ==")
for o in OUTLINES:
    picked = ppt_engine.pick_builtin_template(o["title"], o["style"])
    tpl = ppt_engine.builtin_template(picked)
    print(f"  {o['title'][:14]}… style={o['style']} -> {picked}（{tpl['name']}）")

from pathlib import Path
out_dir = Path(__file__).parent / "_diversity_check"
out_dir.mkdir(exist_ok=True)
assistant = MockLLMGateway()

print("\n== 版式分布 ==")
for o in OUTLINES:
    outline = ppt_engine.normalize_outline(dict(o), require_bookends=False)
    outline = ppt_engine.resolve_slide_images(outline, [])
    tpl_id = ppt_engine.pick_builtin_template(o["title"], o["style"])
    tpl = ppt_engine.template_to_dict(ppt_engine.builtin_template(tpl_id))
    data = ppt_engine.build_pptx(outline, tpl, adaptive=True)
    # 与 build_pptx 内部同序列模拟选版（build 在内部拷贝上写 _layout）
    used, recent, dist = {}, [], []
    for s in outline["slides"]:
        chosen = ppt_engine.choose_layout(s, tpl.get("layouts"), recent=recent, used=used)
        dist.append(f"{s['type']}:{chosen.split('.')[-1]}")
        used[chosen] = used.get(chosen, 0) + 1
        recent = (recent + [chosen])[-2:]
    p = out_dir / f"{tpl_id}.pptx"
    p.write_bytes(data)
    uniq = len(set(dist))
    print(f"  [{tpl_id}] " + " | ".join(dist) + f"  （{uniq} 种版式/{len(dist)} 页）")

print("\n== 几何审计 ==")
import importlib.util
spec = importlib.util.spec_from_file_location(
    "_audit_deck", Path(__file__).parent / "_audit_deck.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
total_fail = 0
for f in sorted(out_dir.glob("*.pptx")):
    n = mod.audit_deck(f, out_dir)
    print(f"  {f.name}: FAIL={n}")
    total_fail += n
print("\n总 FAIL =", total_fail)
sys.exit(1 if total_fail else 0)
