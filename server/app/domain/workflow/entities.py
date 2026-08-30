"""工作流领域实体。"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

# 实例状态：draft / running / completed / archived
# 节点状态：pending / editing / draft / done


@dataclass
class WorkflowTemplate:
    """公共工作流模板（会议/活动/调研/汇报等）。"""
    name: str
    code: str
    id: Optional[str] = None
    category: str = "通用"
    description: str = ""
    icon: str = "Share"
    is_builtin: bool = True
    is_active: bool = True
    sort_order: int = 0
    created_at: Optional[datetime] = None


@dataclass
class WorkflowNode:
    """工作流模板中的节点定义（如 会议通知/会议议程/会议纪要）。"""
    template_id: str
    name: str
    id: Optional[str] = None
    stage: str = "中期"
    description: Optional[str] = None
    write_guide: Optional[str] = None
    sort_order: int = 0
    optional: bool = False


@dataclass
class WorkflowInstance:
    """用户创建的工作流实例（一项具体工作）。

    会议核心上下文统一存储在 basic_info（JSON）中，沿用旧系统约定。
    """
    template_id: str
    user_id: str
    title: str
    id: Optional[str] = None
    status: str = "running"
    basic_info: Dict[str, Any] = field(default_factory=dict)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


@dataclass
class NodeInstance:
    """工作流实例中每个节点的办理状态与成果内容。"""
    instance_id: str
    node_id: str
    id: Optional[str] = None
    sort_order: int = 0
    status: str = "pending"
    content: str = ""
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
