import copy
import io
from PIL import Image

from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE
from pptx.oxml.ns import qn

from app.application.ppt import page_scene, ppt_engine, svg_layer, visual_primitives as vp
from app.core.fonts import DEFAULT_CJK_FONT, DEFAULT_LATIN_FONT


def test_layered_photo_text_requires_scrim_and_pixel_contrast(tmp_path):
    photo = tmp_path / "bright.png"
    Image.new("RGB", (200, 120), "white").save(photo)
    slide = {"type": "content", "title": "现场", "points": ["专题学习现场"],
             "_image": {"file_path": str(photo)},
             "design": {"image_overlay": "dark"}}
    regions = [{"ref": "title", "x": .06, "y": .05, "w": .88, "h": .12},
               {"ref": "image", "x": .08, "y": .25, "w": .84, "h": .55},
               {"ref": "point:0", "x": .15, "y": .40, "w": .50, "h": .20}]
    assert page_scene.explain_layered(copy.deepcopy(regions), slide) == ""
    no_scrim = copy.deepcopy(slide)
    no_scrim["design"]["image_overlay"] = "none"
    assert page_scene.explain_layered(copy.deepcopy(regions), no_scrim)
    wrong_layer = copy.deepcopy(regions)
    wrong_layer[2]["layer"] = "image"
    assert "layer" in page_scene.explain_layered(wrong_layer, slide)
    partial = copy.deepcopy(regions)
    partial[1].update(w=.60)
    partial[2].update(x=.50, w=.24)
    assert page_scene.explain(copy.deepcopy(partial), slide)
    assert page_scene.explain_layered(copy.deepcopy(partial), slide) == ""
    prs = Presentation()
    page = prs.slides.add_slide(prs.slide_layouts[6])
    colors = {"primary": "C00000", "accent": "E25858", "dark": "303030"}
    assert ppt_engine._fill_model_regions_on_template(
        page, {**slide, "design": {**slide["design"], "regions": partial}},
        colors, "微软雅黑", prs.slide_width, prs.slide_height,
        .025, .89, layered=True)
    # Photo scrim plus a second editable scrim covering the overhanging text.
    shades = [shape for shape in page.shapes if shape.shape_type == MSO_SHAPE_TYPE.AUTO_SHAPE
              and shape.fill.type is not None]
    assert len(shades) >= 2
    overlaid = next(shape for shape in page.shapes if shape.has_text_frame
                   and shape.text == "专题学习现场")
    assert str(overlaid.text_frame.paragraphs[0].runs[0].font.color.rgb) == "FFFFFF"


def test_svg_decoration_cannot_paint_behind_editable_body_text():
    slide = {"type": "content", "title": "成果", "points": ["正文"]}
    regions = [{"ref": "title", "x": .06, "y": .05, "w": .88, "h": .12},
               {"ref": "point:0", "x": .10, "y": .30, "w": .60, "h": .30}]
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 540">'
           '<rect x="120" y="200" width="200" height="70" fill="#202020"/>'
           '</svg>')
    png = svg_layer.to_png(svg, scale=.5)
    assert page_scene.svg_text_overlap(png, regions, slide) == "SVG 装饰覆盖文字区域 point:0"


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
    assert scene["version"] == 2
    assert scene["visuals"] == vp.decorations(scene, slide)
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


def test_scene_rebuilds_modified_visuals_from_its_design_contract():
    slide = {"type": "content", "title": "两项工作", "points": ["工作一", "工作二"],
             "design": {"relationship": "comparison"}}
    original = page_scene.plan(slide, "content.two_col")
    assert original["visuals"]
    slide["scene"] = copy.deepcopy(original)
    slide["scene"]["visuals"][0]["x"] = -100
    rebuilt = page_scene.plan(slide, "content.two_col")
    assert rebuilt["visuals"] == original["visuals"]
    assert rebuilt["visuals"][0]["x"] >= 0


def test_two_item_comparison_uses_content_sized_cards():
    slide = {"type": "content", "title": "两条主线", "points": ["一", "二"],
             "design": {"relationship": "comparison"}}
    scene = page_scene.plan(slide, "content.symmetric")
    bodies = [item for item in scene["elements"] if item["ref"].startswith("point:")]
    assert all(item["h"] == .40 and item["y"] == .32 for item in bodies)
    assert scene["visuals"] == vp.decorations(scene, slide)


def test_model_page_visuals_survive_normalization_and_export_as_native_shapes():
    slide = {"type": "content", "title": "两项工作", "points": ["工作一", "工作二"],
             "design": {"relationship": "comparison", "visuals": [
                 {"kind": "rect", "x": .06, "y": .205, "w": .40, "h": .012,
                  "fill": "accent"},
                 {"kind": "line", "x1": .5, "y1": .25, "x2": .5, "y2": .78,
                  "stroke": "line", "width": 1.5}]}}
    outline = ppt_engine.normalize_outline({"slides": [slide]}, require_bookends=False)
    spec = ppt_engine.template_to_dict(ppt_engine.builtin_template("publicity_cyan"))
    data = ppt_engine.render_pptx(outline, spec, adaptive=True)
    scene = outline["slides"][0]["scene"]
    assert [item["kind"] for item in scene["visuals"]][-2:] == ["rect", "line"]
    assert len(scene["visuals"]) > 2  # 模型装饰不会删掉原有的对比版式。
    assert "<line " in page_scene.wireframe(scene, outline["slides"][0])
    shapes = list(Presentation(io.BytesIO(data)).slides[0].shapes)
    assert any(shape.shape_type == MSO_SHAPE_TYPE.LINE for shape in shapes)
    assert any(shape.has_text_frame and "工作一" in shape.text for shape in shapes)
    for shape in shapes:
        if not shape.has_text_frame or shape.text not in ("两项工作", "工作一", "工作二"):
            continue
        run = shape.text_frame.paragraphs[0].runs[0]
        assert run.font.name == DEFAULT_LATIN_FONT
        assert run._r.get_or_add_rPr().find(qn("a:ea")).get("typeface") == DEFAULT_CJK_FONT
        # 高框短句按 26pt 饱满排布（原为 20pt），且同页同级必须一致。
        assert run.font.size.pt == (28 if shape.text == "两项工作" else 26)
    body_sizes = [shape.text_frame.paragraphs[0].runs[0].font.size.pt
                  for shape in shapes if shape.has_text_frame
                  and shape.text in ("工作一", "工作二")]
    assert body_sizes and len(set(body_sizes)) == 1


def test_invalid_model_visuals_fall_back_to_safe_page_language():
    base = {"type": "content", "title": "成果", "points": ["正文"],
            "design": {"relationship": "takeaway"}}
    for visuals in (
        [{"kind": "rect", "x": .05, "y": .25, "w": .8, "h": .5,
          "fill": "dark"}],  # saturated fill hides body text
        [{"kind": "image", "x": .1, "y": .2, "w": .2, "h": .2,
          "src": "https://example.invalid/a.png"}],
        [{"kind": "rect", "x": -10, "y": .2, "w": .2, "h": .02,
          "fill": "accent"}],
        [{"kind": "line", "x1": .2, "y1": .3, "x2": .8, "y2": .7,
          "stroke": "primary", "width": 2}],  # intersects body copy
    ):
        slide = copy.deepcopy(base)
        slide["design"]["visuals"] = visuals
        scene = page_scene.plan(slide, "content.statement")
        assert scene is not None
        assert scene["visuals"] == vp.decorations(scene, slide)


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


# ---------- 视觉原语：渲染与线框共用同一份几何描述 ----------

def _relationship_slide(rel: str, points=("甲项工作稳步推进", "乙项工作持续深化",
                                          "丙项工作取得突破", "丁项工作形成机制")):
    slide = {"type": "content", "title": "年度成效", "points": list(points),
             "design": {"relationship": rel}}
    scene = page_scene.plan(slide, "content.two_col")
    assert scene is not None
    return slide, scene


def test_each_relationship_has_a_distinct_visual_language():
    languages = {}
    for rel in vp.RELATIONSHIPS:
        slide, scene = _relationship_slide(rel)
        kinds = {item["kind"] for item in vp.decorations(scene, slide)}
        languages[rel] = kinds
    assert "line" in languages["comparison"]       # 中轴连接符
    assert "chevron" in languages["parallel"]      # 步骤箭头条
    assert "oval" in languages["takeaway"]         # 强调圆
    assert "badge" in languages["grouped"]         # 圆形序号
    assert "badge" not in languages["none"]        # 克制版式不铺卡片/序号
    assert len({frozenset(kinds) for kinds in languages.values()}) == 5


def test_circular_decorations_are_visually_round_in_16_9():
    for rel in vp.RELATIONSHIPS:
        slide, scene = _relationship_slide(rel)
        for item in vp.decorations(scene, slide):
            if item["kind"] in ("badge", "oval"):
                assert abs(item["w"] * 960 - item["h"] * 540) < .6, (rel, item)


def test_all_decorations_stay_inside_the_safe_area():
    for rel in vp.RELATIONSHIPS:
        slide, scene = _relationship_slide(rel)
        for item in vp.decorations(scene, slide):
            if item["kind"] == "line":
                assert all(0 <= item[k] <= 1 for k in ("x1", "y1", "x2", "y2"))
                continue
            assert item["x"] >= vp.SAFE_X - 1e-9
            assert item["y"] >= vp.SAFE_Y - 1e-9
            assert item["x"] + item["w"] <= vp.SAFE_R + 1e-9
            assert item["y"] + item["h"] <= vp.SAFE_B + 1e-9


def test_wireframe_mirrors_every_decoration_kind():
    slide, scene = _relationship_slide("parallel")
    items = vp.decorations(scene, slide)
    svg = page_scene.wireframe(scene, slide)
    assert svg.count("<polygon") == sum(i["kind"] == "chevron" for i in items)
    assert svg.count("<circle") == sum(i["kind"] == "badge" for i in items)
    assert svg.count("<line ") == sum(i["kind"] == "line" for i in items)
    assert svg.count("<defs>") == sum(i["kind"] == "gradient" for i in items)
    assert "stroke-dasharray" in svg  # 区域轮廓仍在，文字摘录不被装饰吞掉


def test_wireframe_accepts_document_theme_colors():
    slide, scene = _relationship_slide("none")
    svg = page_scene.wireframe(scene, slide,
                               colors={"primary": "#C00000", "accent": "#E8B54D"})
    assert "#C00000" in svg
    assert "#E8B54D" in svg


def test_render_adds_native_primitives_without_losing_text():
    slide, _ = _relationship_slide("comparison", points=("法治政府建设持续深化",
                                                          "普惠法律服务覆盖面扩大"))
    outline = {"slides": [slide]}
    spec = ppt_engine.template_to_dict(ppt_engine.builtin_template("publicity_cyan"))
    data = ppt_engine.render_pptx(outline, spec, adaptive=True)
    prs = Presentation(io.BytesIO(data))
    shapes = list(prs.slides[0].shapes)
    texts = [s.text for s in shapes if s.has_text_frame and s.text.strip()]
    assert all(any(point in t for t in texts) for point in slide["points"])
    assert any(s.shape_type == MSO_SHAPE_TYPE.LINE for s in shapes)  # 原生连接符
    # 正文页不应再出现「primary→light 渐变细条」压在要点上方：右端渐隐在浅底上
    # 像一层灰影，成稿里读作「下面莫名其妙的线条」（用户 2026-11-09 反馈）。
    assert not any(s._element.spPr.find(qn("a:gradFill")) is not None
                   for s in shapes if hasattr(s._element, "spPr"))
    # 装饰必须先于文字，否则几何审计会判 TEXT_HIDDEN
    badge_idx = next(i for i, s in enumerate(shapes)
                     if s.has_text_frame and s.text.strip() in ("1", "2"))
    body_idx = next(i for i, s in enumerate(shapes)
                    if s.shape_type == MSO_SHAPE_TYPE.TEXT_BOX
                    and s.text.strip() in slide["points"])
    assert badge_idx < body_idx


class TestLayoutMotif:
    """同一份要点换版式后，装饰骨架也要跟着变，不只是列数不同。"""

    @staticmethod
    def _slide():
        return {"type": "content", "title": "年度成效",
                "points": ["完善制度体系", "加强队伍建设",
                           "推进数字转型", "健全监督机制"],
                "design": {"relationship": "grouped"}}

    @staticmethod
    def _layouts():
        return ("content.bullets", "content.two_col",
                "content.icon_grid", "content.center")

    def test_different_layouts_produce_different_visual_language(self):
        motifs = {}
        for layout in self._layouts():
            scene = page_scene.plan(dict(self._slide()), layout)
            assert scene is not None and scene["layout"] == layout
            motifs[layout] = tuple((item["kind"], round(item.get("x", 0), 3))
                                   for item in scene["visuals"])
        assert len(set(motifs.values())) == len(self._layouts())

    def test_motif_shapes_stay_inside_safe_area(self):
        for layout in self._layouts():
            scene = page_scene.plan(dict(self._slide()), layout)
            for item in scene["visuals"]:
                if item["kind"] == "line":
                    assert all(0 <= item[k] <= 1 for k in ("x1", "y1", "x2", "y2"))
                    continue
                assert item["x"] >= vp.SAFE_X - 1e-9
                assert item["y"] >= vp.SAFE_Y - 1e-9
                assert item["x"] + item["w"] <= vp.SAFE_R + 1e-9
                assert item["y"] + item["h"] <= vp.SAFE_B + 1e-9

    def test_scene_cache_is_keyed_by_layout(self):
        slide = dict(self._slide())
        first = page_scene.plan(slide, "content.bullets")
        slide["scene"] = first
        second = page_scene.plan(slide, "content.two_col")
        assert second is not None and second["layout"] == "content.two_col"
        assert second["visuals"] != first["visuals"]

class TestCompositionFamilies:
    """版式必须映射到不同构图族，且同页同级字号一致、装饰对齐真实列。"""

    @staticmethod
    def _slide():
        return {"type": "content", "title": "年度重点",
                "points": ["完善制度体系", "加强队伍建设", "推进数字转型"],
                "design": {"relationship": "parallel"}}

    def test_layouts_span_distinct_geometry_families(self):
        sigs = {}
        for layout in ("content.three_cards", "content.bullets",
                       "content.symmetric", "content.center"):
            scene = page_scene.plan(dict(self._slide()), layout)
            assert scene is not None
            sigs[layout] = tuple(
                (round(e["x"], 3), round(e["y"], 3), round(e["w"], 3))
                for e in scene["elements"] if e["ref"].startswith("point:"))
        assert len(set(sigs.values())) == 4

    def test_peer_points_share_one_readable_font_size(self):
        scene = page_scene.plan(dict(self._slide()), "content.three_cards")
        points = [e for e in scene["elements"] if e["ref"].startswith("point:")]
        assert len({e["font_pt"] for e in points}) == 1
        assert points[0]["font_pt"] >= 24  # 大框短句要放大，不再恒 20pt

    def test_motif_bands_follow_real_columns(self):
        slide = {"type": "content", "title": "两类问题",
                 "points": ["资源分布不均", "协同效率待提升"],
                 "design": {"relationship": "comparison"}}
        scene = page_scene.plan(slide, "content.compare")
        boxes = [e for e in scene["elements"] if e["ref"].startswith("point:")]
        columns = {round(b["x"], 3) for b in boxes}
        bands = [d for d in scene["visuals"]
                 if d["kind"] == "rect" and d.get("h", 0) < .012
                 and d.get("y", 0) >= .20]
        assert bands
        assert len(bands) == len(columns)
        assert {round(b["x"], 3) for b in bands} == columns
        # 色带贴各自列顶（差 0.018），不再是一条固定横线穿过错落的两列
        for band in bands:
            top = min(b["y"] for b in boxes if abs(b["x"] - band["x"]) < .01)
            assert abs(band["y"] - (top - .018)) < .002

    def test_short_and_long_points_still_fit_after_uniform_sizing(self):
        slide = {"type": "content", "title": "成效",
                 "points": ["简", "较长的一段说明文字。" * 12],
                 "design": {"relationship": "comparison"}}
        scene = page_scene.plan(slide, "content.two_col")
        assert scene is not None
        assert page_scene.audit(scene["elements"], slide)


class TestModelRegionCompaction:
    """模型给的大框要按文字收紧，模型画的卡片必须跟着走。

    样例是 2026-11-11 样稿里真实出现的构图：一条 24 字的要点分到 46% 页高的
    框里，成稿是「卡片顶上挂一行字、下面空掉半页」。
    """

    slide = {"type": "content", "title": "以制度建设推动工作落实",
             "points": ["建立定期学习和交流机制，明确各部门责任分工。",
                        "围绕重点任务开展督促检查，及时梳理落实情况。"],
             "design": {"regions": [
                 {"ref": "title", "x": .08, "y": .05, "w": .84, "h": .12},
                 {"ref": "point:0", "x": .08, "y": .30, "w": .38, "h": .46},
                 {"ref": "point:1", "x": .54, "y": .30, "w": .38, "h": .46}],
                 "visuals": [
                     {"kind": "rect", "x": .065, "y": .285, "w": .41, "h": .49,
                      "fill": "light", "radius": True},
                     {"kind": "rect", "x": .525, "y": .285, "w": .41, "h": .49,
                      "fill": "light", "radius": True},
                     {"kind": "rect", "x": .065, "y": .285, "w": .41, "h": .008,
                      "fill": "primary"},
                     {"kind": "rect", "x": .525, "y": .285, "w": .41, "h": .008,
                      "fill": "primary"}]}}

    def _compacted(self, slide=None):
        slide = copy.deepcopy(slide or self.slide)
        elements = copy.deepcopy(slide["design"]["regions"])
        assert page_scene.explain(elements, slide) == ""
        return slide, page_scene.compact_regions(
            elements, slide, slide["design"].get("visuals"))

    def test_tall_boxes_shrink_to_the_text_and_stay_equal_height(self):
        _, (elements, _, changed) = self._compacted()
        assert changed
        bodies = [item for item in elements if item["ref"].startswith("point:")]
        assert all(.10 < item["h"] < .30 for item in bodies)
        assert bodies[0]["h"] == bodies[1]["h"]
        assert page_scene.explain(elements, self.slide) == ""

    def test_card_and_top_band_follow_their_text(self):
        _, (elements, visuals, _) = self._compacted()
        bodies = [item for item in elements if item["ref"].startswith("point:")]
        cards = [item for item in visuals if item["h"] > .03]
        bands = [item for item in visuals if item["kind"] == "rect"
                 and item["h"] < .01]
        for body, card, band in zip(bodies, cards, bands):
            # 卡片与文字的相对留白（上下各 1.5%）保持不变
            assert abs(card["y"] - (body["y"] - .015)) < .002
            assert abs(card["h"] - (body["h"] + .03)) < .002
            # 顶盖色带贴在卡片顶边，不能悬在半空
            assert abs(band["y"] - card["y"]) < .002

    def test_image_page_keeps_cards_top_aligned_with_the_photo(self):
        slide = {"type": "content", "title": "开展业务学习与交流研讨",
                 "points": ["围绕岗位要求开展集中学习，交流具体做法。",
                            "结合业务实践梳理常见问题和处理思路。"],
                 "_image": {"file_path": "photo.png"},
                 "design": {"relationship": "grouped", "regions": [
                     {"ref": "title", "x": .08, "y": .05, "w": .84, "h": .12},
                     {"ref": "point:0", "x": .08, "y": .29, "w": .38, "h": .22},
                     {"ref": "point:1", "x": .08, "y": .57, "w": .38, "h": .22},
                     {"ref": "image", "x": .52, "y": .27, "w": .40, "h": .54}]}}
        _, (elements, _, changed) = self._compacted(slide)
        assert changed
        by_ref = {item["ref"]: item for item in elements}
        assert by_ref["point:0"]["y"] == .29          # 顶边不动，跟照片顶边齐
        assert by_ref["point:1"]["y"] < .57            # 第二条上移，不再留大洞
        assert by_ref["point:1"]["y"] > by_ref["point:0"]["y"] + by_ref["point:0"]["h"]
        assert by_ref["image"]["h"] == .54             # 图片区域不受影响

    def test_plan_writes_the_compacted_geometry_back(self):
        slide = copy.deepcopy(self.slide)
        scene = page_scene.plan(slide, "content.two_col")
        bodies = [item for item in scene["elements"] if item["ref"].startswith("point:")]
        regions = {item["ref"]: item for item in slide["design"]["regions"]}
        for body, ref in zip(bodies, ("point:0", "point:1")):
            assert regions[ref]["h"] == body["h"]
            assert regions[ref]["y"] == body["y"]
        # 几何写回后指纹必须重算，否则场景缓存每次都被判未命中。
        assert page_scene.plan(slide, "content.two_col") == scene


def test_toc_grid_with_four_items_is_two_by_two():
    """目录 4 条不能排成「3 + 1」：第四条独占一行、右侧全空（2026-11-09）。"""
    from pptx import Presentation
    from app.application.ppt import ppt_engine

    tpl = dict(ppt_engine.BUILTIN_TEMPLATES[0])
    outline = {"title": "t", "slides": [{
        "type": "toc", "title": "汇报目录",
        "points": ["一、强化思想引领", "二、深学细悟条例",
                   "三、注重学用结合", "四、下一步工作打算"]}]}
    data = ppt_engine.build_pptx(outline, tpl)
    prs = Presentation(io.BytesIO(data))
    boxes = [sh for sh in prs.slides[0].shapes
             if sh.has_text_frame and sh.text_frame.text.strip().startswith("0")]
    columns = {round(sh.left / 914400, 2) for sh in boxes}
    assert len(columns) == 2, f"目录应排 2 列，实际列起点 {columns}"
