"""智能写作后处理与质量校验包。

生产写作链路分层（每层只补一条保证）：
- intent_interpreter：模型理解用户自然语言并输出结构化动作 / tool call；
- semantic_task_service：维护结构字段与正文边界、返回修改摘要；
- grounded_task_service：检索知识库范文用于风格模仿，并对派生金额做程序化复核；
- ops_task_service：程序化定位局部片段并执行 splice 等确定性操作；
- quality_policy：候选修复动作、重试预算与最终拒收规则的单一来源；
- eval_capture_service：人工保存紧跟 AI 版本时自动沉淀 AI→人工终稿候选评测样本；
- structured_field_service：标题/主送/文号/署名/日期彻底由结构化字段接管，正文只保存正文；
- sectioned_generation_service：分节规则（是否分节、兜底骨架、章节指令），模型调用在异步层；
- async_task_service：**唯一的内容生成入口**，所有长耗时模型 HTTP 调用原生 await。

跨层共享的确定性组件（避免同名逻辑抄多份后各自漂移）：
- finalize_pipeline：三条支路共用「收尾 → 终检 → 落库 → 版本快照」，最终候选只检查一次；
- section_policy：文种分类与分节骨架的单一来源。

公开类型不再靠包初始化重绑：``task_service.WritingTaskService`` 始终是无模型 I/O 的
基础服务，生产路由显式依赖 ``ProductionWritingTaskService``。这样静态阅读、类型检查和
运行时拿到的是同一个类，不会再出现导入路径看似是基类、实际被偷偷替换的情况。
"""

from .semantic_task_service import SemanticWritingTaskService
from .grounded_task_service import GroundedWritingTaskService
from .ops_task_service import OpsWritingTaskService
from .quality_retry_service import QualityRetryWritingTaskService
from .eval_capture_service import EvalCaptureWritingTaskService
from .structured_field_service import StructuredFieldWritingTaskService
from .sectioned_generation_service import SectionedGenerationWritingTaskService
from .async_task_service import AsyncWritingTaskService

ProductionWritingTaskService = AsyncWritingTaskService

__all__ = [
    "SemanticWritingTaskService",
    "GroundedWritingTaskService",
    "OpsWritingTaskService",
    "QualityRetryWritingTaskService",
    "EvalCaptureWritingTaskService",
    "StructuredFieldWritingTaskService",
    "SectionedGenerationWritingTaskService",
    "AsyncWritingTaskService",
    "ProductionWritingTaskService",
]
