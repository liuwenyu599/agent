"""自适应排版的渲染后复检与按页修复。"""

import shutil

import pytest

from app.application.ppt import ppt_engine
from app.application.ppt.service import PPTService


def test_material_matching_uses_relevant_caption_and_avoids_unrelated_image():
    outline = {"slides": [
        {"type": "content", "title": "社区矫正工作", "points": ["工作安排"]},
        {"type": "content", "title": "行政复议案件", "image_hint": "行政复议听证现场",
         "points": ["审理情况"]},
    ]}
    images = [{"id": "a", "name": "会议照片.jpg", "caption": "行政复议听证现场",
               "file_path": "/images/a.jpg"}]
    resolved = ppt_engine.resolve_slide_images(outline, images)
    assert resolved["slides"][0]["_image"] is None
    assert resolved["slides"][1]["_image"]["id"] == "a"
    assert resolved["slides"][1]["layout"] == "image_right"


def test_automatic_material_is_not_repeated_on_every_page():
    outline = {"slides": [{"type": "content", "title": "行政复议听证现场"},
                          {"type": "content", "title": "行政复议听证现场"}]}
    images = [{"id": "a", "name": "听证.jpg", "caption": "行政复议听证现场",
               "file_path": "/images/a.jpg"}]
    resolved = ppt_engine.resolve_slide_images(outline, images)
    assert resolved["slides"][0]["_image"]["id"] == "a"
    assert resolved["slides"][1]["_image"] is None


def test_visual_review_uses_rendered_slide_image(monkeypatch):
    calls = []

    class FakeVision:
        def complete(self, messages, **kwargs):
            calls.append(messages)
            return '{"issues":[{"page":1,"code":"visual_overlap","message":"标题遮挡正文"}]}'

    monkeypatch.setattr("app.application.ppt.visual_review.render_slide_images",
                        lambda _data: [b"png"])
    result = PPTService.review_rendered_pages(b"pptx", gateway=FakeVision())
    assert result["pages_checked"] == 1
    assert result["issues"][0]["code"] == "visual_overlap"
    assert calls[0][0]["content"][2]["image_url"]["url"].startswith("data:image/png;base64,")


def test_visual_review_ignores_invalid_model_findings(monkeypatch):
    class FakeVision:
        def complete(self, messages, **kwargs):
            return '{"issues":[{"page":99,"code":"visual_overlap","message":"错页"},' \
                   '{"page":1,"code":"rewrite_content","message":"越权"}]}'

    monkeypatch.setattr("app.application.ppt.visual_review.render_slide_images",
                        lambda _data: [b"png"])
    result = PPTService.review_rendered_pages(b"pptx", gateway=FakeVision())
    assert result["status"] == "passed"
    assert result["issues"] == []


@pytest.mark.skipif(not shutil.which("soffice") or not shutil.which("pdftoppm"),
                    reason="需要本机 PPT 页面渲染组件")
def test_visual_review_renders_actual_pptx_pages():
    from pptx import Presentation
    from io import BytesIO

    presentation = Presentation()
    presentation.slides.add_slide(presentation.slide_layouts[6])
    output = BytesIO()
    presentation.save(output)

    class FakeVision:
        def complete(self, messages, **kwargs):
            assert any(part["type"] == "image_url"
                       for part in messages[0]["content"])
            return '{"issues":[]}'

    result = PPTService.review_rendered_pages(output.getvalue(), gateway=FakeVision())
    assert result == {"status": "passed", "pages_checked": 1,
                      "issues": [], "reason": ""}


def test_adaptive_route_never_calls_legacy_pptagent(monkeypatch):
    from types import SimpleNamespace
    from app.core.config import settings
    from app.infrastructure.ppt.ppt_agent_client import PPTAgentClient

    monkeypatch.setattr(settings, "PPT_AGENT_URL", "http://unused-agent")
    attempted = []
    monkeypatch.setattr(PPTAgentClient, "from_settings",
                        lambda: attempted.append(True))
    monkeypatch.setattr(PPTService, "_render_with_feedback",
                        staticmethod(lambda outline, _template, **_kw: (b"local", outline)))
    svc = object.__new__(PPTService)
    monkeypatch.setattr(svc, "design_prompt_for_document", lambda _doc: "")
    data, renderer = svc._render_pptx_bytes(
        SimpleNamespace(source_content="", title="测试", id="x", user_id="u"),
        {"slides": []}, {"name": "政务"}, None, adaptive=True)
    assert (data, renderer) == (b"local", "local")
    assert attempted == []


def test_free_layout_async_job_uses_local_renderer_with_legacy_url(monkeypatch):
    import importlib
    from types import SimpleNamespace
    agent_job = importlib.import_module("app.application.ppt.agent_job")
    from app.core.config import settings

    monkeypatch.setattr(settings, "PPT_AGENT_URL", "http://unused-agent")
    monkeypatch.setattr(agent_job, "_open", lambda _id: SimpleNamespace(template_id=None))
    assert agent_job.uses_local_renderer("doc") is True
    monkeypatch.setattr(agent_job, "_open", lambda _id: SimpleNamespace(template_id="tpl"))
    assert agent_job.uses_local_renderer("doc") is False


def test_queued_job_bypasses_legacy_queue_for_free_layout(monkeypatch):
    from app.application.ppt import queued_agent_job

    monkeypatch.setattr(queued_agent_job._core, "uses_local_renderer", lambda _id: True)
    monkeypatch.setattr(queued_agent_job._core, "submit_job",
                        lambda *_args: {"job_id": "doc", "status": "pending"})
    result = queued_agent_job.submit_job("doc", "user")
    assert result["job_id"] == "doc"
    assert result["queue_position"] is None


def test_visual_feedback_changes_only_problem_page(monkeypatch):
    outline = {"title": "工作汇报", "slides": [
        {"type": "cover", "title": "工作汇报"},
        {"type": "content", "title": "工作情况",
         "points": ["事项一", "事项二", "事项三"]},
        {"type": "closing", "title": "谢谢聆听"},
    ]}
    renders = []

    def fake_render(candidate, _template, **_kwargs):
        layout = candidate["slides"][1].get("layout") or "content.bullets"
        renders.append(layout)
        return layout.encode()

    def fake_review(data):
        issues = ([] if data.decode() == "content.three_cards" else [{
            "page": 2, "code": "text_overlap", "severity": "error",
            "message": "两个文字区域明显重叠",
        }])
        return {"status": "review" if issues else "passed",
                "pages_checked": 3, "issues": issues}

    monkeypatch.setattr(ppt_engine, "render_pptx", fake_render)
    monkeypatch.setattr(PPTService, "review_pptx_visuals", staticmethod(fake_review))
    warnings = []
    data, adjusted = PPTService._render_with_feedback(
        outline, {"colors": {}, "layouts": {}}, warnings, vision_review=False)

    assert data == b"content.three_cards"
    assert adjusted["slides"][1]["layout"] == "content.three_cards"
    assert "layout" not in outline["slides"][1]
    assert adjusted["slides"][0] == outline["slides"][0]
    assert adjusted["slides"][2] == outline["slides"][2]
    assert warnings == []
    assert len(renders) <= 6


def test_visual_feedback_reports_unresolved_problem(monkeypatch):
    outline = {"slides": [{"type": "content", "title": "文字页",
                           "points": ["事项一", "事项二"]}]}
    monkeypatch.setattr(ppt_engine, "render_pptx", lambda *_args, **_kwargs: b"pptx")
    monkeypatch.setattr(PPTService, "review_pptx_visuals", staticmethod(
        lambda _data: {"status": "review", "pages_checked": 1, "issues": [{
            "page": 1, "code": "text_overflow_risk", "severity": "warning",
            "message": "文字可能超出文本框，请检查预览",
        }]}))
    warnings = []
    data, adjusted = PPTService._render_with_feedback(
        outline, {"colors": {}, "layouts": {}}, warnings, vision_review=False)
    assert data == b"pptx"
    assert len(adjusted["slides"]) == 1
    assert warnings == ["第1页：文字可能超出文本框，请检查预览"]
