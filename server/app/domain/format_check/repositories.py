"""格式校验仓储接口。"""
from typing import List, Optional, Tuple

from app.domain.base import Repository
from app.domain.format_check.entities import FormatCheckRecord, FormatRule


class FormatRuleRepository(Repository[FormatRule]):
    def ensure_user_defaults(self, user_id: str) -> None:
        raise NotImplementedError

    def list_by_user(self, user_id: str) -> List[FormatRule]:
        raise NotImplementedError

    def get_owned(self, rule_id: str, user_id: str) -> Optional[FormatRule]:
        raise NotImplementedError

    def list_for_check(self, user_id: str, rule_ids: Optional[List[str]]) -> List[FormatRule]:
        """只返回该用户已启用的规则。"""
        raise NotImplementedError

    def update(self, rule: FormatRule) -> FormatRule:
        raise NotImplementedError

    def hard_delete(self, rule: FormatRule) -> None:
        raise NotImplementedError


class FormatCheckRecordRepository(Repository[FormatCheckRecord]):
    def list_by_user(self, user_id: str, page: int, page_size: int) -> Tuple[List[FormatCheckRecord], int]:
        raise NotImplementedError
