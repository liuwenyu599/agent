"""知识库访问策略（v3.1 科室强隔离）。

服务端**唯一的**知识权限判定入口。所有知识库/文档的读写、审核、检索，
都必须先经过本模块解析出「用户可访问的知识库集合」与「可召回的 scope 集合」，
再与客户端传入的 kb_ids / scopes / dept_code 取**交集**——
客户端参数只能缩小范围，永远不能扩大权限。

权限矩阵：
| 角色             | 全局公共知识 | 本科室知识 | 其他科室知识 | 个人知识库 | 管理范围           |
|------------------|--------------|------------|--------------|------------|--------------------|
| developer(系统)  | 读写管       | 读写管     | 读写管       | 本人       | 全局               |
| admin(历史)      | 读写管       | 读写管     | 读写管       | 本人       | 全局               |
| knowledge_admin  | 读           | 读写管     | 不可见       | 本人       | 仅本科室           |
| user             | 读           | 读         | 不可见       | 本人读写   | 无                 |
"""
from typing import List, Optional

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.domain.identity.authorization import (
    is_knowledge_admin,
    is_system_admin,
    role_of,
)
from app.domain.organization.departments import (
    SCOPE_GLOBAL,
    dept_scope,
    resolve_code,
    user_scope,
)
from app.infrastructure.database.models.identity import UserModel
from app.infrastructure.database.models.knowledge import KnowledgeBaseModel

# 知识库载体类型
KB_TYPE_PERSONAL = "personal"


class KnowledgeAccessPolicy:
    """按当前登录用户解析科室归属，推导知识可见/可写/可管理范围。"""

    def __init__(self, db: Session) -> None:
        self.db = db

    # ---------------- 用户上下文（服务端解析，不信任任何入参） ----------------

    def dept_code_of(self, user) -> str:
        """用户所属科室 code。

        优先级：实体已带 department_code → users 表 → 按 department 名称反查。
        无法解析时保持空串（仅可见全局公共知识），绝不猜测归口。
        """
        code = (getattr(user, "department_code", "") or "").strip()
        if code:
            return code
        row = None
        user_id = getattr(user, "id", "")
        if user_id:
            row = self.db.get(UserModel, user_id)
            if row is not None:
                code = (getattr(row, "department_code", "") or "").strip()
                if code:
                    return code
        name = (getattr(user, "department", "") or getattr(row, "department", "") or "").strip()
        return resolve_code(name)

    def is_system_admin(self, user) -> bool:
        """系统管理员判定：实体角色优先，缺失时回落 users 表。"""
        role = role_of(user)
        if not role and getattr(user, "id", ""):
            row = self.db.get(UserModel, user.id)
            role = role_of(row)
        return is_system_admin(role)

    def is_dept_admin(self, user) -> bool:
        """本科室知识管理员。"""
        role = role_of(user)
        if not role and getattr(user, "id", ""):
            row = self.db.get(UserModel, user.id)
            role = role_of(row)
        return is_knowledge_admin(role)

    # ---------------- 知识库范围 ----------------

    def accessible_kb_ids(self, user) -> List[str]:
        """可访问知识库 id（系统管理员为全部）。"""
        if self.is_system_admin(user):
            return [kb.id for kb in self.db.scalars(
                select(KnowledgeBaseModel).where(KnowledgeBaseModel.is_active.is_(True))
            ).all()]

        user_id = getattr(user, "id", "") or ""
        dept_code = self.dept_code_of(user)
        conds = [
            # 全局公共知识库（department_code 为空且非个人库）
            (KnowledgeBaseModel.department_code == "") & (KnowledgeBaseModel.kb_type != KB_TYPE_PERSONAL),
            # 本人个人知识库
            (KnowledgeBaseModel.kb_type == KB_TYPE_PERSONAL) & (KnowledgeBaseModel.owner_id == user_id),
        ]
        if dept_code:
            conds.append(KnowledgeBaseModel.department_code == dept_code)
        return [kb.id for kb in self.db.scalars(
            select(KnowledgeBaseModel).where(
                KnowledgeBaseModel.is_active.is_(True), or_(*conds))
        ).all()]

    def can_read_kb(self, kb, user) -> bool:
        if kb is None:
            return False
        if self.is_system_admin(user):
            return True
        if kb.kb_type == KB_TYPE_PERSONAL:
            return kb.owner_id == getattr(user, "id", "")
        dept_code = self.dept_code_of(user)
        if getattr(kb, "department_code", "") or "":
            return bool(dept_code) and kb.department_code == dept_code
        return not getattr(kb, "department_code", "")

    def can_write_kb(self, kb, user) -> bool:
        """能否向该知识库导入/上传文档。"""
        if kb is None:
            return False
        if self.is_system_admin(user):
            return True
        if kb.kb_type == KB_TYPE_PERSONAL:
            return kb.owner_id == getattr(user, "id", "")
        # 科室库：仅本科室知识管理员；全局公共库：仅系统管理员
        dept_code = self.dept_code_of(user)
        if not dept_code:
            return False
        return self.is_dept_admin(user) and kb.department_code == dept_code

    def can_manage_kb(self, kb, user) -> bool:
        """能否改名/删除知识库、以及审核其下文档。"""
        if kb is None:
            return False
        if self.is_system_admin(user):
            return True
        if kb.kb_type == KB_TYPE_PERSONAL:
            return kb.owner_id == getattr(user, "id", "")
        dept_code = self.dept_code_of(user)
        if not dept_code:
            return False
        return self.is_dept_admin(user) and kb.department_code == dept_code

    # ---------------- 文档 ----------------

    def can_read_doc(self, doc, user) -> bool:
        """文档可读性：先看所属知识库，再看文档自身科室标记。"""
        if doc is None:
            return False
        kb = getattr(doc, "knowledge_base", None)
        if kb is None and getattr(doc, "kb_id", ""):
            kb = self.db.get(KnowledgeBaseModel, doc.kb_id)
        if not self.can_read_kb(kb, user):
            return False
        if self.is_system_admin(user):
            return True
        doc_dept = (getattr(doc, "department_code", "") or "").strip()
        if doc_dept and doc_dept != self.dept_code_of(user):
            return False
        return True

    def filter_readable_docs(self, docs, user) -> List:
        """按文档级可见性过滤，保证**列表与详情同口径**。

        ``can_read_doc`` 有两道校验：先看所属知识库，再看文档自身 department_code。
        但列表接口历史上只按 kb_id 取交集，漏掉了第二道——于是文档标了他人科室时
        会出现「列表看得到标题、点进详情才 403」的半泄漏：用户察觉不到自己已经
        看到了越权标题，而列表与详情两套口径本身也是缺陷。

        这里一次性解析用户科室与可访问知识库，再逐条跑与 can_read_doc 完全相同的
        判定，避免列表接口退化成 can_read_doc 的旁路。
        """
        if self.is_system_admin(user):
            return list(docs)
        dept_code = self.dept_code_of(user)
        allowed_kb = set(self.accessible_kb_ids(user))
        result = []
        for d in docs:
            if getattr(d, "kb_id", "") not in allowed_kb:
                continue
            doc_dept = (getattr(d, "department_code", "") or "").strip()
            if doc_dept and doc_dept != dept_code:
                continue
            result.append(d)
        return result

    def can_manage_doc(self, doc, user) -> bool:
        """文档可管理性（改状态/审核/归档）。"""
        if doc is None:
            return False
        kb = getattr(doc, "knowledge_base", None)
        if kb is None and getattr(doc, "kb_id", ""):
            kb = self.db.get(KnowledgeBaseModel, doc.kb_id)
        return self.can_manage_kb(kb, user)

    # ---------------- 检索作用域 ----------------

    def scopes_of(self, user) -> Optional[List[str]]:
        """允许召回的作用域；系统管理员返回 None（不限制）。"""
        if self.is_system_admin(user):
            return None
        scopes = [SCOPE_GLOBAL, user_scope(getattr(user, "id", "") or "")]
        dept_code = self.dept_code_of(user)
        if dept_code:
            scopes.append(dept_scope(dept_code))
        return scopes

    def intersect_kb_ids(self, user, kb_ids: Optional[List[str]]) -> List[str]:
        """客户端传入的 kb_ids 与可访问集合取交集（服务端权限覆盖客户端参数）。"""
        allowed = set(self.accessible_kb_ids(user))
        if not kb_ids:
            return sorted(allowed)
        return [k for k in kb_ids if k in allowed]

    def intersect_scopes(self, user, scopes: Optional[List[str]]) -> Optional[List[str]]:
        """客户端传入的 scopes 与服务端作用域取交集；系统管理员恒为 None。"""
        allowed = self.scopes_of(user)
        if allowed is None:
            return None
        if not scopes:
            return allowed
        allowed_set = set(allowed)
        return [s for s in scopes if s in allowed_set]


def scope_of_kb(kb) -> str:
    """知识库对应的向量作用域：个人库按 owner 隔离，科室库按科室隔离，其余全局。"""
    if kb is None:
        return SCOPE_GLOBAL
    if getattr(kb, "kb_type", "") == KB_TYPE_PERSONAL:
        return user_scope(getattr(kb, "owner_id", "") or "")
    dept_code = (getattr(kb, "department_code", "") or "").strip()
    return dept_scope(dept_code) if dept_code else SCOPE_GLOBAL


def scope_of_doc(db, doc) -> str:
    """文档对应的向量作用域：由其所属知识库决定。"""
    kb = getattr(doc, "knowledge_base", None)
    if kb is None and getattr(doc, "kb_id", ""):
        kb = db.get(KnowledgeBaseModel, doc.kb_id)
    return scope_of_kb(kb)
