"""RAG 检索服务（v2：混合检索）。

召回：向量检索 + 关键词检索双路并行，RRF（Reciprocal Rank Fusion）融合排序；
过滤：向量侧按阈值门控，文档级多样性上限（默认每篇最多 2 块）；
扩展：命中块自动拼接前后相邻块作为上下文（总长受 RAG_EXPAND_BUDGET 约束）。
范文检索 search_examples 按文档聚合取整篇。
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
        from app.domain.organization.departments import resolve_code
        return resolve_code(getattr(user, "department", "") or "")

    def _is_admin(self, user_id: str) -> bool:
        user = self._user_row(user_id)
        return is_system_admin(getattr(user, "role", "") or "")

    @staticmethod
    def resolve_scopes(dept_code: str, is_admin: bool = False,
                       user_id: str = "") -> List[str]:
        """用户可见作用域：GLOBAL + 本人个人 + 本人所属科室。"""
        if is_admin:
            return None
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

    @staticmethod
    def _document_is_accessible(document, accessible_kb_ids: List[str]) -> bool:
        """向量命中后的 DB 二次鉴权。

        向量库的 kb_id/scope 过滤是第一道边界；这里不信任索引元数据，重新以数据库
        文档归属和发布状态校验，防止脏索引、旧索引或 VectorStore 实现缺陷导致跨科室泄漏。
        """
        if document is None:
            return False
        return (
            getattr(document, "status", None) == "published"
            and getattr(document, "kb_id", None) in set(accessible_kb_ids or [])
        )

    # ---------------- 混合检索 ----------------

    def search(self, query: str, user_id: str, kb_types: List[str] = None,
               top_k: int = None, min_score: float = None,
               kb_ids: List[str] = None, dept_code: str = None,
               scopes: List[str] = None) -> List[Dict]:
        """向量 + 关键词双路召回，RRF 融合；权限范围一律由服务端解析。"""
        top_k = top_k or settings.RAG_TOP_K
        min_score = min_score if min_score is not None else settings.RAG_SCORE_THRESHOLD

        dept_code = self._dept_code_of(user_id)
        admin = self._is_admin(user_id)

        server_scopes = self.resolve_scopes(dept_code, admin, user_id)
        if server_scopes is None:
            scopes = None
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
        candidates = settings.RAG_VECTOR_CANDIDATES

        vector_hits = []
        if self.vector_store is not None:
            try:
                query_vec = self.embedder.encode_queries([query])[0]
                raw_hits = self.vector_store.search(
                    query_vec, kb_ids, top_k=candidates, scopes=scopes)
                vector_hits = [h for h in raw_hits if h["distance"] >= min_score]
                logger.info("[RAG] 向量命中: %d（阈值过滤后 %d）",
                            len(raw_hits), len(vector_hits))
            except Exception as e:
                logger.warning("[RAG] 向量检索失败，仅关键词召回: %s", e)
                vector_hits = []

        keyword_hits = self._keyword_search(query, kb_ids, candidates)

        rrf_k = settings.RAG_RRF_K
        fused: Dict[str, Dict] = {}
        for rank, h in enumerate(vector_hits):
            e = fused.setdefault(h["chunk_id"], {"rrf": 0.0, "v": None, "k": None})
            e["v"] = h
            e["rrf"] += 1.0 / (rrf_k + rank + 1)
        for rank, r in enumerate(keyword_hits):
            cid = r.get("chunk_id")
            if not cid:
                continue
            e = fused.setdefault(cid, {"rrf": 0.0, "v": None, "k": None})
            e["k"] = r
            e["rrf"] += 1.0 / (rrf_k + rank + 1)
        ranked = sorted(fused.values(), key=lambda x: x["rrf"], reverse=True)

        results: List[Dict] = []
        per_doc: Dict[str, int] = {}
        doc_cap = settings.RAG_PER_DOC_CAP
        for e in ranked:
            hit, kw = e["v"], e["k"]
            if hit is not None:
                chunk_id, doc_id, score = hit["chunk_id"], hit["doc_id"], hit["distance"]
            else:
                chunk_id, doc_id, score = kw["chunk_id"], kw["doc_id"], kw["score"]

            if per_doc.get(doc_id, 0) >= doc_cap:
                continue
            chunk = self.db.get(ChunkModel, chunk_id)
            if not chunk:
                continue
            # 第二道权限边界：不能只相信 VectorStore 返回的 kb_id/doc_id/scope。
            if not self._document_is_accessible(chunk.document, kb_ids):
                logger.warning("[RAG] 丢弃越权/失效索引命中: chunk=%s doc=%s", chunk_id, doc_id)
                continue
            # 索引里的 doc_id 也必须与数据库真实归属一致，避免伪造元数据影响去重/引用。
            if chunk.doc_id != doc_id:
                logger.warning("[RAG] 丢弃 doc_id 不一致索引命中: chunk=%s", chunk_id)
                continue
            per_doc[doc_id] = per_doc.get(doc_id, 0) + 1

            content = chunk.content
            if settings.RAG_NEIGHBOR_EXPAND:
                content = self._expand_neighbors(chunk)

            meta = (chunk.document.doc_metadata or {}) if chunk.document else {}
            src_type = meta.get("source_type", "file")
            kb = chunk.document.knowledge_base if chunk.document else None
            results.append({
                "content": content,
                "chunk_content": chunk.content,
                "source": f"{chunk.document.title}（第{chunk.chunk_index}段）",
                "chunk_id": chunk_id,
                "chunk_index": chunk.chunk_index,
                "doc_id": doc_id,
                "doc_title": chunk.document.title if chunk.document else "",
                "kb_id": kb.id if kb else "",
                "kb_name": kb.name if kb else "",
                "kb_type": kb.kb_type if kb else "",
                "score": score,
                "match_type": "hybrid" if (hit and kw) else ("vector" if hit else "keyword"),
                "source_type": {"web": "网页", "文件": "文件"}.get(src_type, src_type),
                "source_url": meta.get("source_url"),
                "source_name": meta.get("source_name"),
            })
            if len(results) >= top_k:
                break

        logger.info("[RAG] 最终返回: %d 个（向量 %d / 关键词 %d，融合 top_k=%d）",
                    len(results), len(vector_hits), len(keyword_hits), top_k)
        return results

    def search_examples(self, query: str, user_id: str, top_k: int = 2,
                        max_chars: int = 2500, dept_code: str = None) -> list:
        """检索最相近的完整范文，用于写作模仿（按文档聚合，取整篇）。"""
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
                    doc = self.db.get(DocumentModel, doc_id)
                    if not self._document_is_accessible(doc, kb_ids) or not getattr(doc, "content", None):
                        logger.warning("[RAG] 丢弃越权/失效范文索引命中: doc=%s", doc_id)
                        continue
                    seen.add(doc_id)
                    examples.append({"title": doc.title, "content": doc.content[:max_chars]})
                    if len(examples) >= top_k:
                        break
                if examples:
                    return examples
            except Exception as e:
                logger.warning("[RAG] 向量范文检索失败，回退关键词: %s", e)

        return self._keyword_examples(query, kb_ids, top_k, max_chars)

    # ---------------- 邻块上下文扩展 ----------------

    @staticmethod
    def _expand_neighbors(chunk: ChunkModel) -> str:
        content = chunk.content
        budget = settings.RAG_EXPAND_BUDGET
        if len(content) >= budget:
            return content
        rows = chunk.document.chunks if chunk.document else []
        prev_c = next((c for c in rows if c.chunk_index == chunk.chunk_index - 1), None)
        next_c = next((c for c in rows if c.chunk_index == chunk.chunk_index + 1), None)
        parts = []
        if prev_c is not None:
            parts.append(prev_c.content)
        parts.append(content)
        if next_c is not None:
            parts.append(next_c.content)
        merged = "\n".join(parts)
        return merged if len(merged) <= budget else content

    # ---------------- 关键词召回（与向量路并行） ----------------

    @staticmethod
    def _tokenize(query: str) -> List[str]:
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
                "chunk_id": c.id,
                "doc_id": c.doc_id,
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
