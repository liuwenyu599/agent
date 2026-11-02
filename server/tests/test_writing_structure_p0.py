from app.application.templates.builtin_data import BUILTIN_TEMPLATES
from app.application.writing.task_service import WritingTaskService
from app.application.writing.sectioned_generation_service import SectionedGenerationWritingTaskService


def test_draft_requires_official_numbered_structure():
    svc = WritingTaskService.__new__(WritingTaskService)
    prompt = svc._build_draft_instruction({"document_type": "通知"}, False)
    assert "一、" in prompt and "（一）" in prompt
    assert "1．" in prompt and "（1）" in prompt
    assert "事项超过 3 条" in prompt
    assert "禁止提纲、片段、列表" not in prompt


def test_notification_template_has_concrete_outline():
    template = next(t for t in BUILTIN_TEMPLATES if t["name"] == "通知")
    assert "一、具体事项" in template["content_template"]
    assert "二、工作要求" in template["content_template"]


def test_every_builtin_template_gets_length_and_genre_rules():
    from app.application.writing.section_policy import brief_length_range

    svc = WritingTaskService.__new__(WritingTaskService)
    for template in BUILTIN_TEMPLATES:
        prompt = svc._build_draft_instruction(
            {"document_type": template["name"], "history": []}, False, template)
        # 显式选择的模板字数优先于文种兜底区间。
        expected = template["word_count"]
        assert f"正文目标约 {expected} 字" in prompt, template["name"]
        assert "按所选文种写作" in prompt, template["name"]
        assert "不输出空字段标签" in prompt, template["name"]


def test_user_length_overrides_template_default():
    svc = WritingTaskService.__new__(WritingTaskService)
    template = next(t for t in BUILTIN_TEMPLATES if t["name"] == "通知")
    prompt = svc._build_draft_instruction({"document_type": "通知",
        "word_count_target": 200, "history": []}, False, template)
    assert "正文目标约 200 字" in prompt
    assert f"正文目标约 {template['word_count']} 字" not in prompt


def test_template_default_length_reaches_section_planner_without_changing_task_context():
    svc = WritingTaskService.__new__(WritingTaskService)
    original = {"document_type": "讲话稿"}
    context = svc._effective_draft_context(original, {"word_count": 900})
    assert context["word_count_target"] == 900
    assert "word_count_target" not in original
    assert svc._effective_draft_context(
        {"word_count_target": 200}, {"word_count": 900})["word_count_target"] == 200


def test_section_generation_requires_subheadings_when_needed():
    prompt = SectionedGenerationWritingTaskService._section_instruction(
        {}, {"heading": "一、工作措施", "focus": "落实", "target_chars": 600}, [], [])
    assert "（一）" in prompt and "1．" in prompt
