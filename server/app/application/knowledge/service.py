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
from app.core.exceptions import AppError, NotFoundError, PermissionDeniedError
from app.domain.identity.authorization import is_system_admin, is_knowledge_admin
from app.domain.knowledge.entities import (
    KB_TYPE_PERSONAL,
    KB_TYPE_PUBLIC,
    KnowledgeBase,
)
from app.infrastructure.database.models.knowledge import (
    DocumentModel,
    KnowledgeBaseModel,
)
from app.infrastructure.repositories.knowledge import (
    SqlAlchemyDocumentRepository,
    SqlAlchemyKnowledgeBaseRepository,
)

REVIEW_ROLES = ("knowledge_admin",)  # 仅科室管理员可审核（旧规则：系统管理员不参与审核流程）


class KnowledgeService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.kbs = SqlAlchemyKnowledgeBaseRepository(db)
        self.docs = SqlAlchemyDocumentRepository(db)
        self.access = KnowledgeAccessPolicy(db)

    # ---- 权限小工具 ----

    def _can_review(self, user) -> bool:
        """审核权限：系统管理员 + 科室管理员（科室管理员仅限本科室内容，由调用点校验）。"""
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
            kb = self.kbs.add(KnowledgeBase(
                name="个人知识库", description="用户个人上传的文档",
                kb_type=KB_TYPE_PERSONAL, owner_id=user_id,
            ))
        return kb

    def create_kb(self, user, name: str, description: str = "",
                  kb_type: Optional[str] = None) -> dict:
        """创建知识库，按 kb_type 分为三类：

        - public：全局公共知识库，仅系统管理员可创建；
        - department：本科室知识库，科室管理员 / 系统管理员可创建（科室归属由服务端写入）；
        - personal（默认）：个人知识库，任何登录用户可创建，仅本人可见。
        """
        kind = (kb_type or "personal").strip().lower()
        dept_code = self.access.dept_code_of(user)

        if kind == "public":
            if not is_system_admin(user):
                raise PermissionDeniedError("公共知识库仅系统管理员可创建")
            kb = self.kbs.add(KnowledgeBase(
                name=name, description=description, kb_type=KB_TYPE_PUBLIC))
            return {"id": kb.id, "name": kb.name, "type": "public"}

        if kind == "department":
            if not (is_knowledge_admin(user) or is_system_admin(user)):
                raise PermissionDeniedError("科室知识库仅科室管理员可创建")
            if not dept_code:
                raise PermissionDeniedError("当前账号未归属科室，无法创建科室知识库")
            return self._create_dept_kb(name, description, dept_code)

        # 个人知识库：每次创建都是新库，归属本人
        kb = self.kbs.add(KnowledgeBase(
            name=name or "个人知识库", description=description,
            kb_type=KB_TYPE_PERSONAL, owner_id=user.id,
        ))
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

    def _change_kb_type(self, kb, kb_type: str, user) -> None:
        """调整知识库类型（科室管理员 / 系统管理员均可发起，管理权限已在上层校验）。

        - public：全员可见，仅系统管理员可设置（与创建规则一致）；
        - department：科室管理员 / 系统管理员可设置，科室归属按当前账号服务端解析；
        - personal：仅本人可见，无 owner 时归属当前操作人。
        """
        kind = (kb_type or "").strip().lower()
        if kind == "public":
            if not is_system_admin(user):
                raise PermissionDeniedError("仅系统管理员可将知识库设为公共（全员可见）")
            kb.kb_type = KB_TYPE_PUBLIC
            # department_code 列 NOT NULL：清空归属必须写空串，写 None 会 500
            kb.department_code = ""
            kb.owner_id = None
        elif kind == "department":
            if not (is_knowledge_admin(user) or is_system_admin(user)):
                raise PermissionDeniedError("仅科室管理员可设置科室知识库")
            dept = self.access.dept_code_of(user)
            if not dept:
                raise PermissionDeniedError("当前账号未归属科室，无法设置科室知识库")
            kb.kb_type = KB_TYPE_PUBLIC
            kb.department_code = dept
            kb.owner_id = None
        elif kind == "personal":
            kb.kb_type = KB_TYPE_PERSONAL
            # department_code 列 NOT NULL：清空归属必须写空串，写 None 会 500
            kb.department_code = ""
            if not getattr(kb, "owner_id", None):
                kb.owner_id = user.id
        else:
            raise AppError(400, "kb_type 必须是 public / department / personal")

    def update_kb(self, kb_id: str, name: Optional[str], description: Optional[str],
                  user, kb_type: Optional[str] = None):
        kb = self.get_kb_managed(kb_id, user)
        if name is not None:
            kb.name = name
        if description is not None:
            kb.description = description
        if kb_type is not None:
            self._change_kb_type(kb, kb_type, user)
        self.db.commit()
        self.db.refresh(kb)
        return {"id": kb.id, "message": "Updated",
                "type": kb.kb_type,
                "department_code": getattr(kb, "department_code", "") or "",
                # 返回生效后的类型中文名，前端据此核对「所选类型」与「实际生效类型」是否一致
                "type_label": ("科室" if getattr(kb, "department_code", "") else
                               ("公共" if kb.kb_type == "public" else "个人"))}

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

    def search_kb_documents(self, kb_id: str, user, query: str,
                            limit: int = 50) -> dict:
        """库内文档搜索：标题命中排前、内容命中排后，每篇文档只出现一次。

        一次请求返回全部结果（不分多次查询），前端拿到即展示；
        内容命中的条目附带命中片段（前后各约 40/60 字），便于不打开全文先判断。
        """
        self.get_kb_checked(kb_id, user)
        needle = (query or "").strip().lower()
        if not needle:
            return {"total": 0, "data": []}
        can_review = self._can_review(user)
        q = select(DocumentModel).where(DocumentModel.kb_id == kb_id)
        if not can_review:
            q = q.where(DocumentModel.status == "published")
        rows = self.db.scalars(
            q.order_by(DocumentModel.created_at.desc())).all()

        title_hits: List[DocumentModel] = []
        content_hits: List[DocumentModel] = []
        for m in rows:
            if needle in (m.title or "").lower():
                title_hits.append(m)
            elif needle in (m.content or "").lower():
                content_hits.append(m)

        def to_item(m, match: str) -> dict:
            d = dict(self.docs._display_dict(m))
            d["match"] = match
            if match == "content":
                content = m.content or ""
                idx = content.lower().find(needle)
                if idx >= 0:
                    start = max(0, idx - 40)
                    d["snippet"] = content[start:idx + len(needle) + 60].strip()
            return d

        data = [to_item(m, "title") for m in title_hits]
        data += [to_item(m, "content") for m in content_hits]
        data = data[:max(1, min(limit, 200))]
        return {"total": len(data), "data": data}

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
        """待审队列：科室管理员仅看本科室，系统管理员看全部。"""
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
        """审核前置校验：必须是科室管理员/系统管理员，且文档在本人可管理范围内。"""
        if not self._can_review(user):
            raise PermissionDeniedError("仅科室管理员可执行审核操作")
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
