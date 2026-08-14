import re
from typing import List, Dict
from sqlalchemy.orm import Session
from sqlalchemy import or_

from backend.database.postgres import SessionLocal
from backend.database.models import Chunk, KnowledgeBase, Document
from backend.infrastructure.embedding.bge_embedder import BGEEmbedder
from backend.infrastructure.vectorstore.faiss_store import FAISSVectorStore

class RAGService:
    def __init__(self):
        self.embedder = BGEEmbedder()
        self.vector_store = FAISSVectorStore()
    
    def _get_accessible_kb_ids(self, user_id: str, db: Session) -> List[str]:
        """获取用户可访问的知识库ID"""
        kbs = db.query(KnowledgeBase).filter(
            (KnowledgeBase.kb_type == "public") |
            ((KnowledgeBase.kb_type == "personal") & (KnowledgeBase.owner_id == user_id))
        ).all()
        return [kb.id for kb in kbs]
    
    def search(self, query: str, user_id: str, kb_types: List[str] = None,
               top_k: int = 5, min_score: float = 0.5) -> List[Dict]:
        """
        只做向量检索，低于阈值一律不注入，避免无关文档带偏模型
        """
        db = SessionLocal()
        
        try:
            kb_ids = self._get_accessible_kb_ids(user_id, db)
            if not kb_ids:
                return []
            
            print(f"[RAG] 查询: {query}")
            query_vec = self.embedder.encode_queries([query])[0]
            vector_hits = self.vector_store.search(query_vec, kb_ids, top_k=20)
            print(f"[RAG] 原始向量命中: {len(vector_hits)} 个")
            
            results = []
            seen_chunks = set()
            
            for hit in vector_hits:
                # 关键：低于阈值直接丢弃
                if hit["distance"] < min_score:
                    print(f"[RAG] 过滤低分: score={hit['distance']:.3f} < {min_score}")
                    continue
                
                chunk_id = hit["chunk_id"]
                if chunk_id in seen_chunks:
                    continue
                seen_chunks.add(chunk_id)
                
                # 直接查数据库，不再拼相邻段落
                chunk = db.query(Chunk).filter(Chunk.id == chunk_id).first()
                if chunk:
                    results.append({
                        "content": chunk.content,
                        "source": f"{chunk.document.title}（第{chunk.chunk_index}段）",
                        "score": hit["distance"],
                        "match_type": "vector"
                    })
                
                if len(results) >= top_k:
                    break
            
            print(f"[RAG] 最终返回: {len(results)} 个（阈值 {min_score}）")
            for r in results:
                print(f"  - [{r['match_type']}] {r['source'][:50]}... score={r['score']:.3f}")
            return results
            
        finally:
            db.close()
    
    def search_examples(self, query: str, user_id: str, top_k: int = 2, max_chars: int = 2500) -> list:
        """检索最相近的完整范文，用于写作模仿（按文档聚合，取整篇）"""
        db = SessionLocal()
        try:
            kb_ids = self._get_accessible_kb_ids(user_id, db)
            if not kb_ids:
                return []
            query_vec = self.embedder.encode_queries([query])[0]
            hits = self.vector_store.search(query_vec, kb_ids, top_k=30)
            
            seen, examples = set(), []
            for hit in hits:
                doc_id = hit["doc_id"]
                if doc_id in seen:
                    continue
                doc = db.query(Document).filter(
                    Document.id == doc_id, Document.status == "published"
                ).first()
                if not doc or not doc.content:
                    continue
                seen.add(doc_id)
                examples.append({"title": doc.title, "content": doc.content[:max_chars]})
                if len(examples) >= top_k:
                    break
            return examples
        finally:
            db.close()

