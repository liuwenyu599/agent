"""智能写作后处理与质量校验包。

生产写作链路分层（每层只补一条保证）：
- intent_interpreter：模型理解用户自然语言并输出结构化动作 / tool call；
- semantic_task_service：维护结构字段与正文边界、返回修改摘要；
- grounded_task_service：检索知识库范文用于风格模仿，并对派生金额做程序化复核；
- ops_task_service：程序化定位局部片段并执行 splice 等确定性操作；
- quality_retry_service：D 级正文在离开服务前 fail-closed 拒收（修复策略见 quality_policy）；
- eval_capture_service：人工保存紧跟 AI 版本时自动沉淀 AI→人工终稿候选评测样本；
- structured_field_service：标题/主送/文号/署名/日期彻底由结构化字段接管，正文只保存正文；
- sectioned_generation_service：分节规则（是否分节、兜底骨架、章节指令），模型调用在异步层；
- async_task_service：**唯一的内容生成入口**，所有长耗时模型 HTTP 调用原生 await。

跨层共享的确定性组件（避免同名逻辑抄多份后各自漂移）：
- finalize_pipeline：三条支路共用的「收尾 → 落库 → 版本快照」；
- quality_policy：D 级修复动作、重试预算与拒收响应；
- section_policy：文种分类与分节骨架的单一来源。

兼容说明：现有路由历史上直接从 ``writing.task_service`` 导入 ``WritingTaskService``。
包初始化阶段把该公开类绑定到最新生产实现，路由无需改导入路径。
同名的同步实现（draft / draft_stream / revise / patch_section / chat 及同步模型调用）
已删除：生产始终走异步路径，保留第二套实现只会让改一处忘一处。
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
