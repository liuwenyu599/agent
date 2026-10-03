"""RAG 检索服务（v2：混合检索）。

召回：向量检索 + 关键词检索双路并行，RRF（Reciprocal Rank Fusion）融合排序；
过滤：向量侧按阈值门控，文档级多样性上限（默认每篇最多 2 块）；
扩展：命中块自动拼接前后相邻块作为上下文（总长受 RAG_EXPAND_BUDGET 约束）。
显式反馈：只使用当前用户自己的 👍/👎 对曾引用 chunk 做小幅、有界 rerank。
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

    @property
    def access(self):
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
        if document is None:
            return False
        return (
            getattr(document, "status", None) == "published"
            and getattr(document, "kb_id", None) in set(accessible_kb_ids or [])
        )

    def _feedback_weights(self, user_id: str, chunk_ids: List[str]) -> Dict[str, float]:
        """读取当前用户自己的反馈。失败时只跳过学习信号，绝不影响正常检索。"""
        if not chunk_ids:
            return {}
        try:
            from app.infrastructure.repositories.feedback import SqlAlchemyChatFeedbackRepository
            return SqlAlchemyChatFeedbackRepository(self.db).chunk_weights(user_id, chunk_ids)
        except Exception as exc:  # migration rolling upgrade / damaged optional feedback must not break RAG
            logger.warning("[RAG] 反馈 rerank 不可用，已跳过: %s", exc)
            return {}

    def search(self, query: str, user_id: str, kb_types: List[str] = None,
               top_k: int = None, min_score: float = None,
               kb_ids: List[str] = None, dept_code: str = None,
               scopes: List[str] = None) -> List[Dict]:
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

        # 反馈只做轻量乘法微调，不覆盖本轮语义相关度：赞最多 +9%，踩最多 -15%。
        feedback_weights = self._feedback_weights(user_id, list(fused.keys()))
        for chunk_id, entry in fused.items():
            entry["feedback_delta"] = feedback_weights.get(chunk_id, 0.0)
            entry["rrf"] *= 1.0 + entry["feedback_delta"]
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
            if not self._document_is_accessible(chunk.document, kb_ids):
                logger.warning("[RAG] 丢弃越权/失效索引命中: chunk=%s doc=%s", chunk_id, doc_id)
                continue
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
                "feedback_delta": e.get("feedback_delta", 0.0),
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