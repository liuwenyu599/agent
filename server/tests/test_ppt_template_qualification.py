"""A source slide joins the reusable library only after replacement probes."""
import io
from pathlib import Path

from pptx import Presentation
from pptx.util import Inches, Pt

from app.application.ppt import ppt_engine, template_qualification


def _textbox(slide, x, y, w, h, text, size=20):
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    run = box.text_frame.paragraphs[0].add_run()
    run.text = text
    run.font.size = Pt(size)
    return box


def _source():
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    blank = prs.slide_layouts[6]
    cover = prs.slides.add_slide(blank)
    _textbox(cover, 1.5, 2.1, 10, 1.1, "{{title}}", 34)
    content = prs.slides.add_slide(blank)
    content.notes_slide.notes_text_frame.text = "PPT_LAYOUT_TYPE:content"
    _textbox(content, .8, .5, 11, .8, "{{title}}", 28)
    _textbox(content, .9, 2, 5, 1, "{{point1}}", 20)
    _textbox(content, 7, 2, 5, 1, "{{point2}}", 20)
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


def test_qualified_layouts_are_rendered_with_short_medium_and_long_samples():
    source = _source()
    learned = ppt_engine.analyze_template(source)
    result = template_qualification.qualify_template(source, learned)
    assert result == {"qualified": 2, "rejected": 0}
    assert template_qualification.has_qualified_content(learned)
    for layout in learned["layouts"]:
        review = layout["qualification"]
        assert review["status"] == "qualified"
        assert review["probes"]["short"] == "passed"
        assert review["probes"]["medium"] == "passed"
        assert review["slots"]


def test_review_deck_contains_filled_pages_for_each_qualified_layout(tmp_path):
    source = _source()
    learned = ppt_engine.analyze_template(source)
    template_qualification.qualify_template(source, learned)
    deck, ids = template_qualification.build_probe_deck(source, learned, tmp_path)
    assert ids == [item["id"] for item in learned["layouts"]]
    prs = Presentation(io.BytesIO(deck))
    assert len(prs.slides) == len(ids)
    for slide in prs.slides:
        text = "\n".join(shape.text_frame.text for shape in slide.shapes
                         if getattr(shape, "has_text_frame", False))
        assert "{{" not in text
        assert "推进司法" in text


def test_bad_layout_is_kept_for_review_but_never_selected():
    source = _source()
    learned = ppt_engine.analyze_template(source)
    bad = dict(learned["layouts"][1])
    bad["id"] = "bad"
    bad["element_schema"] = [{"kind": "text", "x": 1.05, "y": .3,
                              "w": .2, "h": .1, "font_size": 20}]
    bad["qualification"] = {"status": "rejected", "issues": ["越出页面"]}
    assert ppt_engine._pick_layout([bad], "content", {}, "bad") is None
    assert ppt_engine.template_content_budget([bad]) == []

    learned["layouts"] = [bad, learned["layouts"][1]]
    result = template_qualification.qualify_template(source, learned)
    assert result["rejected"] == 1
    assert "可编辑文字框越出页面" in bad["qualification"]["issues"]
    assert template_qualification.has_qualified_content(learned)
    assert ppt_engine.template_content_budget([bad] * 25 + [learned["layouts"][1]])


def test_cover_only_after_qualification_is_not_usable():
    source = _source()
    learned = ppt_engine.analyze_template(source)
    learned["layouts"][1]["element_schema"] = []
    template_qualification.qualify_template(source, learned)
    assert not template_qualification.has_qualified_content(learned)


def test_large_kpi_number_cannot_be_mistaken_for_the_page_title():
    layout = {"detected_type": "data", "element_schema": [
        {"kind": "text", "role": "content", "x": .08, "y": .06,
         "w": .8, "h": .1, "font_size": 26, "placeholder_keys": []},
        {"kind": "text", "role": "content", "x": .12, "y": .35,
         "w": .2, "h": .12, "font_size": 42, "placeholder_keys": []},
    ], "text_regions": [
        {"role": "title", "x": .12, "y": .35, "w": .2, "h": .12,
         "font_size": 42},
        {"role": "body", "x": .08, "y": .06, "w": .8, "h": .1,
         "font_size": 26},
    ]}
    assert "标题槽可能误识别为正文数字或卡片" in (
        template_qualification._source_issues(layout))


def test_toc_display_number_is_not_rejected_as_a_card_title():
    layout = {"detected_type": "toc", "element_schema": [
        {"kind": "text", "role": "content", "x": .1, "y": .28,
         "w": .32, "h": .17, "font_size": 72, "placeholder_keys": []},
        {"kind": "text", "role": "content", "x": .59, "y": .12,
         "w": .19, "h": .1, "font_size": 40, "placeholder_keys": []},
    ], "text_regions": []}
    assert "标题槽可能误识别为正文数字或卡片" not in (
        template_qualification._source_issues(layout))


def test_repository_sample_data_page_is_not_misread_as_a_title():
    source = (Path(__file__).resolve().parents[2] /
              "deliverables/_diversity_check/gov_report_red.pptx").read_bytes()
    learned = ppt_engine.analyze_template(source)
    template_qualification.qualify_template(source, learned)
    data_pages = [layout for layout in learned["layouts"]
                  if layout.get("detected_type") == "data"]
    assert data_pages
    assert any("标题槽可能误识别为正文数字或卡片" in
               layout["qualification"]["issues"] for layout in data_pages)


def test_long_probe_failure_is_visible_without_rejecting_compact_layout(monkeypatch):
    source = _source()
    learned = ppt_engine.analyze_template(source)
    original = template_qualification._render_probe

    def probe(source_bytes, learned_spec, layout, density):
        if density == 1.0 and layout.get("detected_type") == "content":
            return "长文超出可用文字区"
        return original(source_bytes, learned_spec, layout, density)

    monkeypatch.setattr(template_qualification, "_render_probe", probe)
    template_qualification.qualify_template(source, learned)
    content = next(layout for layout in learned["layouts"]
                   if layout.get("detected_type") == "content")
    assert content["qualification"]["status"] == "qualified"
    assert "long：长文超出可用文字区" in content["qualification"]["warnings"]
