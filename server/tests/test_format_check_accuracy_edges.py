"""DOCX structures that previously produced false positives or omissions."""

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt

from app.application.format_check.check_engine import FormatCheckEngine


def _check(tmp_path, doc, rules):
    path = tmp_path / "sample.docx"
    doc.save(path)
    return FormatCheckEngine().check_file(path, path.name, rules, use_ai=False)


def test_second_section_margin_is_reported_and_fixed_without_changing_first(tmp_path):
    doc = Document()
    doc.add_paragraph("标题")
    doc.sections[0].top_margin = Cm(3.7)
    second = doc.add_section()
    second.top_margin = Cm(4.0)
    rule = {"target": "page", "checks": {"top_margin_cm": 3.7}}
    result = _check(tmp_path, doc, [rule])
    issues = result["issues"]
    assert len(issues) == 1
    assert issues[0]["location"] == "第2节页面设置"
    assert issues[0]["fix_hint"]["section_index"] == 1
    source = tmp_path / "sample.docx"
    fixed = tmp_path / "fixed.docx"
    FormatCheckEngine().apply_fixes(source, issues, out_path=fixed)
    output = Document(fixed)
    assert abs(output.sections[0].top_margin.cm - 3.7) < 0.01
    assert abs(output.sections[1].top_margin.cm - 3.7) < 0.01


def test_margin_accepts_one_millimetre_tolerance(tmp_path):
    doc = Document()
    doc.sections[0].top_margin = Cm(3.76)
    result = _check(tmp_path, doc, [{"target": "page", "checks": {"top_margin_cm": 3.7}}])
    assert not result["issues"]


def test_inherited_character_indent_is_respected(tmp_path):
    doc = Document()
    style = doc.styles["Normal"]
    style.font.size = Pt(16)
    ppr = style._element.get_or_add_pPr()
    ind = OxmlElement("w:ind")
    ind.set(qn("w:firstLineChars"), "200")
    ppr.append(ind)
    doc.add_paragraph("标题")
    doc.add_paragraph("这是正文内容。")
    result = _check(tmp_path, doc, [{
        "target": "body", "checks": {"first_line_indent_chars": 2},
    }])
    assert not any(i["element"] == "首行缩进" for i in result["issues"])


def test_table_text_is_checked_with_cell_location_and_no_wrong_fix(tmp_path):
    doc = Document()
    doc.add_paragraph("标题")
    cell = doc.add_table(rows=1, cols=1).cell(0, 0)
    run = cell.paragraphs[0].add_run("表内正文")
    run.font.size = Pt(8)
    result = _check(tmp_path, doc, [{"target": "body", "checks": {"font_size_pt": 16}}])
    issue = next(i for i in result["issues"] if i["element"] == "字号")
    assert issue["location"] == "表1第1行第1列"
    assert issue["paragraph_index"] is None
    assert issue["fix_hint"] is None


def test_numbered_first_paragraph_is_heading_not_title(tmp_path):
    doc = Document()
    doc.add_paragraph("一、工作情况")
    result = _check(tmp_path, doc, [
        {"target": "title", "checks": {"font_size_pt": 22}},
        {"target": "heading1", "checks": {"font_size_pt": 16}},
    ])
    assert any("一级标题" in i["location"] for i in result["issues"])
    assert not any("（标题）" in i["location"] for i in result["issues"])
