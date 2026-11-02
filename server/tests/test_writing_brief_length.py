"""事务性公文（通知/请示/批复…）在用户不指定字数时的篇幅收敛。

线上问题：用户只说「写个通知」，ctx 里没有 word_count_target，prompt 里就
没有任何篇幅锚点，35B 按训练语料里的长篇模板铺成 1000+ 字的年度方案。
这里锁定三件事：
1) 未指定字数 → 按文种惯例区间给出锚点；
2) 用户显式给的字数永远优先，不被惯例区间夹紧；
3) 模板自带的示例篇幅不能反过来把短公文撑长。
"""
import asyncio

from app.application.writing.async_task_service import AsyncWritingTaskService
from app.application.writing.quality_gate import QualityGate
from app.application.writing.section_policy import brief_length_range
from app.application.writing.task_service import WritingTaskService


def _service() -> WritingTaskService:
    return WritingTaskService.__new__(WritingTaskService)


def test_notice_without_word_count_gets_genre_length_anchor():
    prompt = _service()._build_draft_instruction(
        {"document_type": "通知", "history": []}, False)
    assert "500-600 字" in prompt
    assert "一事一文" in prompt
    assert "不展开年度任务部署" in prompt


def test_explicit_word_count_wins_over_genre_anchor():
    prompt = _service()._build_draft_instruction(
        {"document_type": "通知", "word_count_target": 1200, "history": []}, False)
    assert "正文目标约 1200 字" in prompt
    assert "500-600 字" not in prompt


def test_selected_template_length_precedes_genre_fallback():
    """An explicitly selected template is a stronger source than generic genre defaults."""
    svc = _service()
    prompt = svc._build_draft_instruction(
        {"document_type": "通知", "history": []}, False,
        {"name": "通知", "word_count": 800})
    assert "正文目标约 800 字" in prompt

    original = {"document_type": "通知"}
    context = svc._effective_draft_context(original, {"word_count": 800})
    assert context["word_count_target"] == 800
    # 不污染调用方上下文（任务里保存的仍是"用户没指定字数"）
    assert "word_count_target" not in original


def test_user_target_still_overrides_template_after_clamp():
    svc = _service()
    context = svc._effective_draft_context(
        {"document_type": "通知", "word_count_target": 3000}, {"word_count": 800})
    assert context["word_count_target"] == 3000


def test_same_type_kb_length_precedes_template_and_user_precedes_both():
    svc = _service()
    class Rag:
        def __init__(self):
            self.calls = []
        def exemplar_length_range(self, user_id, kind, kb_ids):
            self.calls.append((user_id, kind, kb_ids))
            return (480, 720)
    svc.rag = Rag()
    base = {"document_type": "通知", "kb_ids": ["selected"]}
    effective = svc._effective_draft_context(base, {"word_count": 800}, "u1")
    assert effective["word_count_target"] == 600
    assert effective["reference_length_range"] == [480, 720]
    assert "480-720 字" in svc._build_draft_instruction(effective, False)
    assert svc.rag.calls == [("u1", "通知", ["selected"])]
    assert "word_count_target" not in base
    assert svc._effective_draft_context({**base, "word_count_target": 200},
                                        {"word_count": 800}, "u1")["word_count_target"] == 200
    inferred = {**base, "word_count_target": 1200, "word_count_source": "model"}
    assert svc._effective_draft_context(inferred, {"word_count": 800}, "u1")["word_count_target"] == 600
    svc.rag = None
    fallback = svc._effective_draft_context(inferred, None, "u1")
    assert not fallback.get("word_count_target")
    assert "500-600 字" in svc._build_draft_instruction(fallback, False)


def test_long_form_genre_keeps_free_length():
    prompt = _service()._build_draft_instruction(
        {"document_type": "工作总结", "history": []}, False)
    assert "正文篇幅按" not in prompt


def test_brief_range_only_covers_transactional_forms():
    assert brief_length_range("通知") == (500, 600)
    assert brief_length_range("工作通知") == (500, 600)
    assert brief_length_range("请示") == (400, 600)
    assert brief_length_range("报告") is None
    assert brief_length_range("工作总结") is None
    # 函另有自己的「3-5 段、800-1200 字」简明规则，不并入通用表
    assert brief_length_range("函") is None


def _padded(count: int) -> str:
    """生成 count 条互不相同的条目，避免触发「机械重复」干扰长度断言。"""
    return "\n".join(
        f"第{i}项工作要求：请各单位对照分工表推进第{i}阶段任务，按期报送台账。"
        for i in range(1, count + 1)
    )


def test_quality_gate_flags_overlong_notice_without_explicit_target():
    body = "关于做好有关工作的通知\n\n各司法所：\n\n" + _padded(40)
    result = QualityGate().evaluate(body, body_only=True, document_type="通知")
    assert any("正文偏长" in issue["message"] for issue in result["issues"])


def test_quality_gate_accepts_conventional_notice_length():
    body = "各司法所：\n\n" + _padded(15)
    result = QualityGate().evaluate(body, body_only=True, document_type="通知")
    assert not any("正文偏长" in issue["message"] for issue in result["issues"])
    assert not any("正文偏短" in issue["message"] for issue in result["issues"])


def test_overlong_notice_is_compacted_once():
    """超长通知自动精简一次；重写没变短则保留原稿，不改坏。"""
    svc = AsyncWritingTaskService.__new__(AsyncWritingTaskService)
    calls = []

    short_draft = (
        "各司法所：\n\n为做好近期重点工作，现就有关事项通知如下。\n\n"
        "一、加强值班值守。各所要落实领导带班和值守制度，确保通信畅通。\n\n"
        "二、强化排查管控。对重点人员逐人见面建档，动态掌握行踪。\n\n"
        "三、做好信息报送。重大情况随时报告，日常情况每周五前报局办公室。"
    )

    async def fake_draft(instruction, sources, attachment_ctx, user_id, template=None):
        calls.append(instruction)
        return short_draft

    svc._llm_draft_async = fake_draft
    long_text = "关于做好有关工作的通知\n\n各司法所：\n\n" + _padded(45)

    candidate, reason = asyncio.run(svc._regenerate_if_needed_async(
        "原始指令", [], None, "u1", None, long_text, {"document_type": "通知"}))

    assert calls, "超出常规篇幅应触发一次精简重写"
    assert "精简要求" in calls[0]
    assert "500-600 字" in calls[0]
    assert candidate == short_draft
    assert reason and "精简" in reason
