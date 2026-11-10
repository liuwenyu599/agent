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


def test_deck_communication_contract_is_preserved_without_model_style_override():
    outline = ppt_engine.normalize_outline({
        "design_spec": {"density": "balanced", "audience": "局领导",
                        "communication_intent": "汇报进展并说明下一步安排",
                        "core_message": "把学习成果落实到具体工作",
                        "delivery_context": "现场汇报", "font": "任意字体",
                        "palette": ["red", "blue"]},
        "slides": [{"type": "content", "title": "工作进展",
                    "points": ["组织专题学习"]}],
    }, require_bookends=False)
    spec = outline["design_spec"]
    assert spec["audience"] == "局领导"
    assert spec["communication_intent"] == "汇报进展并说明下一步安排"
    assert spec["core_message"] == "把学习成果落实到具体工作"
    assert spec["delivery_context"] == "现场汇报"
    assert "font" not in spec and "palette" not in spec
