"""身份领域仓储接口。"""
from typing import List, Optional

from app.domain.base import Repository
from app.domain.identity.entities import User


class UserRepository(Repository[User]):
    def get_by_username(self, username: str) -> Optional[User]:
        raise NotImplementedError

    def get_by_email(self, email: str) -> Optional[User]:
        raise NotImplementedError

    def list_all(self) -> List[User]:
        raise NotImplementedError

    def count(self) -> int:
        raise NotImplementedError

    def update(self, user: User) -> User:
        raise NotImplementedError
