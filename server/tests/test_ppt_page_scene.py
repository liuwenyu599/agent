import copy
import io

from pptx import Presentation

from app.application.ppt import page_scene, ppt_engine


def test_scene_uses_valid_model_geometry_and_exports_same_positions():
    slide = {"type": "content", "title": "阶段成果", "points": ["办理提速", "服务扩面"],
             "design": {"regions": [
                 {"ref": "title", "x": .06, "y": .05, "w": .88, "h": .12},
                 {"ref": "point:0", "x": .06, "y": .25, "w": .55, "h": .5},
                 {"ref": "point:1", "x": .65, "y": .25, "w": .29, "h": .5},
             ]}}
    outline = {"slides": [slide]}
    spec = ppt_engine.template_to_dict(ppt_engine.builtin_template("public_service_green"))
    data = ppt_engine.render_pptx(outline, spec, adaptive=True)
    scene = slide["scene"]
    assert scene["elements"][1]["w"] == .55
    prs = Presentation(io.BytesIO(data))
    shape = next(s for s in prs.slides[0].shapes if s.has_text_frame and s.text == "办理提速")
    assert abs(shape.left / prs.slide_width - .08) < .001
    assert abs(shape.width / prs.slide_width - .51) < .001
    saved = copy.deepcopy(scene)
    ppt_engine.render_pptx(outline, spec, adaptive=True)
    assert slide["scene"] == saved
    slide["points"][0] = "新的办理结果"
    ppt_engine.render_pptx(outline, spec, adaptive=True)
    assert slide["scene"]["source"] != saved["source"]


def test_invalid_model_geometry_falls_back_without_losing_text():
    slide = {"type": "content", "title": "成果", "points": ["甲", "乙"],
             "design": {"regions": [
                 {"ref": "title", "x": float("nan"), "y": .05, "w": .8, "h": .12}]}}
    scene = page_scene.plan(slide, "content.compare")
    assert scene is not None
    assert page_scene.audit(scene["elements"], slide)
    assert {e["ref"] for e in scene["elements"]} == {"title", "point:0", "point:1"}


def test_repair_layout_changes_geometry_and_explicit_layout_uses_scene():
    slide = {"type": "content", "title": "四项工作", "layout": "bullets",
             "points": ["事项一", "事项二", "事项三", "事项四"]}
    geometries = []
    for layout in ("bullets", "two_col", "symmetric", "center", "three_cards"):
        scene = page_scene.plan(slide, "content." + layout)
        assert scene is not None
        geometries.append(tuple((item["x"], item["y"], item["w"], item["h"])
                                for item in scene["elements"]))
    assert len(set(geometries)) == 5


def test_small_out_of_bounds_region_keeps_other_geometry():
    slide = {"type": "content", "title": "<标题>", "points": ["内容"],
             "design": {"regions": [
                 {"ref": "title", "x": .03, "y": .05, "w": .8, "h": .12},
                 {"ref": "point:0", "x": .2, "y": .3, "w": .6, "h": .4}]}}
    scene = page_scene.plan(slide, "content.bullets")
    assert scene["elements"][0]["x"] == .035
    assert scene["elements"][1]["x"] == .2
    svg = page_scene.wireframe(scene, slide)
    assert "&lt;标题&gt;" in svg
    assert "<标题>" not in svg


def test_far_out_of_bounds_region_uses_safe_layout_instead_of_teleporting():
    slide = {"type": "content", "title": "成果", "points": ["内容"],
             "design": {"regions": [
                 {"ref": "title", "x": -1.0, "y": .05, "w": .8, "h": .12},
                 {"ref": "point:0", "x": .2, "y": .3, "w": .6, "h": .4}]}}
    scene = page_scene.plan(slide, "content.bullets")
    assert scene is not None
    assert page_scene.audit(scene["elements"], slide)
    assert scene["elements"][0]["x"] == .055
    assert slide["design"]["regions"][0]["x"] == -1.0
