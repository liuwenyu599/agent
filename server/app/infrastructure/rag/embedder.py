"""文本向量化：BGE 实现（懒加载重依赖）+ Mock 实现（测试用）。"""
import hashlib
from typing import List

import numpy as np

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class BGEEmbedder:
    """BGE 中文向量模型。模型与 torch 在首次 encode 时才加载。"""

    def __init__(self, model_path: str = None) -> None:
        self.model_path = model_path or settings.EMBED_MODEL_PATH
        self.batch_size = 32
        self._model = None

    def _load(self) -> None:
        if self._model is not None:
            return
        import torch
        from sentence_transformers import SentenceTransformer

        device = "cuda" if torch.cuda.is_available() else "cpu"
        logger.info("[Embedder] 加载模型: %s, device: %s", self.model_path, device)
        self._model = SentenceTransformer(self.model_path, device=device)

    def encode(self, texts: List[str], normalize: bool = True) -> np.ndarray:
        self._load()
        return self._model.encode(
            texts,
            batch_size=self.batch_size,
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=normalize,
        )

    def encode_queries(self, queries: List[str]) -> np.ndarray:
        return self.encode(queries)


class MockEmbedder:
    """确定性 hash 向量（384 维，L2 归一化），不依赖 torch。"""

    DIM = 384

    def encode(self, texts: List[str], normalize: bool = True) -> np.ndarray:
        rows = []
        for t in texts:
            seed = hashlib.sha512(t.encode("utf-8")).digest()
            buf = b""
            while len(buf) < self.DIM:
                seed = hashlib.sha512(seed).digest()
                buf += seed
            # uint8 -> [-1, 1]，避免随机字节直接解释为 float32 产生 NaN/Inf
            vec = np.frombuffer(buf[: self.DIM], dtype=np.uint8).astype(np.float32) / 127.5 - 1.0
            if normalize:
                norm = np.linalg.norm(vec)
                if norm > 0:
                    vec = vec / norm
            rows.append(vec)
        return np.vstack(rows)

    def encode_queries(self, queries: List[str]) -> np.ndarray:
        return self.encode(queries)
