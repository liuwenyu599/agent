"""FAISS 向量库实现。

索引与元数据必须作为一个一致性单元保存：写临时文件后原子 replace，避免进程中断
留下半套 index/meta。Embedding 维度不匹配属于部署错误，禁止 warning 后静默跳过。
"""
import os
import pickle
import threading
from pathlib import Path
from typing import Any, Dict, List

import numpy as np

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class FAISSVectorStore:
    def __init__(self, dim: int = None, index_path: str = None) -> None:
        self.dim = dim
        self.index_path = Path(index_path or settings.vector_index_dir)
        self.index_path.mkdir(parents=True, exist_ok=True)
        self.index = None
        self.metadata: Dict[int, Dict] = {}
        self.next_idx = 0
        self._deleted_doc_ids: set = set()
        self._io_lock = threading.RLock()
        self._load()

    def _load(self) -> None:
        import faiss
        index_file = self.index_path / "index.faiss"
        meta_file = self.index_path / "metadata.pkl"
        if index_file.exists() != meta_file.exists():
            raise RuntimeError("FAISS 索引文件不完整：index.faiss 与 metadata.pkl 必须同时存在")
        if index_file.exists():
            self.index = faiss.read_index(str(index_file))
            with open(meta_file, "rb") as handle:
                data = pickle.load(handle)
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
        index_file = self.index_path / "index.faiss"
        meta_file = self.index_path / "metadata.pkl"
        index_tmp = self.index_path / "index.faiss.tmp"
        meta_tmp = self.index_path / "metadata.pkl.tmp"
        payload = {
            "metadata": self.metadata,
            "next_idx": self.next_idx,
            "deleted_doc_ids": list(self._deleted_doc_ids),
        }
        with self._io_lock:
            try:
                faiss.write_index(self.index, str(index_tmp))
                with open(meta_tmp, "wb") as handle:
                    pickle.dump(payload, handle)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(index_tmp, index_file)
                os.replace(meta_tmp, meta_file)
            finally:
                index_tmp.unlink(missing_ok=True)
                meta_tmp.unlink(missing_ok=True)

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
            raise RuntimeError(
                f"Embedding 维度与现有索引不一致：index={self.dim}, embedding={actual_dim}。"
                "请确认模型配置并重建向量索引，禁止继续写入。"
            )
        with self._io_lock:
            self.index.add(embeddings)
            for i, chunk in enumerate(chunks):
                idx = self.next_idx + i
                self.metadata[idx] = {
                    "chunk_id": chunk["chunk_id"], "doc_id": chunk["doc_id"],
                    "kb_id": chunk["kb_id"], "content": chunk["content"],
                    "title": chunk["title"], "scope": chunk.get("scope") or "GLOBAL",
                }
            for chunk in chunks:
                self._deleted_doc_ids.discard(chunk["doc_id"])
            self.next_idx += len(chunks)
            self._save()
        logger.info("[FAISS] 添加 %d 个向量，总计 %d", len(chunks), self.next_idx)

    def search(self, query_embedding: Any, kb_ids: List[str], top_k: int = 20,
               scopes: List[str] = None) -> List[Dict]:
        if self.index is None or self.index.ntotal == 0:
            return []
        if not kb_ids:
            return []
        query_vec = query_embedding.reshape(1, -1).astype("float32")
        if query_vec.shape[1] != self.dim:
            raise RuntimeError(
                f"查询 embedding 维度 {query_vec.shape[1]} 与索引维度 {self.dim} 不一致；"
                "必须重建索引后再提供检索服务。"
            )
        kb_set = set(kb_ids)
        scope_set = set(scopes) if scopes else None
        allowed = np.array([
            idx for idx, meta in self.metadata.items()
            if meta["kb_id"] in kb_set
            and meta["doc_id"] not in self._deleted_doc_ids
            and (scope_set is None or meta.get("scope", "GLOBAL") in scope_set)
        ], dtype="int64")
        if allowed.size == 0:
            return []
        k = min(top_k * 3, allowed.size)
        distances, indices = self._scoped_search(query_vec, k, allowed)
        results = []
        for dist, idx in zip(distances[0], indices[0]):
            idx = int(idx)
            if idx < 0 or idx not in self.metadata:
                continue
            meta = self.metadata[idx]
            if meta["kb_id"] not in kb_set:
                continue
            if scope_set is not None and meta.get("scope", "GLOBAL") not in scope_set:
                continue
            results.append({
                "chunk_id": meta["chunk_id"], "doc_id": meta["doc_id"],
                "content": meta["content"], "title": meta["title"],
                "distance": float(dist),
            })
            if len(results) >= top_k:
                break
        return results

    def _scoped_search(self, query_vec: "np.ndarray", k: int, allowed: "np.ndarray"):
        try:
            import faiss
            selector = faiss.IDSelectorBatch(allowed)
            params_cls = getattr(faiss, "SearchParametersFlat", None) or faiss.SearchParameters
            params = params_cls()
            params.sel = selector
            return self.index.search(query_vec, k, params=params)
        except Exception as exc:  # pragma: no cover - faiss 版本差异兜底
            logger.warning("[FAISS] IDSelector 不可用（%s），退化为全量召回+后置过滤", exc)
            return self.index.search(query_vec, min(k * 3, self.index.ntotal))

    def delete_by_document(self, doc_id: str) -> int:
        count = sum(1 for meta in self.metadata.values() if meta["doc_id"] == doc_id)
        if count:
            with self._io_lock:
                self._deleted_doc_ids.add(doc_id)
                self._save()
            logger.info("[FAISS] 标记删除文档 %s 的 %d 个向量", doc_id, count)
        return count
