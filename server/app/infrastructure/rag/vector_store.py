"""FAISS 向量库实现。

索引与元数据作为一致性单元保存：跨进程文件锁保护 mutation，写临时文件后原子
replace；embedding 维度不匹配直接失败。删除文档时物理重建 IndexFlatIP，避免
长期 tombstone 导致索引膨胀。
"""
import os
import pickle
import threading
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
from filelock import FileLock

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
        self._file_lock = FileLock(str(self.index_path / ".index.lock"), timeout=60)
        self._loaded_mtime = 0.0
        self._load()

    def _disk_files(self):
        return self.index_path / "index.faiss", self.index_path / "metadata.pkl"

    def _current_mtime(self) -> float:
        index_file, meta_file = self._disk_files()
        values = [p.stat().st_mtime for p in (index_file, meta_file) if p.exists()]
        return max(values, default=0.0)

    def _load_unlocked(self) -> None:
        import faiss
        index_file, meta_file = self._disk_files()
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
            self._loaded_mtime = self._current_mtime()
            logger.info("[FAISS] 加载索引: %d 个向量, 维度: %d", len(self.metadata), self.dim)
        else:
            self.index = None
            self.metadata = {}
            self.next_idx = 0
            self._deleted_doc_ids = set()
            self._loaded_mtime = 0.0
            logger.info("[FAISS] 索引文件不存在，等待首次添加数据")

    def _load(self) -> None:
        with self._io_lock, self._file_lock:
            self._load_unlocked()

    def _refresh_if_changed(self) -> None:
        disk_mtime = self._current_mtime()
        if disk_mtime <= self._loaded_mtime:
            return
        with self._io_lock, self._file_lock:
            if self._current_mtime() > self._loaded_mtime:
                self._load_unlocked()

    def _save_unlocked(self) -> None:
        import faiss
        if self.index is None:
            return
        index_file, meta_file = self._disk_files()
        index_tmp = self.index_path / f"index.faiss.{os.getpid()}.tmp"
        meta_tmp = self.index_path / f"metadata.pkl.{os.getpid()}.tmp"
        payload = {
            "metadata": self.metadata,
            "next_idx": self.next_idx,
            "deleted_doc_ids": list(self._deleted_doc_ids),
        }
        try:
            faiss.write_index(self.index, str(index_tmp))
            with open(meta_tmp, "wb") as handle:
                pickle.dump(payload, handle)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(index_tmp, index_file)
            os.replace(meta_tmp, meta_file)
            self._loaded_mtime = self._current_mtime()
        finally:
            index_tmp.unlink(missing_ok=True)
            meta_tmp.unlink(missing_ok=True)

    def _save(self) -> None:
        with self._io_lock, self._file_lock:
            self._save_unlocked()

    def add_chunks(self, chunks: List[Dict]) -> None:
        import faiss
        if not chunks:
            return
        embeddings = np.array([c["embedding"] for c in chunks]).astype("float32")
        actual_dim = embeddings.shape[1]
        with self._io_lock, self._file_lock:
            # Another worker may have written since this instance was created.
            if self._current_mtime() > self._loaded_mtime:
                self._load_unlocked()
            if self.index is None:
                self.dim = actual_dim
                self.index = faiss.IndexFlatIP(actual_dim)
                logger.info("[FAISS] 创建新索引，维度: %d", actual_dim)
            if actual_dim != self.dim:
                raise RuntimeError(
                    f"Embedding 维度与现有索引不一致：index={self.dim}, embedding={actual_dim}。"
                    "请确认模型配置并重建向量索引，禁止继续写入。"
                )
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
            self._save_unlocked()
        logger.info("[FAISS] 添加 %d 个向量，总计 %d", len(chunks), self.next_idx)

    def search(self, query_embedding: Any, kb_ids: List[str], top_k: int = 20,
               scopes: List[str] = None) -> List[Dict]:
        self._refresh_if_changed()
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

    def _compact_unlocked(self, excluded_doc_ids: set[str]) -> int:
        import faiss
        if self.index is None:
            return 0
        old_count = int(self.index.ntotal)
        survivors = [
            (idx, meta) for idx, meta in sorted(self.metadata.items())
            if meta["doc_id"] not in excluded_doc_ids
            and meta["doc_id"] not in self._deleted_doc_ids
        ]
        rebuilt = faiss.IndexFlatIP(self.dim)
        new_metadata: Dict[int, Dict] = {}
        for new_idx, (old_idx, meta) in enumerate(survivors):
            vector = np.asarray(self.index.reconstruct(int(old_idx)), dtype="float32").reshape(1, -1)
            rebuilt.add(vector)
            new_metadata[new_idx] = dict(meta)
        self.index = rebuilt
        self.metadata = new_metadata
        self.next_idx = len(new_metadata)
        self._deleted_doc_ids = set()
        self._save_unlocked()
        return old_count - self.next_idx

    def compact(self) -> int:
        """Physically remove all tombstoned vectors and rewrite a dense index."""
        with self._io_lock, self._file_lock:
            if self._current_mtime() > self._loaded_mtime:
                self._load_unlocked()
            return self._compact_unlocked(set())

    def delete_by_document(self, doc_id: str) -> int:
        """Physically remove one document and compact the FAISS index immediately."""
        with self._io_lock, self._file_lock:
            if self._current_mtime() > self._loaded_mtime:
                self._load_unlocked()
            count = sum(1 for meta in self.metadata.values() if meta["doc_id"] == doc_id)
            if not count:
                return 0
            removed = self._compact_unlocked({doc_id})
        logger.info("[FAISS] 物理删除文档 %s 的 %d 个向量", doc_id, removed)
        return removed
