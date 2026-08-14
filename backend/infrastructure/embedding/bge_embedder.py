import torch
from sentence_transformers import SentenceTransformer
from typing import List
import numpy as np

class BGEEmbedder:
    def __init__(self, model_path: str = "/home/lwy/models/BAAI/bge-small-zh-v1.5"):
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"[Embedder] 加载模型: {model_path}, device: {self.device}")
        self.model = SentenceTransformer(model_path, device=self.device)
        self.batch_size = 32
    
    def encode(self, texts: List[str], normalize: bool = True) -> np.ndarray:
        embeddings = self.model.encode(
            texts,
            batch_size=self.batch_size,
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=normalize
        )
        return embeddings
    
    def encode_queries(self, queries: List[str]) -> np.ndarray:
        return self.encode(queries)
