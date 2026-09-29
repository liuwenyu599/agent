"""公文文种、文号与落款日期的交付前回归测试。"""

from app.application.writing.postprocessor import (
    TODAY_STR,
    PostProcessor,
    derive_daizi,
)
from app.application.writing.task_service import WritingTaskService


def test_rule_of_law_office_uses_correct_document_number_prefix():
    authority = "中共广州市白云区委全面依法治区委员会办公室"
    assert derive_daizi(authority) == "云法治办发"


def test_draft_instruction_keeps_document_type_and_content_boundary():
    svc = WritingTaskService.__new__(WritingTaskService)
    instruction = svc._build_draft_instruction({
        "document_type": "通知",
        "title": "关于报送有关材料的通知",
        "topic": "报送有关材料",
        "recipient": "各镇街、各部门",
        "authority": "中共广州市白云区委全面依法治区委员会办公室",
        "requirements": "只写报告内容、报送要求、工作要求",
    }, outline_only=False)

    assert "文种：通知" in instruction
    assert "不得把通知写成工作要点" in instruction
    assert "不得把一次报送通知扩写成全年工作部署" in instruction
    assert "文号与成文日期由系统程序处理" in instruction


def test_postprocessor_injects_real_current_signoff_date():
    text = (
        "关于报送有关材料的通知\n\n"
        "请按要求报送有关材料。\n\n"
        "中共广州市白云区委全面依法治区委员会办公室"
    )
    out, _events, _number, out_date = PostProcessor().process(
        text,
        signoff_hint="中共广州市白云区委全面依法治区委员会办公室",
        inject_docnum=False,
        inject_date=True,
    )
    assert TODAY_STR in out
    assert out_date == TODAY_STR
    assert "2026年X月X日" not in out
