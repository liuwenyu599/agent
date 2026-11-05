"""自由生成的整稿视觉风格应稳定、贴合场景，导出后仍保持一致。"""
from io import BytesIO

from pptx import Presentation

from app.application.ppt import ppt_engine


def test_topic_style_selection_is_semantic_and_stable():
    cases = {
        "基层人民调解工作成效": "public_service_green",
        "智慧司法行政平台建设": "digital_slate",
        "社区矫正服务质量调研评估": "public_service_green",
        "司法行政执法质效专题研究": "research_sand",
        "法治宣传教育工作": "publicity_cyan",
        "党风廉政建设": "gov_report_red",
    }
    for topic, expected in cases.items():
        assert ppt_engine.pick_builtin_template(topic, "工作汇报") == expected
    generic = ppt_engine.pick_builtin_template("基层业务工作进展", "工作汇报")
    assert generic == ppt_engine.pick_builtin_template("基层业务工作进展", "工作汇报")
    assert generic in {"gov_report_blue", "public_service_green",
                       "digital_slate", "research_sand"}


def test_builtin_styles_have_distinct_deck_pallets_and_editable_text():
    outline = {"title": "工作进展", "slides": [
        {"type": "cover", "title": "工作进展", "subtitle": "2026 年度"},
        {"type": "content", "title": "重点工作", "points": [
            "完善公共法律服务供给", "提升群众办事便利度", "优化业务协同流程"]},
        {"type": "summary", "title": "下一步", "points": [
            "继续提升服务效能", "定期复盘工作成效"]},
    ]}
    cover_colors = set()
    for theme_id in ("public_service_green", "digital_slate", "research_sand"):
        spec = ppt_engine.builtin_template(theme_id)
        data = ppt_engine.render_pptx(outline, ppt_engine.template_to_dict(spec),
                                      adaptive=True)
        prs = Presentation(BytesIO(data))
        assert len(prs.slides) == 3
        assert any("工作进展" in shape.text for shape in prs.slides[0].shapes
                   if shape.has_text_frame)
        assert any("完善公共法律服务" in shape.text for shape in prs.slides[1].shapes
                   if shape.has_text_frame)
        fills = {str(shape.fill.fore_color.rgb) for shape in prs.slides[0].shapes
                 if shape.fill.type is not None and shape.fill.type == 1
                 and shape.fill.fore_color.type is not None
                 and shape.fill.fore_color.type == 1}
        assert spec["colors"]["primary"] in fills
        cover_colors.add(spec["colors"]["primary"])
    assert len(cover_colors) == 3
