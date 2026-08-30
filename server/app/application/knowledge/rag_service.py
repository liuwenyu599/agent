"""RAG 检索服务（移植自旧 services/rag_service.py）。

向量检索 + 阈值过滤；范文检索按文档聚合取整篇。
chat 模块通过本服务检索知识库，不直接访问向量库。
"""
from typing import Dict, List

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.application.ports import Embedder, VectorStore
from app.core.config import settings
from app.core.logging import get_logger
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

    def _get_accessible_kb_ids(self, user_id: str) -> List[str]:
        kbs = self.db.scalars(select(KnowledgeBaseModel).where(
            (KnowledgeBaseModel.kb_type == "public")
            | ((KnowledgeBaseModel.kb_type == "personal") & (KnowledgeBaseModel.owner_id == user_id))
        )).all()
        return [kb.id for kb in kbs]

    def search(self, query: str, user_id: str, kb_types: List[str] = None,
               top_k: int = None, min_score: float = None) -> List[Dict]:
        """只做向量检索，低于阈值一律不注入，避免无关文档带偏模型。"""
        top_k = top_k or settings.RAG_TOP_K
        min_score = min_score if min_score is not None else settings.RAG_SCORE_THRESHOLD

        kb_ids = self._get_accessible_kb_ids(user_id)
        if not kb_ids:
            return []

        logger.info("[RAG] 查询: %s", query)
        query_vec = self.embedder.encode_queries([query])[0]
        vector_hits = self.vector_store.search(query_vec, kb_ids, top_k=20)
        logger.info("[RAG] 原始向量命中: %d 个", len(vector_hits))

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
                    "source_type": {"web": "网页", "file": "文件"}.get(src_type, src_type),
                    "source_url": meta.get("source_url"),
                    "source_name": meta.get("source_name"),
                })

            if len(results) >= top_k:
                break

        logger.info("[RAG] 最终返回: %d 个（阈值 %.2f）", len(results), min_score)
        return results

    def search_examples(self, query: str, user_id: str, top_k: int = 2,
                        max_chars: int = 2500) -> list:
        """检索最相近的完整范文，用于写作模仿（按文档聚合，取整篇）。"""
        kb_ids = self._get_accessible_kb_ids(user_id)
        if not kb_ids:
            return []
        query_vec = self.embedder.encode_queries([query])[0]
        hits = self.vector_store.search(query_vec, kb_ids, top_k=30)

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
