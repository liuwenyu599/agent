"""Same-genre writing length is derived only from accessible published exemplars."""
from app.application.knowledge.rag_service import RagService
from app.infrastructure.database.session import SessionLocal
from app.infrastructure.database.models.knowledge import DocumentModel, KnowledgeBaseModel


def test_exemplar_length_uses_selected_scope_and_exact_genre():
    with SessionLocal() as db:
        db.add_all([
            KnowledgeBaseModel(id="selected", name="本次知识库", kb_type="public"),
            KnowledgeBaseModel(id="other", name="其他知识库", kb_type="public"),
        ])
        db.flush()
        db.add_all([
            DocumentModel(id="notice1", kb_id="selected", title="关于甲的通知",
                          doc_type="通知", status="published", content="甲" * 500),
            DocumentModel(id="notice2", kb_id="selected", title="关于乙的通知",
                          doc_type="通知", status="published", content="乙" * 600),
            DocumentModel(id="draft", kb_id="selected", title="关于丙的通知",
                          doc_type="通知", status="pending", content="丙" * 5000),
            DocumentModel(id="scheme", kb_id="selected", title="工作方案",
                          doc_type="方案", status="published", content="丁" * 4000),
            DocumentModel(id="outside", kb_id="other", title="关于丁的通知",
                          doc_type="通知", status="published", content="戊" * 6000),
            DocumentModel(id="other-dept", kb_id="selected", title="关于戊的通知",
                          doc_type="通知", department_code="other-dept",
                          status="published", content="己" * 7000),
        ])
        db.flush()
        rag = RagService.__new__(RagService)
        rag.db = db
        rag._dept_code_of = lambda _user: ""
        rag._is_admin = lambda _user: False
        rag._get_accessible_kb_ids = lambda *_args: ["selected", "other"]
        assert rag.exemplar_length_range("user", "通知", ["selected"]) == (440, 660)
        assert rag.exemplar_length_range("user", "请示", ["selected"]) is None
