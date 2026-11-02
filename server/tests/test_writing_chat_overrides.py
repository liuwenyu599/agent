"""写作助手对话的确定性字段兜底（修复两类故障）。

此前 chat_async 完全信赖 LLM 抽结构化字段，导致：
- 「200字以内」被 LLM 漏抽 → 草稿仍按旧目标（如 800 字）生成，字数毫无变化；
- 「写落款日期」被 LLM 幻觉成旧年份（如 2024 年）→ 落款日期错，且不补发文机关。

新增 _reconcile_literal_fields：用户明确说的字数 / 落款日期 / 发文机关等约束
确定性地落到 ctx，且规则优先于 LLM（覆盖漏抽与幻觉）。
"""
import asyncio
import pytest
from fastapi import HTTPException

from app.application.writing.async_task_service import _SIGN_DATE_RE, AsyncWritingTaskService
from app.application.writing import task_parser
from app.application.writing.postprocessor import local_date_string
from app.core.timeutil import now_local


def _svc():
    svc = AsyncWritingTaskService.__new__(AsyncWritingTaskService)
    svc.db = None  # _complete_default_authority 走 except 返回空串，不依赖真实库
    return svc


def test_word_count_override_from_message():
    svc = _svc()
    ctx = {"document_type": "通知", "word_count_target": 800, "authority": None,
           "document_date": None}
    changes = svc._reconcile_literal_fields(ctx, "200字以内", has_draft=True)
    assert ctx["word_count_target"] == 200
    assert ctx["word_count_max"] == 200
    assert any("字数目标" in c for c in changes)
    assert "不超过 200 字" in svc._length_revision_instruction(ctx)


def test_signoff_date_defaults_to_today():
    svc = _svc()
    ctx = {"document_type": "通知", "word_count_target": None, "authority": None,
           "document_date": None}
    changes = svc._reconcile_literal_fields(ctx, "写落款日期", has_draft=True)
    assert ctx["document_date"] == local_date_string()
    assert any("落款日期" in c for c in changes)
    # 今天不是 2024 年：杜绝旧年份幻觉
    assert "2024" not in ctx["document_date"]


def test_explicit_signoff_date_not_overridden_by_today():
    svc = _svc()
    ctx = {"document_type": "通知", "word_count_target": None, "authority": None,
           "document_date": None}
    changes = svc._reconcile_literal_fields(ctx, "落款日期是2026年10月10日", has_draft=True)
    assert ctx["document_date"] == "2026年10月10日"
    assert "2024" not in ctx["document_date"]


def test_neutral_message_produces_no_spurious_change():
    svc = _svc()
    ctx = {"document_type": "通知", "word_count_target": 800, "authority": None,
           "document_date": None}
    changes = svc._reconcile_literal_fields(ctx, "把第二部分写详细一点", has_draft=True)
    assert changes == []
    assert ctx["word_count_target"] == 800


def test_sign_date_regex_scope():
    assert _SIGN_DATE_RE.search("写落款日期")
    assert _SIGN_DATE_RE.search("补全落款日期")
    assert not _SIGN_DATE_RE.search("通知需要落款日期吗")
    assert not _SIGN_DATE_RE.search("这份通知的落款日期应该写在哪里")


def test_today_date_uses_current_year():
    assert str(now_local().year) in local_date_string()


def test_signoff_only_chat_uses_current_date_and_org_without_rewriting():
    from test_writing_local_operations import service_stub

    svc, task = service_stub()
    task.context = {"document_type": "通知", "authority": None}
    svc._default_authority = lambda: "测试司法局"

    async def interpret(*_args, **_kwargs):
        return {"operation": "rewrite_document", "field_updates": {},
                "reply": "已设为2024年5月20日"}

    svc._interpret_async = interpret
    result = asyncio.run(svc.chat_async("task", "user", "写落款日期"))
    assert task.context["document_date"] == local_date_string()
    assert task.context["authority"] == "测试司法局"
    assert "2024" not in result["reply"]
    svc._llm_revise.assert_not_called()


def test_over_limit_revision_never_saves_a_new_version():
    from test_writing_local_operations import service_stub

    svc, task = service_stub()
    task.context = {"document_type": "通知", "word_count_target": 200,
                    "word_count_max": 200}

    async def retrieve(*_args, **_kwargs):
        return []

    async def too_long(*_args, **_kwargs):
        return "正文" * 110

    svc._retrieve_async = retrieve
    svc._llm_revise_async = too_long
    with pytest.raises(HTTPException) as error:
        asyncio.run(svc.revise_async("task", "user", "200字以内", mode="rewrite"))
    assert error.value.status_code == 422
    assert task.version_no == 1
    assert task.current_content != "正文" * 110


def test_knowledge_import_detects_specific_genre_from_title_or_heading():
    from app.application.knowledge.document_service import DocumentService

    service = DocumentService()
    assert service._detect_doc_type("各单位：\n请准时参会。", "关于召开会议的通知") == "通知"
    assert service._detect_doc_type("各单位：\n请准时参会。", "关于召开会议的通知（定稿）.docx") == "通知"
    assert service._detect_doc_type("关于行政执法工作的通知\n请贯彻执行。", "关于行政执法工作的通知.docx") == "通知"
    assert service._detect_doc_type("关于申请经费的请示\n请批准。", "上传材料") == "请示"
    assert service._detect_doc_type("年度工作要点", "上传材料") == "公文"
