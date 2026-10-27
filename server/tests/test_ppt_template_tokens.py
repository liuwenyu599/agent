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
    _rendered, warnings, _analysis = _render(data, outline)
    assert any("未能放入" in warning for warning in warnings)
