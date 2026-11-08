from app.application.ppt import ppt_engine


def test_page_intent_survives_normalization_and_respects_user_layout():
    outline = ppt_engine.normalize_outline({
        "design_spec": {"density": "spacious", "font": "untrusted"},
        "slides": [{"type": "content", "title": "办理成效",
                    "points": ["办理周期缩短", "材料重复提交减少"],
                    "design": {"relationship": "comparison", "image_role": "none"}}],
    }, require_bookends=False)
    assert outline["design_spec"] == {"density": "spacious"}
    slide = outline["slides"][0]
    assert ppt_engine.choose_layout(slide) == "content.compare"
    assert ppt_engine.choose_layout(
        {**slide, "layout": "bullets", "layout_locked": True}) == "content.bullets"
    ppt_engine.resolve_slide_images(outline, [
        {"id": "asset", "name": "办理成效", "caption": "办理成效"},
    ])
    assert slide["_image"] is None
