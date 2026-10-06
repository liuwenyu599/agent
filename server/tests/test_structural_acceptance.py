"""非 loss 结构化验收脚本的把关测试。

验收线本身错了比没有更糟：一个永远通过的验收脚本会让人放心地把还没训好的
模型换上去。所以这里守的是「它能不能真的判出来」。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS = _REPO_ROOT / "training" / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from eval_structural import (  # noqa: E402
    compare_structure, evaluate, structure_fingerprint,
)

_NOTICE_A = """关于加强社区矫正工作的通知

各司法所：

一、提高认识
要高度重视社区矫正工作。

二、落实责任
明确责任分工。

三、加强督导
定期检查通报。

特此通知。

广州市白云区司法局
2026年10月4日"""

_NOTICE_B = """关于加强社区矫正工作的通知

各司法所：

一、提高思想认识
充分认识此项工作的重要性。

二、压实工作责任
逐项落实到人。

三、强化督促检查
按月通报进展。

特此通知。

广州市白云区司法局
2026年10月4日"""

_REQUEST = """关于申请追加普法经费的请示

白云区人民政府：

根据年度工作安排，我区普法经费已使用完毕，现申请追加经费若干。

妥否，请批示。

广州市白云区司法局
2026年10月4日"""


class FingerprintTests(unittest.TestCase):
    def test_all_structural_slots_are_extracted(self):
        fp = structure_fingerprint(_NOTICE_A)
        self.assertEqual(fp["level1"], ["一", "二", "三"])
        self.assertEqual(fp["addressee"], "各司法所")
        self.assertEqual(fp["closing_org"], "广州市白云区司法局")
        self.assertEqual(fp["closing_date"], "2026年10月4日")
        self.assertEqual(fp["closing_phrase"], "特此通知")

    def test_markdown_decorations_do_not_change_the_shape(self):
        """模型有时会用 markdown 输出公文，那不是格式问题，不该判成不一致。"""
        md = "\n".join(f"## {line}" if line.startswith("一、") else line
                       for line in _NOTICE_A.splitlines())
        score, _ = compare_structure(structure_fingerprint(_NOTICE_A),
                                     structure_fingerprint(md))
        self.assertGreaterEqual(score, 0.9)

    def test_wording_differences_survive_but_missing_closing_does_not(self):
        """同文种换措辞应当一致；丢掉落款必须被判出来——这正是用户遇到的现象。"""
        same, _ = compare_structure(structure_fingerprint(_NOTICE_A),
                                    structure_fingerprint(_NOTICE_B))
        self.assertEqual(same, 1.0, "只换措辞不该影响结构判定")

        no_closing = _NOTICE_A.rsplit("\n", 2)[0]  # 去掉落款单位与日期
        broken, diffs = compare_structure(structure_fingerprint(_NOTICE_A),
                                          structure_fingerprint(no_closing))
        self.assertLess(broken, 0.85)
        self.assertIn("closing_date", diffs)
        self.assertIn("closing_org", diffs)

        no_date = _NOTICE_A.rsplit("\n", 1)[0]
        date_score, date_diffs = compare_structure(
            structure_fingerprint(_NOTICE_A), structure_fingerprint(no_date))
        self.assertLess(date_score, 0.85)
        self.assertIn("closing_date", date_diffs)

    def test_addressee_only_change_is_a_meaningful_difference(self):
        changed = _NOTICE_A.replace("各司法所：", "各区人民政府：")
        score, diffs = compare_structure(
            structure_fingerprint(_NOTICE_A), structure_fingerprint(changed))
        self.assertLessEqual(score, 0.7)
        self.assertIn("addressee", diffs)

    def test_different_doc_types_are_not_treated_as_equivalent(self):
        score, _ = compare_structure(structure_fingerprint(_NOTICE_A),
                                     structure_fingerprint(_REQUEST))
        self.assertLess(score, 0.8, "通知和请示本来就是两种格式")


class GateTests(unittest.TestCase):
    def test_consistent_model_passes_and_unstable_one_is_blocked(self):
        good = [{"id": "c1", "variants": [{"tag": "run1", "output": _NOTICE_A},
                                          {"tag": "run2", "output": _NOTICE_B}]}]
        gates, verdict = evaluate(good, {"A": 0.85, "B": 0.30, "C": 0.85})
        self.assertTrue(gates[0].passed)
        self.assertNotIn("先别上线", verdict)

        unstable = [{"id": "c2", "variants": [
            {"tag": "run1", "output": _NOTICE_A},
            {"tag": "run2", "output": _NOTICE_A.rsplit("\n", 2)[0]}]}]
        gates, verdict = evaluate(unstable, {"A": 0.85, "B": 0.30, "C": 0.85})
        self.assertFalse(gates[0].passed, "两次格式不一致必须拦下来")
        self.assertIn("先别上线", verdict)

    def test_collapse_into_one_template_is_caught(self):
        """几百条样本最常见的失败：不同输入套同一个壳。loss 会很好看。"""
        cases = [
            {"id": "a", "variants": [{"tag": "run1", "output": _NOTICE_A}],
             "expected_differs_from": "b"},
            {"id": "b", "variants": [{"tag": "run1", "output": _REQUEST}],
             "expected_differs_from": ""},
        ]
        gates, _ = evaluate(cases, {"A": 0.85, "B": 0.30, "C": 0.85})
        self.assertTrue(gates[1].passed, "格式确实不同，应当通过")

        collapsed = [
            {"id": "a", "variants": [{"tag": "run1", "output": _NOTICE_A}],
             "expected_differs_from": "b"},
            {"id": "b", "variants": [{"tag": "run1", "output": _NOTICE_B}],
             "expected_differs_from": ""},
        ]
        gates, verdict = evaluate(collapsed, {"A": 0.85, "B": 0.30, "C": 0.85})
        self.assertFalse(gates[1].passed, "塌缩成同一模板必须判失败")
        self.assertIn("先别上线", verdict)

    def test_card_removal_verdict_distinguishes_three_outcomes(self):
        thresholds = {"A": 0.85, "B": 0.30, "C": 0.85}
        parity_ok = [{"id": "p", "variants": [
            {"tag": "with_card", "output": _NOTICE_A},
            {"tag": "without_card", "output": _NOTICE_B}]}]
        _, verdict = evaluate(parity_ok, thresholds)
        self.assertIn("不能据此撤卡", verdict)

        parity_bad = [{"id": "p", "variants": [
            {"tag": "with_card", "output": _NOTICE_A},
            {"tag": "without_card", "output": _NOTICE_A.rsplit("\n", 2)[0]}]}]
        _, verdict = evaluate(parity_bad, thresholds)
        self.assertIn("先别撤卡", verdict)

        not_run = [{"id": "p", "variants": [
            {"tag": "run1", "output": _NOTICE_A},
            {"tag": "run2", "output": _NOTICE_B}]}]
        _, verdict = evaluate(not_run, thresholds)
        self.assertIn("不能据此撤卡", verdict,
                      "没跑 C 线就不能说风格已经进权重——这是最容易误判的一种批准")

    def test_all_three_gates_must_pass_before_card_removal(self):
        cases = [
            {"id": "notice", "expected_differs_from": "request", "variants": [
                {"tag": "run1", "output": _NOTICE_A},
                {"tag": "run2", "output": _NOTICE_B},
                {"tag": "with_card", "output": _NOTICE_A},
                {"tag": "without_card", "output": _NOTICE_B},
            ]},
            {"id": "request", "variants": [
                {"tag": "run1", "output": _REQUEST},
                {"tag": "run2", "output": _REQUEST},
                {"tag": "with_card", "output": _REQUEST},
                {"tag": "without_card", "output": _REQUEST},
            ]},
        ]
        gates, verdict = evaluate(cases, {"A": 0.85, "B": 0.30, "C": 0.85})
        self.assertTrue(all(g.passed for g in gates))
        self.assertIn("可以配 WRITING_STYLE_ADAPTER", verdict)

    def test_identically_incomplete_outputs_do_not_pass(self):
        no_date = _NOTICE_A.rsplit("\n", 1)[0]
        cases = [{"id": "same-bad", "variants": [
            {"tag": "run1", "output": no_date},
            {"tag": "run2", "output": no_date},
            {"tag": "with_card", "output": no_date},
            {"tag": "without_card", "output": no_date},
        ]}]
        gates, verdict = evaluate(cases, {"A": 0.85, "B": 0.30, "C": 0.85})
        self.assertFalse(gates[0].passed)
        self.assertFalse(gates[2].passed)
        self.assertIn("先别上线", verdict)


if __name__ == "__main__":
    unittest.main()
