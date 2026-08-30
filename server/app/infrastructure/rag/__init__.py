"""RAG 基础设施工厂：按配置返回 Embedder / VectorStore。"""
from app.application.ports import Embedder, VectorStore
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_embedder: Embedder = None
_vector_store: VectorStore = None


def get_embedder() -> Embedder:
    global _embedder
    if _embedder is not None:
        return _embedder
    if settings.EMBEDDING_PROVIDER == "mock":
        from app.infrastructure.rag.embedder import MockEmbedder
        _embedder = MockEmbedder()
    else:
        from app.infrastructure.rag.embedder import BGEEmbedder
        _embedder = BGEEmbedder()
    logger.info("[RAG] Embedder: %s", type(_embedder).__name__)
    return _embedder


def get_vector_store() -> VectorStore:
    global _vector_store
    if _vector_store is not None:
        return _vector_store
    from app.infrastructure.rag.vector_store import FAISSVectorStore
    _vector_store = FAISSVectorStore()
    return _vector_store


def reset_rag() -> None:
    """测试用：重置缓存实例。"""
    global _embedder, _vector_store
    _embedder = None
    _vector_store = None
