"""公文文种、文号、排版与写作台性能关键路径回归测试。"""

from io import BytesIO

from docx import Document
from docx.shared import Pt

from app.application.chat.docx_export import (
    FONT_BODY,
    FONT_H1,
    FONT_H2,
    FONT_TITLE,
    generate_official_document,
    markdown_to_docx,
)
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
    assert "不得把通知写成工作要点" in instruction
    assert "把报送事项扩写成全年工作部署" in instruction
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


class _FakeDb:
    def add(self, _obj):
        pass

    def commit(self):
        pass

    def refresh(self, _obj):
        pass


class _BoomInterpreter:
    def interpret(self, *args, **kwargs):
        raise AssertionError("planned_context 路径不应再次调用 LLM")


def test_planned_context_skips_second_llm_interpretation():
    svc = WritingTaskService(_FakeDb())
    svc.interpreter = _BoomInterpreter()

    result = svc.create_task(
        "u1",
        "请起草一份关于报送材料的通知",
        planned_context={
            "document_type": "通知",
            "title": "关于报送有关材料的通知",
            "topic": "报送有关材料",
            "recipient": "各镇街、各部门",
            "authority": "中共广州市白云区委全面依法治区委员会办公室",
        },
    )

    ctx = result["task_context"]
    assert ctx["document_type"] == "通知"
    assert ctx["title"] == "关于报送有关材料的通知"
    assert ctx["recipient"] == "各镇街、各部门"


def test_docx_export_recognizes_plain_text_official_headings_and_indent():
    buf = markdown_to_docx(
        "一、总体要求\n"
        "这是普通正文第一段，用于检查正文格式。\n"
        "（一）明确工作安排\n"
        "这是普通正文第二段。",
        title="测试通知",
    )
    doc = Document(BytesIO(buf.getvalue()))
    h1 = next(p for p in doc.paragraphs if p.text == "一、总体要求")
    body = next(p for p in doc.paragraphs if p.text == "这是普通正文第一段，用于检查正文格式。")
    h2 = next(p for p in doc.paragraphs if p.text == "（一）明确工作安排")

    assert h1.runs[0].font.name == FONT_H1
    assert h1.runs[0].font.size == Pt(16)
    assert h2.runs[0].font.name == FONT_H2
    assert h2.runs[0].font.size == Pt(16)
    assert body.runs[0].font.name == FONT_BODY
    assert body.runs[0].font.size == Pt(16)
    assert body.paragraph_format.first_line_indent == Pt(32)
    assert body.paragraph_format.line_spacing == Pt(28)


def test_body_structure_strips_duplicate_title_and_recipient():
    ctx = {
        "document_type": "通知",
        "title": "关于报送有关材料的通知",
        "recipient": "各镇街、各部门",
    }
    raw = (
        "关于报送有关材料的通知\n\n"
        "各镇街、各部门：\n\n"
        "现就有关事项通知如下。"
    )
    assert WritingTaskService._strip_leading_structural_fields(raw, ctx) == (
        "现就有关事项通知如下。"
    )


def test_clear_plan_uses_rule_fast_without_llm_or_material_search():
    svc = WritingTaskService.__new__(WritingTaskService)
    svc.db = None
    svc.rag = None
    svc._interpret = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("明确文种+主题不应调用 LLM 规划"))
    svc._plan_materials = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("未要求参考材料时不应同步做材料向量检索"))
    svc._plan_knowledge = lambda *args, **kwargs: []
    svc._plan_template = lambda *args, **kwargs: {}

    result = svc.plan_task("u1", "请起草一份关于社区矫正工作的通知")

    assert result["source"] == "rule_fast"
    assert result["doc_type"] == "通知"
    assert "社区矫正" in result["title"]
    assert result["materials"] == []


def test_official_export_keeps_red_header_separate_from_document_title():
    authority = "中共广州市白云区委全面依法治区委员会办公室"
    title = "关于报送有关材料的通知"
    buf = generate_official_document(
        content="现就有关事项通知如下。",
        title=title,
        doc_number="",
        recipient="各镇街、各部门：",
        signature=authority,
        date_text=TODAY_STR,
    )
    doc = Document(BytesIO(buf.getvalue()))
    texts = [p.text for p in doc.paragraphs if p.text.strip()]

    assert texts[0] == authority + "文件"
    assert title in texts
    assert texts.index(title) > texts.index(authority + "文件")
    assert not any("××司发" in t or "XX" in t or "××" in t for t in texts)
    title_p = next(p for p in doc.paragraphs if p.text == title)
    assert title_p.runs[0].font.name == FONT_TITLE
    assert title_p.runs[0].font.size == Pt(22)
    assert title_p.runs[0].bold is not True
    assert all(not p.text.strip() for s in doc.sections for p in s.header.paragraphs)
