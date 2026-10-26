"""写作依据带可鉴权打开的文档 ID，并保留旧客户端标题列表。"""
from types import SimpleNamespace

from app.application.writing.task_service import WritingTaskService


def test_reference_items_keep_doc_id_and_deduplicate_chunks():
    sources = [
        {"source": "司法行政工作方案（第1段）", "doc_id": "doc-1"},
        {"source": "司法行政工作方案（第2段）", "doc_id": "doc-1"},
        {"source": "工作规范（第3段）", "doc_id": "doc-2"},
    ]
    labels = WritingTaskService._reference_labels(sources)
    items = WritingTaskService._reference_items(sources)
    assert [item["title"] for item in items] == labels
    assert [item["doc_id"] for item in items] == ["doc-1", "doc-2"]
    task = SimpleNamespace(
        id="task-1", session_id=None, document_id=None,
        context={"references": labels, "reference_items": items},
        current_content="正文", version_no=1, status="editing",
        created_at=None, updated_at=None,
    )
    assert WritingTaskService._to_dict(task)["reference_items"] == items
