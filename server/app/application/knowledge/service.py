"""知识库业务服务：知识库管理 + 文档管理（移植旧 knowledge/manager.py 与 api/knowledge.py 的业务规则）。"""
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.application.knowledge.document_service import DocumentService
from app.core.exceptions import NotFoundError, PermissionDeniedError
from app.domain.identity.entities import ADMIN_OR_ABOVE, ROLE_DEVELOPER, ROLE_KNOWLEDGE_ADMIN, User
from app.infrastructure.repositories.knowledge import (
    SqlAlchemyDocumentRepository,
    SqlAlchemyKnowledgeBaseRepository,
)

REVIEW_ROLES = (ROLE_KNOWLEDGE_ADMIN,)  # 仅知识管理员可审核（旧规则：developer 不可审核）
MANAGE_ROLES = (ROLE_KNOWLEDGE_ADMIN, ROLE_DEVELOPER)


class KnowledgeService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.kbs = SqlAlchemyKnowledgeBaseRepository(db)
        self.docs = SqlAlchemyDocumentRepository(db)

    # ---- 知识库 ----
    def list_accessible(self, user: User) -> List[dict]:
        result = []
        for kb in self.kbs.list_accessible(user.id, user.role):
            result.append({
                "id": kb.id, "name": kb.name, "type": kb.kb_type,
                "description": kb.description,
                "doc_count": self.kbs.published_doc_count(kb.id),
                "created_at": kb.created_at,
            })
        return result

    def get_or_create_personal_kb(self, user_id: str):
        kb = self.kbs.get_personal_kb(user_id)
        if not kb:
            from app.domain.knowledge.entities import KB_TYPE_PERSONAL, KnowledgeBase
            kb = self.kbs.add(KnowledgeBase(
                name="个人知识库", description="用户个人上传的文档",
                kb_type=KB_TYPE_PERSONAL, owner_id=user_id,
            ))
        return kb

    def create_kb(self, user: User, name: str, description: str = "",
                  kb_type: Optional[str] = None) -> dict:
        from app.domain.knowledge.entities import KB_TYPE_PUBLIC, KnowledgeBase
        if user.role in ADMIN_OR_ABOVE:
            if (kb_type or "public") == "public":
                kb = self.kbs.add(KnowledgeBase(name=name, description=description, kb_type=KB_TYPE_PUBLIC))
                return {"id": kb.id, "name": kb.name, "type": "public"}
        # 普通用户只能创建/更新个人知识库
        kb = self.get_or_create_personal_kb(user.id)
        kb.name = name or kb.name
        kb.description = description or kb.description
        kb = self.kbs.update(kb)
        return {"id": kb.id, "name": kb.name, "type": "personal"}

    def get_kb_checked(self, kb_id: str, user: User):
        kb = self.kbs.get(kb_id)
        if not kb:
            raise NotFoundError("Knowledge base not found")
        if kb.kb_type == "personal" and kb.owner_id != user.id:
            raise PermissionDeniedError("No permission")
        return kb

    def check_kb_write(self, kb_id: str, user: User):
        kb = self.get_kb_checked(kb_id, user)
        if kb.kb_type == "public" and user.role not in ADMIN_OR_ABOVE:
            raise PermissionDeniedError("公共知识库仅管理员可导入")
        return kb

    def update_kb(self, kb_id: str, name: Optional[str], description: Optional[str]):
        kb = self.kbs.get(kb_id)
        if not kb:
            raise NotFoundError("Knowledge base not found")
        if name is not None:
            kb.name = name
        if description is not None:
            kb.description = description
        self.kbs.update(kb)
        return {"id": kb.id, "message": "Updated"}

    def delete_kb(self, kb_id: str):
        kb = self.kbs.get(kb_id)
        if not kb:
            raise NotFoundError("Knowledge base not found")
        _, docs = self.docs.list_by_kb(kb_id, page=1, page_size=100000)
        for doc in docs:
            doc.status = "archived"
            self.docs.update(doc)
        self.kbs.delete(kb)
        return {"message": "Knowledge base deleted"}

    def kb_to_dict(self, kb) -> dict:
        return {
            "id": kb.id, "name": kb.name, "type": kb.kb_type,
            "description": kb.description,
            "doc_count": self.kbs.published_doc_count(kb.id),
            "created_at": kb.created_at,
        }

    # ---- 文档 ----
    def get_document_detail(self, doc_id: str, user: User) -> dict:
        doc = self.docs.get_model(doc_id)
        if not doc:
            raise NotFoundError("Document not found")
        kb = doc.knowledge_base
        if kb.kb_type == "personal" and kb.owner_id != user.id:
            raise PermissionDeniedError("No permission")
        if user.role not in MANAGE_ROLES and doc.status != "published":
            raise PermissionDeniedError("Document not available")
        return {
            "id": doc.id, "title": doc.title, "doc_type": doc.doc_type, "status": doc.status,
            "content": doc.content or "", "department": doc.department, "doc_number": doc.doc_number,
            "uploaded_by": doc.uploader.real_name if doc.uploader else None,
            "reviewed_by": doc.reviewer.real_name if doc.reviewer else None,
            "review_comment": doc.review_comment, "created_at": doc.created_at,
        }

    def update_document(self, doc_id: str, user: User, title=None, doc_type=None,
                        status=None, department=None, doc_number=None) -> dict:
        doc = self.docs.get(doc_id)
        if not doc:
            raise NotFoundError("Document not found")
        if doc.uploaded_by != user.id and user.role not in MANAGE_ROLES:
            raise PermissionDeniedError("No permission")
        if title is not None:
            doc.title = title
        if doc_type is not None:
            doc.doc_type = doc_type
        if status is not None and user.role in MANAGE_ROLES:
            doc.status = status
        if department is not None:
            doc.department = department
        if doc_number is not None:
            doc.doc_number = doc_number
        self.docs.update(doc)
        return {"id": doc.id, "message": "Updated"}

    def archive_document(self, doc_id: str, user: User = None) -> dict:
        doc = self.docs.get(doc_id)
        if not doc:
            raise NotFoundError("Document not found")
        if user and doc.uploaded_by != user.id and user.role not in MANAGE_ROLES:
            raise PermissionDeniedError("No permission")
        self.docs.delete(doc)  # delete = 归档（软删除）
        return {"message": "Document archived"}

    def list_kb_documents(self, kb_id: str, user: User, status: str = "published",
                          page: int = 1, page_size: int = 20) -> dict:
        self.get_kb_checked(kb_id, user)
        effective_status = None if status == "all" else status
        if user.role not in MANAGE_ROLES:
            effective_status = "published"
        total, items = self.docs.list_with_display(
            kb_id=kb_id, status=effective_status, page=page, page_size=page_size
        )
        return {"total": total, "page": page, "page_size": page_size, "data": items}

    def list_all_documents(self, status: str = "all", page: int = 1, page_size: int = 20) -> dict:
        effective = None if status == "all" else status
        total, items = self.docs.list_with_display(
            status=effective, page=page, page_size=page_size, order_desc=True
        )
        return {"total": total, "page": page, "page_size": page_size, "data": items}

    def list_pending(self) -> List[dict]:
        docs = self.docs.list_by_status("pending")
        result = []
        for d in docs:
            m = self.docs.get_model(d.id)
            result.append({
                "id": d.id, "title": d.title, "doc_type": d.doc_type,
                "uploaded_by": m.uploader.real_name if m and m.uploader else None,
                "uploaded_at": d.created_at,
                "kb_name": m.knowledge_base.name if m and m.knowledge_base else None,
            })
        return result

    def stats(self, user_count: int, session_count: int) -> dict:
        return {
            "user_count": user_count,
            "doc_count": self.docs.count(),
            "session_count": session_count,
            "kb_count": self.kbs.count_active(),
            "published": self.docs.count("published"),
            "pending": self.docs.count("pending"),
        }
