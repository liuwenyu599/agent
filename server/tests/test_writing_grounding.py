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


def test_kb_examples_are_labeled_as_style_exemplars_not_plain_sources():
    block = _Svc()._example_style_block("社区矫正工作情况报告", "u1")
    assert "知识库范文模仿契约" in block
    assert "本单位范文1" in block
    assert "结构层级" in block
    assert "固定套语" in block
    assert "不得只把范文当作事实引用" in block


def test_production_service_is_grounded_service():
    from app.application.writing import task_service
    assert task_service.WritingTaskService is GroundedWritingTaskService
