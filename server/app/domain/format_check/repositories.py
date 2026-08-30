"""格式校验仓储接口。"""
from typing import List, Optional, Tuple

from app.domain.base import Repository
from app.domain.format_check.entities import FormatCheckRecord, FormatRule


class FormatRuleRepository(Repository[FormatRule]):
    def list_active(self) -> List[FormatRule]:
        raise NotImplementedError

    def list_for_check(self, rule_ids: Optional[List[str]]) -> List[FormatRule]:
        """rule_ids 为空时返回全部默认启用规则。"""
        raise NotImplementedError

    def update(self, rule: FormatRule) -> FormatRule:
        raise NotImplementedError

    def hard_delete(self, rule: FormatRule) -> None:
        raise NotImplementedError


class FormatCheckRecordRepository(Repository[FormatCheckRecord]):
    def list_by_user(self, user_id: str, page: int, page_size: int) -> Tuple[List[FormatCheckRecord], int]:
        raise NotImplementedError
