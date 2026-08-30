"""FAISS 向量库实现。持久化格式与旧系统 index.faiss/metadata.pkl 兼容。

FAISS IndexFlatIP 不支持单条删除，delete_by_document 采用元数据标记删除
（search 时过滤），并在删除后重写持久化文件。
"""
import pickle
from pathlib import Path
from typing import Any, Dict, List

import numpy as np

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class FAISSVectorStore:
    def __init__(self, dim: int = None, index_path: str = None) -> None:
        self.dim = dim  # None 表示首次 add 时自动检测
        self.index_path = Path(index_path or settings.vector_index_dir)
        self.index_path.mkdir(parents=True, exist_ok=True)

        self.index = None
        self.metadata: Dict[int, Dict] = {}
        self.next_idx = 0
        self._deleted_doc_ids: set = set()

        self._load()

    def _load(self) -> None:
        import faiss

        index_file = self.index_path / "index.faiss"
        meta_file = self.index_path / "metadata.pkl"

        if index_file.exists() and meta_file.exists():
            self.index = faiss.read_index(str(index_file))
            with open(meta_file, "rb") as f:
                data = pickle.load(f)
                self.metadata = data["metadata"]
                self.next_idx = data["next_idx"]
                self._deleted_doc_ids = set(data.get("deleted_doc_ids", []))
            self.dim = self.index.d
            logger.info("[FAISS] 加载索引: %d 个向量, 维度: %d", len(self.metadata), self.dim)
        else:
            logger.info("[FAISS] 索引文件不存在，等待首次添加数据")

    def _save(self) -> None:
        import faiss

        if self.index is None:
            return
        faiss.write_index(self.index, str(self.index_path / "index.faiss"))
        with open(self.index_path / "metadata.pkl", "wb") as f:
            pickle.dump({
                "metadata": self.metadata,
                "next_idx": self.next_idx,
                "deleted_doc_ids": list(self._deleted_doc_ids),
            }, f)

    def add_chunks(self, chunks: List[Dict]) -> None:
        import faiss

        if not chunks:
            return

        embeddings = np.array([c["embedding"] for c in chunks]).astype("float32")
        actual_dim = embeddings.shape[1]

        if self.index is None:
            self.dim = actual_dim
            self.index = faiss.IndexFlatIP(actual_dim)
            logger.info("[FAISS] 创建新索引，维度: %d", actual_dim)

        if actual_dim != self.dim:
            logger.warning(
                "[FAISS] 维度不匹配! 索引维度=%d, 实际维度=%d，跳过这批数据",
                self.dim, actual_dim,
            )
            return

        self.index.add(embeddings)

        for i, chunk in enumerate(chunks):
            idx = self.next_idx + i
            self.metadata[idx] = {
                "chunk_id": chunk["chunk_id"],
                "doc_id": chunk["doc_id"],
                "kb_id": chunk["kb_id"],
                "content": chunk["content"],
                "title": chunk["title"],
            }

        self.next_idx += len(chunks)
        self._save()
        logger.info("[FAISS] 添加 %d 个向量，总计 %d", len(chunks), self.next_idx)

    def search(self, query_embedding: Any, kb_ids: List[str], top_k: int = 20) -> List[Dict]:
        if self.index is None or self.index.ntotal == 0:
            return []

        query_vec = query_embedding.reshape(1, -1).astype("float32")

        if query_vec.shape[1] != self.dim:
            logger.error("[FAISS] 查询维度 %d != 索引维度 %d", query_vec.shape[1], self.dim)
            return []

        distances, indices = self.index.search(query_vec, min(top_k * 3, self.index.ntotal))

        results = []
        for dist, idx in zip(distances[0], indices[0]):
            if idx < 0 or idx not in self.metadata:
                continue
            meta = self.metadata[idx]
            if meta["doc_id"] in self._deleted_doc_ids:
                continue
            if meta["kb_id"] in kb_ids:
                results.append({
                    "chunk_id": meta["chunk_id"],
                    "doc_id": meta["doc_id"],
                    "content": meta["content"],
                    "title": meta["title"],
                    "distance": float(dist),
                })
            if len(results) >= top_k:
                break
        return results

    def delete_by_document(self, doc_id: str) -> int:
        """标记删除某文档的全部向量（search 时过滤），返回标记数量。"""
        count = 0
        for meta in self.metadata.values():
            if meta["doc_id"] == doc_id:
                count += 1
        if count:
            self._deleted_doc_ids.add(doc_id)
            self._save()
            logger.info("[FAISS] 标记删除文档 %s 的 %d 个向量", doc_id, count)
        return count
