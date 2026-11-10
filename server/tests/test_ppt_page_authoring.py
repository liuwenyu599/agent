"""The second design pass may place content but cannot alter its facts."""
import copy
import io
import json
import sys
from pathlib import Path

from pptx import Presentation

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.application.ppt import ppt_engine
from app.application.ppt.page_authoring import _prompt, author_pages
from app.application.ppt.ppt_engine import normalize_outline


class Assistant:
    def __init__(self, replies):
        self.replies = list(replies)
        self.prompts = []

    def complete(self, messages, **kwargs):
        self.prompts.append(messages[0]["content"])
        return json.dumps(self.replies.pop(0), ensure_ascii=False)


def _regions(count=2):
    rows = [{"ref": "title", "x": .08, "y": .05, "w": .84, "h": .12}]
    rows.extend({"ref": f"point:{index}", "x": .08 + index * .46,
                 "y": .28, "w": .38, "h": .50} for index in range(count))
    return rows


def _outline():
    return {"title": "工作汇报", "style": "工作汇报", "slides": [
        {"type": "content", "title": "工作安排",
         "points": ["明确职责分工", "组织专题学习"],
         "design": {"job": "说明两项安排", "relationship": "parallel"}},
        {"type": "closing", "title": "谢谢聆听"},
    ]}


def test_author_pages_accepts_model_geometry_without_rewriting_content():
    original = _outline()
    original["design_spec"] = {"density": "balanced", "audience": "局领导",
                               "core_message": "说明具体工作安排"}
    assistant = Assistant([{"pages": [{"page": 1, "regions": _regions(),
                                        "visuals": [{"kind": "rect", "x": .08,
                                                     "y": .20, "w": .20, "h": .008,
                                                     "fill": "primary"}]}]}])
    result = author_pages(original, {"colors": {"primary": "C00000"}}, assistant)
    assert result["slides"][0]["design"]["regions"] == _regions()
    assert result["slides"][0]["points"] == original["slides"][0]["points"]
    assert "plan_signature" in result["slides"][0]["design"]
    assert "先判断每页的图文关系" in assistant.prompts[0]
    assert "局领导" in assistant.prompts[0]
    assert original["slides"][0]["design"].get("regions") is None
    author_pages(result, {"colors": {"primary": "C00000"}}, assistant)
    assert len(assistant.prompts) == 1


def test_author_pages_retries_overlap_then_accepts_repair():
    bad = _regions()
    bad[2]["x"] = .40
    assistant = Assistant([
        {"pages": [{"page": 1, "regions": bad, "visuals": []}]},
        {"pages": [{"page": 1, "regions": _regions(), "visuals": []}]},
    ])
    result = author_pages(_outline(), {}, assistant)
    assert result["slides"][0]["design"]["regions"] == _regions()
    assert len(assistant.prompts) == 2


def test_author_pages_falls_back_per_page_after_invalid_repair():
    bad = _regions()
    bad[2]["x"] = .40
    assistant = Assistant([
        {"pages": [{"page": 1, "regions": bad, "visuals": []}]},
        {"pages": [{"page": 1, "regions": bad, "visuals": []}]},
    ])
    warnings = []
    result = author_pages(_outline(), {}, assistant, warnings)
    assert "regions" not in result["slides"][0]["design"]
    assert result["slides"][0]["points"] == _outline()["slides"][0]["points"]
    assert warnings == ["第1页模型构图未通过检查，已采用可读版式"]


def test_author_pages_does_not_retry_every_page_when_model_is_unavailable():
    class Unavailable:
        calls = 0

        def complete(self, *_args, **_kwargs):
            self.calls += 1
            raise TimeoutError("model unavailable")

    assistant = Unavailable()
    warnings = []
    result = author_pages(_outline(), {}, assistant, warnings)
    assert assistant.calls == 1
    assert result["slides"][0]["points"] == _outline()["slides"][0]["points"]
    assert warnings == ["第1页模型构图未通过检查，已采用可读版式"]


def test_author_pages_replans_stale_auto_design():
    outline = _outline()
    outline["slides"][0]["design"].update(regions=copy.deepcopy(_regions()),
                                            plan_signature="stale")
    assistant = Assistant([{"pages": [{"page": 1, "regions": _regions(),
                                        "visuals": []}]}])
    result = author_pages(outline, {}, assistant)
    assert result["slides"][0]["design"]["plan_signature"] != "stale"
    assert len(assistant.prompts) == 1


def test_switching_template_invalidates_auto_page_plan():
    first = Assistant([{"pages": [{"page": 1, "regions": _regions(),
                                    "visuals": []}]}])
    original = author_pages(_outline(), {"id": "template-a", "colors": {}}, first)
    second = Assistant([{"pages": [{"page": 1, "regions": _regions(),
                                     "visuals": []}]}])
    updated = author_pages(original, {"id": "template-b", "colors": {}}, second)
    assert len(second.prompts) == 1
    assert (updated["slides"][0]["design"]["plan_signature"] !=
            original["slides"][0]["design"]["plan_signature"])


def test_authored_page_signature_survives_draft_normalization():
    assistant = Assistant([{"pages": [{"page": 1, "regions": _regions(),
                                        "visuals": []}]}])
    authored = author_pages(_outline(), {}, assistant)
    restored = normalize_outline(authored, require_bookends=False)
    assert restored["slides"][0]["design"]["plan_signature"] == (
        authored["slides"][0]["design"]["plan_signature"])
    author_pages(restored, {}, assistant)
    assert len(assistant.prompts) == 1


def test_retry_prompt_names_the_offending_regions():
    """重试反馈必须具体到区域，否则模型第二次只会原样再错一遍。"""
    bad = _regions()
    bad[2]["x"] = .40                      # point:1 压到 point:0 上
    assistant = Assistant([
        {"pages": [{"page": 1, "regions": bad, "visuals": []}]},
        {"pages": [{"page": 1, "regions": _regions(), "visuals": []}]},
    ])
    author_pages(_outline(), {}, assistant)
    retry = assistant.prompts[1]
    assert "重叠" in retry
    assert "point:0" in retry and "point:1" in retry
    assert "区域缺失、重叠、越界或容纳不下文字" not in retry


def test_retry_prompt_names_the_missing_region():
    assistant = Assistant([
        {"pages": [{"page": 1, "regions": _regions(1), "visuals": []}]},
        {"pages": [{"page": 1, "regions": _regions(), "visuals": []}]},
    ])
    author_pages(_outline(), {}, assistant)
    assert "缺少 point:1" in assistant.prompts[1]


def test_missing_assistant_reports_fallback_instead_of_silence():
    """没接上模型时 designed 不能装作生效：成稿全是可读兜底却无人知晓。"""
    warnings: list = []
    result = author_pages(_outline(), {}, None, warnings)
    assert warnings == ["页面构图模型未配置，正文页使用可读版式"]
    assert "regions" not in result["slides"][0]["design"]


def test_string_page_numbers_are_accepted():
    """模型把页码写成 "1" 不能整页丢掉。"""
    assistant = Assistant([{"pages": [{"page": " 1 ", "regions": _regions(),
                                       "visuals": []}]}])
    result = author_pages(_outline(), {}, assistant)
    assert result["slides"][0]["design"].get("regions") == _regions()


def test_batch_failure_reports_one_warning_for_all_pages():
    """一次请求失败拖累整批时，提示区不该出现四条一样的话。"""
    outline = {"slides": [
        {"type": "content", "title": f"第{i}页", "points": ["要点一", "要点二"]}
        for i in range(1, 4)
    ]}

    class Dead:
        def complete(self, *_args, **_kwargs):
            raise TimeoutError("model unavailable")

    warnings: list = []
    author_pages(outline, {}, Dead(), warnings)
    assert warnings == ["第1、2、3页模型构图未通过检查，已采用可读版式"]


def test_gateway_failure_skips_remaining_batched_requests():
    outline = {"slides": [
        {"type": "content", "title": f"第{i}页", "points": ["要点一", "要点二"]}
        for i in range(1, 7)
    ]}

    class Dead:
        calls = 0

        def complete(self, *_args, **_kwargs):
            self.calls += 1
            raise TimeoutError("model unavailable")

    assistant = Dead()
    warnings = []
    result = author_pages(outline, {}, assistant, warnings)
    assert assistant.calls == 1
    assert all(not slide.get("design", {}).get("regions") for slide in result["slides"])
    assert len(warnings) == 1 and "1、2、3、4、5、6" in warnings[0]


def test_adjacent_identical_pages_trigger_a_distinct_composition():
    outline = {"slides": [
        {"type": "content", "title": "问题一", "points": ["原因", "影响"]},
        {"type": "content", "title": "问题二", "points": ["做法", "结果"]},
    ]}
    stacked = [{"ref": "title", "x": .08, "y": .05, "w": .84, "h": .12},
               {"ref": "point:0", "x": .08, "y": .25, "w": .84, "h": .22},
               {"ref": "point:1", "x": .08, "y": .55, "w": .84, "h": .22}]
    assistant = Assistant([
        {"pages": [{"page": 1, "regions": _regions(), "visuals": []},
                   {"page": 2, "regions": _regions(), "visuals": []}]},
        {"pages": [{"page": 2, "regions": stacked, "visuals": []}]},
    ])
    result = author_pages(outline, {}, assistant)
    assert result["slides"][1]["design"]["regions"] == stacked
    assert len(assistant.prompts) == 2
    assert "与上一页的图文区域几乎相同" in assistant.prompts[1]


def test_repeated_page_keeps_valid_design_when_diversity_retry_is_invalid():
    outline = {"slides": [
        {"type": "content", "title": "问题一", "points": ["原因", "影响"]},
        {"type": "content", "title": "问题二", "points": ["做法", "结果"]},
    ]}
    assistant = Assistant([
        {"pages": [{"page": 1, "regions": _regions(), "visuals": []},
                   {"page": 2, "regions": _regions(), "visuals": []}]},
        {"pages": [{"page": 2, "regions": [], "visuals": []}]},
    ])
    warnings = []
    result = author_pages(outline, {}, assistant, warnings)
    assert result["slides"][1]["design"]["regions"] == _regions()
    assert warnings == ["第2页与前页构图相近，已保留可用方案"]


def test_missing_evidence_image_is_reported_to_generation_feedback():
    outline = _outline()
    outline["slides"][0]["design"]["image_role"] = "evidence"
    warnings = []
    author_pages(outline, {}, None, warnings)
    assert "图库没有匹配素材" in warnings[0]
    assert "页面构图模型未配置" in warnings[1]


def test_saved_adjacent_duplicate_is_replanned_on_next_export():
    outline = {"slides": [
        {"type": "content", "title": "问题一", "points": ["原因", "影响"]},
        {"type": "content", "title": "问题二", "points": ["做法", "结果"]},
    ]}
    from app.application.ppt.page_authoring import _signature
    for slide in outline["slides"]:
        slide["design"] = {"regions": _regions(),
                           "plan_signature": _signature(slide, {})}
    stacked = [{"ref": "title", "x": .08, "y": .05, "w": .84, "h": .12},
               {"ref": "point:0", "x": .08, "y": .25, "w": .84, "h": .22},
               {"ref": "point:1", "x": .08, "y": .55, "w": .84, "h": .22}]
    assistant = Assistant([{"pages": [{"page": 2, "regions": stacked,
                                        "visuals": []}]}])
    result = author_pages(outline, {}, assistant)
    assert result["slides"][0]["design"]["regions"] == _regions()
    assert result["slides"][1]["design"]["regions"] == stacked
    assert len(assistant.prompts) == 1


def test_next_batch_sees_previous_page_geometry():
    slides = [{"type": "content", "title": f"第{i}页",
               "points": ["要点一", "要点二"]} for i in range(1, 6)]
    slides[3]["design"] = {"regions": _regions()}
    prompt = _prompt({"slides": slides}, {}, [{"page": 5, "title": "第5页"}])
    context = json.loads(prompt.split("设计输入：", 1)[1])
    assert context["recent_compositions"] == [{
        "page": 4, "type": "content", "title": "第4页", "regions": _regions()}]


def test_comparison_page_rejects_stacked_geometry_and_repairs_side_by_side():
    outline = _outline()
    outline["slides"][0]["design"]["relationship"] = "comparison"
    stacked = [{"ref": "title", "x": .08, "y": .05, "w": .84, "h": .12},
               {"ref": "point:0", "x": .08, "y": .25, "w": .84, "h": .22},
               {"ref": "point:1", "x": .08, "y": .55, "w": .84, "h": .22}]
    assistant = Assistant([
        {"pages": [{"page": 1, "regions": stacked, "visuals": []}]},
        {"pages": [{"page": 1, "regions": _regions(), "visuals": []}]},
    ])
    result = author_pages(outline, {}, assistant)
    assert result["slides"][0]["design"]["regions"] == _regions()
    assert "对比关系" in assistant.prompts[1]


def test_takeaway_page_requires_a_dominant_region():
    from app.application.ppt.page_scene import intent_issue
    slide = {"type": "content", "title": "结论", "points": ["主结论", "支撑说明"],
             "design": {"relationship": "takeaway"}}
    assert "主结论" in intent_issue(_regions(), slide)
    dominant = _regions()
    dominant[1].update(x=.08, y=.26, w=.84, h=.34)
    dominant[2].update(x=.08, y=.64, w=.84, h=.16)
    assert intent_issue(dominant, slide) == ""


def test_template_preview_is_sent_as_visual_reference_only():
    from PIL import Image
    source = io.BytesIO()
    Image.new("RGB", (320, 180), "#f5efe8").save(source, "PNG")
    assistant = Assistant([{"pages": [{"page": 1, "regions": _regions(),
                                        "visuals": []}]}])
    result = author_pages(_outline(), {}, assistant,
                          reference_image=source.getvalue())
    content = assistant.prompts[0]
    assert isinstance(content, list)
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert "文字、照片和事实都不得带入" in content[0]["text"]
    assert result["slides"][0]["design"]["regions"] == _regions()


def test_unsupported_template_image_retries_with_text_summary():
    from PIL import Image
    source = io.BytesIO()
    Image.new("RGB", (320, 180), "white").save(source, "PNG")

    class TextOnly:
        contents = []

        def complete(self, messages, **_kwargs):
            self.contents.append(messages[0]["content"])
            if isinstance(messages[0]["content"], list):
                raise RuntimeError("模型调用失败")
            return json.dumps({"pages": [{"page": 1, "regions": _regions(),
                                           "visuals": []}]})

    assistant = TextOnly()
    result = author_pages(_outline(), {}, assistant,
                          reference_image=source.getvalue())
    assert len(assistant.contents) == 2
    assert isinstance(assistant.contents[1], str)
    assert result["slides"][0]["design"]["regions"] == _regions()


def test_new_model_shapes_compile_as_editable_ppt_shapes():
    from pptx.enum.shapes import MSO_SHAPE
    from app.application.ppt.visual_primitives import model_visuals, svg_decoration

    visuals = [
        {"kind": "donut", "x": .52, "y": .19, "w": .10, "h": .18,
         "fill": "light"},
        {"kind": "trapezoid", "x": .08, "y": .19, "w": .30, "h": .05,
         "fill": "light"},
        {"kind": "down_arrow", "x": .50, "y": .70, "w": .06, "h": .08,
         "fill": "light"},
    ]
    assert len(model_visuals(visuals, _regions())) == 3
    assert all("<path" in svg_decoration(item) or "<polygon" in svg_decoration(item)
               for item in visuals)
    source = _learned_deck_with_content_slide()
    library = ppt_engine.analyze_template(source)["layouts"]
    outline = {"slides": [{"type": "content", "title": "工作安排",
                           "points": ["明确职责分工", "组织专题学习"],
                           "design": {"regions": _regions(), "visuals": visuals}}]}
    pptx = ppt_engine.build_pptx_learned(
        outline, {"colors": ppt_engine.DEFAULT_COLORS, "font": "思源黑体"},
        source, library, warnings=[])
    shapes = {shape.auto_shape_type for slide in Presentation(io.BytesIO(pptx)).slides
              for shape in slide.shapes if shape.shape_type == 1}
    assert {MSO_SHAPE.DONUT, MSO_SHAPE.TRAPEZOID,
            MSO_SHAPE.DOWN_ARROW} <= shapes


def test_updated_template_preview_invalidates_saved_composition():
    from PIL import Image

    def png(color):
        output = io.BytesIO()
        Image.new("RGB", (16, 9), color).save(output, "PNG")
        return output.getvalue()

    first = Assistant([{"pages": [{"page": 1, "regions": _regions(),
                                    "visuals": []}]}])
    saved = author_pages(_outline(), {}, first, reference_image=png("white"))
    second = Assistant([{"pages": [{"page": 1, "regions": _regions(),
                                     "visuals": []}]}])
    renewed = author_pages(saved, {}, second, reference_image=png("red"))
    assert len(second.prompts) == 1
    assert (renewed["slides"][0]["design"]["plan_signature"] !=
            saved["slides"][0]["design"]["plan_signature"])


def test_new_model_shapes_also_compile_on_clean_canvas():
    from pptx.enum.shapes import MSO_SHAPE

    outline = {"slides": [{"type": "content", "title": "工作安排",
                           "points": ["明确职责分工", "组织专题学习"],
                           "design": {"regions": _regions(), "visuals": [
                               {"kind": "donut", "x": .52, "y": .19,
                                "w": .10, "h": .18, "fill": "light"}]}}]}
    data = ppt_engine.render_pptx(
        outline, {"colors": ppt_engine.DEFAULT_COLORS, "font": "思源黑体",
                  "layouts": {}},
        adaptive=True)
    assert any(shape.auto_shape_type == MSO_SHAPE.DONUT
               for slide in Presentation(io.BytesIO(data)).slides
               for shape in slide.shapes if shape.shape_type == 1)


def test_text_led_case_uses_model_composition():
    outline = {"slides": [{"type": "case", "title": "案例复盘",
                           "points": ["发现问题", "落实整改"]}]}
    assistant = Assistant([{"pages": [{"page": 1, "regions": _regions(),
                                        "visuals": []}]}])
    result = author_pages(outline, {}, assistant)
    slide = result["slides"][0]
    assert slide["design"]["regions"] == _regions()
    from app.application.ppt.page_scene import plan
    assert plan(slide, "case.block")["elements"]


def test_structured_case_keeps_specialized_renderer():
    outline = {"slides": [{"type": "case", "title": "案例复盘",
                           "points": ["发现问题", "落实整改"],
                           "blocks": {"chart": {"kind": "bar"}}}]}
    assistant = Assistant([])
    result = author_pages(outline, {}, assistant)
    assert not assistant.prompts
    from app.application.ppt.page_scene import plan
    assert plan(result["slides"][0], "case.block") is None


def test_text_led_case_compiles_with_model_regions_on_template():
    source = _learned_deck_with_content_slide()
    library = ppt_engine.analyze_template(source)["layouts"]
    outline = {"slides": [{"type": "case", "title": "案例复盘",
                           "points": ["发现问题", "落实整改"],
                           "design": {"regions": _regions()}}]}
    diagnostics = []
    ppt_engine.build_pptx_learned(
        outline, {"colors": ppt_engine.DEFAULT_COLORS, "font": "思源黑体"},
        source, library, warnings=[], diagnostics=diagnostics)
    assert diagnostics[0]["composition"] == "model"


def _learned_deck_with_content_slide(*, line_inside_body: bool = False):
    """一页空白底版 + 一条正文版式；用来量「编译落地」而不是审美。"""
    from pptx.enum.shapes import MSO_CONNECTOR
    from pptx.util import Emu

    prs = Presentation()
    prs.slide_width, prs.slide_height = Emu(12192000), Emu(6858000)
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    slide.shapes.add_textbox(Emu(int(12192000 * .06)), Emu(int(6858000 * .05)),
                            Emu(int(12192000 * .88)), Emu(int(6858000 * .11))
                            ).text = "模板标题占位"
    slide.shapes.add_textbox(Emu(int(12192000 * .06)), Emu(int(6858000 * .30)),
                            Emu(int(12192000 * .88)), Emu(int(6858000 * .20))
                            ).text = "模板正文占位"
    if line_inside_body:
        # 模板常把「段落之间的引线/箭头」留成独立线条，内容一换就悬空。
        slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT,
                                   Emu(int(12192000 * .38)), Emu(int(6858000 * .74)),
                                   Emu(int(12192000 * .44)), Emu(int(6858000 * .74)))
    source = io.BytesIO()
    prs.save(source)
    return source.getvalue()


def test_render_diagnostics_separate_model_composition_from_readable_fallback():
    source = _learned_deck_with_content_slide()
    library = ppt_engine.analyze_template(source)["layouts"]
    template = {"colors": ppt_engine.DEFAULT_COLORS, "font": "思源黑体"}
    designed = {"ref": "title", "x": .06, "y": .05, "w": .88, "h": .12}
    outline = {"slides": [
        {"type": "content", "title": "按模型构图", "points": ["要点一", "要点二"],
         "design": {"regions": [designed] + _regions(2)[1:]}},
        {"type": "content", "title": "没有构图", "points": ["要点一", "要点二"]},
    ]}
    diagnostics = []
    ppt_engine.build_pptx_learned(outline, template, source, library,
                                  warnings=[], diagnostics=diagnostics)
    by_page = {item["page"]: item for item in diagnostics}
    assert by_page[1]["composition"] == "model"
    assert by_page[1]["composition_skip"] == ""
    assert by_page[2]["composition"] == "readable"
    assert "没有 regions" in by_page[2]["composition_skip"]


def test_model_composition_removes_template_guide_lines_in_the_body():
    source = _learned_deck_with_content_slide(line_inside_body=True)
    library = ppt_engine.analyze_template(source)["layouts"]
    template = {"colors": ppt_engine.DEFAULT_COLORS, "font": "思源黑体"}
    designed = {"ref": "title", "x": .06, "y": .05, "w": .88, "h": .12}
    outline = {"slides": [
        {"type": "content", "title": "按模型构图", "points": ["要点一", "要点二"],
         "design": {"regions": [designed] + _regions(2)[1:]}},
    ]}
    data = ppt_engine.build_pptx_learned(outline, template, source, library,
                                         warnings=[])
    from pptx.enum.shapes import MSO_SHAPE_TYPE
    deck = Presentation(io.BytesIO(data))
    lines = [shape for shape in deck.slides[0].shapes
             if shape.shape_type == MSO_SHAPE_TYPE.LINE]
    assert lines == []
