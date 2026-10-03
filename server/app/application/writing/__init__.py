"""智能写作后处理与质量校验包。

生产写作链路分层：
- intent_interpreter：模型理解用户自然语言并输出结构化动作 / tool call；
- semantic_task_service：维护结构字段与正文边界、返回修改摘要；
- grounded_task_service：检索知识库范文用于风格模仿，并对派生金额做程序化复核；
- ops_task_service：执行 set_fields / patch_section / rewrite_document 等操作，局部修改由程序 splice；
- quality_retry_service：D 级结果回灌具体 issues，最多重试两次，仍失败则禁止落库；
- eval_capture_service：人工保存紧跟 AI 版本时自动沉淀 AI→人工终稿候选评测样本；
- structured_field_service：标题/主送/文号/署名/日期彻底由结构化字段接管，正文只保存正文；
- sectioned_generation_service：长文按一级章节分别检索、生成、质检后组装，避免整篇反复重写；
- async_task_service：ASGI 生产入口，所有长耗时模型 HTTP 调用原生 await，不占 worker thread；
- task_service：保留成熟的版本/RAG/导出/质量链路作为基类。

兼容说明：现有路由历史上直接从 ``writing.task_service`` 导入 ``WritingTaskService``。
包初始化阶段把该公开类绑定到最新生产实现，路由无需改导入路径。
"""

from . import task_service as _task_service
from .semantic_task_service import SemanticWritingTaskService
from .grounded_task_service import GroundedWritingTaskService
from .ops_task_service import OpsWritingTaskService
from .quality_retry_service import QualityRetryWritingTaskService
from .eval_capture_service import EvalCaptureWritingTaskService
from .structured_field_service import StructuredFieldWritingTaskService
from .sectioned_generation_service import SectionedGenerationWritingTaskService
from .async_task_service import AsyncWritingTaskService

_task_service.WritingTaskService = AsyncWritingTaskService

__all__ = [
    "SemanticWritingTaskService",
    "GroundedWritingTaskService",
    "OpsWritingTaskService",
    "QualityRetryWritingTaskService",
    "EvalCaptureWritingTaskService",
    "StructuredFieldWritingTaskService",
    "SectionedGenerationWritingTaskService",
    "AsyncWritingTaskService",
]
