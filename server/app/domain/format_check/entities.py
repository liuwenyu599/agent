"""格式校验领域实体。"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

VALID_RULE_TARGETS = [
    "title", "body", "heading1", "heading2", "page", "signature", "date", "general",
]


@dataclass
class FormatRule:
    """公文格式规则（可配置，不写死）。

    target: 作用对象：title/body/heading1/heading2/page/signature/date/general
    checks: JSON 字典，只配置需要检查的项，未配置的项不检查。
    """
    name: str
    target: str
    checks: Dict[str, Any]
    id: Optional[str] = None
    severity: str = "error"  # error / warning
    is_active: bool = True
    is_default: bool = False
    remark: Optional[str] = None
    created_by: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


@dataclass
class FormatCheckRecord:
    """格式校验历史记录。"""
    user_id: str
    filename: str
    id: Optional[str] = None
    file_type: Optional[str] = None
    rule_snapshot: List[Dict[str, Any]] = field(default_factory=list)
    issues: List[Dict[str, Any]] = field(default_factory=list)
    issue_count: int = 0
    rule_issue_count: int = 0
    ai_issue_count: int = 0
    created_at: Optional[datetime] = None
