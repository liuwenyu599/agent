"""Prompt slimming / structured few-shot acceptance tests (items 9-10)."""
from app.application.shared.prompt_budget import compact_style_examples
from app.application.shared.writing_assistant import WritingAssistant
from app.core.config import settings


class _Gateway:
    model_name = "mock"

    def complete(self, messages, temperature=None, max_tokens=None):
        return "ok"


def test_style_example_is_one_structured_card_under_budget():
    content = """2026年工作总结
一、总体情况
根据上级部署，坚持围绕中心工作推进，完成123项任务。
二、主要做法
一是强化统筹。二是压实责任。三是闭环落实。
三、下一步工作
下一步，坚持问题导向持续改进。
特此报告。"""
    result = compact_style_examples([
        {"title": "第一篇", "content": content * 20},
        {"title": "第二篇不应注入", "content": "二、另一篇" * 100},
    ])

    assert len(result) <= 1100
    assert "一级结构骨架" in result
    assert "固定用语/过渡句式" in result
    assert "第二篇不应注入" not in result
    assert "123" not in result


def test_writing_assistant_keeps_only_three_history_rounds():
    assistant = WritingAssistant(_Gateway())
    history = []
    for i in range(10):
        history.append({"role": "user" if i % 2 == 0 else "assistant", "content": str(i)})
    messages, _ = assistant._assemble_messages("new", history, "system")

    assert [m["content"] for m in messages[1:-1]] == ["4", "5", "6", "7", "8", "9"]
    assert messages[-1]["content"] == "new"


def test_rag_defaults_are_three_hits_and_800_char_expansion():
    assert settings.RAG_TOP_K == 3
    assert settings.RAG_EXPAND_BUDGET == 800


def test_each_prompt_source_is_capped_at_800_chars():
    assistant = WritingAssistant(_Gateway())
    prompt = assistant._default_prompt(sources=[{"content": "甲" * 1200}])
    assert "甲" * 800 in prompt
    assert "甲" * 801 not in prompt
