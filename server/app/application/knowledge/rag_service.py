"""RAG 检索服务（移植自旧 services/rag_service.py）。

向量检索 + 阈值过滤；范文检索按文档聚合取整篇。
chat 模块通过本服务检索知识库，不直接访问向量库。
"""
import re

from typing import Dict, List

from sqlalchemy import select, or_
from sqlalchemy.orm import Session

from app.application.ports import Embedder, VectorStore
from app.core.config import settings
from app.core.logging import get_logger
from app.domain.identity.authorization import is_system_admin
from app.domain.organization.departments import (
    SCOPE_GLOBAL,
    dept_scope,
    user_scope,
)
from app.infrastructure.database.models.identity import UserModel
from app.infrastructure.database.models.knowledge import (
    ChunkModel,
    DocumentModel,
    KnowledgeBaseModel,
)

logger = get_logger(__name__)


class RagService:
    def __init__(self, db: Session, embedder: Embedder, vector_store: VectorStore) -> None:
        self.db = db
        self.embedder = embedder
        self.vector_store = vector_store

    # ---------------- 组织隔离：作用域解析 ----------------

    @property
    def access(self):
        """知识访问策略（唯一权限判定入口）。"""
        if getattr(self, "_access", None) is None:
            from app.application.knowledge.access import KnowledgeAccessPolicy
            self._access = KnowledgeAccessPolicy(self.db)
        return self._access

    def _user_row(self, user_id: str):
        return self.db.get(UserModel, user_id)

    def _dept_code_of(self, user_id: str) -> str:
        user = self._user_row(user_id)
        code = getattr(user, "department_code", "") or ""
        if code:
            return code
        # 历史数据：按部门名称反查，不做猜测
        from app.domain.organization.departments import resolve_code
        return resolve_code(getattr(user, "department", "") or "")

    def _is_admin(self, user_id: str) -> bool:
        """系统管理员判定（developer 正式角色 + admin 历史兼容）。"""
        user = self._user_row(user_id)
        return is_system_admin(getattr(user, "role", "") or "")

    @staticmethod
    def resolve_scopes(dept_code: str, is_admin: bool = False,
                       user_id: str = "") -> List[str]:
        """用户可见作用域：GLOBAL + 本人个人 + 本人所属科室。

        系统管理员返回 None 表示不限制。该作用域下传到 FAISS 召回阶段，
        越权向量不参与 Top-K 竞争。
        """
        if is_admin:
            return None  # None 表示不限制（仅系统管理员）
        scopes = [SCOPE_GLOBAL]
        if user_id:
            scopes.append(user_scope(user_id))
        if dept_code:
            scopes.append(dept_scope(dept_code))
        return scopes

    def _get_accessible_kb_ids(self, user_id: str, dept_code: str = "",
                               is_admin: bool = False) -> List[str]:
        """可访问知识库：全局公共 + 个人 + 本人科室（系统管理员全部）。"""
        if is_admin:
            kbs = self.db.scalars(
                select(KnowledgeBaseModel).where(KnowledgeBaseModel.is_active.is_(True))
            ).all()
            return [kb.id for kb in kbs]

        conds = [
            (KnowledgeBaseModel.kb_type != "personal")
            & (KnowledgeBaseModel.department_code == ""),
            (KnowledgeBaseModel.kb_type == "personal")
            & (KnowledgeBaseModel.owner_id == user_id),
        ]
        if dept_code:
            conds.append(KnowledgeBaseModel.department_code == dept_code)
        kbs = self.db.scalars(
            select(KnowledgeBaseModel).where(
                KnowledgeBaseModel.is_active.is_(True), or_(*conds))
        ).all()
        return [kb.id for kb in kbs]

    def search(self, query: str, user_id: str, kb_types: List[str] = None,
               top_k: int = None, min_score: float = None,
               kb_ids: List[str] = None, dept_code: str = None,
               scopes: List[str] = None) -> List[Dict]:
        """向量检索为主；向量库不可用或结果不足时，回退关键词检索（SQL LIKE）。

        :param kb_ids: 限定检索的知识库（写作任务关联知识库）；与可访问库取交集，
                       传 None 表示全部可访问库。
        :param dept_code: **忽略**——用户所属科室一律由服务端从 users 表解析，
                       客户端传值无法扩大检索范围。
        :param scopes: 允许的作用域（GLOBAL / DEPT:x / USER:id）；
                       与服务端解析出的作用域取交集，系统管理员恒为全部。
        """
        top_k = top_k or settings.RAG_TOP_K
        min_score = min_score if min_score is not None else settings.RAG_SCORE_THRESHOLD

        # 服务端解析，不信任入参
        dept_code = self._dept_code_of(user_id)
        admin = self._is_admin(user_id)

        # 客户端 scopes 只能收窄，不能放大
        server_scopes = self.resolve_scopes(dept_code, admin, user_id)
        if server_scopes is None:
            scopes = None  # 系统管理员：不限制
        elif scopes:
            allowed = set(server_scopes)
            scopes = [s for s in scopes if s in allowed]
        else:
            scopes = server_scopes

        accessible = self._get_accessible_kb_ids(user_id, dept_code, admin)
        if kb_ids:
            keep = set(kb_ids)
            accessible = [k for k in accessible if k in keep]
        kb_ids = accessible
        if not kb_ids:
            return []

        logger.info("[RAG] 查询: %s（scope=%s）", query, scopes or "ALL")

        # 向量检索（向量库可用时）
        vector_hits = []
        if self.vector_store is not None:
            try:
                query_vec = self.embedder.encode_queries([query])[0]
                vector_hits = self.vector_store.search(
                    query_vec, kb_ids, top_k=20, scopes=scopes)
                logger.info("[RAG] 原始向量命中: %d 个", len(vector_hits))
            except Exception as e:
                logger.warning("[RAG] 向量检索失败，回退关键词检索: %s", e)
                vector_hits = []

        results = []
        seen_chunks = set()

        for hit in vector_hits:
            if hit["distance"] < min_score:
                logger.info("[RAG] 过滤低分: score=%.3f < %.3f", hit["distance"], min_score)
                continue

            chunk_id = hit["chunk_id"]
            if chunk_id in seen_chunks:
                continue
            seen_chunks.add(chunk_id)

            chunk = self.db.get(ChunkModel, chunk_id)
            if chunk:
                meta = (chunk.document.doc_metadata or {}) if chunk.document else {}
                src_type = meta.get("source_type", "file")
                results.append({
                    "content": chunk.content,
                    "source": f"{chunk.document.title}（第{chunk.chunk_index}段）",
                    "score": hit["distance"],
                    "match_type": "vector",
                    "source_type": {"web": "网页", "文件": "文件"}.get(src_type, src_type),
                    "source_url": meta.get("source_url"),
                    "source_name": meta.get("source_name"),
                })

            if len(results) >= top_k:
                break

        # 向量结果不足时，用关键词检索补充
        if len(results) < top_k:
            existing = {x["content"] for x in results}
            for r in self._keyword_search(query, kb_ids, top_k - len(results)):
                if r["content"] not in existing:
                    results.append(r)

        logger.info("[RAG] 最终返回: %d 个（阈值 %.2f）", len(results), min_score)
        return results

    def search_examples(self, query: str, user_id: str, top_k: int = 2,
                        max_chars: int = 2500, dept_code: str = None) -> list:
        """检索最相近的完整范文，用于写作模仿（按文档聚合，取整篇）。

        向量库不可用时回退关键词检索。检索范围同样受科室作用域约束。
        """
        # 服务端解析，不信任入参
        dept_code = self._dept_code_of(user_id)
        admin = self._is_admin(user_id)
        scopes = self.resolve_scopes(dept_code, admin, user_id)
        kb_ids = self._get_accessible_kb_ids(user_id, dept_code, admin)
        if not kb_ids:
            return []

        if self.vector_store is not None:
            try:
                query_vec = self.embedder.encode_queries([query])[0]
                hits = self.vector_store.search(query_vec, kb_ids, top_k=30, scopes=scopes)

                seen, examples = set(), []
                for hit in hits:
                    doc_id = hit["doc_id"]
                    if doc_id in seen:
                        continue
                    doc = self.db.scalar(select(DocumentModel).where(
                        DocumentModel.id == doc_id, DocumentModel.status == "published"
                    ))
                    if not doc or not doc.content:
                        continue
                    seen.add(doc_id)
                    examples.append({"title": doc.title, "content": doc.content[:max_chars]})
                    if len(examples) >= top_k:
                        break
                return examples
            except Exception as e:
                logger.warning("[RAG] 向量范文检索失败，回退关键词: %s", e)

        return self._keyword_examples(query, kb_ids, top_k, max_chars)

    # ---------------- 关键词回退（无需向量） ----------------

    @staticmethod
    def _tokenize(query: str) -> List[str]:
        """CJK 二元分词 + ASCII 词（>=2 字符）。"""
        tokens: List[str] = []
        for w in re.findall(r"[a-zA-Z0-9]+", query.lower()):
            if len(w) >= 2:
                tokens.append(w)
        for seg in re.findall(r"[\u4e00-\u9fff]+", query):
            if len(seg) == 1:
                tokens.append(seg)
            else:
                for i in range(len(seg) - 1):
                    tokens.append(seg[i:i + 2])
        return tokens

    def _keyword_search(self, query: str, kb_ids: List[str], top_k: int) -> List[Dict]:
        tokens = self._tokenize(query)
        if not tokens:
            return []
        stmt = (
            select(ChunkModel)
            .join(DocumentModel, ChunkModel.doc_id == DocumentModel.id)
            .where(DocumentModel.kb_id.in_(kb_ids), DocumentModel.status == "published")
        )
        stmt = stmt.where(or_(*[ChunkModel.content.like(f"%{t}%") for t in tokens]))
        chunks = self.db.scalars(stmt).all()
        scored = []
        for c in chunks:
            cnt = sum(1 for t in tokens if t in c.content)
            if cnt == 0:
                continue
            score = min(1.0, cnt / len(tokens))
            scored.append({
                "content": c.content,
                "source": f"{c.document.title}（第{c.chunk_index}段）",
                "score": score,
                "match_type": "keyword",
                "source_type": "文件",
                "source_url": None,
                "source_name": None,
            })
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:top_k]

    def _keyword_examples(self, query: str, kb_ids: List[str], top_k: int, max_chars: int) -> list:
        tokens = self._tokenize(query)
        if not tokens:
            return []
        docs = self.db.scalars(
            select(DocumentModel).where(
                DocumentModel.kb_id.in_(kb_ids),
                DocumentModel.status == "published",
                DocumentModel.content.isnot(None),
            )
        ).all()
        scored = []
        for d in docs:
            cnt = sum(1 for t in tokens if t in (d.content or ""))
            if cnt == 0:
                continue
            score = min(1.0, cnt / len(tokens))
            scored.append((score, d))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [{"title": d.title, "content": d.content[:max_chars]} for _, d in scored[:top_k]]
