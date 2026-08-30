"""用户仓储的 SQLAlchemy 实现。"""
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.identity.entities import User
from app.domain.identity.repositories import UserRepository
from app.infrastructure.database.models.identity import UserModel


def _to_entity(m: UserModel) -> User:
    return User(
        id=m.id,
        username=m.username,
        email=m.email,
        hashed_password=m.hashed_password,
        real_name=m.real_name or "",
        department=m.department or "",
        role=m.role or "user",
        is_active=bool(m.is_active),
        created_at=m.created_at,
        updated_at=m.updated_at,
    )


class SqlAlchemyUserRepository(UserRepository):
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, id: str) -> Optional[User]:
        m = self.db.get(UserModel, id)
        return _to_entity(m) if m else None

    def get_by_username(self, username: str) -> Optional[User]:
        m = self.db.scalar(select(UserModel).where(UserModel.username == username))
        return _to_entity(m) if m else None

    def get_by_email(self, email: str) -> Optional[User]:
        m = self.db.scalar(select(UserModel).where(UserModel.email == email))
        return _to_entity(m) if m else None

    def list_all(self) -> List[User]:
        return [_to_entity(m) for m in self.db.scalars(select(UserModel)).all()]

    def count(self) -> int:
        return len(self.db.scalars(select(UserModel.id)).all())

    def add(self, user: User) -> User:
        m = UserModel(
            username=user.username,
            email=user.email,
            hashed_password=user.hashed_password,
            real_name=user.real_name,
            department=user.department,
            role=user.role,
            is_active=user.is_active,
        )
        self.db.add(m)
        self.db.commit()
        self.db.refresh(m)
        return _to_entity(m)

    def update(self, user: User) -> User:
        m = self.db.get(UserModel, user.id)
        if not m:
            return user
        m.real_name = user.real_name
        m.department = user.department
        m.role = user.role
        m.is_active = user.is_active
        m.hashed_password = user.hashed_password
        self.db.commit()
        self.db.refresh(m)
        return _to_entity(m)

    def delete(self, user: User) -> None:
        m = self.db.get(UserModel, user.id)
        if m:
            m.is_active = False  # 软删除：停用
            self.db.commit()
