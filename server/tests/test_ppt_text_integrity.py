# -*- coding: utf-8 -*-
"""模板克隆文本完整性回归测试（实机验收暴露的两类 P0）：

1. 文本截断：模板槽位比内容小时必须自动缩号；缩到硬下限仍装不下要
   触发告警并降级可读兜底版式——绝不能给用户一篇半截话的公文。
2. 换行丢失：模型输出的列表/段落（\n 或 "- " 前缀）填充时必须保留
   段落结构，多占位符（{{point1}}/{{point2}}）逐条入座。
"""
import io
import sys
from pathlib import Path

from pptx import Presentation
from pptx.util import Emu, Inches, Pt

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.application.ppt import ppt_engine  # noqa: E402

W, H = 12192000, 6858000
LONG_POINT = ("坚持和发展新时代枫桥经验，深化人民调解、行政调解、司法调解联动机制，"
              "把矛盾纠纷化解在基层、化解在萌芽状态，切实提升人民群众的获得感幸福感安全感。")


def _blank_deck():
    prs = Presentation()
    prs.slide_width, prs.slide_height = Emu(W), Emu(H)
    return prs, prs.slide_layouts[6]


def test_split_multiline_points_expands_and_strips_bullets():
    assert ppt_engine._split_multiline_points(
        ["第一项工作\n第二项工作", "- 第三项工作", "• 第四项\n* 第五项", "", "普通要点"]) == [
        "第一项工作", "第二项工作", "第三项工作", "第四项", "第五项", "普通要点"]
    # 拆不出子行时保持原样
    assert ppt_engine._split_multiline_points(["单条要点"]) == ["单条要点"]
    assert ppt_engine._split_multiline_points([]) == []


def test_replace_tokens_preserves_newlines_as_paragraphs():
    prs, blank = _blank_deck()
    shape = prs.slides.add_slide(blank).shapes.add_textbox(
        Inches(1), Inches(1), Inches(6), Inches(3))
    shape.text_frame.text = "{{point1}}"
    ppt_engine._replace_template_tokens(
        shape, {"point1": "第一行要点\n第二行要点\n\n第三行要点"})
    paras = [p.text for p in shape.text_frame.paragraphs]
    assert paras == ["第一行要点", "第二行要点", "", "第三行要点"]
    assert "\n" not in "".join(p.text for p in shape.text_frame.paragraphs[:1])


def test_replace_tokens_keeps_run_format_across_split_lines():
    from pptx.dml.color import RGBColor
    shape = _blank_deck()[0].slides.add_slide(_blank_deck()[1]).shapes.add_textbox(
        Inches(1), Inches(1), Inches(6), Inches(3))
    run = shape.text_frame.paragraphs[0].add_run()
    run.text = "{{point1}}"
    run.font.size = Pt(20)
    run.font.bold = True
    run.font.color.rgb = RGBColor(20, 80, 160)
    ppt_engine._replace_template_tokens(shape, {"point1": "甲要点\n乙要点"})
    first, second = shape.text_frame.paragraphs[0].runs[0], \
        shape.text_frame.paragraphs[1].runs[0]
    assert (first.text, second.text) == ("甲要点", "乙要点")
    assert second.font.size.pt == 20 and second.font.bold
    assert second.font.color.rgb == RGBColor(20, 80, 160)


def test_multiline_point_becomes_separate_paragraphs_after_fill():
    """含 \n 的单条要点填充后必须展开为多段，而不是捏成一个长段。"""
    prs, blank = _blank_deck()
    slide = prs.slides.add_slide(blank)
    slide.shapes.add_textbox(Inches(0.5), Inches(0.4), Inches(7), Inches(1)).text = "{{title}}"
    body = slide.shapes.add_textbox(Inches(0.8), Inches(1.8), Inches(8), Inches(3.2))
    body.text_frame.text = "{{point1}}"
    source = io.BytesIO()
    prs.save(source)
    library = ppt_engine.analyze_template(source.getvalue())["layouts"]
    outline = {"slides": [{"type": "content", "title": "主要工作成效",
                           "points": ["矛盾纠纷排查化解\n诉源治理减量增效\n联动机制闭环管理"]}]}
    warnings = []
    data = ppt_engine.build_pptx_learned(
        outline, {"colors": ppt_engine.DEFAULT_COLORS, "font": "思源黑体",
                  "layouts": {}}, source.getvalue(), library, warnings)
    result = Presentation(io.BytesIO(data))
    all_paras = [p.text.strip() for sh in result.slides[0].shapes
                 if sh.has_text_frame for p in sh.text_frame.paragraphs]
    lines = ["矛盾纠纷排查化解", "诉源治理减量增效", "联动机制闭环管理"]
    # 每行都是独立段落（learned 直填的段落化，或可读兜底的逐条排版，两种机制都算过）
    for line in lines:
        assert any(line == p for p in all_paras), \
            f"「{line}」未独立成段: {all_paras}"
    # 且绝无两行被捏进同一个段落（换行丢失的标志）
    assert not any(lines[0] in p and lines[2] in p for p in all_paras), all_paras


def test_shrink_returns_flag_not_silent_overflow():
    prs, blank = _blank_deck()
    slide = prs.slides.add_slide(blank)
    tiny = slide.shapes.add_textbox(Inches(0.2), Inches(0.2), Inches(1.0), Inches(0.30))
    run = tiny.text_frame.paragraphs[0].add_run()
    run.text = LONG_POINT
    run.font.size = Pt(24)
    # 硬下限仍装不下 → 返回 None（不再静默保持原字号溢出）
    assert ppt_engine._shrink_text_to_fit(
        tiny, prs.slide_width, prs.slide_height) is None
    roomy = slide.shapes.add_textbox(Inches(1.5), Inches(1.5), Inches(8), Inches(3))
    run2 = roomy.text_frame.paragraphs[0].add_run()
    run2.text = LONG_POINT
    run2.font.size = Pt(24)
    fitted = ppt_engine._shrink_text_to_fit(roomy, prs.slide_width, prs.slide_height)
    assert fitted is not None and fitted >= 13


def test_body_shrunk_below_wuhao_is_unfit_not_delivered():
    """长正文缩到五号（10.5pt）以下虽能「挤进」小框，也必须整页降级——
    正式汇报不给用户一页 9pt 的正文（短标签/图注不受此限）。"""
    prs, blank = _blank_deck()
    slide = prs.slides.add_slide(blank)
    # 2.0in 宽 × 0.55in 高的槽：六十字长句只能缩到 9~10pt 才装得下
    box = slide.shapes.add_textbox(Inches(0.3), Inches(0.3), Inches(2.0), Inches(0.55))
    box.text_frame.text = "{{point1}}"
    layout = {"detected_type": "content", "element_schema": []}
    sdata = {"type": "content", "title": "深化调解工作", "points": [LONG_POINT]}
    warnings = []
    unfit = ppt_engine._fill_learned_slide(
        slide, layout, sdata, ppt_engine.DEFAULT_COLORS, "思源黑体",
        prs.slide_width, prs.slide_height, prs, warnings)
    assert unfit is True
    assert any("放不下" in w or "可读版式" in w for w in warnings)


def test_short_label_may_stay_small_without_degrade():
    """短标签（<20 字）走小字槽是模板设计，不该触发整页降级。"""
    prs, blank = _blank_deck()
    slide = prs.slides.add_slide(blank)
    box = slide.shapes.add_textbox(Inches(0.3), Inches(0.3), Inches(1.2), Inches(0.35))
    box.text_frame.text = "{{point1}}"
    layout = {"detected_type": "content", "element_schema": []}
    sdata = {"type": "content", "title": "标题", "points": ["2026年11月"]}
    warnings = []
    unfit = ppt_engine._fill_learned_slide(
        slide, layout, sdata, ppt_engine.DEFAULT_COLORS, "思源黑体",
        prs.slide_width, prs.slide_height, prs, warnings)
    assert unfit is False


def test_unfittable_fill_flags_page_for_readable_fallback():
    """缩号到硬下限仍装不下：填充方返回 unfit 标记并写告警，由调用方降级。"""
    prs, blank = _blank_deck()
    slide = prs.slides.add_slide(blank)
    box = slide.shapes.add_textbox(Inches(0.3), Inches(0.3), Inches(1.0), Inches(0.35))
    box.text_frame.text = "{{point1}}"
    layout = {"detected_type": "content", "element_schema": []}
    sdata = {"type": "content", "title": "深化调解工作", "points": [LONG_POINT]}
    warnings = []
    unfit = ppt_engine._fill_learned_slide(
        slide, layout, sdata, ppt_engine.DEFAULT_COLORS, "思源黑体",
        prs.slide_width, prs.slide_height, prs, warnings)
    assert unfit is True
    assert any("放不下" in w or "可读版式" in w for w in warnings)


def test_unfittable_page_falls_back_with_full_content_end_to_end():
    """端到端：内容装不进模板槽 → 该页降级可读版式，正文一字不少。"""
    prs, blank = _blank_deck()
    slide = prs.slides.add_slide(blank)
    slide.shapes.add_textbox(Inches(0.5), Inches(0.4), Inches(7), Inches(1)).text = "{{title}}"
    tiny = slide.shapes.add_textbox(Inches(0.6), Inches(1.8), Inches(1.1), Inches(0.35))
    tiny.text_frame.text = "{{point1}}"
    source = io.BytesIO()
    prs.save(source)
    library = ppt_engine.analyze_template(source.getvalue())["layouts"]
    outline = {"slides": [{"type": "content", "title": "深化调解工作",
                           "points": [LONG_POINT,
                                      "第二项：推进公共法律服务体系建设，实现村居法律顾问全覆盖。"]}]}
    warnings = []
    data = ppt_engine.build_pptx_learned(
        outline, {"colors": ppt_engine.DEFAULT_COLORS, "font": "思源黑体",
                  "layouts": {}}, source.getvalue(), library, warnings)
    result = Presentation(io.BytesIO(data))
    all_text = "\n".join(sh.text or "" for sh in result.slides[0].shapes
                         if sh.has_text_frame)
    # 正文完整在页面上（含长句开头与结尾），绝无半截话
    assert LONG_POINT[:12] in all_text and LONG_POINT[-12:] in all_text
    assert "法律顾问全覆盖" in all_text
    assert any("可读版式" in w or "放不下" in w for w in warnings)


# --- 中西文字体统一 / 同级模块字号协调 -------------------------------------

def test_apply_cjk_font_writes_all_three_scripts_and_clears_italic():
    """只写 <a:latin> 时中文仍按 <a:ea> 继承模板宋体、数字落回斜体 Times。"""
    from pptx.oxml.ns import qn
    from app.core.fonts import DEFAULT_CJK_FONT, apply_cjk_font

    prs, blank = _blank_deck()
    shape = prs.slides.add_slide(blank).shapes.add_textbox(
        Inches(1), Inches(1), Inches(5), Inches(1))
    run = shape.text_frame.paragraphs[0].add_run()
    run.text = "98.5%"
    run.font.name = "Times New Roman"
    run.font.italic = True
    apply_cjk_font(run, DEFAULT_CJK_FONT)
    r_pr = run._r.get_or_add_rPr()
    assert run.font.name == DEFAULT_CJK_FONT
    for tag in ("a:ea", "a:cs"):
        node = r_pr.find(qn(tag))
        assert node is not None and node.get("typeface") == DEFAULT_CJK_FONT
    assert r_pr.get("i") in (None, "0", "false")


def test_normalize_theme_font_rejects_latin_and_serif_fonts():
    from app.core.fonts import DEFAULT_CJK_FONT, normalize_theme_font

    assert normalize_theme_font("Times New Roman") == DEFAULT_CJK_FONT
    assert normalize_theme_font("Arial") == DEFAULT_CJK_FONT
    assert normalize_theme_font("SimSun") == DEFAULT_CJK_FONT
    assert normalize_theme_font("宋体") == DEFAULT_CJK_FONT
    assert normalize_theme_font("+mj-lt") == DEFAULT_CJK_FONT
    assert normalize_theme_font(None) == DEFAULT_CJK_FONT
    assert normalize_theme_font("Noto Sans CJK SC") == "Noto Sans CJK SC"
    assert normalize_theme_font("微软雅黑") == "微软雅黑"


def test_extract_style_does_not_inherit_foreign_theme_font():
    import re
    import zipfile
    from app.core.fonts import DEFAULT_CJK_FONT

    prs, blank = _blank_deck()
    slide = prs.slides.add_slide(blank)
    slide.shapes.add_textbox(Inches(1), Inches(1), Inches(5), Inches(1)) \
        .text_frame.text = "98.5%"
    buf = io.BytesIO()
    prs.save(buf)
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(buf.getvalue())) as zin, \
            zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if re.match(r"ppt/theme/theme\d+\.xml$", item.filename):
                data = re.sub(rb'<a:latin typeface="[^"]*"',
                              b'<a:latin typeface="Times New Roman"', data)
                data = re.sub(rb'<a:ea typeface="[^"]*"',
                              b'<a:ea typeface="Times New Roman"', data)
            zout.writestr(item, data)
    assert ppt_engine.extract_style_from_pptx(out.getvalue())["font"] == DEFAULT_CJK_FONT


def test_peer_point_slots_share_one_larger_font_and_official_typeface():
    """模板 sibling 槽「一大三小」或全小字：成稿同页同级必须同号，且往大拉齐。"""
    from pptx.oxml.ns import qn
    from app.core.fonts import DEFAULT_CJK_FONT

    prs, blank = _blank_deck()
    slide = prs.slides.add_slide(blank)
    points = ["坚持政治引领，确保司法行政工作正确方向",
              "聚焦主责主业，全面提升法治建设水平",
              "深化改革创新，激发司法行政内生动力",
              "强化责任担当，为建设法治社会贡献力量"]
    boxes = []
    for index, (text, size) in enumerate(zip(points, (26, 16, 16, 16))):
        col, row = index % 2, index // 2
        box = slide.shapes.add_textbox(
            Emu(int(W * (.08 + col * .45))), Emu(int(H * (.30 + row * .30))),
            Emu(int(W * .38)), Emu(int(H * .20)))
        box.text_frame.text = "{{point%d}}" % (index + 1)
        run = box.text_frame.paragraphs[0].runs[0]
        run.font.size = Pt(size)
        run.font.name = "Times New Roman"
        run.font.italic = True
        boxes.append(box)
    warnings = []
    ppt_engine._fill_learned_slide(
        slide, {"detected_type": "content", "element_schema": []},
        {"type": "content", "title": "总结与展望", "points": points},
        ppt_engine.DEFAULT_COLORS, DEFAULT_CJK_FONT,
        prs.slide_width, prs.slide_height, prs, warnings)

    final_sizes = []
    for index, box in enumerate(boxes, 1):
        runs = [r for p in box.text_frame.paragraphs for r in p.runs]
        assert runs and "".join(r.text for r in runs) == points[index - 1]
        final_sizes.append(max(r.font.size.pt for r in runs
                               if r.font.size is not None))
        r_pr = runs[0]._r.get_or_add_rPr()
        assert runs[0].font.name == DEFAULT_CJK_FONT
        assert r_pr.find(qn("a:ea")).get("typeface") == DEFAULT_CJK_FONT
        assert r_pr.get("i") in (None, "0", "false")
    assert len(set(final_sizes)) == 1, final_sizes
    assert final_sizes[0] >= 20, final_sizes
