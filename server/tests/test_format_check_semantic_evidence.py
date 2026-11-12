"""Semantic findings must be grounded in visible document and law text."""

from types import SimpleNamespace

from app.application.format_check.check_engine import FormatCheckEngine
from app.application.format_check.service import FormatCheckService


class Assistant:
    def __init__(self, reply):
        self.reply = reply
        self.calls = 0

    def complete(self, *args, **kwargs):
        self.calls += 1
        return self.reply


class Rag:
    def __init__(self, authoritative):
        self.authoritative = authoritative

    def search(self, **kwargs):
        return [{
            "authoritative": self.authoritative, "doc_type": "法规",
            "doc_title": "中华人民共和国示例法", "doc_id": "law-1",
            "chunk_id": "article-1", "chunk_index": 1,
            "chunk_content": "第一条 国家依法保护合法权益。",
        }]


def _service(reply, authoritative):
    service = FormatCheckService.__new__(FormatCheckService)
    service.engine = FormatCheckEngine(Assistant(reply))
    service.rag = Rag(authoritative)
    return service


def test_law_conflict_requires_authoritative_article_and_verbatim_spans():
    text = "根据《中华人民共和国示例法》第一条，国家不保护合法权益。"
    reply = ('[{"evidence_index":1,"current":"国家不保护合法权益",'
             '"expected":"国家依法保护合法权益","reason":"引文与原文不符"}]')
    user = SimpleNamespace(id="u-1")
    untrusted = _service(reply, False)
    assert untrusted._law_citation_issues(text, user) == []
    assert untrusted.engine.assistant.calls == 0
    trusted = _service(reply, True)
    issues = trusted._law_citation_issues(text, user)
    assert len(issues) == 1
    assert issues[0]["source"] == "law"
    assert issues[0]["evidence"]["doc_id"] == "law-1"


def test_law_model_cannot_invent_expected_or_current_text():
    text = "根据《中华人民共和国示例法》第一条，国家不保护合法权益。"
    reply = ('[{"evidence_index":1,"current":"不存在的正文",'
             '"expected":"不存在的法条","reason":"错误"}]')
    assert _service(reply, True)._law_citation_issues(text, SimpleNamespace(id="u")) == []


def test_grammar_model_cannot_report_unlocatable_sentence():
    assistant = Assistant('[{"current":"虚构的病句","element":"语病"}]')
    issues = FormatCheckEngine(assistant)._ai_check("这是实际正文。", [])
    assert issues == []


def test_grammar_finding_uses_real_paragraph_number_not_model_guess():
    assistant = Assistant('[{"current":"第二段有明显语病",'
                          '"paragraph_index":0,"element":"语病"}]')
    issues = FormatCheckEngine(assistant)._ai_check(
        "第一段正常。\n第二段有明显语病。", [],
        numbered_text="[第1段] 第一段正常。\n[第4段] 第二段有明显语病。")
    assert issues[0]["paragraph_index"] == 3
    assert issues[0]["location"] == "第4段"
