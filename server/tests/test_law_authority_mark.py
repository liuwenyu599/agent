"""Only an attested published public law may become legal evidence."""

from types import SimpleNamespace

import pytest

from app.application.knowledge.dto import LawAuthorityRequest
from app.core.exceptions import AppError
from app.interfaces.knowledge import mark_law_authority


def test_law_authority_requires_public_published_law_and_source():
    doc = SimpleNamespace(doc_type="法规", status="published",
                          knowledge_base=SimpleNamespace(kb_type="public"),
                          doc_metadata={})
    svc = SimpleNamespace(docs=SimpleNamespace(get_model=lambda _id: doc))
    db = SimpleNamespace(commits=0, commit=lambda: None)
    with pytest.raises(AppError):
        mark_law_authority("law-1", LawAuthorityRequest(authoritative=True),
                           user=SimpleNamespace(id="admin"), db=db, svc=svc)
    result = mark_law_authority(
        "law-1", LawAuthorityRequest(authoritative=True,
                                     source_reference="全国人大常委会正式公布文本"),
        user=SimpleNamespace(id="admin"), db=db, svc=svc)
    assert result["authoritative"] is True
    assert doc.doc_metadata["authoritative"] is True
    doc.status = "pending"
    with pytest.raises(AppError):
        mark_law_authority("law-1", LawAuthorityRequest(authoritative=True,
                                                        source_reference="正式文本"),
                           user=SimpleNamespace(id="admin"), db=db, svc=svc)
