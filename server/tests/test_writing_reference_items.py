"""写作依据带可鉴权打开的文档 ID，并保留旧客户端标题列表。"""
from types import SimpleNamespace

from app.application.writing.task_service import WritingTaskService
from app.application.writing.finalize_pipeline import append_matched_attachments


def test_reference_items_keep_doc_id_and_deduplicate_chunks():
    sources = [
        {"source": "司法行政工作方案（第1段）", "doc_id": "doc-1",
         "chunk_content": "上半年全区法律援助服务进一步完善。后续工作。"},
        {"source": "司法行政工作方案（第2段）", "doc_id": "doc-1"},
        {"source": "工作规范（第3段）", "doc_id": "doc-2"},
    ]
    labels = WritingTaskService._reference_labels(sources)
    items = WritingTaskService._reference_items(sources)
    assert [item["title"] for item in items] == labels
    assert [item["doc_id"] for item in items] == ["doc-1", "doc-2"]
    assert items[0]["match_text"] == "上半年全区法律援助服务进一步完善"
    task = SimpleNamespace(
        id="task-1", session_id=None, document_id=None,
        context={"references": labels, "reference_items": items},
        current_content="正文", version_no=1, status="editing",
        created_at=None, updated_at=None,
    )
    assert WritingTaskService._to_dict(task)["reference_items"] == items


def test_uploaded_reference_needs_exact_substantive_match():
    sentence = "上半年共受理法律援助案件一百二十件"
    uploaded = [
        SimpleNamespace(id="a", filename="统计表.docx", text_content=sentence + "。其他数据。"),
        SimpleNamespace(id="b", filename="未引用.docx", text_content="未进入正文的另一项统计数据。"),
    ]
    items, labels = [], []
    append_matched_attachments(items, labels, uploaded, "工作总结：" + sentence + "。")
    assert items == [{"title": "统计表.docx", "attachment_id": "a",
                      "match_text": sentence, "source_kind": "attachment"}]
    assert labels == ["上传材料：统计表.docx"]
