"""生成「真母版」政务 PPT 模板包（数据驱动）。

背景
----
`docs/ppt-template-image-library-handoff.md` 与何总指导都指出：当前 10 套内置模板只是换配色、
共用一套版式骨架，所以生成出来「全是一个模板一个结构」。克隆填充链路
(analyze_template -> build_pptx_learned) 早已存在，缺的只是**真母版 pptx 本体**——本脚本补上它。

本脚本造 4 套**视觉语言真正不同**的母版 pptx（深蓝经典 / 暖金简约 / 科技深色 / 青绿卡片），
每套内部含 ≥5 种不同布局签名，使系统真正拥有多种可区分的设计。

关键规则（确保 analyze_template 通过且不被去重）
------------------------------------------------
- 16:9（13.333 x 7.5 英寸），否则 validate_learned_template 直接拒。
- 每套至少 1 个内容页（非封面/目录/结尾）且含 ≥2 个可替换文本框。
- 内容页结构彼此不同（文本框 x/y/w/h 坐标不同），否则 _layout_signature 去重只留一张。
- 页眉强调条 + 页脚文字在 ≥60% 的内容页同坐标出现 -> 被 _mark_fixed 判为固定装饰，
  克隆填充时保留为背景/装饰，不被当内容清掉。

产物
----
    server/app/application/ppt/templates/gov/<id>.pptx

运行
----
    cd server && D:/apps/anaconda3/python.exe ../deploy/gen_master_templates.py
（脚本自行把 repo/server 加入 sys.path 以导入 app.core.fonts）
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt

# ---- 让其能从 server 目录导入 app.core.fonts ----
REPO = Path(__file__).resolve().parent.parent
if str(REPO / "server") not in sys.path:
    sys.path.insert(0, str(REPO / "server"))

from app.core.fonts import DEFAULT_CJK_FONT, apply_cjk_font  # noqa: E402

SW, SH = 13.333, 7.5
MARGIN = 0.6
CJK = "Microsoft YaHei"
LATIN = "Times New Roman"


def rgb(h: str) -> RGBColor:
    return RGBColor.from_string(h.lstrip("#"))


def txt(slide, l, t, w, h, lines, size, color, bold=False, align=PP_ALIGN.LEFT,
        anchor=MSO_ANCHOR.TOP, spacing=1.15, italic=False, font=CJK):
    """加文本框。lines: str 或 [(text,size?,color?,bold?)]。每个 run 固定 CJK+拉丁字体。"""
    tb = slide.shapes.add_textbox(Inches(l), Inches(t), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    if isinstance(lines, str):
        lines = [(lines,)]
    for i, item in enumerate(lines):
        if isinstance(item, str):
            item = (item,)
        text, *rest = item
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        p.line_spacing = spacing
        r = p.add_run()
        r.text = text
        r.font.size = Pt(rest[0] if len(rest) > 0 and rest[0] else size)
        r.font.color.rgb = rgb(rest[1]) if len(rest) > 1 and rest[1] else rgb(color)
        r.font.bold = rest[2] if len(rest) > 2 and rest[2] is not None else bold
        r.font.italic = italic
        apply_cjk_font(r, font=font, latin=LATIN)
    return tb


def rect(slide, l, t, w, h, fill, line=None, line_w=None, shape=MSO_SHAPE.RECTANGLE):
    sp = slide.shapes.add_shape(shape, Inches(l), Inches(t), Inches(w), Inches(h))
    sp.shadow.inherit = False
    if fill is None:
        sp.fill.background()
    else:
        sp.fill.solid()
        sp.fill.fore_color.rgb = rgb(fill)
    if line is None:
        sp.line.fill.background()
    else:
        sp.line.color.rgb = rgb(line)
        sp.line.width = Pt(line_w or 1)
    return sp


def decoration(slide, th):
    """固定装饰：页眉强调条 + 页脚文字，同坐标出现于 ≥60% 内容页 -> 被标记 fixed。"""
    rect(slide, MARGIN, 0.5, SW - 2 * MARGIN, 0.07, th["accent"])
    txt(slide, MARGIN, 7.02, 8.0, 0.32, "白云区司法局 · 工作汇报", 9, th["footer"],
        align=PP_ALIGN.LEFT)
    txt(slide, SW - MARGIN - 2.2, 7.02, 2.2, 0.32, "内部资料 · 请勿外传", 9, th["footer"],
        align=PP_ALIGN.RIGHT)


# ---------------------------------------------------------------------------
# 每套模板的页型绘制（结构彼此不同，保证 _layout_signature 不重复）
# ---------------------------------------------------------------------------
def page_cover(slide, th, title, subtitle, variant):
    bg = slide.background.fill
    bg.solid(); bg.fore_color.rgb = rgb(th["cover_bg"])
    if variant == "center":
        txt(slide, 1.5, 2.55, 10.33, 1.4, title, 46, th["cover_title"], bold=True,
            align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
        rect(slide, SW / 2 - 1.2, 4.05, 2.4, 0.06, th["accent"])
        txt(slide, 1.5, 4.25, 10.33, 0.8, subtitle, 20, th["cover_sub"], align=PP_ALIGN.CENTER)
    elif variant == "left":
        rect(slide, MARGIN, 2.7, 0.12, 2.0, th["accent"])
        txt(slide, 1.0, 2.7, 11.3, 1.6, title, 44, th["cover_title"], bold=True,
            anchor=MSO_ANCHOR.MIDDLE)
        txt(slide, 1.0, 4.4, 11.3, 0.8, subtitle, 20, th["cover_sub"])
    elif variant == "right":
        txt(slide, 1.0, 2.7, 9.6, 1.6, title, 44, th["cover_title"], bold=True,
            align=PP_ALIGN.RIGHT, anchor=MSO_ANCHOR.MIDDLE)
        rect(slide, SW - MARGIN - 2.4, 4.35, 2.4, 0.06, th["accent"])
        txt(slide, 2.7, 4.55, 8.0, 0.8, subtitle, 20, th["cover_sub"], align=PP_ALIGN.RIGHT)
    else:  # top
        txt(slide, MARGIN, 1.4, 12.1, 1.2, title, 42, th["cover_title"], bold=True)
        rect(slide, MARGIN, 2.75, 3.0, 0.07, th["accent"])
        txt(slide, MARGIN, 3.0, 12.1, 0.8, subtitle, 20, th["cover_sub"])


def page_toc(slide, th, items):
    bg = slide.background.fill
    bg.solid(); bg.fore_color.rgb = rgb(th["bg"])
    txt(slide, MARGIN, 0.7, 6, 1.3, "目录", 34, th["title"], bold=True)
    rect(slide, MARGIN, 1.95, 2.2, 0.06, th["accent"])
    col_w = (SW - 2 * MARGIN - 0.6) / 2
    for i, it in enumerate(items):
        col = i // 3
        row = i % 3
        x = MARGIN + col * (col_w + 0.6)
        y = 2.4 + row * 1.35
        # 单文本框、数字与文字同字号（仅粗细不同）-> 避免被判「同级卡片字号差异过大」
        txt(slide, x, y, col_w, 0.9,
            [(f"{i+1:02d}  ", 18, None, True), (it, 18, None, False)],
            18, th["body"], bold=False)


def page_section(slide, th, num, title, guide):
    bg = slide.background.fill
    bg.solid(); bg.fore_color.rgb = rgb(th["bg"])
    rect(slide, MARGIN + 0.3, 2.6, 0.12, 2.0, th["accent"])
    # 章节号并入标题行（同字号），引导语单独成段 -> 单一标题层级，避免数字/标题被判同级卡片
    txt(slide, MARGIN + 0.7, 2.55, 11.0, 1.4, f"{num}  {title}", 40, th["title"], bold=True,
        anchor=MSO_ANCHOR.MIDDLE)
    txt(slide, MARGIN + 0.7, 4.15, 11.0, 1.0, guide, 16, th["body"])


# 5 种内容版式（坐标各异 -> 签名不同 -> 各自注册）
def page_content_a(slide, th, title, paras):
    bg = slide.background.fill
    bg.solid(); bg.fore_color.rgb = rgb(th["bg"])
    decoration(slide, th)
    rect(slide, MARGIN, 1.0, 0.1, 0.95, th["accent"])
    txt(slide, MARGIN + 0.3, 0.95, 11.0, 1.0, title, 30, th["title"], bold=True,
        anchor=MSO_ANCHOR.MIDDLE)
    y = 2.4
    for p in paras:
        txt(slide, MARGIN, y, SW - 2 * MARGIN, 1.1, p, 15, th["body"], spacing=1.3)
        y += 1.15


def page_two_col(slide, th, title, left, right):
    bg = slide.background.fill
    bg.solid(); bg.fore_color.rgb = rgb(th["bg"])
    decoration(slide, th)
    txt(slide, MARGIN, 0.95, 11.0, 1.0, title, 28, th["title"], bold=True)
    rect(slide, MARGIN, 1.85, SW - 2 * MARGIN, 0.05, th["accent"])
    col_w = (SW - 2 * MARGIN - 0.8) / 2
    txt(slide, MARGIN, 2.3, col_w, 3.8, left, 14, th["body"], spacing=1.35)
    txt(slide, MARGIN + col_w + 0.8, 2.3, col_w, 3.8, right, 14, th["body"], spacing=1.35)


def page_content_image(slide, th, title, paras):
    bg = slide.background.fill
    bg.solid(); bg.fore_color.rgb = rgb(th["bg"])
    decoration(slide, th)
    txt(slide, MARGIN, 0.95, 7.0, 1.0, title, 28, th["title"], bold=True)
    y = 2.3
    for p in paras:
        # 正文框加高(1.3")使其与标题(28pt)的 peer 尺寸不同，避免被判「同级卡片字号差异过大」
        txt(slide, MARGIN, y, 6.8, 1.3, p, 14, th["body"], spacing=1.3)
        y += 1.45
    rect(slide, 7.8, 2.3, 4.9, 3.7, th["card"], line=th["accent"], line_w=1)


def page_cards(slide, th, title, cards):
    bg = slide.background.fill
    bg.solid(); bg.fore_color.rgb = rgb(th["bg"])
    decoration(slide, th)
    txt(slide, MARGIN, 0.65, 11.0, 0.55, title, 28, th["title"], bold=True)
    # 导语：宽文本框（w≥0.25 比例）作为可编辑正文区域，避免被判「缺少可编辑正文区域」
    txt(slide, MARGIN, 0.80, 11.0, 0.6,
        "围绕年度重点任务，以下为各项工作抓手与具体举措概览。", 14, th["body"])
    rect(slide, MARGIN, 1.95, SW - 2 * MARGIN, 0.05, th["accent"])
    n = len(cards)
    gap = 0.8
    card_w = (SW - 2 * MARGIN - gap * (n - 1)) / n
    for i, (ct, cd) in enumerate(cards):
        x = MARGIN + i * (card_w + gap)
        rect(slide, x, 2.4, card_w, 3.6, th["card"], line=th["accent"], line_w=1)
        # 卡片内：标题(18) + 正文(14, 大框便于试填装下内容) 两个明确区域
        txt(slide, x + 0.3, 2.7, card_w - 0.6, 0.8, ct, 18, th["accent"], bold=True)
        txt(slide, x + 0.3, 3.65, card_w - 0.6, 2.6, cd, 14, th["body"], spacing=1.35)


def page_content_b(slide, th, title, paras):
    bg = slide.background.fill
    bg.solid(); bg.fore_color.rgb = rgb(th["bg"])
    decoration(slide, th)
    txt(slide, MARGIN, 1.1, SW - 2 * MARGIN, 1.0, title, 30, th["title"], bold=True,
        align=PP_ALIGN.CENTER)
    rect(slide, SW / 2 - 1.0, 2.15, 2.0, 0.05, th["accent"])
    y = 2.7
    for p in paras:
        txt(slide, 2.2, y, SW - 4.4, 1.1, p, 15, th["body"], align=PP_ALIGN.CENTER, spacing=1.3)
        y += 1.15


def page_closing(slide, th, title, subtitle):
    bg = slide.background.fill
    bg.solid(); bg.fore_color.rgb = rgb(th["cover_bg"])
    txt(slide, 1.5, 2.7, 10.33, 1.4, title, 44, th["cover_title"], bold=True,
        align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
    rect(slide, SW / 2 - 1.0, 4.2, 2.0, 0.06, th["accent"])
    txt(slide, 1.5, 4.4, 10.33, 0.8, subtitle, 18, th["cover_sub"], align=PP_ALIGN.CENTER)


# ---------------------------------------------------------------------------
# 四套视觉语言（套与套之间颜色 / 封面构成 / 装饰母题截然不同）
# ---------------------------------------------------------------------------
THEMES = [
    {
        "id": "master_classic_blue", "name": "政务经典（深蓝）", "category": "工作汇报",
        "bg": "FFFFFF", "title": "1F3A5F", "body": "333333", "accent": "1F3A5F",
        "card": "EAF0F7", "cover_bg": "1F3A5F", "cover_title": "FFFFFF",
        "cover_sub": "DCE6F2", "footer": "9AA7B5", "cover_variant": "center",
    },
    {
        "id": "master_warm_gold", "name": "暖金简约（米棕）", "category": "总结汇报",
        "bg": "FBF6EC", "title": "5C4326", "body": "4A4036", "accent": "8B6834",
        "card": "F1E6D2", "cover_bg": "8B6834", "cover_title": "FFFFFF",
        "cover_sub": "F3E6CF", "footer": "B7A88C", "cover_variant": "left",
    },
    {
        "id": "master_tech_dark", "name": "科技深色（石板青）", "category": "数字治理",
        "bg": "1B2733", "title": "FFFFFF", "body": "C9D4DC", "accent": "2BA8A0",
        "card": "243443", "cover_bg": "0F1A24", "cover_title": "2BA8A0",
        "cover_sub": "8FB7B2", "footer": "6E8493", "cover_variant": "top",
    },
    {
        "id": "master_fresh_green", "name": "清新青绿（卡片）", "category": "法治宣传",
        "bg": "F4FAF6", "title": "1F5C42", "body": "2E3D36", "accent": "2E7D5B",
        "card": "DDF1E6", "cover_bg": "2E7D5B", "cover_title": "FFFFFF",
        "cover_sub": "DDF1E6", "footer": "8FB7A6", "cover_variant": "right",
    },
]

TOC_ITEMS = ["总体工作情况", "重点数据分析", "典型经验做法", "存在问题剖析", "下一步工作安排"]
SECTION_1 = ("01", "总体工作情况", "全年工作脉络与核心成效概览")
SECTION_2 = ("02", "下一步工作安排", "明确目标、压实责任、务求实效")
CONTENT_A = [
    "围绕年度重点任务，统筹推进各项工作落地见效，形成可复制、可推广的经验做法。",
    "坚持问题导向与目标导向相结合，把规范化建设贯穿业务全流程，持续提升履职能力。",
    "注重源头治理与末端化解并重，推动矛盾发现在早、化解在小，切实维护社会和谐稳定。",
]
TWO_COL_L = ("一、健全工作机制。\n完善闭环管理，明确责任清单，确保事事有人抓、件件有着落。\n\n"
             "二、强化能力建设。\n分层分类开展培训，提升一线人员专业素养与实战本领。")
TWO_COL_R = ("三、深化数字赋能。\n推动业务上线、数据贯通，以信息化手段提升治理效能。\n\n"
             "四、严格监督考核。\n建立量化指标，定期开展评估，倒逼工作提质增效。")
IMAGE_PARAS = [
    "图示展示关键环节的衔接关系与流程要点，便于直观理解整体脉络。",
    "强调协同联动，打破条块分割，形成上下贯通、左右协同的工作格局。",
]
CARDS = [
    ("压实责任", "将任务分解到岗、落实到人，建立台账跟踪问效，形成闭环管理。"),
    ("数字赋能", "以信息化手段贯通业务，推动数据贯通与流程协同，提升治理整体效能。"),
]
CONTENT_B = [
    "以群众满意度为标尺，把每一项工作做细做实，让法治成果可感可及。",
    "健全长效机制，推动从“被动应对”向“主动治理”转变。",
]


def build_one(theme: dict, out_dir: Path) -> Path:
    prs = Presentation()
    prs.slide_width = Inches(SW)
    prs.slide_height = Inches(SH)
    blank = prs.slide_layouts[6]

    s = prs.slides.add_slide(blank)
    page_cover(s, theme, "XX 工作汇报", "年度总结与下一步安排", theme["cover_variant"])

    s = prs.slides.add_slide(blank)
    page_toc(s, theme, TOC_ITEMS)

    s = prs.slides.add_slide(blank)
    page_section(s, theme, *SECTION_1)

    s = prs.slides.add_slide(blank)
    page_section(s, theme, *SECTION_2)

    s = prs.slides.add_slide(blank)
    page_content_a(s, theme, "一、总体工作成效", CONTENT_A)

    s = prs.slides.add_slide(blank)
    page_two_col(s, theme, "二、主要举措", TWO_COL_L, TWO_COL_R)

    s = prs.slides.add_slide(blank)
    page_content_image(s, theme, "三、流程与协同", IMAGE_PARAS)

    s = prs.slides.add_slide(blank)
    page_cards(s, theme, "四、工作抓手", CARDS)

    s = prs.slides.add_slide(blank)
    page_content_b(s, theme, "五、总体要求", CONTENT_B)

    s = prs.slides.add_slide(blank)
    page_closing(s, theme, "谢谢聆听", "恳请批评指正")

    out = out_dir / f"{theme['id']}.pptx"
    prs.save(str(out))
    return out


def main():
    out_dir = REPO / "server" / "app" / "application" / "ppt" / "templates" / "gov"
    out_dir.mkdir(parents=True, exist_ok=True)
    for th in THEMES:
        p = build_one(th, out_dir)
        print("written:", p.name)


if __name__ == "__main__":
    main()
