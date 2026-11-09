"""模板占位符契约：重复出现的 {{title}} 仍是内容槽，block 内容也能进 {{pointN}}。

这两条都是实测出来的坑：标题每页都在同一位置，被 _mark_fixed 判成装饰后
占位符原样印进成品；卡片/时间轴的内容在 blocks 里，只读 points 会整页取空。
"""
from __future__ import annotations

import io

from pptx import Presentation
from pptx.util import Emu, Pt

from app.application.ppt import ppt_engine

SW, SH = 12192000, 6858000


def _text(slide, x, y, w, h, text, size):
    box = slide.shapes.add_textbox(Emu(int(x)), Emu(int(y)), Emu(int(w)), Emu(int(h)))
    box.text_frame.word_wrap = True
    box.text_frame.paragraphs[0].text = text
    for run in box.text_frame.paragraphs[0].runs:
        run.font.size = Pt(size)
    return box


def _two_page_template(second_body_tokens=3):
    """两页同位置标题：足以触发 _mark_fixed 的“重复出现”判定。
    两页正文槽数量不同，避免被 _layout_signature 去重成单一版式。"""
    prs = Presentation()
    prs.slide_width, prs.slide_height = Emu(SW), Emu(SH)
    blank = prs.slide_layouts[6]

    s = prs.slides.add_slide(blank)
    _text(s, SW * .08, SH * .08, SW * .84, SH * .12, "{{title}}", 30)
    for i, _ in enumerate(range(2)):
        _text(s, SW * .08, SH * (.3 + i * .14), SW * .84, SH * .12, "{{point%d}}" % (i + 1), 18)

    s = prs.slides.add_slide(blank)
    _text(s, SW * .08, SH * .08, SW * .84, SH * .12, "{{title}}", 30)
    for i in range(second_body_tokens):
        _text(s, SW * .08, SH * (.3 + i * .14), SW * .84, SH * .12, "{{point%d}}" % (i + 1), 18)

    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


def _render(data, outline):
    analysis = ppt_engine.analyze_template(data)
    template = {"colors": analysis["colors"], "font": analysis["font"],
                "slide_size": analysis["slide_size"],
                "layouts": {}, "layout_library": analysis["layouts"]}
    warnings = []
    out = ppt_engine.render_pptx(outline, template, base_pptx=data, warnings=warnings)
    return out, warnings, analysis


def _all_text(path_bytes):
    prs = Presentation(io.BytesIO(path_bytes))
    return "\n".join(sh.text_frame.text for slide in prs.slides
                     for sh in slide.shapes if sh.has_text_frame)


def test_repeated_title_placeholder_stays_content_and_is_replaced():
    data = _two_page_template(second_body_tokens=3)
    analysis = ppt_engine.analyze_template(data)
    for layout in analysis["layouts"]:
        for element in layout["element_schema"]:
            if "title" in (element.get("placeholder_keys") or []):
                assert element["role"] == "content"

    outline = {"slides": [
        {"type": "cover", "title": "第一页标题", "points": ["要点甲", "要点乙"]},
        {"type": "content", "title": "第二页标题", "points": ["要点丙", "要点丁"]},
    ]}
    rendered, warnings, analysis = _render(data, outline)
    assert len(analysis["layouts"]) >= 2, "两页应被识别为不同版式，否则没走到克隆链路"
    assert not any("基础排版" in w for w in warnings), "不应整体回退基础排版"
    text = _all_text(rendered)
    assert "{{" not in text
    assert "第一页标题" in text and "第二页标题" in text


def test_block_content_fills_point_tokens():
    data = _two_page_template(second_body_tokens=3)
    outline = {"slides": [
        {"type": "cover", "title": "封面", "points": ["甲"]},
        {"type": "timeline", "title": "推进节点", "blocks": {"timeline": [
            {"time": "一季度", "event": "部署启动"},
            {"time": "二季度", "event": "全面推开"},
            {"time": "三季度", "event": "督查整改"},
        ]}},
    ]}
    rendered, warnings, _analysis = _render(data, outline)
    assert not any("基础排版" in w for w in warnings)
    text = _all_text(rendered)
    assert "一季度　部署启动" in text
    assert "三季度　督查整改" in text


def test_overflow_content_is_reported_instead_of_dropped_silently():
    data = _two_page_template()
    outline = {"slides": [
        {"type": "cover", "title": "封面", "points": ["甲"]},
        {"type": "timeline", "title": "推进节点", "blocks": {"timeline": [
            {"time": "一季度", "event": "部署启动"},
            {"time": "二季度", "event": "全面推开"},
            {"time": "三季度", "event": "督查整改"},
            {"time": "四季度", "event": "总结验收"},
        ]}},
    ]}
    rendered, warnings, _analysis = _render(data, outline)
    # 要点超出槽位时合并进最后一个槽（内容一个不丢），不再整页退回可读排版；
    # 只有真的一格都装不下时才允许出现「仅该页使用可读版式」警告。
    assert "四季度　总结验收" in _all_text(rendered)
    assert "一季度　部署启动" in _all_text(rendered)
    assert not any("仅该页使用可读版式" in warning for warning in warnings)


def test_prepare_template_bytes_inserts_tokens_and_drops_empty_pages():
    """上传即预处理契约：token 写入、主题字体改写、空页删除、4:3 拒绝。"""
    import zipfile

    from app.application.ppt import template_prepare

    prs = Presentation()
    prs.slide_width, prs.slide_height = Emu(12192000), Emu(6858000)
    blank = prs.slide_layouts[6]
    s1 = prs.slides.add_slide(blank)
    s1.shapes.add_textbox(Emu(600000), Emu(400000), Emu(6000000), Emu(700000)) \
        .text_frame.text = "年度工作汇报"
    s1.shapes.add_textbox(Emu(600000), Emu(1300000), Emu(6000000), Emu(800000)) \
        .text_frame.text = "汇报人：张三"
    s2 = prs.slides.add_slide(blank)
    s2.shapes.add_textbox(Emu(600000), Emu(400000), Emu(6000000), Emu(700000)) \
        .text_frame.text = "工作安排"
    s2.shapes.add_textbox(Emu(600000), Emu(1300000), Emu(6000000), Emu(3000000)) \
        .text_frame.text = "事项一"
    prs.slides.add_slide(blank)  # 无文本无图片 → 自动删除
    buf = io.BytesIO()
    prs.save(buf)

    out, notes = template_prepare.prepare_template_bytes(buf.getvalue())
    assert any("空页" in note for note in notes)
    prs2 = Presentation(io.BytesIO(out))
    assert len(prs2.slides) == 2
    texts = "\n".join(sh.text_frame.text for sl in prs2.slides
                      for sh in sl.shapes if sh.has_text_frame)
    assert "{{title}}" in texts
    assert "{{subtitle}}" in texts
    assert "{{point1}}" in texts
    from app.core.fonts import DEFAULT_CJK_FONT, DEFAULT_LATIN_FONT
    with zipfile.ZipFile(io.BytesIO(out)) as z:
        theme = z.read("ppt/theme/theme1.xml").decode("utf-8")
        assert DEFAULT_CJK_FONT in theme
    # run 级：西文 Times / 中文思源，模板的斜体衬线数字不会残留
    from pptx.oxml.ns import qn
    for slide in prs2.slides:
        for shape in slide.shapes:
            if not shape.has_text_frame:
                continue
            for para in shape.text_frame.paragraphs:
                for run in para.runs:
                    r_pr = run._r.get_or_add_rPr()
                    assert run.font.name == DEFAULT_LATIN_FONT
                    for tag in ("a:ea", "a:cs"):
                        node = r_pr.find(qn(tag))
                        assert node is not None and node.get("typeface") == DEFAULT_CJK_FONT
                    assert r_pr.get("i") in (None, "0", "false")

    prs3 = Presentation()  # 默认 4:3 → 明确拒绝，不做等比拉伸
    b3 = io.BytesIO()
    prs3.save(b3)
    try:
        template_prepare.prepare_template_bytes(b3.getvalue())
        raise AssertionError("非 16:9 应被拒绝")
    except template_prepare.RatioNotSupported:
        pass


def test_cover_hint_capsule_takes_subtitle_and_prefix_cleared():
    """封面「在此输入您的党组织名称」提示框是模板留给单位名称的位置，应拿到
    {{subtitle}}；标题前缀框（“20XX 基层党委党支部”式拆段）清空。渲染时副标题
    只进 token 槽，不得按位置兜底落进前缀框、横在主标题旁边。"""
    from app.application.ppt import template_prepare

    prs = Presentation()
    prs.slide_width, prs.slide_height = Emu(12192000), Emu(6858000)
    blank = prs.slide_layouts[6]
    s1 = prs.slides.add_slide(blank)
    s1.shapes.add_textbox(Emu(2800000), Emu(1300000), Emu(4000000), Emu(1100000)) \
        .text_frame.text = "年度党建工作汇报"
    prefix = s1.shapes.add_textbox(Emu(600000), Emu(1400000), Emu(2000000), Emu(800000))
    prefix.text_frame.text = "20XX 基层党委党支部"
    capsule = s1.shapes.add_textbox(Emu(2000000), Emu(3000000), Emu(3000000), Emu(400000))
    capsule.text_frame.text = "在此输入您的党组织名称"
    s2 = prs.slides.add_slide(blank)
    s2.shapes.add_textbox(Emu(600000), Emu(400000), Emu(6000000), Emu(700000)) \
        .text_frame.text = "工作安排"
    s2.shapes.add_textbox(Emu(600000), Emu(1300000), Emu(6000000), Emu(3000000)) \
        .text_frame.text = "事项一"
    buf = io.BytesIO()
    prs.save(buf)

    out, notes = template_prepare.prepare_template_bytes(buf.getvalue())
    assert any("{{subtitle}}" in note for note in notes)
    prs2 = Presentation(io.BytesIO(out))
    cover = prs2.slides[0]
    frames = [(sh.top, sh.text_frame.text.strip()) for sh in cover.shapes
              if sh.has_text_frame]
    by_top = dict(frames)
    assert by_top[3000000] == "{{subtitle}}", "提示框（y=3M）应拿到 subtitle token"
    assert by_top[1400000] == "", "前缀框（y=1.4M）应被清空"

    analysis = ppt_engine.analyze_template(out)
    template = {"colors": analysis["colors"], "font": analysis["font"],
                "slide_size": analysis["slide_size"], "layouts": {},
                "layout_library": analysis["layouts"]}
    outline = {"slides": [
        {"type": "cover", "title": "2024 年度党建工作汇报",
         "subtitle": "中共某某单位委员会", "points": []},
        {"type": "content", "title": "工作安排", "points": ["事项一"]},
    ]}
    rendered = ppt_engine.render_pptx(outline, template, base_pptx=out)
    cover_out = Presentation(io.BytesIO(rendered)).slides[0]
    texts = [sh.text_frame.text.strip() for sh in cover_out.shapes
             if sh.has_text_frame and sh.text_frame.text.strip()]
    assert texts.count("中共某某单位委员会") == 1, "副标题只出现一次（胶囊内）"
    assert "2024 年度党建工作汇报" in texts
