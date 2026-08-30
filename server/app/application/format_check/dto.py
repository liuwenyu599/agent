"""格式校验 DTO。"""
from typing import List, Optional

from pydantic import BaseModel


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
    accepted_indices: List[int]
