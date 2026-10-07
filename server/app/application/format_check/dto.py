"""格式校验 DTO。"""
from typing import List, Optional

from pydantic import BaseModel, Field


class RuleRequest(BaseModel):
    name: str
    target: str
    checks: dict
    severity: str = "error"
    is_default: bool = False
    is_active: bool = True
    remark: Optional[str] = ""


class RuleCompileRequest(BaseModel):
    """白话描述 → AI 生成校验项（不落库，确认后再走规则保存）。"""
    target: str
    description: str
    name: Optional[str] = None


class RuleActiveRequest(BaseModel):
    is_active: bool


class ContentUpdateRequest(BaseModel):
    """工作台中栏的人工正文修改：整篇段落文本，写回记录文件成为新基线。"""
    paragraphs: List[str]


class FixRequest(BaseModel):
    record_id: str
    # 不传（None）时使用持久化的 applied_ids，便于桌面端直接「导出修正稿」
    accepted_indices: Optional[List[int]] = None


class IssueActionRequest(BaseModel):
    """审校工作台单项操作：应用 / 撤销某一条 issue。"""
    issue_id: int = Field(..., description="issue 的稳定整数 id")
