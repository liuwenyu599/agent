"""Every catalog genre must survive model-led planning without a template binding.

The model is scripted here so this suite checks orchestration, not 14B prose quality.
The two catalogs are finite; the extra arbitrary forms exercise the open-ended path.
"""

import asyncio

import pytest

from app.application.templates.builtin_data import BUILTIN_TEMPLATES
from app.application.writing.async_task_service import AsyncWritingTaskService
from app.application.writing.sectioned_generation_service import SectionedGenerationWritingTaskService
from app.application.writing import task_parser
from app.application.writing.agent_graph.routing import classify_writing_route


OFFICIAL_GENRES = (
    "决议", "决定", "命令", "公报", "公告", "通告", "意见", "通知", "通报",
    "报告", "请示", "批复", "议案", "函", "纪要",
)
OPEN_GENRES = ("倡议书", "公开信", "新闻评论", "情况说明", "读书分享稿")
ALL_GENRES = tuple(dict.fromkeys(
    [item["name"] for item in BUILTIN_TEMPLATES] +
    list(OFFICIAL_GENRES) + list(OPEN_GENRES)
))


@pytest.mark.parametrize("genre", ALL_GENRES)
def test_one_sentence_request_keeps_model_genre_and_skips_template(genre):
    service = AsyncWritingTaskService.__new__(AsyncWritingTaskService)
    service.db = None
    service.rag = None

    async def model_plan(*args, **kwargs):
        return {"document_type": genre, "topic": "社区法治宣传活动"}

    service._interpret_async = model_plan
    service._plan_knowledge = lambda *args, **kwargs: []
    plan = asyncio.run(service.plan_task_async("user-1", f"写一篇社区法治宣传活动{genre}"))

    assert plan["doc_type"] == genre
    assert plan["template_id"] == ""
    assert plan["planned_context"]["document_type"] == genre
    context = dict(plan["planned_context"])
    context["history"] = [{"role": "user", "content": f"写一篇社区法治宣传活动{genre}"}]
    instruction = service._build_draft_instruction(context, False)
    assert f"文种：{genre}" in instruction
    assert f"用户原始需求：写一篇社区法治宣传活动{genre}" in instruction
    assert not SectionedGenerationWritingTaskService._should_section(
        {"document_type": genre, "word_count_target": 2000}
    ) or SectionedGenerationWritingTaskService._fallback_plan(
        {"document_type": genre, "word_count_target": 2000}
    )
    # Agent admission is based on task complexity, never a closed genre enum.
    assert classify_writing_route(
        {"document_type": genre, "word_count_target": 1800},
        outline_only=False,
        has_attachments=False,
    ) == "agent"


@pytest.mark.parametrize("prompt,genre", [
    ("写一篇方案发布会新闻稿", "新闻稿"),
    ("写一篇报告解读活动致辞稿", "致辞稿"),
    ("写一篇方案执行情况调研报告", "调研报告"),
    ("写一篇社区法治宣传活动方案", "活动方案"),
])
def test_topic_keyword_does_not_override_requested_genre(prompt, genre):
    service = AsyncWritingTaskService.__new__(AsyncWritingTaskService)
    service.db = None
    service.rag = None

    async def model_plan(*args, **kwargs):
        return {"document_type": genre, "topic": "社区法治宣传"}

    service._interpret_async = model_plan
    service._plan_knowledge = lambda *args, **kwargs: []
    plan = asyncio.run(service.plan_task_async("user-1", prompt))
    assert plan["doc_type"] == genre


@pytest.mark.parametrize("prompt,model_type,expected", [
    ("写个调研报告", "报告", "调研报告"),
    ("写个活动方案", "方案", "活动方案"),
    ("写个发言稿2000字", "讲话稿", "发言稿"),
    ("写个方案发布会新闻稿", "新闻稿", "新闻稿"),
    ("写个法治宣传读书分享稿", "读书分享稿", "读书分享稿"),
])
def test_precise_user_genre_wins_in_production_planner(prompt, model_type, expected):
    service = AsyncWritingTaskService.__new__(AsyncWritingTaskService)
    service.db = None
    service.rag = None

    async def model_plan(*args, **kwargs):
        return {"document_type": model_type, "topic": "法治宣传"}

    service._interpret_async = model_plan
    service._plan_knowledge = lambda *args, **kwargs: []
    plan = asyncio.run(service.plan_task_async("user-1", prompt))
    assert plan["doc_type"] == expected
    assert plan["planned_context"]["document_type"] == expected


def test_builtin_names_are_in_lexical_fallback_without_restricting_model_genres():
    for item in BUILTIN_TEMPLATES:
        genre = item["name"]
        assert task_parser.explicit_document_type(f"写一篇{genre}") == genre
    assert task_parser.resolved_document_type("写一篇新闻评论", "新闻评论") == "新闻评论"
