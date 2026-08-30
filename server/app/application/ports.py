"""跨模块端口协议（Clean Architecture：application 只依赖这些抽象）。

基础设施实现位于 app.infrastructure.ai / app.infrastructure.rag，
通过各自模块的工厂函数获取（按配置切换真实/mock 实现）。
"""
from typing import Any, Dict, List, Optional, Protocol


class LLMGateway(Protocol):
    """大模型网关：OpenAI 兼容 chat/completions 传输层。"""

    def complete(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> str:
        """同步对话补全，返回模型文本。失败抛 app.core.exceptions.AIServiceError。"""
        ...

    @property
    def model_name(self) -> str:
        ...


class Embedder(Protocol):
    """文本向量化。"""

    def encode(self, texts: List[str]) -> Any:
        """返回 numpy 数组 (n, dim)。"""
        ...

    def encode_queries(self, queries: List[str]) -> Any:
        ...


class VectorStore(Protocol):
    """向量库：按知识库范围检索。"""

    def add_chunks(self, chunks: List[Dict]) -> None:
        """chunks 项：{chunk_id, doc_id, kb_id, content, title, embedding}"""
        ...

    def search(self, query_embedding: Any, kb_ids: List[str], top_k: int = 20) -> List[Dict]:
        """返回 [{chunk_id, doc_id, content, title, distance}]，distance 越大越相似（内积）。"""
        ...

    def delete_by_document(self, doc_id: str) -> int:
        """删除某文档的全部向量，返回删除数量。"""
        ...
