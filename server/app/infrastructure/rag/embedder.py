"""文本向量化：BGE 实现（懒加载重依赖）+ HTTP 远程实现 + Mock 实现（测试用）。"""
import hashlib
import json
import urllib.request
from typing import List

import numpy as np

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# BGE v1.5 中文模型官方推荐的查询侧检索指令（仅加在 query 上，文档侧不加）
BGE_QUERY_INSTRUCTION = "为这个句子生成表示以用于检索相关文章："


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
        # 检索场景：查询加指令前缀可显著提升 BGE v1.5 召回质量
        return self.encode([BGE_QUERY_INSTRUCTION + q for q in queries])


class HTTPEmbedder:
    """OpenAI 兼容 /embeddings 远程向量化（stdlib urllib，无额外依赖）。

    未配置 EMBEDDING_HTTP_URL 时 __init__ 抛 RuntimeError，由上层回退关键词检索。
    """

    DIM = 384

    def __init__(self) -> None:
        self.url = settings.EMBEDDING_HTTP_URL
        self.model = settings.EMBEDDING_HTTP_MODEL
        if not self.url:
            raise RuntimeError("[Embedder] EMBEDDING_HTTP_URL 未配置，无法使用 http embedder")

    def _post(self, texts):
        body = json.dumps({"model": self.model, "input": texts}).encode("utf-8")
        req = urllib.request.Request(
            self.url, data=body, headers={"Content-Type": "application/json"}, method="POST"
        )
        with urllib.request.urlopen(req, timeout=settings.EMBEDDING_HTTP_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data

    @staticmethod
    def _normalize(vec):
        arr = np.asarray(vec, dtype=np.float32)
        norm = np.linalg.norm(arr)
        if norm > 0:
            arr = arr / norm
        return arr

    def encode(self, texts: List[str], normalize: bool = True) -> np.ndarray:
        data = self._post(texts)
        out = [self._normalize(item["embedding"]) for item in data["data"]]
        return np.vstack(out)

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
