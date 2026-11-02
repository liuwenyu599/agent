"""RAG 检索服务：混合召回 + RRF + CrossEncoder 二阶段重排。

安全基线：向量阈值先过滤，向量/关键词最多召回 30 个候选，经 RRF 与用户本人反馈
轻量调整后，交给本地 bge-reranker-v2-m3 重排，最终只返回 top_k（默认 3）。
"""
import re
import time
from typing import Dict, List

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.application.knowledge.reranker import reranker
from app.application.ports import Embedder, VectorStore
from app.core.config import settings
from app.core.logging import get_logger
from app.domain.identity.authorization import is_system_admin
from app.domain.organization.departments import SCOPE_GLOBAL, dept_scope, user_scope
from app.infrastructure.database.models.identity import UserModel
from app.infrastructure.database.models.knowledge import ChunkModel, DocumentModel, KnowledgeBaseModel

logger = get_logger(__name__)


class RagService:
    def __init__(self, db: Session, embedder: Embedder, vector_store: VectorStore,
                 fast_mode: bool = False) -> None:
        self.db = db
        self.embedder = embedder
        self.vector_store = vector_store
        self.fast_mode = fast_mode

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
        if not chunk_ids:
            return {}
        try:
            from app.infrastructure.repositories.feedback import SqlAlchemyChatFeedbackRepository
            return SqlAlchemyChatFeedbackRepository(self.db).chunk_weights(user_id, chunk_ids)
        except Exception as exc:
            logger.warning("[RAG] 反馈 rerank 不可用，已跳过: %s", exc)
            return {}

    def search(self, query: str, user_id: str, kb_types: List[str] = None,
               top_k: int = None, min_score: float = None,
               kb_ids: List[str] = None, dept_code: str = None,
               scopes: List[str] = None) -> List[Dict]:
        started = time.perf_counter()
        top_k = top_k or settings.RAG_TOP_K
        configured_min = min_score if min_score is not None else settings.RAG_SCORE_THRESHOLD
        # 调用方不能把政务检索阈值降回不安全值。
        min_score = max(float(configured_min), 0.7)

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

        candidates = max(30, int(settings.RAG_VECTOR_CANDIDATES))
        logger.info("[RAG耗时] 开始 mode=%s kb_count=%d scope_count=%d",
                    "keyword" if self.fast_mode else "hybrid", len(kb_ids),
                    len(scopes or []))

        vector_hits = []
        if self.vector_store is not None and not self.fast_mode:
            vector_started = time.perf_counter()
            try:
                query_vec = self.embedder.encode_queries([query])[0]
                raw_hits = self.vector_store.search(
                    query_vec, kb_ids, top_k=candidates, scopes=scopes)
                vector_hits = [h for h in raw_hits if h["distance"] >= min_score]
                logger.info("[RAG] 向量命中: %d（阈值过滤后 %d）",
                            len(raw_hits), len(vector_hits))
            except Exception as exc:
                logger.warning("[RAG] 向量检索失败，仅关键词召回: %s", exc)
            finally:
                logger.info("[RAG耗时] 向量阶段完成 duration=%.3fs hit_count=%d",
                            time.perf_counter() - vector_started, len(vector_hits))

        keyword_started = time.perf_counter()
        keyword_hits = self._keyword_search(query, kb_ids, candidates)
        logger.info("[RAG耗时] 关键词阶段完成 duration=%.3fs hit_count=%d",
                    time.perf_counter() - keyword_started, len(keyword_hits))

        rrf_k = settings.RAG_RRF_K
        fused: Dict[str, Dict] = {}
        for rank, hit in enumerate(vector_hits):
            entry = fused.setdefault(hit["chunk_id"], {"rrf": 0.0, "v": None, "k": None})
            entry["v"] = hit
            entry["rrf"] += 1.0 / (rrf_k + rank + 1)
        for rank, hit in enumerate(keyword_hits):
            cid = hit.get("chunk_id")
            if not cid:
                continue
            entry = fused.setdefault(cid, {"rrf": 0.0, "v": None, "k": None})
            entry["k"] = hit
            entry["rrf"] += 1.0 / (rrf_k + rank + 1)

        feedback_weights = self._feedback_weights(user_id, list(fused.keys()))
        for chunk_id, entry in fused.items():
            entry["feedback_delta"] = feedback_weights.get(chunk_id, 0.0)
            entry["rrf"] *= 1.0 + entry["feedback_delta"]
        ranked = sorted(fused.values(), key=lambda item: item["rrf"], reverse=True)

        # 先生成可审计的候选对象，再做 cross-encoder 重排。不能在这里提前截断 top_k。
        candidate_results: List[Dict] = []
        per_doc: Dict[str, int] = {}
        doc_cap = settings.RAG_PER_DOC_CAP
        for entry in ranked:
            vector_hit, keyword_hit = entry["v"], entry["k"]
            if vector_hit is not None:
                chunk_id = vector_hit["chunk_id"]
                doc_id = vector_hit["doc_id"]
                score = vector_hit["distance"]
            else:
                chunk_id = keyword_hit["chunk_id"]
                doc_id = keyword_hit["doc_id"]
                score = keyword_hit["score"]

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
            kb = chunk.document.knowledge_base if chunk.document else None
            src_type = meta.get("source_type", "file")
            candidate_results.append({
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
                "rrf_score": entry["rrf"],
                "match_type": "hybrid" if (vector_hit and keyword_hit) else (
                    "vector" if vector_hit else "keyword"),
                "feedback_delta": entry.get("feedback_delta", 0.0),
                "source_type": {"web": "网页", "文件": "文件"}.get(src_type, src_type),
                "source_url": meta.get("source_url"),
                "source_name": meta.get("source_name"),
            })
            if len(candidate_results) >= candidates:
                break

        do_rerank = settings.RAG_RERANK_ENABLED and not self.fast_mode
        final_k = min(top_k, int(settings.RAG_RERANK_TOP_K)) if do_rerank else top_k
        if do_rerank:
            results = reranker.rerank(query, candidate_results, final_k)
        else:
            results = candidate_results[:final_k]

        logger.info(
            "[RAG] 最终返回: %d 个（候选 %d / 向量 %d / 关键词 %d / rerank=%s）",
            len(results), len(candidate_results), len(vector_hits), len(keyword_hits),
            do_rerank,
        )
        logger.info("[RAG耗时] 完成 mode=%s duration=%.3fs result_count=%d",
                    "keyword" if self.fast_mode else "hybrid",
                    time.perf_counter() - started, len(results))
        return results

    def search_examples(self, query: str, user_id: str, top_k: int = 2,
                        max_chars: int = 2500, dept_code: str = None,
                        document_type: str = "") -> list:
        dept_code = self._dept_code_of(user_id)
        admin = self._is_admin(user_id)
        scopes = self.resolve_scopes(dept_code, admin, user_id)
        kb_ids = self._get_accessible_kb_ids(user_id, dept_code, admin)
        if not kb_ids:
            return []

        if self.vector_store is not None and not self.fast_mode:
            try:
                query_vec = self.embedder.encode_queries([query])[0]
                hits = self.vector_store.search(query_vec, kb_ids, top_k=30, scopes=scopes)
                seen, examples = set(), []
                for hit in hits:
                    doc_id = hit["doc_id"]
                    if doc_id in seen:
                        continue
                    doc = self.db.get(DocumentModel, doc_id)
                    if (not self._document_is_accessible(doc, kb_ids)
                            or not getattr(doc, "content", None)
                            or not admin and (getattr(doc, "department_code", "") or "")
                            not in ("", dept_code)):
                        logger.warning("[RAG] 丢弃越权/失效范文索引命中: doc=%s", doc_id)
                        continue
                    if document_type and not self._same_genre(doc, document_type):
                        continue
                    seen.add(doc_id)
                    examples.append({"title": doc.title, "content": doc.content[:max_chars],
                                     "doc_type": doc.doc_type})
                    if len(examples) >= top_k:
                        break
                if examples:
                    return examples
            except Exception as exc:
                logger.warning("[RAG] 向量范文检索失败，回退关键词: %s", exc)
        return self._keyword_examples(query, kb_ids, top_k, max_chars,
                                      document_type, dept_code, admin)

    @staticmethod
    def _same_genre(doc: DocumentModel, kind: str) -> bool:
        return (doc.doc_type == kind or
                doc.doc_type == "公文" and kind in (doc.title or ""))

    def exemplar_length_range(self, user_id: str, document_type: str,
                              selected_kb_ids: list[str] | None = None) -> tuple[int, int] | None:
        """Use complete, published documents of the same form within this user's KB scope."""
        from statistics import median
        kind = (document_type or "").strip()
        if not kind or kind == "公文":
            return None
        dept = self._dept_code_of(user_id)
        allowed = set(self._get_accessible_kb_ids(user_id, dept, self._is_admin(user_id)))
        if selected_kb_ids:
            allowed.intersection_update(selected_kb_ids)
        if not allowed:
            return None
        filters = [
            DocumentModel.kb_id.in_(allowed), DocumentModel.status == "published",
            DocumentModel.content.isnot(None),
            or_(DocumentModel.doc_type == kind,
                (DocumentModel.doc_type == "公文") & DocumentModel.title.contains(kind)),
        ]
        if not self._is_admin(user_id):
            filters.append(or_(DocumentModel.department_code == "",
                               DocumentModel.department_code == dept))
        docs = self.db.scalars(select(DocumentModel).where(
            *filters).order_by(DocumentModel.updated_at.desc()).limit(120)).all()
        lengths = []
        for doc in docs:
            if doc.doc_type != kind and not (doc.doc_type == "公文" and kind in (doc.title or "")):
                continue
            body = (doc.content or "").strip()
            count = len(re.sub(r"\s+", "", body))
            if 100 <= count <= 20000:
                lengths.append(count)
            if len(lengths) >= 12:
                break
        if len(lengths) < 2:
            return None
        center = int(median(lengths))
        return max(100, int(center * .8)), int(center * 1.2)

    @staticmethod
    def _expand_neighbors(chunk: ChunkModel) -> str:
        content = chunk.content
        budget = settings.RAG_EXPAND_BUDGET
        if len(content) >= budget:
            return content
        rows = chunk.document.chunks if chunk.document else []
        prev_chunk = next((c for c in rows if c.chunk_index == chunk.chunk_index - 1), None)
        next_chunk = next((c for c in rows if c.chunk_index == chunk.chunk_index + 1), None)
        parts = []
        if prev_chunk is not None:
            parts.append(prev_chunk.content)
        parts.append(content)
        if next_chunk is not None:
            parts.append(next_chunk.content)
        merged = "\n".join(parts)
        return merged if len(merged) <= budget else content

    @staticmethod
    def _tokenize(query: str) -> List[str]:
        tokens: List[str] = []
        for word in re.findall(r"[a-zA-Z0-9]+", query.lower()):
            if len(word) >= 2:
                tokens.append(word)
        for segment in re.findall(r"[\u4e00-\u9fff]+", query):
            if len(segment) == 1:
                tokens.append(segment)
            else:
                for index in range(len(segment) - 1):
                    tokens.append(segment[index:index + 2])
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
        stmt = stmt.where(or_(*[ChunkModel.content.like(f"%{token}%") for token in tokens]))
        chunks = self.db.scalars(stmt).all()
        scored = []
        for chunk in chunks:
            count = sum(1 for token in tokens if token in chunk.content)
            if count == 0:
                continue
            score = min(1.0, count / len(tokens))
            scored.append({
                "chunk_id": chunk.id,
                "doc_id": chunk.doc_id,
                "content": chunk.content,
                "source": f"{chunk.document.title}（第{chunk.chunk_index}段）",
                "score": score,
                "match_type": "keyword",
                "source_type": "文件",
                "source_url": None,
                "source_name": None,
            })
        scored.sort(key=lambda item: item["score"], reverse=True)
        return scored[:top_k]

    def _keyword_examples(self, query: str, kb_ids: List[str], top_k: int,
                          max_chars: int, document_type: str = "",
                          dept_code: str = "", admin: bool = False) -> list:
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
        for doc in docs:
            if not admin and (getattr(doc, "department_code", "") or "") not in ("", dept_code):
                continue
            if document_type and not self._same_genre(doc, document_type):
                continue
            searchable = (doc.title or "") + "\n" + (doc.content or "")
            count = sum(1 for token in tokens if token in searchable)
            if count == 0:
                continue
            score = min(1.0, count / len(tokens))
            scored.append((score, doc))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [{"title": doc.title, "content": doc.content[:max_chars],
                 "doc_type": doc.doc_type}
                for _, doc in scored[:top_k]]
