"""PPT 任务细粒度阶段进度（Stage）回报器。

后台渲染链路跨 agent_job → service → page_authoring/ppt_engine 多层，
逐层加回调参数侵入太大。这里用 contextvar 绑定「当前 job 的阶段回报器」：
渲染链路任意深处都可以 ``job_progress.report("正在…")``，由 agent_job
在执行线程入口绑定到 ``_update_job(..., job_stage_detail=...)``。

- 非 job 场景（同步导出、单元测试）未绑定，report 是零成本 no-op；
- 回报器内部异常绝不外抛，进度回写失败不能拖垮生成主链路；
- contextvar 按线程隔离，多 job 并行互不串扰（线程池子线程不继承，
  因此并行构图的进度只在主线程汇总点报告）。
"""
import contextvars
import logging
from typing import Callable, Optional

logger = logging.getLogger(__name__)

Reporter = Callable[[str], None]

_current: contextvars.ContextVar[Optional[Reporter]] = contextvars.ContextVar(
    "ppt_job_stage_reporter", default=None)


def bind(reporter: Reporter) -> contextvars.Token:
    """绑定当前线程的阶段回报器，返回 token 供 unbind 恢复。"""
    return _current.set(reporter)


def unbind(token: contextvars.Token) -> None:
    _current.reset(token)


def report(detail: str) -> None:
    """回写一条阶段明细（如「正在设计页面构图（第 2/5 批）」）。

    未绑定时静默忽略；回报器异常只记日志，绝不影响主流程。
    """
    reporter = _current.get()
    if reporter is None or not detail:
        return
    try:
        reporter(detail[:120])
    except Exception as exc:  # noqa: BLE001 - 进度回写绝不拖垮主链路
        logger.info("PPT 阶段进度回写失败（忽略）：%s", type(exc).__name__)
