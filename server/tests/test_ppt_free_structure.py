"""Free PPT creation keeps the model's page roles instead of inserting a fixed skeleton."""

import json
from types import SimpleNamespace

from app.application.ppt import ppt_engine
from app.application.ppt.dto import DraftIn
from app.application.ppt.service import PPTService


def test_free_outline_keeps_content_first_and_summary_last():
    outline = {"title": "专题分析", "slides": [
        {"type": "content", "title": "核心结论", "points": ["发现一"]},
        {"type": "process", "title": "办理流程", "blocks": {"process": ["受理", "办理"]}},
        {"type": "summary", "title": "下一步", "points": ["安排一"]},
    ]}
    result = ppt_engine.normalize_outline(outline, require_bookends=False)
    assert [slide["type"] for slide in result["slides"]] == [
        "content", "process", "summary"]
    clean = PPTService.sanitize_outline(result, ensure_toc=False,
                                        enforce_bookends=False)
    assert [slide["type"] for slide in clean["slides"]] == [
        "content", "process", "summary"]


def test_free_outline_does_not_insert_directory_for_long_deck():
    outline = {"title": "业务分析", "slides": [
        {"type": "content", "title": f"主题{i}", "points": [f"事项{i}"]}
        for i in range(8)
    ]}
    clean = PPTService.sanitize_outline(outline, target_count=8,
                                        ensure_toc=False, enforce_bookends=False)
    assert len(clean["slides"]) == 8
    assert all(slide["type"] == "content" for slide in clean["slides"])


def test_legacy_normalization_still_supports_old_documents():
    outline = {"title": "旧稿", "slides": [
        {"type": "content", "title": "正文", "points": ["要点"]}]}
    result = ppt_engine.normalize_outline(outline)
    assert result["slides"][0]["type"] == "cover"
    assert result["slides"][-1]["type"] == "closing"


def test_model_can_choose_opening_and_page_count_when_user_did_not_specify():
    calls = []

    class FakeAssistant:
        def complete(self, messages, **kwargs):
            calls.append(messages[-1]["content"])
            return json.dumps({"title": "专题分析", "slides": [
                {"type": "content", "title": "结论先行", "points": ["主要发现"]},
                {"type": "summary", "title": "行动建议", "points": ["建议一"]},
            ]}, ensure_ascii=False)

    result = ppt_engine.generate_outline(
        FakeAssistant(), "topic", "专题分析", "", [], slide_count=6,
        enforce_exact_count=False, free_structure=True)
    assert [item["type"] for item in result["slides"]] == ["content", "summary"]
    assert "封面（由你判断是否需要" in calls[0]
    assert "建议约 6 页" in calls[0]


def test_free_outline_never_pads_explicit_count_with_placeholder():
    class FakeAssistant:
        def complete(self, messages, **kwargs):
            return json.dumps({"title": "专题", "slides": [
                {"type": "content", "title": "结论", "points": ["依据材料"]},
                {"type": "summary", "title": "安排", "points": ["安排一"]},
            ]}, ensure_ascii=False)

    result = ppt_engine.generate_outline(
        FakeAssistant(), "topic", "专题", "", [], slide_count=6,
        enforce_exact_count=True, free_structure=True)
    assert len(result["slides"]) == 2
    assert all(slide["title"] != "补充内容" for slide in result["slides"])


def test_switching_from_template_to_auto_keeps_free_structure():
    document = SimpleNamespace(
        template_id="old-template", outline={}, title="旧稿", subtitle="",
        status="draft", updated_at=None)
    service = PPTService.__new__(PPTService)
    service._get_doc_checked = lambda _id, _user: document
    service.documents = SimpleNamespace(update=lambda doc: doc)

    service.save_draft("doc-1", DraftIn(
        title="专题分析", template_id=None,
        outline={"title": "专题分析", "slides": [
            {"type": "content", "title": "主要发现", "points": ["依据材料"]},
        ]}), SimpleNamespace(id="user-1"))

    assert document.template_id is None
    assert [slide["type"] for slide in document.outline["slides"]] == ["content"]
