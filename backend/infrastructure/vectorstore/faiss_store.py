import faiss
import numpy as np
import pickle
from typing import List, Dict
from pathlib import Path

class FAISSVectorStore:
    def __init__(self, dim: int = None, index_path: str = "/home/lwy/judicial-ai/vector_index"):
        self.dim = dim  # None 表示自动检测
        self.index_path = Path(index_path)
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        
        self.index = None
        self.metadata = {}
        self.next_idx = 0
        
        self._load()
        
        # 如果加载后 index 仍为 None，创建一个空的
        if self.index is None:
            # 延迟创建，等知道维度后再创建
            self.index = None
    
    def _load(self):
        index_file = self.index_path / "index.faiss"
        meta_file = self.index_path / "metadata.pkl"
        
        if index_file.exists() and meta_file.exists():
            self.index = faiss.read_index(str(index_file))
            with open(meta_file, 'rb') as f:
                data = pickle.load(f)
                self.metadata = data['metadata']
                self.next_idx = data['next_idx']
            self.dim = self.index.d
            print(f"[FAISS] 加载索引: {len(self.metadata)} 个向量, 维度: {self.dim}")
        else:
            print(f"[FAISS] 索引文件不存在，等待首次添加数据")
    
    def _save(self):
        if self.index is None:
            return
        faiss.write_index(self.index, str(self.index_path / "index.faiss"))
        with open(self.index_path / "metadata.pkl", 'wb') as f:
            pickle.dump({
                'metadata': self.metadata,
                'next_idx': self.next_idx
            }, f)
    
    def add_chunks(self, chunks: List[Dict]):
        if not chunks:
            return
        
        embeddings = np.array([c["embedding"] for c in chunks]).astype('float32')
        actual_dim = embeddings.shape[1]
        
        # 首次创建索引
        if self.index is None:
            self.dim = actual_dim
            self.index = faiss.IndexFlatIP(actual_dim)
            print(f"[FAISS] 创建新索引，维度: {actual_dim}")
        
        # 检查维度
        if actual_dim != self.dim:
            print(f"[FAISS] 警告: 维度不匹配! 索引维度={self.dim}, 实际维度={actual_dim}")
            print(f"[FAISS] 跳过这批数据，请确保使用相同的 embedding 模型")
            return
        
        self.index.add(embeddings)
        
        for i, chunk in enumerate(chunks):
            idx = self.next_idx + i
            self.metadata[idx] = {
                "chunk_id": chunk["chunk_id"],
                "doc_id": chunk["doc_id"],
                "kb_id": chunk["kb_id"],
                "content": chunk["content"],
                "title": chunk["title"]
            }
        
        self.next_idx += len(chunks)
        self._save()
        print(f"[FAISS] 添加 {len(chunks)} 个向量，总计 {self.next_idx}, 维度: {self.dim}")
    
    def search(self, query_embedding: np.ndarray, kb_ids: List[str], top_k: int = 20) -> List[Dict]:
        if self.index is None or self.index.ntotal == 0:
            return []
        
        query_vec = query_embedding.reshape(1, -1).astype('float32')
        
        # 检查维度
        if query_vec.shape[1] != self.dim:
            print(f"[FAISS] 错误: 查询维度 {query_vec.shape[1]} != 索引维度 {self.dim}")
            return []
        
        distances, indices = self.index.search(query_vec, min(top_k * 3, self.index.ntotal))
        
        results = []
        for dist, idx in zip(distances[0], indices[0]):
            if idx < 0 or idx not in self.metadata:
                continue
            
            meta = self.metadata[idx]
            if meta["kb_id"] in kb_ids:
                results.append({
                    "chunk_id": meta["chunk_id"],
                    "doc_id": meta["doc_id"],
                    "content": meta["content"],
                    "title": meta["title"],
                    "distance": float(dist)
                })
            
            if len(results) >= top_k:
                break
        
        return results
