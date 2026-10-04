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


def test_section_generation_requires_subheadings_when_needed():
    prompt = SectionedGenerationWritingTaskService._section_instruction(
        {}, {"heading": "一、工作措施", "focus": "落实", "target_chars": 600}, [], [])
    assert "（一）" in prompt and "1．" in prompt
