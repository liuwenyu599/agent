"""格式校验 DTO。"""
from typing import List, Optional

from pydantic import BaseModel, Field


class RuleRequest(BaseModel):
    name: str
    target: str
    checks: dict
    severity: str = "error"
    is_default: bool = True
    is_active: bool = True
    remark: Optional[str] = ""


class FixRequest(BaseModel):
    record_id: str
    # 不传（None）时使用持久化的 applied_ids，便于桌面端直接「导出修正稿」
    accepted_indices: Optional[List[int]] = None


class IssueActionRequest(BaseModel):
    """审校工作台单项操作：应用 / 撤销某一条 issue。"""
    issue_id: int = Field(..., description="issue 的稳定整数 id")
