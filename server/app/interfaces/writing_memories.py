"""Manage writing habits at public, department and personal scopes."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.application.writing.scoped_memory import ScopedWritingMemory
from app.domain.identity.entities import User
from app.infrastructure.database import get_db
from app.interfaces.deps import get_current_user

router = APIRouter(prefix="/writing/memories", tags=["写作记忆"])


class CreateMemory(BaseModel):
    scope: str
    document_type: str = Field(default="", max_length=100)
    content: str = Field(min_length=1, max_length=500)
    model_config = {"extra": "forbid"}


class UpdateMemory(BaseModel):
    document_type: str | None = Field(default=None, max_length=100)
    content: str | None = Field(default=None, min_length=1, max_length=500)
    enabled: bool | None = None
    model_config = {"extra": "forbid"}


@router.get("")
def list_memories(db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    return {"items": ScopedWritingMemory(db).list_visible(user.id)}


@router.post("")
def create_memory(payload: CreateMemory, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    return ScopedWritingMemory(db).create(user.id, payload.scope,
                                          payload.document_type, payload.content)


@router.patch("/{memory_id}")
def update_memory(memory_id: str, payload: UpdateMemory,
                  db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    return ScopedWritingMemory(db).update(user.id, memory_id,
        **payload.model_dump(exclude_unset=True))


@router.delete("/{memory_id}")
def delete_memory(memory_id: str, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    ScopedWritingMemory(db).delete(user.id, memory_id)
    return {"deleted": True}
