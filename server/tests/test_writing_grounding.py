from app.application.writing.calculation_guard import verify_and_fix_calculations
from app.application.writing.grounded_task_service import GroundedWritingTaskService


def test_natural_per_person_month_amount_is_repaired():
    text = "本次补助涉及1336人，按每人每月150元补助，补助12个月，共计239.85万元。"
    fixed, events = verify_and_fix_calculations(text)
    assert "240.48万元" in fixed
    assert "239.85万元" not in fixed
    assert events


def test_correct_natural_amount_is_left_unchanged():
    text = "本次补助涉及1336人，按每人每月150元补助，补助12个月，共计240.48万元。"
    fixed, events = verify_and_fix_calculations(text)
    assert fixed == text
    assert events == []


def test_explicit_formula_is_repaired():
    fixed, _ = verify_and_fix_calculations("1336×150×12=239.85万元")
    assert fixed == "1336×150×12=240.48万元"


class _FakeRag:
    def search_examples(self, query, user_id, top_k=2, max_chars=2600):
        return [
            {
                "title": "白云区司法局工作情况报告",
                "content": "一、工作开展情况\n（一）强化统筹协调。……\n二、下一步工作安排\n……",
            }
        ]


class _Svc(GroundedWritingTaskService):
    def __init__(self):
        self.rag = _FakeRag()


def test_kb_examples_are_compacted_into_style_cards_not_plain_sources():
    block = _Svc()._example_style_block("社区矫正工作情况报告", "u1")
    assert "知识库范文风格卡" in block
    assert "风格卡：白云区司法局工作情况报告" in block
    assert "结构层级" in block or "一级结构骨架" in block
    assert "固定用语" in block or "固定套语" in block
    assert "禁止迁移" in block
    assert "事实只能来自用户输入、附件和本轮 RAG" in block


def test_production_service_keeps_grounded_behavior():
    from app.application.writing import task_service

    # The public production service may add stricter layers (ops routing / QualityGate retries),
    # but it must continue to inherit all grounded-writing behavior rather than bypass it.
    assert issubclass(task_service.WritingTaskService, GroundedWritingTaskService)
