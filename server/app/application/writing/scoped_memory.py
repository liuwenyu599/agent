"""Permission-scoped, bounded writing guidance. Facts still come from the task/RAG."""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import and_, or_, select, func
from sqlalchemy.orm import Session

from app.domain.identity.authorization import is_knowledge_admin, is_system_admin
from app.infrastructure.database.models.identity import UserModel
from app.infrastructure.database.models.writing_memory import WritingMemoryModel

SCOPES = frozenset({"public", "department", "personal"})


class ScopedWritingMemory:
    def __init__(self, db: Session):
        self.db = db

    def _user(self, user_id: str) -> UserModel:
        user = self.db.get(UserModel, user_id)
        if user is None or not user.is_active:
            raise HTTPException(403, "用户不可用")
        return user

    @staticmethod
    def _visible_filter(user: UserModel):
        choices = [WritingMemoryModel.scope == "public",
                   and_(WritingMemoryModel.scope == "personal",
                        WritingMemoryModel.owner_user_id == user.id)]
        if user.department_code:
            choices.append(and_(WritingMemoryModel.scope == "department",
                                WritingMemoryModel.department_code == user.department_code))
        return or_(*choices)

    @staticmethod
    def _can_edit(user: UserModel, row: WritingMemoryModel) -> bool:
        if row.scope == "personal":
            return row.owner_user_id == user.id
        if row.scope == "public":
            return is_system_admin(user)
        return (bool(user.department_code) and
                row.department_code == user.department_code and
                (is_system_admin(user) or is_knowledge_admin(user)))

    @staticmethod
    def payload(row: WritingMemoryModel) -> dict:
        return {"id": row.id, "scope": row.scope,
                "document_type": row.document_type, "content": row.content,
                "enabled": row.enabled, "department_code": row.department_code,
                "source": getattr(row, "source", "manual"),
                "can_edit": False}

    def list_visible(self, user_id: str) -> list[dict]:
        user = self._user(user_id)
        rows = self.db.scalars(select(WritingMemoryModel).where(
            self._visible_filter(user)).order_by(WritingMemoryModel.created_at.desc())
            .limit(200)).all()
        result = []
        for row in rows:
            item = self.payload(row)
            item["can_edit"] = self._can_edit(user, row)
            result.append(item)
        return result

    def create(self, user_id: str, scope: str, document_type: str,
               content: str) -> dict:
        user = self._user(user_id)
        if scope not in SCOPES:
            raise HTTPException(400, "记忆范围无效")
        if scope == "public" and not is_system_admin(user):
            raise HTTPException(403, "只有系统管理员可设置公共记忆")
        if scope == "department" and not (
                user.department_code and
                (is_knowledge_admin(user) or is_system_admin(user))):
            raise HTTPException(403, "只有本科室管理员可设置科室记忆")
        content = content.strip()
        document_type = document_type.strip()
        if not content or len(content) > 500 or len(document_type) > 100:
            raise HTTPException(400, "记忆内容须为 1 至 500 字，文种不超过 100 字")
        owner = user.id if scope == "personal" else None
        dept = user.department_code if scope == "department" else ""
        count = self.db.scalar(select(func.count(WritingMemoryModel.id)).where(
            WritingMemoryModel.scope == scope,
            WritingMemoryModel.owner_user_id == owner if scope == "personal"
            else WritingMemoryModel.department_code == dept,
        )) or 0
        if count >= (30 if scope == "personal" else 50):
            raise HTTPException(409, "此范围的记忆条目已满，请先整理旧条目")
        row = WritingMemoryModel(scope=scope, owner_user_id=owner,
                                 department_code=dept, created_by=user.id,
                                 document_type=document_type, content=content,
                                 source="manual")
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        result = self.payload(row)
        result["can_edit"] = True
        return result

    def update(self, user_id: str, memory_id: str, *, content: str | None = None,
               document_type: str | None = None, enabled: bool | None = None) -> dict:
        user = self._user(user_id)
        row = self.db.get(WritingMemoryModel, memory_id)
        if row is None or not self._can_edit(user, row):
            raise HTTPException(404, "记忆不存在")
        if content is not None:
            content = content.strip()
            if not content or len(content) > 500:
                raise HTTPException(400, "记忆内容须为 1 至 500 字")
            row.content = content
        if document_type is not None:
            if len(document_type.strip()) > 100:
                raise HTTPException(400, "文种不能超过 100 字")
            row.document_type = document_type.strip()
        if enabled is not None:
            row.enabled = enabled
        self.db.commit()
        result = self.payload(row)
        result["can_edit"] = True
        return result

    def delete(self, user_id: str, memory_id: str) -> None:
        user = self._user(user_id)
        row = self.db.get(WritingMemoryModel, memory_id)
        if row is None or not self._can_edit(user, row):
            raise HTTPException(404, "记忆不存在")
        self.db.delete(row)
        self.db.commit()

    def prompt_block(self, user_id: str, document_type: str, budget: int = 800) -> str:
        user = self._user(user_id)
        rows = self.db.scalars(select(WritingMemoryModel).where(
            self._visible_filter(user), WritingMemoryModel.enabled.is_(True),
            or_(WritingMemoryModel.document_type == "",
                WritingMemoryModel.document_type == document_type),
        ).order_by(WritingMemoryModel.updated_at.desc()).limit(150)).all()
        # Read in precedence order; later scopes may refine earlier style guidance.
        parts = []
        remaining = max(0, min(budget, 1200))
        for scope, label in (("public", "公共"), ("department", "本科室"),
                             ("personal", "个人")):
            for row in (r for r in rows if r.scope == scope):
                if len(parts) >= 8:
                    break
                line = f"{label}·{row.document_type or '通用'}：{row.content.strip()}"
                if len(line) + 1 <= remaining:
                    parts.append(line)
                    remaining -= len(line) + 1
        if not parts:
            return ""
        return ("\n\n【写作习惯记忆】\n" + "\n".join(parts) +
                "\n仅用于语气、结构和习惯；本次用户要求优先。不得把记忆中的事实、"
                "日期、数字或单位名称当作本次依据，也不得改变知识库权限。")
