"""格式覆盖层必须随版本保存，并在 Word 中体现。"""
from io import BytesIO
import asyncio
from types import SimpleNamespace

import pytest
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.application.chat.docx_export import markdown_to_docx
from app.application.documents.dto import DocumentCreateRequest, DocumentSaveRequest
from app.application.documents.service import DocumentService
from app.application.documents.formatting import (
    effective_formatting, format_warnings, normalize_formatting, remap_formatting,
)
from app.infrastructure.database.base import Base
from app.infrastructure.database.models.document import MyDocumentModel, MyDocumentVersionModel
from app.infrastructure.database.models.format_check import FormatRuleModel
from app.infrastructure.database.models.writing_task import WritingTaskModel
from app.application.writing.task_service import WritingTaskService


def test_user_style_survives_normalization_and_export():
    content = "第一段\n第二段"
    stored = normalize_formatting(content, {
        "title": {"font_name": "思源黑体", "font_size_pt": 20, "alignment": "center"},
        "paragraphs": {"1": {"font_name": "宋体", "font_size_pt": 18,
                             "bold": True, "alignment": "right"}},
    })
    style = effective_formatting(content, stored)
    document = Document(BytesIO(markdown_to_docx(
        content, title="测试标题", formatting=style).getvalue()))
    title = next(p for p in document.paragraphs if p.text == "测试标题")
    body = next(p for p in document.paragraphs if p.text == "第二段")
    assert title.runs[0].font.size.pt == 20
    assert title.runs[0]._element.rPr.rFonts.get(qn("w:eastAsia")) == "思源黑体"
    assert body.runs[0].font.size.pt == 18
    assert body.runs[0].bold is True
    assert body.alignment == WD_ALIGN_PARAGRAPH.RIGHT


def test_style_does_not_apply_to_a_different_body_or_shifted_line():
    content = "甲\n乙"
    stored = normalize_formatting(content, {"paragraphs": {"1": {"bold": True}}})
    assert effective_formatting("甲\n丙", stored)["paragraphs"] == {}
    remapped = remap_formatting(content, "乙", effective_formatting(content, stored))
    assert remapped["paragraphs"]["0"]["bold"] is True


def test_official_format_warns_but_speech_allows_custom_style():
    content = "正文"
    stored = normalize_formatting(content, {"paragraphs": {"0": {"font_name": "Arial"}}})
    assert format_warnings(content, stored, "通知")
    assert format_warnings(content, stored, "致辞稿") == []


def test_rejects_untrusted_font_and_alignment():
    with pytest.raises(Exception):
        normalize_formatting("正文", {"paragraphs": {"0": {"font_name": "未知字体"}}})
    with pytest.raises(Exception):
        normalize_formatting("正文", {"paragraphs": {"0": {"alignment": "invalid"}}})


def test_formatting_is_snapshotted_with_each_document_version():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[MyDocumentModel.__table__,
                                          MyDocumentVersionModel.__table__,
                                          WritingTaskModel.__table__])
    with Session(engine) as db:
        service = DocumentService(db)
        doc = service.create_document("user-1", DocumentCreateRequest(
            title="测试", content="第一版", formatting={
                "paragraphs": {"0": {"bold": True}}}))
        doc_id = doc["id"]
        service.save_version(doc_id, "user-1", DocumentSaveRequest(
            content="第二版", formatting={"paragraphs": {"0": {"font_name": "宋体"}}}))
        old = service.get_version(doc_id, 1, "user-1")
        new = service.get_version(doc_id, 2, "user-1")
        assert effective_formatting(old["content"], old["formatting"])["paragraphs"]["0"]["bold"]
        assert effective_formatting(new["content"], new["formatting"])["paragraphs"]["0"]["font_name"] == "宋体"
    engine.dispose()


def test_writing_task_restore_and_export_use_selected_version_style():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[MyDocumentModel.__table__,
                                          MyDocumentVersionModel.__table__,
                                          WritingTaskModel.__table__])
    with Session(engine) as db:
        task = WritingTaskModel(user_id="user-1", context={
            "title": "测试通知", "document_type": "通知"}, current_content="第一版")
        db.add(task)
        db.commit()
        service = WritingTaskService(db)
        first = service.save_version(task.id, "user-1", "第一版", formatting={
            "paragraphs": {"0": {"bold": True}}})
        assert first["formatting"]["paragraphs"]["0"]["bold"] is True
        service.save_version(task.id, "user-1", "第二版", formatting={
            "paragraphs": {"0": {"font_name": "宋体"}}})
        previous = service.get_version(task.id, "user-1", 1)
        assert previous["formatting"] is not None
        restored = service.restore_version(task.id, "user-1", 1)
        assert restored["formatting"]["paragraphs"]["0"]["bold"] is True
        buffer, _filename = service.export_docx(task.id, "user-1", red_header=False)
        document = Document(BytesIO(buffer.getvalue()))
        paragraph = next(p for p in document.paragraphs if p.text == "第一版")
        assert paragraph.runs[0].bold is True
    engine.dispose()


def test_writing_workbench_rechecks_saved_word_with_user_rules():
    import app.infrastructure.database.models  # register all tables for per-user rules

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        task = WritingTaskModel(user_id="user-1", context={
            "title": "测试通知", "document_type": "通知"}, current_content="正文")
        db.add(task)
        db.commit()
        service = WritingTaskService(db)
        service.save_version(task.id, "user-1", "正文", formatting={
            "paragraphs": {"0": {"font_name": "Arial"}}})
        checked = service.check_current_format(task.id, "user-1")
        assert any(issue["element"] == "字体" and issue["current"] == "Arial"
                   for issue in checked["issues"])
        for rule in db.query(FormatRuleModel).filter_by(
                created_by="user-1", target="body").all():
            rule.is_active = False
        db.commit()
        assert not any(issue["element"] == "字体" for issue in
                       service.check_current_format(task.id, "user-1")["issues"])
    engine.dispose()


def test_my_documents_export_preserves_linked_writing_task_signature():
    from app.interfaces.documents import export_document_docx

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[MyDocumentModel.__table__,
                                          MyDocumentVersionModel.__table__,
                                          WritingTaskModel.__table__])
    with Session(engine) as db:
        task = WritingTaskModel(user_id="user-1", context={
            "title": "测试通知", "document_type": "通知",
            "authority": "白云区司法局", "document_date": "2026年10月24日"},
            current_content="正文")
        db.add(task)
        db.commit()
        writing = WritingTaskService(db)
        writing.save_version(task.id, "user-1", "正文")
        response = export_document_docx(
            task.document_id, user=SimpleNamespace(id="user-1"),
            svc=DocumentService(db))

        async def read_response():
            return b"".join([chunk async for chunk in response.body_iterator])

        exported = Document(BytesIO(asyncio.run(read_response())))
        text = "\n".join(p.text for p in exported.paragraphs)
        assert "白云区司法局" in text
        assert "2026年10月24日" in text
    engine.dispose()

