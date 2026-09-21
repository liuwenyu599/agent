"""知识库业务服务：知识库管理 + 文档管理（移植旧 knowledge/manager.py 与 api/knowledge.py 的业务规则）。

v3.1 科室强隔离：
- 所有读写一律先经 KnowledgeAccessPolicy 解析「服务端权限」，再由知识库/文档所属科室校验；
- 角色判定统一走 app.domain.identity.authorization，不出现 role == "admin" 字面量；
- 客户端只能传 kb_ids / dept_code 等**收窄**参数，无法扩大可见范围。
"""
from typing import Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.application.knowledge.access import KnowledgeAccessPolicy
from app.application.knowledge.document_service import DocumentService
from app.core.exceptions import NotFoundError, PermissionDeniedError
from app.domain.identity.authorization import is_system_admin, is_knowledge_admin
from app.domain.knowledge.entities import KB_TYPE_PUBLIC, KnowledgeBase
from app.infrastructure.database.models.knowledge import (
    DocumentModel,
    KnowledgeBaseModel,
)
from app.infrastructure.repositories.knowledge import (
    SqlAlchemyDocumentRepository,
    SqlAlchemyKnowledgeBaseRepository,
)

REVIEW_ROLES = ("knowledge_admin",)  # 仅知识管理员可审核（旧规则：系统管理员不参与审核流程）


class KnowledgeService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.kbs = SqlAlchemyKnowledgeBaseRepository(db)
        self.docs = SqlAlchemyDocumentRepository(db)
        self.access = KnowledgeAccessPolicy(db)

    # ---- 权限小工具 ----

    def _can_review(self, user) -> bool:
        """审核权限：系统管理员 + 知识管理员（知识管理员仅限本科室内容，由调用点校验）。"""
        return is_knowledge_admin(user) or is_system_admin(user)

    def _get_kb(self, kb_id: str):
        kb = self.kbs.get_model(kb_id)
        if not kb:
            raise NotFoundError("Knowledge base not found")
        return kb

    # ---- 知识库 ----

    def list_accessible(self, user) -> List[dict]:
        """可见知识库：按服务端解析的科室作用域过滤，前端无法越权获取。"""
        allowed = set(self.access.accessible_kb_ids(user))
        if not allowed:
            return []
        rows = self.db.scalars(
            select(KnowledgeBaseModel).where(KnowledgeBaseModel.id.in_(allowed))
        ).all()
        return [self.kb_to_dict(kb) for kb in rows]

    def get_or_create_personal_kb(self, user_id: str):
        kb = self.kbs.get_personal_kb(user_id)
        if not kb:
            from app.domain.knowledge.entities import KB_TYPE_PERSONAL
            kb = self.kbs.add(KnowledgeBase(
                name="个人知识库", description="用户个人上传的文档",
                kb_type=KB_TYPE_PERSONAL, owner_id=user_id,
            ))
        return kb

    def create_kb(self, user, name: str, description: str = "",
                  kb_type: Optional[str] = None) -> dict:
        """创建知识库。

        - 系统管理员：可创建全局公共知识库（department_code 为空）；
        - 知识管理员：可创建本科室知识库；
        - 普通用户：只能维护自己的个人知识库。
        """
        dept_code = self.access.dept_code_of(user)
        wants_public = (kb_type or "public") == "public"
        if wants_public and is_system_admin(user):
            # 全局公共知识库只有系统管理员可建
            kb = self.kbs.add(KnowledgeBase(
                name=name, description=description, kb_type=KB_TYPE_PUBLIC))
            return {"id": kb.id, "name": kb.name, "type": "public"}
        if wants_public and is_knowledge_admin(user) and dept_code:
            # 知识管理员只能建本科室知识库
            return self._create_dept_kb(name, description, dept_code)
        # 其余：退化为个人知识库
        kb = self.get_or_create_personal_kb(user.id)
        kb.name = name or kb.name
        kb.description = description or kb.description
        kb = self.kbs.update(kb)
        return {"id": kb.id, "name": kb.name, "type": "personal"}

    def _create_dept_kb(self, name: str, description: str, dept_code: str) -> dict:
        kb = self.kbs.add(KnowledgeBase(
            name=name, description=description, kb_type=KB_TYPE_PUBLIC))
        row = self.db.get(KnowledgeBaseModel, kb.id)
        row.department_code = dept_code
        self.db.commit()
        self.db.refresh(row)
        return {"id": row.id, "name": row.name, "type": "public", "department_code": dept_code}

    def get_kb_checked(self, kb_id: str, user):
        """读权限校验：不可见的知识库一律 403（不泄漏是否存在）。"""
        kb = self._get_kb(kb_id)
        if not self.access.can_read_kb(kb, user):
            raise PermissionDeniedError("No permission")
        return kb

    def check_kb_write(self, kb_id: str, user):
        """写权限校验：上传/导入前调用。"""
        kb = self._get_kb(kb_id)
        if not self.access.can_write_kb(kb, user):
            raise PermissionDeniedError("无权向该知识库导入文档")
        return kb

    def get_kb_managed(self, kb_id: str, user):
        """管理权限校验：改名 / 删除 / 审核队列前调用。"""
        kb = self._get_kb(kb_id)
        if not self.access.can_manage_kb(kb, user):
            raise PermissionDeniedError("无权管理该知识库")
        return kb

    def update_kb(self, kb_id: str, name: Optional[str], description: Optional[str], user):
        kb = self.get_kb_managed(kb_id, user)
        if name is not None:
            kb.name = name
        if description is not None:
            kb.description = description
        self.db.commit()
        self.db.refresh(kb)
        return {"id": kb.id, "message": "Updated"}

    def delete_kb(self, kb_id: str, user):
        kb = self.get_kb_managed(kb_id, user)
        _, docs = self.docs.list_by_kb(kb_id, page=1, page_size=100000)
        for doc in docs:
            m = self.db.get(DocumentModel, doc.id)
            if m:
                m.status = "archived"
        kb.is_active = False
        self.db.commit()
        return {"message": "Knowledge base deleted"}

    def kb_to_dict(self, kb) -> dict:
        return {
            "id": kb.id, "name": kb.name, "type": kb.kb_type,
            "description": kb.description,
            "doc_count": self.kbs.published_doc_count(kb.id),
            "created_at": kb.created_at,
            "department_code": getattr(kb, "department_code", "") or "",
        }

    # ---- 文档 ----

    def get_document_checked(self, doc_id: str, user):
        """取文档并校验读权限（审核流程复用）。"""
        doc = self.docs.get_model(doc_id)
        if not doc:
            raise NotFoundError("Document not found")
        if not self.access.can_read_doc(doc, user):
            raise PermissionDeniedError("No permission")
        return doc

    def get_document_detail(self, doc_id: str, user) -> dict:
        doc = self.get_document_checked(doc_id, user)
        can_review = self._can_review(user)
        if not can_review and doc.status != "published":
            raise PermissionDeniedError("Document not available")
        return {
            "id": doc.id, "title": doc.title, "doc_type": doc.doc_type, "status": doc.status,
            "content": doc.content or "", "department": doc.department, "doc_number": doc.doc_number,
            "uploaded_by": doc.uploader.real_name if doc.uploader else None,
            "reviewed_by": doc.reviewer.real_name if doc.reviewer else None,
            "review_comment": doc.review_comment, "created_at": doc.created_at,
            "kb_id": doc.kb_id,
        }

    def update_document(self, doc_id: str, user, title=None, doc_type=None,
                        status=None, department=None, doc_number=None) -> dict:
        doc = self.docs.get_model(doc_id)
        if not doc:
            raise NotFoundError("Document not found")
        if not self.access.can_read_doc(doc, user):
            raise PermissionDeniedError("No permission")
        # 改状态属于审核动作：需对本知识库有管理权限
        manages = self.access.can_manage_doc(doc, user)
        is_owner = doc.uploaded_by == getattr(user, "id", "")
        if not (manages or is_owner):
            raise PermissionDeniedError("No permission")
        if title is not None:
            doc.title = title
        if doc_type is not None:
            doc.doc_type = doc_type
        if status is not None and manages:
            doc.status = status
        if department is not None:
            doc.department = department
        if doc_number is not None:
            doc.doc_number = doc_number
        self.db.commit()
        self.db.refresh(doc)
        return {"id": doc.id, "message": "Updated"}

    def archive_document(self, doc_id: str, user=None) -> dict:
        doc = self.docs.get_model(doc_id)
        if not doc:
            raise NotFoundError("Document not found")
        if user is not None:
            if not (self.access.can_manage_doc(doc, user)
                    or doc.uploaded_by == getattr(user, "id", "")):
                raise PermissionDeniedError("No permission")
        doc.status = "archived"
        self.db.commit()
        return {"message": "Document archived"}

    def list_kb_documents(self, kb_id: str, user, status: str = "published",
                          page: int = 1, page_size: int = 20) -> dict:
        self.get_kb_checked(kb_id, user)
        can_review = self._can_review(user)
        effective_status = None if (status == "all" and can_review) else "published"
        total, items = self.docs.list_with_display(
            kb_id=kb_id, status=effective_status, page=page, page_size=page_size
        )
        return {"total": total, "page": page, "page_size": page_size, "data": items}

    def list_all_documents(self, user, status: str = "all",
                           page: int = 1, page_size: int = 20) -> dict:
        """全量文档列表：按可访问知识库过滤（系统管理员可见全部）。"""
        allowed = self.access.accessible_kb_ids(user)
        if not allowed:
            return {"total": 0, "page": page, "page_size": page_size, "data": []}
        effective = None if status == "all" else status
        q = select(DocumentModel).where(DocumentModel.kb_id.in_(allowed))
        if effective:
            q = q.where(DocumentModel.status == effective)
        q = q.order_by(DocumentModel.created_at.desc())
        total = len(self.db.scalars(q).all())
        rows = self.db.scalars(q.offset((page - 1) * page_size).limit(page_size)).all()
        return {"total": total, "page": page, "page_size": page_size,
                "data": [self.docs._display_dict(m) for m in rows]}

    def list_pending(self, user) -> List[dict]:
        """待审队列：知识管理员仅看本科室，系统管理员看全部。"""
        allowed = set(self.access.accessible_kb_ids(user))
        result = []
        for d in self.docs.list_by_status("pending"):
            if d.kb_id not in allowed:
                continue
            m = self.docs.get_model(d.id)
            if not self.access.can_manage_kb(
                    self.db.get(KnowledgeBaseModel, d.kb_id), user):
                continue
            result.append({
                "id": d.id, "title": d.title, "doc_type": d.doc_type,
                "uploaded_by": m.uploader.real_name if m and m.uploader else None,
                "uploaded_at": d.created_at,
                "kb_name": m.knowledge_base.name if m and m.knowledge_base else None,
            })
        return result

    def assert_can_review(self, doc_id: str, user):
        """审核前置校验：必须是知识管理员/系统管理员，且文档在本人可管理范围内。"""
        if not self._can_review(user):
            raise PermissionDeniedError("仅知识管理员可执行审核操作")
        doc = self.get_document_checked(doc_id, user)
        if not self.access.can_manage_doc(doc, user):
            raise PermissionDeniedError("无权审核该科室的文档")
        return doc

    def stats(self, user_count: int, session_count: int) -> dict:
        return {
            "user_count": user_count,
            "doc_count": self.docs.count(),
            "session_count": session_count,
            "kb_count": self.kbs.count_active(),
            "published": self.docs.count("published"),
            "pending": self.docs.count("pending"),
        }
