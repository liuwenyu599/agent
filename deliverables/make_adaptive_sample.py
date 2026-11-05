# -*- coding: utf-8 -*-
"""本地出一份自适应排版样稿（不依赖 DB / LLM）。

覆盖三个自适应场景：
  1. 密集要点页  -> point_rows 按字量分配行高 + 字号自适应
  2. 长文对比页  -> compare_geometry 触发上下 stacked 布局
  3. 宽图图文页  -> image_geometry 触发 panorama 模式
"""
import io
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "server"))

from PIL import Image, ImageDraw  # noqa: E402

from app.application.ppt import ppt_engine  # noqa: E402

OUT = os.path.join(REPO, "deliverables", "adaptive_sample.pptx")

# ---------- 造一张 2:1 宽图（触发 panorama） ----------
img_path = os.path.join(REPO, "deliverables", "sample_wide_image.png")
im = Image.new("RGB", (1600, 800), (34, 197, 94))
d = ImageDraw.Draw(im)
d.rectangle([0, 500, 1600, 800], fill=(21, 128, 61))
for x in range(0, 1600, 160):
    d.rectangle([x, 560, x + 90, 800], fill=(240, 253, 244))
d.rectangle([120, 180, 420, 480], fill=(240, 253, 244))
d.rectangle([520, 260, 820, 480], fill=(240, 253, 244))
im.save(img_path)

DENSE_POINTS = [
    "持续推进公共法律服务体系标准化建设，全年累计办理法律援助案件 1,286 件，同比增长 18.4%，受援人满意率达到 98.2%，案件回访覆盖率保持 100%。",
    "深化人民调解组织网络建设，新建行业性专业性调解委员会 12 个，培训人民调解员 860 人次，全年化解矛盾纠纷 4,372 起，调解成功率达 96.8%。",
    "全面推行行政执法三项制度，组织执法资格考试 2 轮，参考人员 512 人，通过率 91.3%；开展执法案卷评查 4 次，抽查案卷 680 卷，整改问题 137 项。",
    "扎实开展普法宣传工作，组织宪法宣传周、民法典宣传月等主题活动 46 场，覆盖群众约 5.6 万人次，新媒体普法作品阅读量突破 120 万。",
    "加强行政复议应诉能力建设，全年收到行政复议申请 342 件，受理 298 件，调解和解率 34.2%，行政机关负责人出庭应诉率保持 100%。",
]

LONG_A = ("整改前：部分窗口存在材料清单不统一的问题，同一事项在不同镇街办理时需要的证明材料数量不一致，"
          "群众平均需要往返 2.4 次才能办结，一次性受理率仅为 78.6%，2024 年一季度 related 投诉工单 43 件，"
          "占窗口类投诉总量的 61.4%，主要集中在大额公证与司法鉴定预审环节，材料补正通知书出具不及时的问题较为突出。")
LONG_B = ("整改后：统一编制全区通用的办事指南与材料清单，推行一次性告知承诺制与容缺受理机制，"
          "群众平均往返次数降至 1.2 次，一次性受理率提升至 95.8%，2025 年三季度窗口类投诉工单下降至 11 件，"
          "环比降幅 74.4%，同步建立超时预警与首问负责台账，材料补正平均出具时长压缩至半个工作日以内，群众满意度回升至 97.6%。")

outline = {
    "title": "公共法律服务体系建设工作汇报",
    "subtitle": "白云区司法局 · 2026 年度",
    "slides": [
        {"type": "cover", "title": "公共法律服务体系建设工作汇报",
         "subtitle": "白云区司法局 · 2026 年度"},
        {"type": "toc", "title": "目录",
         "points": ["体系建设总体情况", "重点领域工作成效", "存在不足与下步打算"]},
        {"type": "content", "title": "重点领域工作成效",
         "points": DENSE_POINTS},
        {"type": "content", "title": "公证服务窗口专项整治前后对比",
         "layout": "content.compare", "points": [LONG_A, LONG_B]},
        {"type": "content", "title": "区公共法律服务中心实景",
         "layout": "content.image_right",
         "points": ["中心面积 1,200 平方米，设 6 个服务窗口",
                    "全年接待群众咨询 2.1 万人次",
                    "推行一窗受理、集成服务模式"],
         "image_name": "center_hall", "_image": {
             "name": "center_hall",
             "caption": "区公共法律服务中心服务大厅",
             "file_path": img_path}},
        {"type": "data", "title": "年度核心指标",
         "blocks": {"cards": [
             {"label": "法律援助案件", "value": "1,286 件"},
             {"label": "化解矛盾纠纷", "value": "4,372 起"},
             {"label": "调解成功率", "value": "96.8%"},
             {"label": "受援人满意率", "value": "98.2%"}]}},
        {"type": "process", "title": "法律援助办理流程",
         "blocks": {"process": ["当事人申请", "受理审查", "指派承办", "跟踪督办", "结案回访"]}},
        {"type": "summary", "title": "总结与展望",
         "points": ["服务体系实现城乡全覆盖，15 分钟服务圈基本建成",
                    "数字赋能初见成效，线上办理率达 42.6%",
                    "下步重点补齐镇街站点专业力量短板"]},
        {"type": "closing", "title": "谢谢聆听，请批评指正"},
    ],
}

template = {"layouts": ppt_engine.DEFAULT_LAYOUTS,
            "colors": ppt_engine.DEFAULT_COLORS}
warnings = []
data = ppt_engine.render_pptx(outline, template, warnings=warnings, adaptive=True)

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "wb") as f:
    f.write(data)

print("SAVED:", OUT, len(data), "bytes")
print("RENDER WARNINGS:", warnings or "(none)")

from app.application.ppt.service import PPTService  # noqa: E402
review = PPTService.review_pptx_visuals(data)
print("REVIEW STATUS:", review.get("status"))
for issue in review.get("issues") or []:
    print(f"  p{issue.get('page')} [{issue.get('code')}] {issue.get('message')}")
