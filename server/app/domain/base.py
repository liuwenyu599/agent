"""Repository 基接口（Application/Domain 只依赖这些抽象）。"""
from abc import ABC
from typing import Generic, Optional, TypeVar

T = TypeVar("T")


class Repository(ABC, Generic[T]):
    """通用仓储接口。各模块在自己的 repository.py 中扩展具体查询方法。"""

    def get(self, id: str) -> Optional[T]:
        raise NotImplementedError

    def add(self, entity: T) -> T:
        raise NotImplementedError

    def delete(self, entity: T) -> None:
        raise NotImplementedError
