"""写作台对话历史：落库与「切回页面恢复」的服务端契约。

背景（待修正清单 #5「退出写作再进入，对话记录消失」）：
对话历史存在任务上下文的 ``history`` 字段里（``_push_history`` 写入），
桌面端切回写作页时按 taskId 调 ``GET /writing/tasks/{id}``，
从返回体的 ``task_context.history`` 回填消息列表。

真实根因在桌面端：``applyResponse`` 恢复任务时没有回填 messages，
于是切回页面后正文在、对话记录空。桌面端修复（419dba4）依赖下面这条
服务端契约——``get_task`` 必须把完整 history 带回 ``task_context``。
这里把它锁死，防止后端改结构时把桌面端恢复悄悄弄坏。
"""
from types import SimpleNamespace

from app.application.writing.task_service import WritingTaskService


def _task(ctx):
    """构造一个够 _to_dict 使用的任务桩。"""
    return SimpleNamespace(
        id="task-1", session_id="s-1", document_id=None,
        context=ctx, current_content="正文内容", version_no=1,
        status="drafting", created_at=None, updated_at=None,
    )


def test_history_round_trips_through_get_task_for_desktop_restore():
    """#5 回归：history 必须随 get_task 往返，且角色/顺序完整。"""
    ctx = {}
    WritingTaskService._push_history(ctx, "user", "写一份申报通知")
    WritingTaskService._push_history(ctx, "assistant", "好的，已为你起草")

    payload = WritingTaskService._to_dict(_task(ctx))
    history = payload["task_context"]["history"]

    assert [m["role"] for m in history] == ["user", "assistant"]
    assert history[0]["content"] == "写一份申报通知"
    assert history[-1]["content"] == "好的，已为你起草"


def test_push_history_caps_length_and_truncates():
    """历史只保留最近 12 条、单条截断 1000 字，避免上下文无限膨胀。"""
    ctx = {}
    for i in range(20):
        WritingTaskService._push_history(ctx, "user", f"第{i}轮")
    assert len(ctx["history"]) == 12
    # 只保留最近 12 条：第 8~19 轮
    assert ctx["history"][0]["content"] == "第8轮"

    WritingTaskService._push_history(ctx, "assistant", "长" * 1500)
    assert len(ctx["history"][-1]["content"]) == 1000


def test_to_dict_exposes_history_under_task_context():
    """桌面端读的是 task_context.history，键名不能变。"""
    ctx = {"history": [{"role": "user", "content": "在补贴标准那节加一句话"}]}
    payload = WritingTaskService._to_dict(_task(ctx))
    assert payload["task_context"]["history"][0]["role"] == "user"
    # 恢复正文仍然走 current_content，与 history 互不影响
    assert payload["current_content"] == "正文内容"
