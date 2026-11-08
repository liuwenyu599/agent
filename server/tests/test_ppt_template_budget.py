from types import SimpleNamespace

import pytest

from app.application.ppt.ppt_engine import template_content_budget
from app.application.ppt.service import PPTService
from app.core.config import settings
from app.core.exceptions import AppError, PermissionDeniedError


def test_template_budget_uses_real_geometry():
    def layout(width, font):
        return {"id": "L1", "text_regions": [
            {"role": "body", "w": width, "h": .3, "font_size": font}]}
    small = template_content_budget([layout(.2, 24)])[0]["slots"][0]
    wide = template_content_budget([layout(.6, 24)])[0]["slots"][0]
    tiny = template_content_budget([layout(.2, 12)])[0]["slots"][0]
    assert small["suggested_chars"] < wide["suggested_chars"]
    assert small["suggested_chars"] < tiny["suggested_chars"]


def test_cloud_deployment_gate_precedes_network_and_config(monkeypatch):
    monkeypatch.setattr(settings, "PPT_CLOUD_ALLOWED", False)
    service = PPTService.__new__(PPTService)
    with pytest.raises(AppError):
        service.generate_cloud(SimpleNamespace(), SimpleNamespace(role="user"))
    with pytest.raises(PermissionDeniedError):
        service.put_cloud_config(SimpleNamespace(enabled=True), SimpleNamespace(role="user"))
    with pytest.raises(AppError):
        service.put_cloud_config(SimpleNamespace(enabled=True), SimpleNamespace(role="developer"))
    with pytest.raises(PermissionDeniedError):
        service.import_template_url(SimpleNamespace(url="https://example.org/template.pptx"),
                                    SimpleNamespace(role="user"))
    with pytest.raises(AppError):
        service.import_template_url(SimpleNamespace(url="https://example.org/template.pptx"),
                                    SimpleNamespace(role="developer"))


@pytest.mark.parametrize("number,accepted", [("12", True), ("13", False)])
def test_template_compaction_preserves_numbers_and_input(monkeypatch, number, accepted):
    import json
    service = PPTService.__new__(PPTService)
    assistant = SimpleNamespace(complete=lambda *args, **kwargs: json.dumps({
        "pages": [{"index": 0, "title": "结果", "points": [f"办结{number}件"]}]}))
    monkeypatch.setattr(service, "_ppt_assistant", lambda: assistant)
    original = {"slides": [{"type": "content", "layout": "L1", "title": "结果",
                            "points": ["本年度相关业务工作已累计办结12件"]}]}
    template = {"layout_library": [{"id": "L1", "text_regions": [
        {"role": "title", "w": .5, "h": .1, "font_size": 24},
        {"role": "body", "w": .15, "h": .09, "font_size": 18}]}]}
    result = service._compact_template_text(original, template)
    assert original["slides"][0]["points"] == ["本年度相关业务工作已累计办结12件"]
    assert result["slides"][0]["points"] == (
        [f"办结{number}件"] if accepted else original["slides"][0]["points"])


@pytest.mark.parametrize("number,accepted", [("12", True), ("13", False)])
def test_adaptive_rewrite_requires_numeric_fidelity_and_better_score(monkeypatch, number, accepted):
    import io
    import json
    from pptx import Presentation
    from app.application.ppt import ppt_engine
    calls = []
    def complete(messages, **kwargs):
        calls.append(messages)
        return json.dumps({"points": [f"办结{number}件"], "regions": [
            {"ref": "title", "x": .06, "y": .05, "w": .88, "h": .12},
            {"ref": "point:0", "x": .06, "y": .25, "w": .88, "h": .5}]})
    original = "本年度相关业务工作已累计办结12件"
    def review(data):
        slide = Presentation(io.BytesIO(data)).slides[0]
        found = any(s.has_text_frame and original in s.text for s in slide.shapes)
        return {"issues": [{"page": 1, "code": "small_font", "message": "测试问题"}] if found else []}
    monkeypatch.setattr(PPTService, "review_pptx_visuals", staticmethod(review))
    outline = {"slides": [{"type": "content", "title": "办理成效", "points": [original]}]}
    _, adjusted = PPTService._render_with_feedback(
        outline, ppt_engine.template_to_dict(ppt_engine.BUILTIN_TEMPLATES[0]),
        vision_review=False, assistant=SimpleNamespace(complete=complete))
    assert len(calls) == 1
    assert "budget_chars" in calls[0][0]["content"]
    assert adjusted["slides"][0]["points"] == ([f"办结{number}件"] if accepted else [original])
    assert outline["slides"][0]["points"] == [original]


def test_partial_vision_review_still_accepts_improved_rewrite(monkeypatch):
    """视觉模型超时/部分页失败时不能否决重写，也不该为候选页白调一次 35B。"""
    import io
    import json
    from pptx import Presentation
    from app.application.ppt import page_scene
    from app.application.ppt import ppt_engine

    monkeypatch.setattr(settings, "VISION_MODEL_URL", "http://vision.local/v1")
    original = "本年度相关业务工作已累计办结12件"
    rewritten = "办结12件"
    slide = {"type": "content", "title": "办理成效", "points": [original]}
    scene = page_scene.plan(slide, "content.bullets")
    assert scene is not None
    slide["scene"] = scene
    regions = [{"ref": e["ref"], "x": e["x"], "y": e["y"], "w": e["w"], "h": e["h"]}
               for e in scene["elements"]]

    calls, visual_calls = [], []

    def complete(messages, **kwargs):
        calls.append(messages)
        return json.dumps({"points": [rewritten], "regions": regions})

    def fake_visual(data):
        visual_calls.append(data)
        return {"status": "partial", "pages_checked": 1, "issues": [
            {"page": 1, "code": "clipped_text", "message": "旧稿文字裁切"}]}

    def review(data):
        texts = [s.text for s in Presentation(io.BytesIO(data)).slides[0].shapes
                 if s.has_text_frame]
        return {"issues": [{"page": 1, "code": "small_font", "message": "字号偏小"}]
                if any(original in t for t in texts) else []}

    monkeypatch.setattr(PPTService, "review_rendered_pages", staticmethod(fake_visual))
    monkeypatch.setattr(PPTService, "review_pptx_visuals", staticmethod(review))
    template = ppt_engine.template_to_dict(ppt_engine.BUILTIN_TEMPLATES[0])
    monkeypatch.setattr(ppt_engine, "layout_ids", lambda _type: [])
    outline = {"slides": [slide]}
    warnings = []
    _, adjusted = PPTService._render_with_feedback(
        outline, template,
        warnings=warnings, vision_review=True,
        assistant=SimpleNamespace(complete=complete))
    assert adjusted["slides"][0]["points"] == [rewritten]
    assert len(calls) == 1
    assert len(visual_calls) == 1
    assert not any("旧稿文字裁切" in warning for warning in warnings)
    assert any("视觉复检未全部完成" in warning for warning in warnings)


def test_rewrite_clamps_slightly_out_of_bounds_regions(monkeypatch):
    """重写与正常生成共用局部修正：轻微越界平移保留，而非整页拒绝。"""
    import io
    import json
    from pptx import Presentation
    from app.application.ppt import page_scene
    from app.application.ppt import ppt_engine

    original = "本年度相关业务工作已累计办结12件"
    rewritten = "办结12件"
    slide = {"type": "content", "title": "办理成效", "points": [original]}
    scene = page_scene.plan(slide, "content.bullets")
    assert scene is not None
    regions = [{"ref": e["ref"], "x": e["x"], "y": e["y"], "w": e["w"], "h": e["h"]}
               for e in scene["elements"]]
    regions[1]["x"] = -.02

    def complete(messages, **kwargs):
        return json.dumps({"points": [rewritten], "regions": regions})

    def review(data):
        texts = [s.text for s in Presentation(io.BytesIO(data)).slides[0].shapes
                 if s.has_text_frame]
        return {"issues": [{"page": 1, "code": "small_font", "message": "字号偏小"}]
                if any(original in t for t in texts) else []}

    monkeypatch.setattr(PPTService, "review_pptx_visuals", staticmethod(review))
    outline = {"slides": [slide]}
    _, adjusted = PPTService._render_with_feedback(
        outline, ppt_engine.template_to_dict(ppt_engine.BUILTIN_TEMPLATES[0]),
        vision_review=False, assistant=SimpleNamespace(complete=complete))
    assert adjusted["slides"][0]["points"] == [rewritten]
    assert adjusted["slides"][0]["design"]["regions"][1]["x"] == .035


def test_rewrite_keeps_condensed_text_when_regions_are_far_out():
    """模型坐标偏离过远时退安全布局，不能把已通过校验的精简文字一起作废。"""
    import json
    from app.application.ppt import page_scene

    original = "本年度相关业务工作已累计办结12件"
    rewritten = "办结12件"
    slide = {"type": "content", "title": "办理成效", "points": [original]}
    scene = page_scene.plan(slide, "content.bullets")
    assert scene is not None
    slide["scene"] = scene
    regions = [{"ref": e["ref"], "x": e["x"], "y": e["y"], "w": e["w"], "h": e["h"]}
               for e in scene["elements"]]
    regions[1]["x"] = -.30

    def complete(messages, **kwargs):
        return json.dumps({"points": [rewritten], "regions": regions})

    out = PPTService._rewrite_scene_page(
        slide, [{"page": 1, "code": "text_density", "message": "文字过密"}],
        SimpleNamespace(complete=complete))
    assert out is not None
    assert out["points"] == [rewritten]
    assert out["design"]["regions"] is None
    safe = page_scene.plan(out, "content.bullets")
    assert safe is not None
    assert {e["ref"] for e in safe["elements"]} == {"title", "point:0"}
