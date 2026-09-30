"""智能写作后处理与质量校验包。

写作工作台的语义入口统一由模型驱动：
- intent_interpreter：模型理解用户自然语言并输出结构化动作；
- semantic_task_service：执行模型动作、维护结构字段与正文边界、返回修改摘要；
- task_service：保留成熟的版本/RAG/导出/质量链路作为基类；
- postprocessor / quality_gate / content_check：只做确定性文档约束，不负责猜用户意图。

兼容说明：现有路由历史上直接从 ``writing.task_service`` 导入 ``WritingTaskService``。
为避免交付前重写整个路由文件，这里在包初始化阶段把该公开类绑定到新的语义服务。
基类本身仍由 ``semantic_task_service`` 持有，可单独测试和回滚。
"""

# 加载旧基类，再加载新语义服务；最后只替换 task_service 模块对外公开的类引用。
# Python 导入子模块前会先执行包 __init__，因此现有 writing_tasks 路由无需改动即可得到新实现。
from . import task_service as _task_service
from .semantic_task_service import SemanticWritingTaskService

_task_service.WritingTaskService = SemanticWritingTaskService

__all__ = ["SemanticWritingTaskService"]
