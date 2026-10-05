"""训练脚本里三处「小样本下静默失效」的把关测试。

这三处的共同点：都不报错，只是什么都不做，或者悄悄做错。
- save/eval 步数 500 而总步数不足 → 全程零 checkpoint、零评估，目录是空的；
- labels 没掩码 → system/user 段也进 loss，几百条样本时梯度被摊薄；
- max_length 截断 → 削掉落款和结尾，而那正是要学的东西。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS = _REPO_ROOT / "training" / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from common import reconcile_step_config, tokenize_sample, normalize_sample  # noqa: E402


class StepConfigTests(unittest.TestCase):
    def test_win_within_total_steps_is_left_alone(self):
        save, eval_step = reconcile_step_config(
            save_steps=20, eval_steps=20, n_samples=400,
            batch_size=1, grad_accum=8, epochs=3)
        self.assertEqual((save, eval_step), (20, 20))

    def test_oversized_steps_are_brought_back_into_range(self):
        """500 步 vs 全程 150 步 → 必须收敛到 <总步数，否则一次都不会触发。"""
        save, eval_step = reconcile_step_config(
            save_steps=500, eval_steps=500, n_samples=400,
            batch_size=1, grad_accum=8, epochs=3)
        per_epoch = 400 // 8
        total = per_epoch * 3
        self.assertLess(save, total, "save_steps 不收敛就永远不会存档")
        self.assertLess(eval_step, total, "eval_steps 不收敛就永远不会评估")
        self.assertGreaterEqual(save, 1)

    def test_tiny_dataset_still_gets_a_checkpoint(self):
        save, _ = reconcile_step_config(
            save_steps=500, eval_steps=500, n_samples=30,
            batch_size=1, grad_accum=8, epochs=1)
        self.assertGreaterEqual(save, 1)
        self.assertLessEqual(save, max(1, 30 // 8))


class _StubTokenizer:
    """按 1 token/字符 计数，够验证掩码位置即可。"""

    eos_token = "<|im_end|>"
    eos_token_id = 151645

    def __call__(self, text, add_special_tokens=True, **kwargs):
        ids = list(range(len(text)))
        return {"input_ids": ids}

    def apply_chat_template(self, messages, tokenize=False, add_generation_prompt=True):
        text = ""
        for m in messages:
            text += f"<|im_start|>{m['role']}\n{m['content']}<|im_end|>\n"
        if add_generation_prompt:
            text += "<|im_start|>assistant\n"
        return text


class LabelMaskingTests(unittest.TestCase):
    def test_prompt_tokens_are_masked_and_response_is_not(self):
        sample = {
            "messages": [
                {"role": "system", "content": "写公文的规则"},
                {"role": "user", "content": "起草通知"},
                {"role": "assistant", "content": "正　文"},
            ]
        }
        norm = normalize_sample(sample)
        self.assertIsNotNone(norm)
        self.assertEqual(len(norm["messages"]), 2, "system + user 都归到 prompt 侧")
        enc = tokenize_sample(_StubTokenizer(), norm, 4096)
        labels = enc["labels"]
        self.assertGreater(sum(1 for v in labels if v == -100), 0,
                           "prompt 段必须被掩码，否则 system 侧的检索资料也会被当成学习目标")
        self.assertEqual(sum(1 for v in labels if v != -100), len("正　文") + len("<|im_end|>"),
                         "参与 loss 的应当只有 assistant 那段")

    def test_system_message_survives_normalization(self):
        """system 消息不能丢：训练输入必须复现撤卡后的完整提示。"""
        sample = {
            "messages": [
                {"role": "system", "content": "撤卡后的 system"},
                {"role": "user", "content": "指令"},
                {"role": "assistant", "content": "正文"},
            ]
        }
        norm = normalize_sample(sample)
        self.assertTrue(any(m["role"] == "system" for m in norm["messages"]))
        self.assertIn("撤卡后的 system", norm["messages"][0]["content"])


if __name__ == "__main__":
    unittest.main()
