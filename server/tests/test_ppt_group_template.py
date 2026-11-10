# -*- coding: utf-8 -*-
"""组合形状（Group）解析回归测试。

采购来的政务模板常把标题、正文、装饰打包进组合。学习器若只遍历顶层，
组内示例文字既不会被替换，还会原样印进成品，所以解析与填充都必须递归，
并按 chOff/chExt 把子坐标系换算回页面坐标。
"""
import io
import sys
from pathlib import Path

import pytest
from pptx import Presentation
from pptx.oxml.ns import qn
from pptx.util import Emu, Inches

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.application.ppt import ppt_engine  # noqa: E402

W, H = 12192000, 6858000
INCH = 914400


def _set_group_frame(group, left, top, width, height, ch_off=(0, 0), ch_ext=(W, H)):
    """直接写 xfrm，构造「组合边界与子坐标系不一致」的真实模板结构。"""
    xfrm = group._element.grpSpPr.find(qn("a:xfrm"))
    assert xfrm is not None
    off = xfrm.find(qn("a:off"))
    off.set("x", str(int(left)))
    off.set("y", str(int(top)))
    ext = xfrm.find(qn("a:ext"))
    ext.set("cx", str(int(width)))
    ext.set("cy", str(int(height)))
    ch_off_el = xfrm.find(qn("a:chOff"))
    ch_off_el.set("x", str(int(ch_off[0])))
    ch_off_el.set("y", str(int(ch_off[1])))
    ch_ext_el = xfrm.find(qn("a:chExt"))
    ch_ext_el.set("cx", str(int(ch_ext[0])))
    ch_ext_el.set("cy", str(int(ch_ext[1])))


def _blank_deck():
    prs = Presentation()
    prs.slide_width, prs.slide_height = Emu(W), Emu(H)
    return prs, prs.slide_layouts[6]


def test_missing_learned_page_uses_basic_layout_only_for_that_page():
    prs, blank = _blank_deck()
    cover = prs.slides.add_slide(blank)
    cover.shapes.add_textbox(Inches(1), Inches(1), Inches(6), Inches(1)).text = "模板封面"
    cover.shapes.add_textbox(Inches(1), Inches(2), Inches(6), Inches(1)).text = "模板副标题"
    source = io.BytesIO()
    prs.save(source)
    library = ppt_engine.analyze_template(source.getvalue())["layouts"]
    assert library
    outline = {"slides": [
        {"type": "cover", "title": "生成封面", "subtitle": "部门汇报", "points": []},
        {"type": "content", "title": "具体工作", "points": ["要点一", "要点二"]},
    ]}
    warnings = []
    data = ppt_engine.build_pptx_learned(
        outline, {"colors": ppt_engine.DEFAULT_COLORS, "font": "思源黑体",
                  "layouts": {}}, source.getvalue(), library, warnings)
    result = Presentation(io.BytesIO(data))
    assert len(result.slides) == 2
    assert "生成封面" in " ".join(shape.text for shape in result.slides[0].shapes
                                if shape.has_text_frame)
    assert "要点一" in " ".join(shape.text for shape in result.slides[1].shapes
                              if shape.has_text_frame)
    assert any("仅该页" in warning for warning in warnings)


def test_decorative_title_and_tiny_body_are_not_used_for_content():
    layout = {"detected_type": "content", "element_schema": [
        {"kind": "text", "role": "content", "font_size": 138,
         "x": .4, "y": .3, "w": .17, "h": .32, "placeholder_keys": ["title"]},
        {"kind": "text", "role": "content", "font_size": 40,
         "x": .3, "y": .63, "w": .29, "h": .1, "placeholder_keys": ["point1"]},
    ]}
    slide = {"type": "content", "title": "强化政治引领，筑牢思想根基",
             "points": ["严格落实第一议题制度，开展专题研讨。"]}
    assert ppt_engine._learned_layout_fits(layout, slide) is False
    assert ppt_engine._learned_layout_fits(layout, {"type": "toc", "title": "目录"}) is False


def test_unselected_template_photo_cannot_become_generated_content():
    from PIL import Image

    prs, blank = _blank_deck()
    cover = prs.slides.add_slide(blank)
    cover.shapes.add_textbox(Inches(1), Inches(1), Inches(8), Inches(1)).text = "封面"
    page = prs.slides.add_slide(blank)
    page.shapes.add_textbox(Inches(.8), Inches(.5), Inches(9), Inches(.7)).text = "{{title}}"
    page.shapes.add_textbox(Inches(.8), Inches(1.5), Inches(5), Inches(3)).text = "{{point1}}"
    picture = io.BytesIO()
    Image.new("RGB", (16, 16), "red").save(picture, format="PNG")
    picture.seek(0)
    page.shapes.add_picture(picture, Inches(7), Inches(1.5), Inches(5), Inches(3))
    source = io.BytesIO()
    prs.save(source)
    learned = ppt_engine.analyze_template(source.getvalue())
    warnings = []
    result = ppt_engine.render_pptx({"slides": [
        {"type": "content", "title": "工作安排", "points": ["明确职责与时限"]},
    ]}, {"colors": learned["colors"], "font": learned["font"],
         "layout_library": learned["layouts"]}, source.getvalue(), warnings)
    slide = Presentation(io.BytesIO(result)).slides[0]
    assert not any(shape.shape_type == 13 for shape in slide.shapes)
    assert "明确职责与时限" in " ".join(
        shape.text for shape in slide.shapes if shape.has_text_frame)
    # 2026-11-10 起不再强制退回可读版式：示例照片能被精确删掉之后，这一页
    # 继续用模板自己的版式（用户要求「把他们的模板用起来」）。守卫点仍是
    # 「模板的示例照片不能变成成稿内容」，不是「必须退化」。
    assert warnings == [] or not any("示例图片未替换" in w for w in warnings)


def test_picture_fill_inside_rectangle_is_an_example_photo():
    import copy
    from PIL import Image
    from pptx.enum.shapes import MSO_SHAPE

    prs, blank = _blank_deck()
    page = prs.slides.add_slide(blank)
    page.shapes.add_textbox(Inches(.8), Inches(.5), Inches(9), Inches(.7)).text = "{{title}}"
    page.shapes.add_textbox(Inches(.8), Inches(1.5), Inches(5), Inches(3)).text = "{{point1}}"
    payload = io.BytesIO()
    Image.new("RGB", (16, 16), "red").save(payload, format="PNG")
    payload.seek(0)
    picture = page.shapes.add_picture(payload, Inches(7), Inches(1.5), Inches(5), Inches(3))
    frame = page.shapes.add_shape(MSO_SHAPE.RECTANGLE,
                                  Inches(7), Inches(1.5), Inches(5), Inches(3))
    fill = copy.deepcopy(picture._element.blipFill)
    fill.tag = qn("a:blipFill")
    frame._element.spPr.append(fill)
    picture._element.getparent().remove(picture._element)
    source = io.BytesIO()
    prs.save(source)
    learned = ppt_engine.analyze_template(source.getvalue())
    assert any(element.get("image_fill") for layout in learned["layouts"]
               for element in layout["element_schema"])
    warnings = []
    result = ppt_engine.render_pptx({"slides": [
        {"type": "content", "title": "工作安排", "points": ["明确职责与时限"]},
    ]}, {"colors": learned["colors"], "font": learned["font"],
         "layout_library": learned["layouts"]}, source.getvalue(), warnings)
    slide = Presentation(io.BytesIO(result)).slides[0]
    assert not any(shape._element.xpath(".//a:blip") for shape in slide.shapes)
    assert any("可读版式" in warning for warning in warnings)


@pytest.mark.parametrize("point_count", [2, 6])
def test_readable_template_page_retains_selected_image(tmp_path, point_count):
    from PIL import Image

    source_prs, blank = _blank_deck()
    source_prs.slides.add_slide(blank).shapes.add_textbox(
        Inches(1), Inches(1), Inches(6), Inches(1)).text = "{{title}}"
    source = io.BytesIO()
    source_prs.save(source)
    learned = ppt_engine.analyze_template(source.getvalue())
    image_path = tmp_path / "selected.png"
    Image.new("RGB", (640, 360), "blue").save(image_path)
    output = ppt_engine.render_pptx({"slides": [{
        "type": "content", "title": "工作安排",
        "points": [f"工作要点 {index}" for index in range(point_count)],
        "_image": {"file_path": str(image_path)},
    }]}, {"colors": learned["colors"], "font": learned["font"],
          "layout_library": learned["layouts"]}, source.getvalue())
    slide = Presentation(io.BytesIO(output)).slides[0]
    assert sum(shape.shape_type == 13 for shape in slide.shapes) == 1


def test_explicit_image_uses_readable_layout_when_template_has_only_text(tmp_path):
    from PIL import Image

    source_prs, blank = _blank_deck()
    source_slide = source_prs.slides.add_slide(blank)
    source_slide.shapes.add_textbox(Inches(.8), Inches(.5), Inches(10), Inches(.8)).text = "{{title}}"
    source_slide.shapes.add_textbox(Inches(.8), Inches(2), Inches(10), Inches(3)).text = "{{point1}}"
    source = io.BytesIO()
    source_prs.save(source)
    learned = ppt_engine.analyze_template(source.getvalue())
    image_path = tmp_path / "chosen.png"
    Image.new("RGB", (640, 360), "green").save(image_path)
    warnings = []
    output = ppt_engine.render_pptx({"slides": [{
        "type": "content", "title": "工作安排", "points": ["明确职责"],
        "_image": {"file_path": str(image_path)},
    }]}, {"colors": learned["colors"], "font": learned["font"],
          "layout_library": learned["layouts"]}, source.getvalue(), warnings)

    slide = Presentation(io.BytesIO(output)).slides[0]
    assert sum(shape.shape_type == 13 for shape in slide.shapes) == 1
    assert any("可读版式" in item for item in warnings)


def test_template_image_area_follows_page_content_not_source_slot(tmp_path):
    from PIL import Image

    source_prs, blank = _blank_deck()
    source_slide = source_prs.slides.add_slide(blank)
    source_slide.shapes.add_textbox(Inches(.8), Inches(.5), Inches(10), Inches(.8)).text = "{{title}}"
    source_slide.shapes.add_textbox(Inches(.8), Inches(2), Inches(10), Inches(3)).text = "{{point1}}"
    source = io.BytesIO()
    source_prs.save(source)
    learned = ppt_engine.analyze_template(source.getvalue())
    image_path = tmp_path / "wide.png"
    Image.new("RGB", (1200, 700), "blue").save(image_path)
    template = {"colors": learned["colors"], "font": learned["font"],
                "layout_library": learned["layouts"]}

    def rendered(points):
        payload = {"slides": [{"type": "content", "title": "培训安排",
                               "points": points,
                               "_image": {"file_path": str(image_path)}}]}
        data = ppt_engine.render_pptx(payload, template, source.getvalue())
        return Presentation(io.BytesIO(data)).slides[0]

    brief = rendered(["完成专题培训"])
    dense_points = ["组织各部门围绕法规开展专题学习和交流研讨。" * 2
                    for _ in range(5)]
    dense = rendered(dense_points)
    brief_image = next(shape for shape in brief.shapes if shape.shape_type == 13)
    dense_image = next(shape for shape in dense.shapes if shape.shape_type == 13)
    assert brief_image.width > dense_image.width
    dense_text = " ".join(shape.text for shape in dense.shapes if shape.has_text_frame)
    assert all(point in dense_text for point in dense_points)


def test_learned_template_uses_valid_model_regions_for_body_page():
    from pptx.enum.shapes import MSO_SHAPE

    prs, blank = _blank_deck()
    page = prs.slides.add_slide(blank)
    page.shapes.add_textbox(Inches(.8), Inches(.5), Inches(10), Inches(.8)).text = "{{title}}"
    page.shapes.add_textbox(Inches(.8), Inches(2), Inches(10), Inches(3)).text = "{{point1}}"
    stale = page.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(7.5), Inches(2.5),
                                  Inches(2), Inches(2))
    stale.name = "stale-content-card"
    brand = page.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(.15), Inches(.1),
                                  Inches(.4), Inches(.15))
    brand.name = "top-brand-decoration"
    source = io.BytesIO()
    prs.save(source)
    learned = ppt_engine.analyze_template(source.getvalue())
    outline = {"slides": [{
        "type": "content", "title": "工作成效", "points": ["办理流程更加清晰", "群众咨询更加便利"],
        "design": {"regions": [
            {"ref": "title", "x": .12, "y": .05, "w": .76, "h": .13},
            {"ref": "point:0", "x": .12, "y": .30, "w": .33, "h": .36},
            {"ref": "point:1", "x": .55, "y": .30, "w": .33, "h": .36},
        ], "visuals": [
            {"kind": "rect", "x": .10, "y": .28, "w": .37, "h": .40,
             "fill": "light", "radius": True},
            {"kind": "rect", "x": .53, "y": .28, "w": .37, "h": .40,
             "fill": "light", "radius": True},
            {"kind": "gradient", "x": .12, "y": .205, "w": .76, "h": .008,
             "from": "light", "to": "white"},
            {"kind": "line", "x1": .50, "y1": .30, "x2": .50, "y2": .66,
             "stroke": "line", "width": 1.2},
        ]},
    }]}
    template = {"colors": learned["colors"], "font": learned["font"],
                "layout_library": learned["layouts"]}
    data = ppt_engine.render_pptx(outline, template, source.getvalue())
    result = Presentation(io.BytesIO(data))
    rendered = result.slides[0]
    positions = {shape.text: shape.left / result.slide_width
                 for shape in rendered.shapes if shape.has_text_frame and shape.text.strip()}
    # 模型给的是文字框，卡片是它自己画的装饰壳；成稿按内置版式同样的 2% 内缩
    # 排字，否则文字会直接压在卡片边框和顶盖色带上（样稿实测就是这样）。
    assert abs(positions["工作成效"] - .12) < .01
    assert abs(positions["办理流程更加清晰"] - .14) < .01
    assert abs(positions["群众咨询更加便利"] - .57) < .01
    assert "stale-content-card" not in {shape.name for shape in rendered.shapes}
    assert "top-brand-decoration" in {shape.name for shape in rendered.shapes}
    assert sum(shape.name.startswith("Rounded Rectangle") for shape in rendered.shapes) == 2
    assert any(shape._element.xpath(".//a:gradFill") for shape in rendered.shapes)


def test_learned_template_rejects_overlapping_model_regions():
    prs, blank = _blank_deck()
    page = prs.slides.add_slide(blank)
    page.shapes.add_textbox(Inches(.8), Inches(.5), Inches(10), Inches(.8)).text = "{{title}}"
    page.shapes.add_textbox(Inches(.8), Inches(2), Inches(10), Inches(3)).text = "{{point1}}"
    source = io.BytesIO()
    prs.save(source)
    learned = ppt_engine.analyze_template(source.getvalue())
    outline = {"slides": [{
        "type": "content", "title": "工作成效", "points": ["办理流程更加清晰", "群众咨询更加便利"],
        "design": {"regions": [
            {"ref": "title", "x": .12, "y": .05, "w": .76, "h": .13},
            {"ref": "point:0", "x": .12, "y": .30, "w": .50, "h": .36},
            {"ref": "point:1", "x": .55, "y": .30, "w": .33, "h": .36},
        ]},
    }]}
    template = {"colors": learned["colors"], "font": learned["font"],
                "layout_library": learned["layouts"]}
    data = ppt_engine.render_pptx(outline, template, source.getvalue())
    result = Presentation(io.BytesIO(data))
    texts = [shape.text for shape in result.slides[0].shapes
             if shape.has_text_frame and shape.text.strip()]
    assert "工作成效" in texts
    assert all(point in " ".join(texts) for point in outline["slides"][0]["points"])
    assert not any(shape.text == "{{title}}" for shape in result.slides[0].shapes
                   if shape.has_text_frame)


def test_learned_template_uses_model_image_region(tmp_path):
    from PIL import Image

    prs, blank = _blank_deck()
    page = prs.slides.add_slide(blank)
    page.shapes.add_textbox(Inches(.8), Inches(.5), Inches(10), Inches(.8)).text = "{{title}}"
    source = io.BytesIO()
    prs.save(source)
    learned = ppt_engine.analyze_template(source.getvalue())
    image_path = tmp_path / "scene.png"
    Image.new("RGB", (640, 360), "blue").save(image_path)
    outline = {"slides": [{
        "type": "content", "title": "普法宣传", "points": ["面向社区居民讲解常见法律问题"],
        "_image": {"file_path": str(image_path)},
        "design": {"regions": [
            {"ref": "title", "x": .08, "y": .05, "w": .84, "h": .13},
            {"ref": "point:0", "x": .08, "y": .30, "w": .38, "h": .40},
            {"ref": "image", "x": .52, "y": .27, "w": .40, "h": .48},
        ]},
    }]}
    template = {"colors": learned["colors"], "font": learned["font"],
                "layout_library": learned["layouts"]}
    data = ppt_engine.render_pptx(outline, template, source.getvalue())
    result = Presentation(io.BytesIO(data))
    slide = result.slides[0]
    picture = next(shape for shape in slide.shapes if shape.shape_type == 13)
    assert abs(picture.left / result.slide_width - .52) < .01
    assert abs(picture.width / result.slide_width - .40) < .01
    assert "普法宣传" in " ".join(shape.text for shape in slide.shapes
                                  if shape.has_text_frame)


def test_template_body_starts_below_inherited_header_rule():
    from copy import deepcopy
    from pptx.enum.shapes import MSO_SHAPE

    prs, blank = _blank_deck()
    page = prs.slides.add_slide(blank)
    rule = page.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, int(prs.slide_height * .157),
                                 prs.slide_width, int(prs.slide_height * .002))
    blank.shapes._spTree.insert_element_before(deepcopy(rule._element), "p:extLst")
    ppt_engine._delete_shape(rule)
    top, _ = ppt_engine._keep_template_decorations(
        page, prs.slide_width, prs.slide_height)
    assert top >= .17


def test_model_regions_keep_source_template_body_font_scale():
    prs, blank = _blank_deck()
    page = prs.slides.add_slide(blank)
    slide = {"type": "content", "title": "工作进展", "points": ["组织专题学习"],
             "design": {"regions": [
                 {"ref": "title", "x": .08, "y": .05, "w": .84, "h": .12},
                 {"ref": "point:0", "x": .08, "y": .30, "w": .84, "h": .42},
             ]}}
    used = ppt_engine._fill_model_regions_on_template(
        page, slide, {"primary": "C00000", "dark": "262626"}, "思源黑体",
        prs.slide_width, prs.slide_height, .12, .89,
        {"title_font_pt": 32, "body_font_pt": 20})
    assert used
    text = {shape.text: shape for shape in page.shapes if shape.has_text_frame}
    body = text["组织专题学习"].text_frame.paragraphs[0].runs[0]
    assert body.font.size.pt == 20


def test_fill_learned_text_keeps_template_run_format():
    from pptx.dml.color import RGBColor
    from pptx.util import Pt
    prs, blank = _blank_deck()
    shape = prs.slides.add_slide(blank).shapes.add_textbox(
        Inches(1), Inches(1), Inches(6), Inches(2))
    run = shape.text_frame.paragraphs[0].add_run()
    run.text = "示例正文"
    run.font.size = Pt(24)
    run.font.bold = True
    run.font.color.rgb = RGBColor(20, 80, 160)
    ppt_engine._fill_text_region(shape, ["替换后的正文", "第二项"])
    first = shape.text_frame.paragraphs[0].runs[0]
    second = shape.text_frame.paragraphs[1].runs[0]
    assert first.text == "替换后的正文"
    assert first.font.size.pt == second.font.size.pt == 24
    assert first.font.bold and second.font.bold
    assert first.font.color.rgb == second.font.color.rgb == RGBColor(20, 80, 160)


def test_template_import_rejects_four_by_three_page_size():
    prs, blank = _blank_deck()
    prs.slide_width = Inches(10)
    slide = prs.slides.add_slide(blank)
    slide.shapes.add_textbox(Inches(1), Inches(1), Inches(6), Inches(1)).text = "标题"
    slide.shapes.add_textbox(Inches(2), Inches(2), Inches(6), Inches(2)).text = "正文"
    source = io.BytesIO()
    prs.save(source)
    learned = ppt_engine.analyze_template(source.getvalue())
    with pytest.raises(ValueError, match="16:9"):
        ppt_engine.validate_learned_template(learned)


def test_circle_badge_layout_rejects_long_points():
    """「圆徽章+箭头」过渡页：正圆槽的可用文字区是内接矩形（约 72%×72%），
    按外接框估容量会放行整句要点塞进 170×170 圆徽章，渲染成溢出叠压。
    旧库 schema 无几何信息时用「小而近正方形」启发式兜底，同样必须拒绝。"""
    layout = {"detected_type": "content", "element_schema": [
        {"kind": "text", "role": "content", "font_size": 32,
         "x": .104, "y": .048, "w": .385, "h": .085, "placeholder_keys": ["title"]},
        {"kind": "text", "role": "content", "font_size": 27,
         "x": .104, "y": .318, "w": .177, "h": .315, "placeholder_keys": ["point1"]},
        {"kind": "text", "role": "content", "font_size": 19,
         "x": .133, "y": .593, "w": .118, "h": .209, "placeholder_keys": ["point2"]},
        {"kind": "text", "role": "content", "font_size": 20,
         "x": .393, "y": .318, "w": .52, "h": .485, "placeholder_keys": ["point3"]},
    ]}
    slide = {"type": "content", "title": "清醒认识短板弱项",
             "points": ["部分支部组织生活形式单一，“三会一课”吸引力有待提升。",
                        "党务干部多为兼职，专业化能力与新时代要求仍有差距。",
                        "党建与业务融合不够深，存在“两张皮”现象。"]}
    assert ppt_engine._learned_layout_fits(layout, slide) is False


def test_circle_geom_schema_rejects_even_non_square_slots():
    """schema 显式带 geom=circle 时，即使框不是正方形也按内接矩形算容量。"""
    layout = {"detected_type": "content", "element_schema": [
        {"kind": "text", "role": "content", "font_size": 32,
         "x": .104, "y": .048, "w": .385, "h": .085, "placeholder_keys": ["title"]},
        {"kind": "text", "role": "content", "font_size": 27, "geom": "circle",
         "x": .104, "y": .318, "w": .177, "h": .28, "placeholder_keys": ["point1"]},
        {"kind": "text", "role": "content", "font_size": 20,
         "x": .393, "y": .318, "w": .52, "h": .485, "placeholder_keys": ["point2"]},
    ]}
    slide = {"type": "content", "title": "聚焦重点，谋实举措",
             "points": ["实施“堡垒提质”行动，年内打造 3 个市级标杆党支部。",
                        "深化党建业务双融双促，建立融合成效量化评估机制。"]}
    assert ppt_engine._learned_layout_fits(layout, slide) is False


def test_circle_shape_detection_and_schema():
    from pptx.enum.shapes import MSO_SHAPE
    prs, blank = _blank_deck()
    slide = prs.slides.add_slide(blank)
    oval = slide.shapes.add_shape(MSO_SHAPE.OVAL, Inches(1), Inches(1),
                                  Inches(2), Inches(2))
    oval.text_frame.text = "椭圆形状示例"
    pill = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(4),
                                  Inches(1), Inches(2), Inches(2))
    pill.adjustments[0] = 0.5
    pill.text_frame.text = "全圆角矩形示例"
    rect = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(7),
                                  Inches(1), Inches(2), Inches(2))
    rect.text_frame.text = "普通圆角矩形"
    assert ppt_engine._is_circle_shape(oval) is True
    assert ppt_engine._is_circle_shape(pill) is True
    assert ppt_engine._is_circle_shape(rect) is False
    source = io.BytesIO()
    prs.save(source)
    texts = [e for lay in ppt_engine.analyze_template(source.getvalue())["layouts"]
             for e in lay["element_schema"] if e["kind"] == "text"]
    geoms = {e.get("geom") for e in texts if e.get("sample") != "普通圆角矩形"}
    assert geoms == {"circle"}


def test_shrink_text_to_fit_respects_circle_geometry():
    """圆形槽内长句必须收缩字号：旧逻辑按外接框算会判定 27pt 就装得下。"""
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.util import Pt
    prs, blank = _blank_deck()
    circ = prs.slides.add_slide(blank).shapes.add_shape(
        MSO_SHAPE.OVAL, Inches(0.5), Inches(0.5), Inches(2.36), Inches(2.36))
    run = circ.text_frame.paragraphs[0].add_run()
    run.text = "部分支部组织生活形式单一，“三会一课”吸引力有待提升。"
    run.font.size = Pt(27)
    ppt_engine._shrink_text_to_fit(circ, Emu(W), Emu(H))
    sizes = [r.font.size.pt for p in circ.text_frame.paragraphs for r in p.runs
             if r.font.size is not None]
    assert sizes and max(sizes) < 27


def test_empty_slot_deletion_spares_filled_neighbor():
    """同一水平带里并排两槽（如 L15 底行左右两栏）：右槽为空要删，但左槽
    已填入内容，连带删除必须豁免带文字的形状，否则内容随装饰一起丢。"""
    from pptx.enum.shapes import MSO_SHAPE
    prs, blank = _blank_deck()
    slide = prs.slides.add_slide(blank)
    filled = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE,
                                    Inches(1), Inches(3), Inches(2.4), Inches(1.5))
    filled.text_frame.text = "党务干部多为兼职，专业化能力与新时代要求仍有差距。"
    empty = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE,
                                   Inches(4.6), Inches(3), Inches(3.9), Inches(1.4))
    element = {"x": 4.6 * INCH / W, "y": 3 * INCH / H,
               "w": 3.9 * INCH / W, "h": 1.4 * INCH / H}
    ppt_engine._delete_empty_slot(slide, element, empty, Emu(W), Emu(H))
    ids = {sh.shape_id for sh in slide.shapes}
    assert filled.shape_id in ids
    assert empty.shape_id not in ids


def test_group_text_uses_page_coordinates():
    """组内文本框按 chOff/chExt 换算成页面坐标，而不是子坐标系的原始值。"""
    prs, blank = _blank_deck()
    slide = prs.slides.add_slide(blank)
    group = slide.shapes.add_group_shape()
    box = group.shapes.add_textbox(Inches(1), Inches(1), Inches(3), Inches(0.8))
    box.text_frame.text = "组合里的标题"
    # 组合落在 (2in, 3in)，子坐标系原点在 (0, 0)、尺寸与页面一致 → 缩放 1:1
    _set_group_frame(group, 2 * INCH, 3 * INCH, W, H,
                     ch_off=(0, 0), ch_ext=(W, H))

    buf = io.BytesIO()
    prs.save(buf)
    learned = ppt_engine.analyze_template(buf.getvalue())
    texts = [e for lay in learned["layouts"] for e in lay["element_schema"]
             if e["kind"] == "text"]

    assert len(texts) == 1
    el = texts[0]
    assert el.get("in_group") is True
    # x/y 是页面比例：组合 2in + 框 1in = 3in
    assert el["x"] * (W / INCH) == pytest.approx(3.0, abs=0.05)
    assert el["y"] * (H / INCH) == pytest.approx(4.0, abs=0.05)


def test_filled_page_rejects_a_tiny_title_box_inside_a_group():
    from pptx.util import Pt

    prs, blank = _blank_deck()
    slide = prs.slides.add_slide(blank)
    group = slide.shapes.add_group_shape()
    title = "三、下一步工作打算"
    box = group.shapes.add_textbox(Inches(1), Inches(1), Inches(1.1), Inches(.7))
    box.text_frame.paragraphs[0].add_run().text = title
    box.text_frame.paragraphs[0].runs[0].font.size = Pt(36)
    _set_group_frame(group, 0, 0, W, H, ch_off=(0, 0), ch_ext=(W, H))

    assert ppt_engine._filled_page_issue(slide, {"type": "section", "title": title},
                                         W, H) == "文字在模板文本框中放不下"


def test_nested_group_coordinates_accumulate():
    """两层组合：父级偏移与缩放必须逐层累加。"""
    prs, blank = _blank_deck()
    slide = prs.slides.add_slide(blank)
    outer = slide.shapes.add_group_shape()
    inner = outer.shapes.add_group_shape()
    box = inner.shapes.add_textbox(Inches(1), Inches(1), Inches(2), Inches(0.6))
    box.text_frame.text = "嵌套组合文字"
    # 外层：页面 (1in, 1in)，子坐标系 0..W/H，缩放 1:1
    _set_group_frame(outer, 1 * INCH, 1 * INCH, W, H, ch_off=(0, 0), ch_ext=(W, H))
    # 内层：父级子坐标系 (1in, 1in)，横向压缩一半
    _set_group_frame(inner, 1 * INCH, 1 * INCH, 6 * INCH, 5 * INCH,
                     ch_off=(0, 0), ch_ext=(12 * INCH, 5 * INCH))

    buf = io.BytesIO()
    prs.save(buf)
    learned = ppt_engine.analyze_template(buf.getvalue())
    els = [e for lay in learned["layouts"] for e in lay["element_schema"]
           if e["kind"] == "text"]

    assert len(els) == 1
    # 外层 1in + 内层 1in + 文本框 1in×0.5 = 2.5in（x 为页面比例）
    assert els[0]["x"] * (W / INCH) == pytest.approx(2.5, abs=0.05)


def _group_template(pages=5):
    """内容页的标题与正文都放在组合里，模拟商用模板的常见打包方式。"""
    prs, blank = _blank_deck()
    cover = prs.slides.add_slide(blank)
    t = cover.shapes.add_textbox(Inches(1), Inches(2.4), Inches(8), Inches(1.2))
    t.text_frame.text = "示例标题"
    sub = cover.shapes.add_textbox(Inches(1), Inches(3.8), Inches(8), Inches(0.8))
    sub.text_frame.text = "示例副标题"

    for i in range(pages):
        slide = prs.slides.add_slide(blank)
        group = slide.shapes.add_group_shape()
        head = group.shapes.add_textbox(Inches(0.8), Inches(0.4 + i * 0.02),
                                        Inches(10), Inches(0.9))
        head.text_frame.text = "点击输入标题"
        body = group.shapes.add_textbox(Inches(0.8), Inches(2.0 + i * 0.02),
                                        Inches(10), Inches(3.0))
        body.text_frame.text = "点击输入正文\n点击输入正文\n点击输入正文"
        _set_group_frame(group, 0.5 * INCH, 0.4 * INCH, 12 * INCH, 5.6 * INCH,
                         ch_off=(0, 0), ch_ext=(W, H))

    end = prs.slides.add_slide(blank)
    t = end.shapes.add_textbox(Inches(3), Inches(3), Inches(6), Inches(1))
    t.text_frame.text = "谢谢"
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


def test_group_template_passes_validation():
    learned = ppt_engine.analyze_template(_group_template())
    assert learned["layouts"], "组合模板应至少识别出一个版式"
    ppt_engine.validate_learned_template(learned)


def test_group_text_is_replaced_not_kept():
    """出稿后组合里的示例文字必须被换掉，不能原样印进成品。"""
    src = _group_template()
    learned = ppt_engine.analyze_template(src)
    outline = {"slides": [
        {"type": "content", "title": f"第{i}页标题",
         "points": [f"第{i}页要点一", f"第{i}页要点二", f"第{i}页要点三"]}
        for i in range(1, 6)]}
    template = {"colors": learned["colors"], "font": learned["font"],
                "layouts": {}, "layout_library": learned["layouts"]}
    warnings = []
    out = ppt_engine.build_pptx_learned(outline, template, src,
                                        learned["layouts"], warnings=warnings)

    prs = Presentation(io.BytesIO(out))
    texts = []
    for slide in prs.slides:
        for shape, _rect, _depth in ppt_engine._iter_shapes(slide.shapes):
            try:
                if shape.has_text_frame:
                    texts.append(shape.text_frame.text)
            except Exception:
                pass
    joined = "\n".join(texts)
    assert "点击输入" not in joined
    assert "示例标题" not in joined
    assert "第1页标题" in joined


def test_repeated_sample_title_stays_content():
    """每页重复的示例标题不能因为「重复出现」被判成装饰。"""
    learned = ppt_engine.analyze_template(_group_template())
    body_layouts = [lay for lay in learned["layouts"]
                    if lay.get("detected_type") not in {"cover", "toc", "closing"}]
    assert body_layouts
    for lay in body_layouts:
        texts = [e for e in lay["element_schema"] if e["kind"] == "text"]
        assert any(e.get("role") != "fixed" for e in texts), lay["id"]


def test_readable_fallback_varies_by_point_count():
    """兜底页不再千篇一律：2 点上下双卡、3 点圆角色卡、4 短点 2x2 网格、章节页色带。"""
    colors = {"primary": "C01F1F", "dark": "262626"}
    cases = {
        "cards_v": {"type": "content", "title": "双卡页",
                    "points": ["要点甲" * 8, "要点乙" * 8]},
        "zebra": {"type": "content", "title": "三卡页",
                  "points": ["第一" * 6, "第二" * 6, "第三" * 6]},
        "grid": {"type": "content", "title": "网格页",
                 "points": ["短点一。", "短点二。", "短点三。", "短点四。"]},
        "section": {"type": "section", "title": "一、总体情况", "points": []},
    }
    shapes_count = {}
    for name, sdata in cases.items():
        prs, blank = _blank_deck()
        slide = prs.slides.add_slide(blank)
        ppt_engine._fill_readable_template_page(
            slide, sdata, colors, "微软雅黑", prs.slide_width, prs.slide_height)
        shapes_count[name] = len(slide.shapes)
        text = " ".join(sh.text for sh in slide.shapes if sh.has_text_frame)
        for point in (sdata.get("points") or []):
            assert point in text, f"{name} 丢内容"
        assert sdata["title"] in text
    # 版式间装饰形状数应有明显差异（卡片版式比章节页装饰多）
    assert len(set(shapes_count.values())) >= 3, shapes_count


def test_fix_text_contrast_flips_dark_text_on_dark_fill():
    """透明文本框叠在深色实底上时，继承色深字应翻白；浅底白字不动。"""
    from pptx.dml.color import RGBColor
    prs, blank = _blank_deck()
    slide = prs.slides.add_slide(blank)
    red = slide.shapes.add_shape(
        __import__("pptx").enum.shapes.MSO_SHAPE.RECTANGLE,
        Inches(1), Inches(1), Inches(4), Inches(2))
    red.fill.solid()
    red.fill.fore_color.rgb = RGBColor(0xC0, 0x1F, 0x1F)
    tb = slide.shapes.add_textbox(Inches(1.2), Inches(1.3), Inches(3.5), Inches(1.4))
    tb.text_frame.text = "继承色深字压红底"
    tb2 = slide.shapes.add_textbox(Inches(6), Inches(1.3), Inches(3.5), Inches(1))
    tb2.text_frame.text = "白字浅底"
    tb2.text_frame.paragraphs[0].runs[0].font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
    ppt_engine._fix_text_contrast(slide, prs.slide_width, prs.slide_height)
    c1 = tb.text_frame.paragraphs[0].runs[0].font.color
    assert c1.type is not None and str(c1.rgb) == "FFFFFF"
    c2 = tb2.text_frame.paragraphs[0].runs[0].font.color
    assert str(c2.rgb) == "FFFFFF"

def test_single_line_bar_slot_rejects_long_sentence():
    """红条/标题条（框高 < 字号 1.8 倍）是单行框：长句缩到下限也装不进一行，
    旧判据靠 1.15 高度容差放行两行，第二行溢出到框外。"""
    from app.application.ppt.adaptive_design import fit_font_size
    # 0.442x0.054 框（960x540 页上高 29pt）配 18pt 字：单行判定
    assert fit_font_size("严格落实第一议题制度，全年开展中心组学习二十四次、专题研讨八次。", 0.442, 0.054, 18) is None
    # 短句 13pt 单行可容纳
    got = fit_font_size("部分支部组织生活形式单一。", 0.442, 0.054, 18)
    assert got is not None and got <= 18


def test_layout_fit_score_uses_circle_heuristic_without_geom():
    """旧库 schema 无 geom 字段时，近正方形小槽按启发式当圆槽：
    长句缩号「装得下」也必须拒——圆里塞三行小字是叠压灾难。"""
    layout = {"detected_type": "content", "element_schema": [
        {"kind": "text", "role": "content", "font_size": 32,
         "x": .104, "y": .048, "w": .385, "h": .085, "placeholder_keys": ["title"]},
        {"kind": "text", "role": "content", "font_size": 27,
         "x": .104, "y": .318, "w": .177, "h": .315, "placeholder_keys": ["point1"]},
        {"kind": "text", "role": "content", "font_size": 20,
         "x": .393, "y": .318, "w": .52, "h": .485, "placeholder_keys": ["point2"]},
    ]}
    slide = {"type": "content", "title": "清醒认识短板弱项",
             "points": ["部分支部组织生活形式单一，“三会一课”吸引力有待提升。",
                        "党建与业务融合不够深，存在“两张皮”现象。"]}
    assert ppt_engine._learned_layout_fits(layout, slide) is False



def _minimal_deck(pages):
    """构造带显式 token 的最小模板：cover + 按 pages 描述追加内容页。"""
    prs, blank = _blank_deck()
    cover = prs.slides.add_slide(blank)
    t = cover.shapes.add_textbox(Inches(1), Inches(2.4), Inches(8), Inches(1.2))
    t.text_frame.text = "{{title}}"
    t.text_frame.paragraphs[0].runs[0].font.size = __import__("pptx.util", fromlist=["Pt"]).Pt(44)
    sub = cover.shapes.add_textbox(Inches(1), Inches(3.8), Inches(8), Inches(0.8))
    sub.text_frame.text = "{{subtitle}}"
    for spec in pages:
        slide = prs.slides.add_slide(blank)
        for text, left, top, width, height, size in spec:
            box = slide.shapes.add_textbox(Inches(left), Inches(top),
                                           Inches(width), Inches(height))
            box.text_frame.text = text
            if box.text_frame.paragraphs[0].runs:
                box.text_frame.paragraphs[0].runs[0].font.size = \
                    __import__("pptx.util", fromlist=["Pt"]).Pt(size)
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


_TPL_KW = {"colors": ppt_engine.DEFAULT_COLORS, "font": "思源黑体", "layouts": {}}


def test_overflow_points_merge_into_last_slot_without_fallback():
    """要点多于 point 槽：合并进最后一个槽，不整页退回可读排版。"""
    source = _minimal_deck([[
        ("{{title}}", 0.6, 0.3, 11, 0.9, 36),
        ("{{point1}}", 0.8, 1.6, 4.5, 1.0, 20),
        ("{{point2}}", 0.8, 3.2, 4.5, 1.2, 20),
    ]])
    library = ppt_engine.analyze_template(source)["layouts"]
    outline = {"slides": [
        {"type": "cover", "title": "年度汇报", "subtitle": "办公室", "points": []},
        {"type": "content", "title": "具体工作",
         "points": ["要点一", "要点二", "要点三"]},
    ]}
    warnings = []
    data = ppt_engine.build_pptx_learned(outline, _TPL_KW, source, library, warnings)
    result = Presentation(io.BytesIO(data))
    text = " ".join(shape.text for shape in result.slides[1].shapes
                    if shape.has_text_frame)
    assert "要点一" in text and "要点二" in text and "要点三" in text
    assert not any("仅该页" in warning for warning in warnings)


def test_chart_data_survives_when_template_has_no_chart_slot():
    source = _minimal_deck([[
        ("{{title}}", 0.6, 0.3, 11, 0.9, 36),
        ("{{point1}}", 0.8, 1.6, 10, 1.0, 20),
        ("{{point2}}", 0.8, 3.2, 10, 1.2, 20),
    ]])
    library = ppt_engine.analyze_template(source)["layouts"]
    outline = {"slides": [{
        "type": "chart", "title": "学习活动数据",
        "points": ["专题学习覆盖主要岗位", "培训活动分批开展"],
        "blocks": {"chart": {"chart_type": "bar", "categories": ["专题学习", "集中培训"],
                              "series": [{"name": "场次", "values": [35, 17]}]}},
    }]}
    warnings = []
    data = ppt_engine.build_pptx_learned(outline, _TPL_KW, source, library, warnings)
    slide = Presentation(io.BytesIO(data)).slides[0]
    assert any(shape.has_chart for shape in slide.shapes)
    assert all(point in " ".join(shape.text for shape in slide.shapes
                                 if shape.has_text_frame)
               for point in outline["slides"][0]["points"])


def test_pasted_in_layout_from_another_palette_is_excluded():
    foreign = {"element_schema": [
        {"kind": "shape", "fill": "007CA8"},
        {"kind": "shape", "fill": "619428"},
    ]}
    matching = {"element_schema": [
        {"kind": "shape", "fill": "C00000"},
        {"kind": "shape", "fill": "D9A441"},
    ]}
    assert not ppt_engine._layout_matches_theme(foreign, "C00000")
    assert ppt_engine._layout_matches_theme(matching, "C00000")


def test_special_page_borrows_content_layout_when_type_missing():
    """模板没有章节页型：目录/章节页应借用正文版式保留模板设计，而不是退通用页。"""
    source = _minimal_deck([[
        ("{{title}}", 0.6, 0.3, 11, 0.9, 36),
        ("{{point1}}", 0.8, 1.8, 10, 3.2, 18),
        ("{{point2}}", 0.8, 3.4, 10, 1.6, 16),
    ]])
    library = ppt_engine.analyze_template(source)["layouts"]
    assert not any(l.get("detected_type") == "section" for l in library)
    outline = {"slides": [
        {"type": "cover", "title": "年度汇报", "subtitle": "办公室", "points": []},
        {"type": "section", "title": "一、主要工作成效", "points": []},
    ]}
    warnings = []
    data = ppt_engine.build_pptx_learned(outline, _TPL_KW, source, library, warnings)
    result = Presentation(io.BytesIO(data))
    text = " ".join(shape.text for shape in result.slides[1].shapes
                    if shape.has_text_frame)
    assert "一、主要工作成效" in text
    assert not any("仅该页" in warning for warning in warnings)


def test_section_page_big_shape_survives_empty_slot_cleanup():
    """章节页的大装饰色块不是空槽的容器：空槽清理不得把它一并删掉。"""
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.dml.color import RGBColor

    prs, blank = _blank_deck()
    cover = prs.slides.add_slide(blank)
    t = cover.shapes.add_textbox(Inches(1), Inches(2.4), Inches(8), Inches(1.2))
    t.text_frame.text = "{{title}}"
    slide = prs.slides.add_slide(blank)
    bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.8), Inches(0.6),
                                 Inches(3.0), Inches(4.2))
    bar.fill.solid()
    bar.fill.fore_color.rgb = RGBColor.from_string("222222")
    slot = slide.shapes.add_textbox(Inches(1.2), Inches(2.3), Inches(4.0), Inches(0.8))
    slot.text_frame.text = "{{point1}}"
    slot.text_frame.paragraphs[0].runs[0].font.size = __import__(
        "pptx.util", fromlist=["Pt"]).Pt(32)
    title = slide.shapes.add_textbox(Inches(5.5), Inches(2.3), Inches(6.0), Inches(1.0))
    title.text_frame.text = "{{title}}"
    title.text_frame.paragraphs[0].runs[0].font.size = __import__(
        "pptx.util", fromlist=["Pt"]).Pt(44)
    buf = io.BytesIO()
    prs.save(buf)
    library = ppt_engine.analyze_template(buf.getvalue())["layouts"]
    lay = next(l for l in library if l.get("detected_type") == "section")
    outline = {"slides": [
        {"type": "cover", "title": "年度汇报", "subtitle": "办公室", "points": []},
        {"type": "section", "title": "一、主要工作成效", "points": []},
    ]}
    data = ppt_engine.build_pptx_learned(outline, _TPL_KW, buf.getvalue(), library, [])
    result = Presentation(io.BytesIO(data))
    filled = result.slides[1]
    big_shapes = [shape for shape in filled.shapes
                  if shape.width and shape.width >= Inches(2.5)
                  and not (shape.has_text_frame and shape.text_frame.text.strip())]
    assert big_shapes, "章节页大色块被空槽清理误删，模板设计被掏空"


def test_learned_section_number_and_three_card_grid_are_complete():
    """A four-slot grouped layout must not leave a hole after filling three points."""
    from pptx.dml.color import RGBColor
    from pptx.enum.shapes import MSO_SHAPE, MSO_CONNECTOR
    from pptx.util import Pt

    prs, blank = _blank_deck()
    section = prs.slides.add_slide(blank)
    section.notes_slide.notes_text_frame.text = "PPT_LAYOUT_TYPE:section"
    title = section.shapes.add_textbox(Inches(4), Inches(1.2), Inches(8), Inches(1))
    title.text = "{{title}}"
    title.text_frame.paragraphs[0].runs[0].font.size = Pt(32)
    badge = section.shapes.add_group_shape()
    badge_shape = badge.shapes.add_shape(
        MSO_SHAPE.RECTANGLE, Inches(1.5), Inches(1.2), Inches(2.3), Inches(1.2))
    badge_shape.fill.solid()
    badge_shape.fill.fore_color.rgb = RGBColor.from_string("C00000")

    content = prs.slides.add_slide(blank)
    content.notes_slide.notes_text_frame.text = "PPT_LAYOUT_TYPE:two_col"
    title = content.shapes.add_textbox(Inches(1.3), Inches(.35), Inches(8), Inches(.7))
    title.text = "{{title}}"
    title.text_frame.paragraphs[0].runs[0].font.size = Pt(30)
    positions = [(1.39, 1.94, 3.33, 2.12), (6.08, 1.94, 6.17, 2.12),
                 (1.39, 4.49, 3.33, 2.12), (6.08, 4.49, 6.17, 2.12)]
    for index, (x, y, w, h) in enumerate(positions, 1):
        group = content.shapes.add_group_shape()
        card = group.shapes.add_shape(
            MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
        card.fill.solid()
        card.fill.fore_color.rgb = RGBColor.from_string(
            "C00000" if index in (1, 3) else "FFF8F2")
        card.text = "{{point%d}}" % index
        card.text_frame.paragraphs[0].runs[0].font.size = Pt(18)
    content.shapes.add_connector(MSO_CONNECTOR.STRAIGHT,
                                 Inches(5.08), Inches(3), Inches(5.85), Inches(3))
    content.shapes.add_connector(MSO_CONNECTOR.STRAIGHT,
                                 Inches(5.08), Inches(5.55), Inches(5.85), Inches(5.55))
    source = io.BytesIO()
    prs.save(source)
    learned = ppt_engine.analyze_template(source.getvalue())
    outline = {"slides": [
        {"type": "section", "title": "二、深化学习", "index": 2},
        {"type": "content", "title": "学习举措", "points": [
            "深入学习党纪法规并开展专题研讨", "领导干部带头宣讲推动学习落实",
            "组织党员交流经验并总结有效做法"]},
    ]}
    data = ppt_engine.build_pptx_learned(
        outline, {"colors": {"primary": "C00000", "accent": "D9A441",
                             "dark": "361818", "light": "FFF8F2"},
                  "font": "微软雅黑", "layouts": {}}, source.getvalue(),
        learned["layouts"], [])
    result = Presentation(io.BytesIO(data))
    badge_groups = [shape for shape in result.slides[0].shapes
                    if shape.shape_type == 6]
    assert any(child.has_text_frame and child.text.strip() == "二"
               for group in badge_groups for child in group.shapes)
    section_text = " ".join(shape.text for shape in result.slides[0].shapes
                            if shape.has_text_frame)
    assert "深化学习" in section_text
    assert "二、深化学习" not in section_text
    groups = [shape for shape in result.slides[1].shapes
              if shape.shape_type == 6 and ppt_engine._has_visible_text(shape)]
    # 2026-11-10 起正文页统一走「模板皮 + 引擎骨架」：模板的 2+1 卡片网格在
    # 条数/字数一变就留空框、半边空白（用户连拍三处）。几何复用让位给排整齐，
    # 守卫点从「必须复用模板分组」改为「三条要点都在页面上、不留占位符」。
    page_text = " ".join(shape.text for shape in result.slides[1].shapes
                         if shape.has_text_frame)
    for point in outline["slides"][1]["points"]:
        assert point in page_text
    assert "{{" not in page_text
    two_points = {"slides": [{"type": "content", "title": "学习举措",
                              "points": outline["slides"][1]["points"][:2]}]}
    two_data = ppt_engine.build_pptx_learned(
        two_points, {"colors": {"primary": "C00000", "accent": "D9A441",
                                "dark": "361818", "light": "FFF8F2"},
                     "font": "微软雅黑", "layouts": {}}, source.getvalue(),
        learned["layouts"], [])
    two_page = Presentation(io.BytesIO(two_data)).slides[0]
    two_text = " ".join(shape.text for shape in two_page.shapes
                        if shape.has_text_frame)
    for point in two_points["slides"][0]["points"]:
        assert point in two_text


# ============ 兜底链路可配置（readable / learned / none） ============

def _fallback_deck():
    prs, blank = _blank_deck()
    page = prs.slides.add_slide(blank)
    page.shapes.add_textbox(Inches(.8), Inches(.5), Inches(10), Inches(.8)).text = "{{title}}"
    page.shapes.add_textbox(Inches(.8), Inches(2.2), Inches(9), Inches(1.6)).text = "{{point1}}"
    source = io.BytesIO()
    prs.save(source)
    learned = ppt_engine.analyze_template(source.getvalue())
    return source.getvalue(), {"colors": learned["colors"], "font": learned["font"],
                               "layout_library": learned["layouts"]}


def _rejected_outline(fallback):
    # 只给标题区域：缺少 point:0，模型构图必然在编译期被拒，正好卡在兜底分叉上。
    return {"template_mode": "designed", "fallback_mode": fallback, "slides": [{
        "type": "content", "title": "工作成效", "points": ["办理流程更加清晰"],
        "design": {"regions": [{"ref": "title", "x": .08, "y": .05,
                                "w": .84, "h": .12}]}}]}


def _render_texts(fallback):
    base, template = _fallback_deck()
    warnings: list = []
    diags: list = []
    data = ppt_engine.render_pptx(_rejected_outline(fallback), template, base,
                                  warnings=warnings, diagnostics=diags)
    page = Presentation(io.BytesIO(data)).slides[0]
    texts = [shape.text_frame.text.strip() for shape in page.shapes
             if shape.has_text_frame and shape.text_frame.text.strip()]
    return texts, warnings, diags


def test_fallback_none_leaves_page_bare_and_says_why():
    texts, warnings, diags = _render_texts("none")
    assert diags[0]["composition"] == "none"
    assert texts == []
    assert any("已关闭兜底排版" in item and "缺少 point:0" in item for item in warnings)


def test_fallback_readable_keeps_engine_skeleton():
    texts, warnings, diags = _render_texts("readable")
    assert diags[0]["composition"] == "readable"
    assert "工作成效" in texts and "办理流程更加清晰" in texts


def test_fallback_learned_attempts_template_slots_before_readable():
    # 这套模板只有封面版式，学不到正文版式；learned 档必须明确说出来，
    # 而不是静默按 readable 跑完让用户以为「先试原版式」生效了。
    texts, warnings, diags = _render_texts("learned")
    assert any("没有可容纳正文的原版式" in item for item in warnings)
    assert "办理流程更加清晰" in texts


def test_fallback_readable_never_touches_template_slots():
    texts, warnings, diags = _render_texts("readable")
    assert not any("原版式" in item for item in warnings)


def test_unknown_fallback_falls_back_to_readable():
    texts, warnings, diags = _render_texts("bogus")
    assert diags[0]["composition"] == "readable"
    assert "办理流程更加清晰" in texts


# ============ 演示保底：一键彻底不试模型构图 ============

def _safe_mode_outline(force, with_regions, fallback="readable"):
    slide = {"type": "content", "title": "工作成效",
             "points": ["办理流程更加清晰"]}
    if with_regions:
        # 合法的模型构图：不重叠、不越界、放得下文字。
        slide["design"] = {"regions": [
            {"ref": "title", "x": .06, "y": .05, "w": .88, "h": .12},
            {"ref": "point:0", "x": .06, "y": .28, "w": .86, "h": .22}]}
    return {"template_mode": "designed", "force_template_layout": force,
            "fallback_mode": fallback, "slides": [slide]}


def _safe_mode_render(outline):
    base, template = _fallback_deck()
    diags: list = []
    data = ppt_engine.render_pptx(outline, template, base, diagnostics=diags)
    prs = Presentation(io.BytesIO(data))
    shapes = tuple(
        (str(item.shape_type), round(item.left / prs.slide_width, 3),
         round(item.top / prs.slide_height, 3),
         round(item.width / prs.slide_width, 3),
         round(item.height / prs.slide_height, 3),
         item.text_frame.text if item.has_text_frame else "")
        for item in prs.slides[0].shapes)
    return shapes, diags


def test_force_template_layout_ignores_even_a_valid_model_composition():
    plain, _ = _safe_mode_render(_safe_mode_outline(False, False))
    _, modeled = _safe_mode_render(_safe_mode_outline(False, True))
    forced, forced_diag = _safe_mode_render(_safe_mode_outline(True, True))
    # 构图本身是合法的，不开保底时确实会用它；保底必须能盖过它。
    assert modeled[0]["composition"] == "model"
    assert forced_diag[0]["composition"] == "readable"
    assert "演示保底" in forced_diag[0]["composition_skip"]
    assert forced == plain          # 与昨天的模板化版式逐形状一致


def test_force_template_layout_overrides_none_fallback():
    # 演示保底优先于「留空并提示」：勾了保底就不能反而给出空页。
    shapes, diags = _safe_mode_render(_safe_mode_outline(True, True, "none"))
    assert diags[0]["composition"] == "readable"
    assert any("办理流程更加清晰" in item[-1] for item in shapes)
