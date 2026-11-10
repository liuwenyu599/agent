"""Model SVG artwork and photo/text overlay remain bounded and renderable."""
import io
import json
import sys
from pathlib import Path

import pytest
from PIL import Image
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.util import Inches

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.application.ppt import ppt_engine, svg_layer
from app.application.ppt.page_authoring import _accept, author_pages
from app.application.ppt.page_scene import explain, plan, wireframe


SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 540">'
       '<path d="M 80 260 C 260 80 650 450 890 160" fill="none" '
       'stroke="#c00000" stroke-width="22"/></svg>')


def _overlay_slide(photo: Path):
    return {"type": "content", "title": "现场学习", "points": [
        "围绕业务问题开展研讨", "结合实际提出改进办法"],
        "_image": {"file_path": str(photo), "caption": "会议现场"},
        "design": {"image_overlay": "dark", "image_role": "evidence", "svg": SVG,
                   "regions": [
                       {"ref": "title", "x": .08, "y": .05, "w": .84, "h": .12},
                       {"ref": "image", "x": .08, "y": .24, "w": .84, "h": .60},
                       {"ref": "point:0", "x": .13, "y": .35, "w": .72, "h": .17},
                       {"ref": "point:1", "x": .13, "y": .60, "w": .72, "h": .17},
                   ]}}


def test_svg_curved_paths_render_to_transparent_layer():
    assert svg_layer.validate(SVG) == ""
    with Image.open(io.BytesIO(svg_layer.to_png(SVG))) as image:
        assert image.size == (2400, 1350)
        assert image.mode == "RGBA"
        assert image.getpixel((0, 0))[3] == 0


def test_svg_canvas_matches_a_four_by_three_slide():
    svg = SVG.replace('0 0 960 540', '0 0 960 720')
    assert svg_layer.validate(svg, width=10 * 914400, height=7.5 * 914400) == ""
    assert svg_layer.validate(SVG, width=10 * 914400, height=7.5 * 914400)
    with Image.open(io.BytesIO(svg_layer.to_png(
            svg, width=10 * 914400, height=7.5 * 914400))) as image:
        assert image.size == (2400, 1800)


def test_four_by_three_svg_renders_at_240_dpi_and_caps_larger_requests():
    svg = SVG.replace('0 0 960 540', '0 0 960 720')
    with Image.open(io.BytesIO(svg_layer.to_png(svg, scale=2.5))) as image:
        assert image.size == (2400, 1800)
    with Image.open(io.BytesIO(svg_layer.to_png(svg, scale=4))) as image:
        assert image.width * image.height <= 2400 * 1800
        assert image.width >= 2000


def test_invisible_svg_shape_reports_its_element_number():
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 540">'
           '<rect x="20" y="20" width="100" height="100" fill="#c00000"/>'
           '<path d="" fill="#c00000"/></svg>')
    with pytest.raises(ValueError, match="第2个图形"):
        svg_layer.to_png(svg, scale=.5)


def test_fully_covered_svg_shape_is_reported_but_thin_curve_is_kept():
    covered = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 540">'
               '<rect x="20" y="20" width="100" height="100" fill="#c00000"/>'
               '<rect x="20" y="20" width="100" height="100" fill="#0000ff"/>'
               '</svg>')
    with pytest.raises(ValueError, match="第1个图形"):
        svg_layer.to_png(covered, scale=.5)
    thin = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 540">'
            '<path d="M 0 0 L 960 540" fill="none" '
            'stroke="#c00000" stroke-width="1"/></svg>')
    assert svg_layer.to_png(thin, scale=.5)


def test_model_receives_specific_invisible_shape_reason(tmp_path):
    photo = tmp_path / "photo.png"
    Image.new("RGB", (900, 600), "#667788").save(photo)
    slide = _overlay_slide(photo)
    bad_svg = SVG.replace('</svg>', '<path d="" fill="#c00000"/></svg>')
    accepted, reason = _accept(slide, {}, {
        "regions": slide["design"]["regions"], "svg": bad_svg,
        "image_overlay": "dark"})
    assert not accepted and "第2个图形" in reason


def test_adaptive_export_warns_when_svg_is_invalid():
    slide = {"type": "content", "title": "现场", "points": ["工作要点"],
             "design": {"svg": SVG.replace('</svg>',
                       '<path d="" fill="#c00000"/></svg>')}}
    template = {"colors": ppt_engine.DEFAULT_COLORS,
                "layouts": ppt_engine.DEFAULT_LAYOUTS, "font": "微软雅黑"}
    warnings = []
    ppt_engine.render_pptx({"slides": [slide]}, template,
                           adaptive=True, warnings=warnings)
    assert any("第2个图形" in warning for warning in warnings)


def test_svg_rejects_nearly_full_opaque_background_layer():
    background = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 540">'
                  '<rect width="960" height="540" fill="#c00000"/></svg>')
    with pytest.raises(ValueError, match="60%"):
        svg_layer.to_png(background, scale=.5)


def test_four_by_three_wireframe_uses_full_height():
    slide = {"type": "content", "title": "现场", "points": ["要点"],
             "design": {"svg": SVG.replace('0 0 960 540', '0 0 960 720')}}
    scene = plan(slide, "content.bullets")
    preview = wireframe(scene, slide, canvas_height=720)
    assert 'viewBox="0 0 960 720"' in preview
    assert 'width="960" height="720"/>' in preview


def test_svg_rejects_text_images_scripts_and_external_resources():
    for fragment in ('<text x="1">示例事实</text>', '<image href="https://x"/>',
                     '<script>bad()</script>', '<path fill="url(https://x)"/>',
                     '<defs><linearGradient id="g"/></defs>', '<!DOCTYPE svg>'):
        candidate = SVG.replace('</svg>', fragment + '</svg>')
        assert svg_layer.validate(candidate)
    assert svg_layer.validate(SVG.replace('#c00000', 'url(#missing)'))
    assert svg_layer.validate(SVG.replace('#c00000', 'unsupported-color'))


def test_svg_rejects_renderer_unsupported_clip_and_mask():
    for fragment in ('<clipPath id="c"><rect width="30" height="30"/></clipPath>',
                     '<mask id="m"><rect width="30" height="30"/></mask>'):
        assert svg_layer.validate(SVG.replace('</svg>', fragment + '</svg>'))


def test_photo_text_overlap_requires_a_contained_text_region(tmp_path):
    photo = tmp_path / "photo.png"
    Image.new("RGB", (900, 600), "#667788").save(photo)
    slide = _overlay_slide(photo)
    assert explain(slide["design"]["regions"], slide) == ""
    slide["design"]["image_overlay"] = "none"
    assert "重叠" in explain(slide["design"]["regions"], slide)


def test_model_authored_svg_overlay_survives_outline_normalization(tmp_path):
    photo = tmp_path / "photo.png"
    Image.new("RGB", (900, 600), "#667788").save(photo)
    slide = _overlay_slide(photo)
    proposal = {"pages": [{"page": 1, "regions": slide["design"]["regions"],
                           "svg": SVG, "image_overlay": "dark"}]}

    class Assistant:
        def complete(self, *_args, **_kwargs):
            return json.dumps(proposal)

    slide["design"] = {"image_role": "evidence"}
    authored = author_pages({"slides": [slide]}, {}, Assistant())
    design = authored["slides"][0]["design"]
    assert design["svg"] == SVG and design["image_overlay"] == "dark"
    normalized = ppt_engine.normalize_outline(authored, require_bookends=False)
    assert normalized["slides"][0]["design"]["svg"] == SVG
    assert normalized["slides"][0]["design"]["image_overlay"] == "dark"


def test_model_receives_four_by_three_svg_viewbox(tmp_path):
    photo = tmp_path / "photo.png"
    Image.new("RGB", (900, 600), "#667788").save(photo)
    slide = _overlay_slide(photo)
    slide["design"] = {"image_role": "evidence"}
    proposal = {"pages": [{"page": 1, "regions": _overlay_slide(photo)["design"]["regions"],
                           "svg": SVG.replace('0 0 960 540', '0 0 960 720'),
                           "image_overlay": "dark"}]}

    class Assistant:
        prompt = ""

        def complete(self, messages, **_kwargs):
            self.prompt = messages[0]["content"]
            return json.dumps(proposal)

    assistant = Assistant()
    template = {"layout_library": [{"slide_size": {
        "w": 10 * 914400, "h": int(7.5 * 914400)}}]}
    authored = author_pages({"slides": [slide]}, template, assistant)
    assert "0 0 960 720" in assistant.prompt
    assert authored["slides"][0]["design"]["svg"] == proposal["pages"][0]["svg"]


def test_template_overlay_exports_photo_scrim_and_editable_white_text(tmp_path):
    photo = tmp_path / "photo.png"
    Image.new("RGB", (900, 600), "#667788").save(photo)
    source = Presentation()
    source.slides.add_slide(source.slide_layouts[6])
    stream = io.BytesIO()
    source.save(stream)
    base = stream.getvalue()
    library = ppt_engine.analyze_template(base)["layouts"]
    slide = _overlay_slide(photo)
    slide["design"]["svg"] = SVG.replace('0 0 960 540', '0 0 960 720')
    diagnostics = []
    output = ppt_engine.build_pptx_learned(
        {"slides": [slide]}, {"colors": ppt_engine.DEFAULT_COLORS,
                              "font": "微软雅黑"}, base, library,
        warnings=[], diagnostics=diagnostics)
    assert diagnostics[0]["composition"] == "model"
    result = Presentation(io.BytesIO(output)).slides[0]
    assert sum(shape.shape_type == 13 for shape in result.shapes) >= 2
    assert next(shape.image.size for shape in result.shapes
                if shape.shape_type == 13) == (2400, 1800)
    for shape in result.shapes:
        if shape.has_text_frame and shape.text in slide["points"]:
            run = shape.text_frame.paragraphs[0].runs[0]
            assert run.font.color.rgb == RGBColor(255, 255, 255)


def test_adaptive_overlay_keeps_svg_photo_and_editable_text(tmp_path):
    photo = tmp_path / "photo.png"
    Image.new("RGB", (900, 600), "#667788").save(photo)
    slide = _overlay_slide(photo)
    template = {"colors": ppt_engine.DEFAULT_COLORS,
                "layouts": ppt_engine.DEFAULT_LAYOUTS, "font": "微软雅黑"}
    output = ppt_engine.render_pptx({"slides": [slide]}, template, adaptive=True)
    result = Presentation(io.BytesIO(output)).slides[0]
    assert sum(shape.shape_type == 13 for shape in result.shapes) >= 2
    for shape in result.shapes:
        if shape.has_text_frame and shape.text in slide["points"]:
            run = shape.text_frame.paragraphs[0].runs[0]
            assert run.font.color.rgb == RGBColor(255, 255, 255)


def test_svg_cannot_cover_preserved_template_footer(tmp_path):
    photo = tmp_path / "photo.png"
    Image.new("RGB", (900, 600), "#667788").save(photo)
    source = Presentation()
    page = source.slides.add_slide(source.slide_layouts[6])
    page.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(.5), Inches(6.9),
                          Inches(1.2), Inches(.3))
    stream = io.BytesIO()
    source.save(stream)
    base = stream.getvalue()
    library = ppt_engine.analyze_template(base)["layouts"]
    slide = _overlay_slide(photo)
    slide["design"]["svg"] = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 720">'
        '<rect x="45" y="655" width="130" height="45" fill="#c00000"/>'
        '</svg>')
    diagnostics = []
    warnings = []
    ppt_engine.build_pptx_learned(
        {"slides": [slide]}, {"colors": ppt_engine.DEFAULT_COLORS,
                              "font": "微软雅黑"}, base, library,
        warnings=warnings, diagnostics=diagnostics)
    assert diagnostics[0]["composition"] == "readable"
    assert "SVG" in diagnostics[0]["composition_skip"]
    assert any("SVG" in warning for warning in warnings)
