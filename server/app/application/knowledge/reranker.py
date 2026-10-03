"""Second-stage cross-encoder reranker for grounded RAG.

The model is loaded lazily from a local offline path. In production, enabling rerank
without the model present is a deployment error: silently skipping rerank would make
the configured safety policy differ from the actual behavior. Explicit mock mode is
allowed to bypass the heavyweight model so unit tests remain hermetic.
"""
from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Dict, List

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class Reranker:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._model = None

    def _load(self):
        provider = os.getenv("AI_PROVIDER", settings.AI_PROVIDER).strip().lower()
        if provider == "mock" or not settings.RAG_RERANK_ENABLED:
            return None
        if self._model is not None:
            return self._model
        with self._lock:
            if self._model is not None:
                return self._model
            model_path = Path(settings.RAG_RERANK_MODEL_PATH)
            if not model_path.exists():
                raise RuntimeError(
                    f"RAG reranker 已启用但模型不存在：{model_path}。"
                    "请部署 bge-reranker-v2-m3；生产环境禁止静默跳过二阶段重排。"
                )
            from sentence_transformers import CrossEncoder
            self._model = CrossEncoder(str(model_path), local_files_only=True)
            logger.info("[RAG] reranker 已加载: %s", model_path)
            return self._model

    def rerank(self, query: str, candidates: List[Dict], top_k: int) -> List[Dict]:
        if not candidates:
            return []
        model = self._load()
        if model is None:
            return candidates[:top_k]
        pairs = [(query, str(item.get("content") or "")) for item in candidates]
        scores = model.predict(pairs)
        ranked = []
        for item, score in zip(candidates, scores):
            clone = dict(item)
            clone["rerank_score"] = float(score)
            ranked.append(clone)
        ranked.sort(key=lambda x: x["rerank_score"], reverse=True)
        return ranked[:top_k]


reranker = Reranker()
