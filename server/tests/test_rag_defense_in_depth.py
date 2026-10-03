"""Defense-in-depth checks for vector retrieval authorization."""
from types import SimpleNamespace

from app.application.knowledge.rag_service import RagService


def _doc(kb_id="kb-a", status="published"):
    return SimpleNamespace(kb_id=kb_id, status=status)


def test_vector_hit_document_must_still_belong_to_accessible_kb():
    assert RagService._document_is_accessible(_doc("kb-a"), ["kb-a", "kb-public"])
    assert not RagService._document_is_accessible(_doc("kb-b"), ["kb-a", "kb-public"])


def test_unpublished_or_missing_document_is_rejected_after_vector_hit():
    assert not RagService._document_is_accessible(_doc("kb-a", "pending"), ["kb-a"])
    assert not RagService._document_is_accessible(_doc("kb-a", "archived"), ["kb-a"])
    assert not RagService._document_is_accessible(None, ["kb-a"])
