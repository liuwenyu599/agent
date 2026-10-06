from types import SimpleNamespace

from app.application.ppt.dto import DraftIn
from app.application.ppt.service import PPTService


def test_explicit_auto_selection_clears_previous_template():
    service = object.__new__(PPTService)
    doc = SimpleNamespace(
        template_id="previous-template", status="generated", outline={},
        title="标题", subtitle="", updated_at=None,
    )
    service._get_doc_checked = lambda *_: doc
    service.documents = SimpleNamespace(update=lambda d: d)
    service.templates = SimpleNamespace(get=lambda _: None)

    service.save_draft("doc", DraftIn(template_id=None), SimpleNamespace(id="user"))
    assert doc.template_id is None
    assert doc.status == "draft"


def test_omitted_template_preserves_previous_choice():
    service = object.__new__(PPTService)
    doc = SimpleNamespace(
        template_id="previous-template", status="generated", outline={},
        title="标题", subtitle="", updated_at=None,
    )
    service._get_doc_checked = lambda *_: doc
    service.documents = SimpleNamespace(update=lambda d: d)
    service.templates = SimpleNamespace(get=lambda _: None)

    service.save_draft("doc", DraftIn(), SimpleNamespace(id="user"))
    assert doc.template_id == "previous-template"
    assert doc.status == "generated"
