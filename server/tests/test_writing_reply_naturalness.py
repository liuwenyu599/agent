"""写作台对话回复「去模板化」契约测试。

运行方式（在 server/ 目录下）：
    AI_PROVIDER=mock python -m pytest tests/test_writing_reply_naturalness.py -v

背景：用户反馈「写作台的对话响应比较死板」。根因是四层叠加（详见当日工作日志）：
1. intent_interpreter 的 system prompt 写死「reply 只说明理解到的操作」；
2. 工具调用 temperature=0.0 把自然语言部分也锁到最保守 token；
3. tool schema 里 reply 是唯一没有 description 的字段；
4. 兜底 _collecting_reply 是纯 f-string，且草稿回复恒拼同一句尾巴。

本文件锁定改后的行为，并**防止后续改动把正确的底线写回去**——尤其是
「不得谎称尚未执行的修改已经完成」这条必须保留。
"""
import os
import asyncio
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("AI_PROVIDER", "mock")
os.environ.setdefault("DATA_DIR", f"/tmp/test-reply-{uuid.uuid4().hex[:8]}")

from app.application.writing.intent_interpreter import (  # noqa: E402
    SYSTEM_PROMPT,
    WRITING_OPS_TOOL,
)
from app.application.writing import ProductionWritingTaskService  # noqa: E402
from app.application.writing.async_intent_interpreter import AsyncWritingIntentInterpreter  # noqa: E402
from app.application.writing.semantic_task_service import (  # noqa: E402
    SemanticWritingTaskService,
)
from app.application.writing.task_service import WritingTaskService  # noqa: E402

# 改动前钉在代码里的两句话，改后一律不得再出现
FROZEN_DRAFT_TAIL = "您可以继续对话修改，或直接编辑正文后保存版本。"
FROZEN_READY_LINE = "关键信息已齐，回复「起草」即可生成第一版草稿。"
FROZEN_LOCK_CLAUSE = "reply 只说明理解到的操作"


@pytest.fixture()
def svc():
    """绕过 __init__ 构造：本用例只验证纯函数逻辑，不需要 db / 模型。"""
    return WritingTaskService.__new__(WritingTaskService)


@pytest.fixture()
def semantic_svc():
    return SemanticWritingTaskService.__new__(SemanticWritingTaskService)


# ---------------------------------------------------------------- 1. 提示词与 schema


def test_reply_field_now_has_description():
    """reply 此前是 tool schema 里唯一没有 description 的字段，模型没有体例可参照。"""
    reply_schema = WRITING_OPS_TOOL["function"]["parameters"]["properties"]["reply"]
    desc = reply_schema.get("description") or ""
    assert desc, "reply 缺少 description，模型无法知道该用什么语气"
    assert len(desc) > 20, "description 过短，起不到体例引导作用"


def test_reply_is_still_required():
    """reply 必须仍是必填：改写体例不能顺手把必填性去掉。"""
    assert "reply" in WRITING_OPS_TOOL["function"]["parameters"]["required"]


def test_prompt_no_longer_locks_reply_to_operation_restatement():
    """改动主因：这句约束导致模型只被允许复述操作，是「死板」的根源。"""
    assert FROZEN_LOCK_CLAUSE not in SYSTEM_PROMPT


def test_prompt_still_forbids_claiming_unexecuted_changes():
    """底线必须保留：不能为了「说人话」就让模型谎称还没落库的修改已完成。"""
    assert "不得谎称尚未执行的修改已经完成" in SYSTEM_PROMPT


def test_prompt_encourages_collegial_tone():
    """新约束要真正要求「像同事对话」，不能只删掉了旧句。"""
    assert "同事协作" in SYSTEM_PROMPT
    assert "reply 怎么写" in SYSTEM_PROMPT


def test_prompt_allows_proactive_clarification():
    """用户确认要「主动追问缺失信息」， clarify 的触发条件必须被放宽。"""
    assert "缺的那项会实质改变写法时用" in SYSTEM_PROMPT
    # 但仍要防止变成「什么都问」：锦上添花的细节不许拦人
    assert "锦上添花的细节" in SYSTEM_PROMPT


# ---------------------------------------------------------------- 2. 兜底话术轮换


def test_collecting_reply_varies_across_messages(svc):
    """同一情境下换个说法，句式必须跟着变——否则轮换等于没做。"""
    messages = ["帮我写个通知", "起草一份函", "搞个工作汇报", "整理个材料", "写个整改通知"]
    replies = {svc._collecting_reply({"document_type": "通知"}, [], ["联系电话"], m)
               for m in messages}
    assert len(replies) >= 3, f"五种说法只产出 {len(replies)} 种回复，轮换不足：{replies}"


def test_collecting_reply_is_deterministic(svc):
    """同一句话重放必须稳定：用随机会让用户刷新一次换一个说法，更不可信。"""
    kwargs = dict(ctx={"document_type": "通知", "topic": "安全生产"},
                  changes=["主送机关"], missing=["联系电话"], message="帮我写个通知")
    first = svc._collecting_reply(**kwargs)
    assert svc._collecting_reply(**kwargs) == first
    for _ in range(5):
        assert svc._collecting_reply(**kwargs) == first


def test_collecting_reply_drops_frozen_ready_line(svc):
    """旧版「关键信息已齐，回复「起草」即可生成第一版草稿。」必须消失。"""
    reply = svc._collecting_reply({"document_type": "通知"}, [], [], "随便写点什么")
    assert FROZEN_READY_LINE not in reply
    # 但仍要告诉用户下一步怎么走，否则他会卡住
    assert "起草" in reply


def test_collecting_reply_keeps_missing_escape_hatch(svc):
    """缺资料时不能把用户拦死：「先写一版」这个逃生口必须保留。

    现实情况是用户常常手头没有材料，这里若只追问不提供出路，写作台就成了摆设。
    """
    reply = svc._collecting_reply({}, [], ["主送机关", "联系电话"], "写个通知")
    assert "先写一版" in reply
    assert "联系电话" in reply, "必须说清缺的是哪一项，不能泛泛追问"


def test_collecting_reply_reads_naturally(svc):
    """回复应是完整句子，不能是一串字段名罗列。"""
    reply = svc._collecting_reply({"document_type": "通知", "topic": "安全生产"},
                                  [], [], "写个通知")
    assert reply.endswith("。") or reply.endswith("？"), reply
    assert "好的，目前我知道：" not in reply


# ---------------------------------------------------------------- 3. 草稿尾巴


def test_draft_followup_never_returns_the_old_stamp(svc):
    """改动前每篇草稿都拼同一句，这是最刺眼的橡皮图章。"""
    for seed in ["", "正文内容", "很长的一篇通知" * 50]:
        reply = svc._draft_followup({"review": []}, None, seed)
        assert FROZEN_DRAFT_TAIL not in reply, seed


def test_draft_followup_prioritises_missing_fields(svc):
    """缺事实依据时先说这个，而不是给通用引导——这是最有价值的下一条建议。"""
    reply = svc._draft_followup({"review": ["疑似截断"]}, ["具体金额"], "x")
    assert "具体金额" in reply
    assert "疑似截断" not in reply, "缺字段优先级更高，不要同时抛两个待办砸给用户"


def test_draft_followup_reports_review_item_when_no_missing(svc):
    """没有缺字段但有质检待复核项时，应该点出来让用户定稿前留意。"""
    reply = svc._draft_followup({"review": ["结尾缺少成文日期"]}, None, "x")
    assert "结尾缺少成文日期" in reply


def test_draft_followup_falls_back_to_variants(svc):
    """没得说时才给通用引导，且不同稿子之间措辞要轮换。"""
    seen = {svc._draft_followup({"review": []}, None, s)
            for s in ["稿子甲", "稿子乙", "稿子丙", "稿子丁"]}
    assert len(seen) >= 2, f"通用引导没有轮换：{seen}"
    for r in seen:
        assert r and r != FROZEN_DRAFT_TAIL


# ---------------------------------------------------------------- 4. 修改完成的话术


def test_revise_reply_summarizes_what_changed(semantic_svc):
    """改前只报版本号，用户不知道改了什么——现在要说出改动类型与处数。"""
    summary = "原：aaa\n改：bbb\n\n新增：ccc\n\n删除：ddd"
    reply = semantic_svc._revise_reply(2, summary, [], "把语气改正式点")
    assert "v2" in reply
    assert "改写了 1 处" in reply
    assert "补进了 1 处" in reply
    assert "删掉了 1 处" in reply


def test_revise_reply_without_diff_still_reports_version(semantic_svc):
    """没有算出差异（如仅格式规范化）时，至少要交代版本号，不能空白或报错。"""
    reply = semantic_svc._revise_reply(3, "", [], "规范化一下")
    assert "v3" in reply


def test_revise_reply_varies_across_instructions(semantic_svc):
    """同一类改动换不同指令，开场措辞要轮换。"""
    seen = {semantic_svc._revise_reply(1, "新增：a", [], m)
            for m in ["语气正式点", "压缩篇幅", "补一段成效", "换个标题"]}
    assert len(seen) >= 2, f"修改完成的话术没有轮换：{seen}"


def test_revise_reply_keeps_citation_warning(semantic_svc):
    """移除无法核实的文号这件事必须继续告知，不能被「说人话」改掉。

    这是安全相关：用户必须知道有号码被替换成「相关文件」，否则会拿着错稿出门。
    """
    reply = semantic_svc._revise_reply(2, "新增：a", ["穗司发〔2026〕1号"], "改一下")
    assert "相关文件" in reply or "核实不到" in reply


# ---------------------------------------------------------------- 5. 不能改破的底线


def test_collecting_reply_is_only_a_fallback():
    """模型给出的 reply 必须原样透传，不能被任何模板重写。

    _collecting_reply 只是 LLM 不可用时的兜底，主路径永远是模型的自然回复。
    这里用假的 interpreter 验证透传链路没有被中间的模板逻辑截断。
    """

    class FakeInterpreter:
        async def interpret_async(self, message, context=None, has_draft=False, history=None):
            return {"operation": "answer", "reply": "这是一句来自模型的自然回复",
                    "field_updates": {}}

    svc = ProductionWritingTaskService.__new__(ProductionWritingTaskService)
    svc.interpreter = FakeInterpreter()
    result = asyncio.run(svc._interpret_async("随便", {}, has_draft=False))
    assert result["reply"] == "这是一句来自模型的自然回复"


def test_new_reply_logic_reaches_explicit_production_service_class():
    svc = ProductionWritingTaskService.__new__(ProductionWritingTaskService)
    reply = svc._collecting_reply({"document_type": "通知"}, [], [], "写个通知")
    assert FROZEN_READY_LINE not in reply
    assert reply


def test_interpret_failure_returns_none_not_fabricated_reply(monkeypatch):
    """解释失败必须返回 None，让调用方走兜底——绝不能凭空编一个 reply 去改正文。

    这条是既有安全设计，本轮改动不得破坏：模板轮换再自然，也只配出现在模型
    没接管的场合，不能反过来替模型编话。
    """
    interp = AsyncWritingIntentInterpreter.__new__(AsyncWritingIntentInterpreter)
    interp.assistant = None  # 模型未配置
    assert asyncio.run(interp.interpret_async("写个通知")) is None
