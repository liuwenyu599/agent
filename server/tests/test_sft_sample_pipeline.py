"""SFT 样本采集链路。

锁的是「把推理期的 1100 字风格卡蒸馏到权重里」这条链路的成立条件：

1. 训练样本的输入侧必须是**撤了卡**的完整提示（否则撤了卡还是不会写）；
2. 输入侧必须带着当时的检索资料（否则训练等于教模型编事实）；
3. 满意的样本要抓得到（只看「改过的」会让数据整体偏向负例）；
4. 未配置开关时全部为空操作（旁路功能不得影响主流程）。
"""
from __future__ import annotations

import importlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

# 导出脚本在 training/scripts，不在 server 包下，测试要自己把仓库根加进来
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.application.writing import grounded_task_service
from app.application.writing import prompt_snapshot


class _AssistantStub:
    """最小替身：模拟 WritingAssistant._build_system_prompt 的行为。

    真实实现把 sources 拼进 system；这里保留同样的语义就够了——测试关心的是
    快照还原出的数据结构，不是那段拼接文案本身。
    """

    def _build_system_prompt(self, message, sources, examples=None, system_prompt=None,
                             memories=None, reference_template=None,
                             task_reference_context=None, template_reference_context=None,
                             user_preference=None, attachment_context=None):
        docs = "\n\n".join(f"[参考资料{i+1}]\n{s['content']}"
                           for i, s in enumerate(sources or []))
        return (system_prompt or "") + ("\n\n" + docs if docs else "")


class SnapshotRoundTripTests(unittest.TestCase):
    def test_disabled_by_default(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SFT_SNAPSHOT_DIR", None)
            self.assertFalse(prompt_snapshot.enabled())
            self.assertFalse(prompt_snapshot.record(
                "t1", base_system="A", style_card="C", instruction="写份通知"))

    def test_record_and_read_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"SFT_SNAPSHOT_DIR": tmp}):
                prompt_snapshot.enter_task("task-1", "u1", session_id="sess-1")
                self.assertTrue(prompt_snapshot.record(
                    "task-1", base_system="基础提示", style_card="【风格卡：X】结构一→二",
                    instruction="写份通知",
                    sources=[{"title": "细则", "content": "第三条 请假须审批"}],
                    attachment_context="附件：会议纪要"))
                snap = prompt_snapshot.latest("task-1")
            self.assertIsNotNone(snap)
            self.assertEqual(snap["session_id"], "sess-1")
            self.assertEqual(snap["base_system"], "基础提示")
            self.assertEqual(snap["sources"][0]["title"], "细则")

    def test_snapshot_keeps_every_source_and_full_attachment_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"SFT_SNAPSHOT_DIR": tmp}):
                prompt_snapshot.enter_task("task-all", "u1", session_id="sess-all")
                sources = [{"title": str(i), "content": f"依据{i}"} for i in range(13)]
                attachment = "附件依据" * 600
                self.assertTrue(prompt_snapshot.record(
                    "task-all", base_system="基础", style_card="", instruction="起草",
                    sources=sources, attachment_context=attachment))
                snap = prompt_snapshot.latest("task-all")
        self.assertEqual(len(snap["sources"]), 13)
        self.assertEqual(snap["attachment_context"], attachment)

    def test_build_inputs_drops_the_style_card_and_keeps_sources(self):
        snap = {
            "base_system": "基础提示", "style_card": "【风格卡：X】一级结构骨架",
            "instruction": "起草通知：加班管理",
            "sources": [{"title": "细则", "content": "第三条 请假须审批"}],
            "attachment_context": "",
        }
        inputs = prompt_snapshot.build_inputs(snap, _AssistantStub(), keep_style_card=False)
        self.assertNotIn("风格卡", inputs["system"],
                         "训练输入必须是不含风格卡的那一版，否则撤卡后模型没有学会这套结构")
        self.assertIn("第三条 请假须审批", inputs["system"],
                      "检索资料丢了，训练就变成「给个标题凭空写一篇」，等于鼓励虚构")
        self.assertEqual(inputs["user"], "起草通知：加班管理")

    def test_build_inputs_can_restore_the_card_for_ablation(self):
        snap = {
            "base_system": "基础提示", "style_card": "【风格卡：X】一级结构骨架",
            "instruction": "起草通知", "sources": [], "attachment_context": "",
        }
        with_card = prompt_snapshot.build_inputs(snap, _AssistantStub(),
                                                 keep_style_card=True)
        self.assertIn("风格卡", with_card["system"])


class ExportIndexTests(unittest.TestCase):
    def test_pick_snapshot_before_sample_creation(self):
        from training.scripts import export_accepted_samples as exporter

        snaps = [
            {"ts": "2026-10-01T10:00:00", "base_system": "首版"},
            {"ts": "2026-10-01T11:00:00", "base_system": "第二次改写"},
            {"ts": "2026-10-01T12:00:00", "base_system": "第三次改写"},
        ]
        chosen = exporter.pick_snapshot(snaps, "2026-10-01T11:30:00")
        self.assertEqual(chosen["base_system"], "第二次改写",
                         "要取样本产生那一刻之前最近的一次调用，而不是首版或末版")

    def test_pick_snapshot_falls_back_to_last(self):
        from training.scripts import export_accepted_samples as exporter

        snaps = [{"ts": "2026-10-01T10:00:00", "base_system": "首版"}]
        self.assertEqual(exporter.pick_snapshot(snaps, "")["base_system"], "首版")

    def test_pick_snapshot_rejects_future_context(self):
        from training.scripts import export_accepted_samples as exporter

        snaps = [{"ts": "2026-10-01T12:00:00", "base_system": "后续改写"}]
        self.assertIsNone(exporter.pick_snapshot(snaps, "2026-10-01T11:00:00"))

    def test_intermediate_dir_avoids_dangling_symlink(self):
        """training/data/raw 是断链符号链接，mkdir(exist_ok=True) 仍会抛错。"""
        from training.scripts import export_accepted_samples as exporter

        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            (data_dir / "collected").mkdir()
            target = data_dir / "raw"
            try:
                target.symlink_to(data_dir / "不存在的目标", target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("当前环境无法创建符号链接")
            chosen = exporter.ensure_intermediate_dir(data_dir)
            self.assertTrue(chosen.is_dir())
            self.assertFalse(chosen.is_symlink())


class StyleAdapterSwitchTests(unittest.TestCase):
    """「哪怕不训练也不影响」

    用户明确要求这条。做法是让风格卡成为一个**运行期开关**：不配
    WRITING_STYLE_ADAPTER 就走今天的路（压这张卡），配了才撤卡走权重。
    训与不训共用一套代码，不存在「adapter 一旦没有，质量塌掉」的中间态。
    """

    def test_card_is_injected_when_no_adapter(self):
        os.environ.pop("WRITING_STYLE_ADAPTER", None)
        importlib.reload(grounded_task_service)
        self.assertFalse(grounded_task_service.style_adapter_active())

    def test_card_is_dropped_once_style_lives_in_weights(self):
        with mock.patch.dict(os.environ, {"WRITING_STYLE_ADAPTER": "judicial-style-v1"}):
            self.assertTrue(grounded_task_service.style_adapter_active())
            svc = grounded_task_service.GroundedWritingTaskService.__new__(
                grounded_task_service.GroundedWritingTaskService)
            svc.rag = object()  # 有 rag 也会被开关挡住
            self.assertEqual(svc._example_style_block("写个通知", "u1"), "")


if __name__ == "__main__":
    unittest.main()
