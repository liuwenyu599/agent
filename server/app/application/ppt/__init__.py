"""PPT 应用服务包。

``agent_job`` 对外暴露带并发准入控制的包装层；底层单任务 runner 仍保留在
``app.application.ppt.agent_job``，避免把队列策略侵入生成实现。
"""
from . import agent_job as _agent_job_core
from . import queued_agent_job as agent_job

__all__ = ["agent_job"]
