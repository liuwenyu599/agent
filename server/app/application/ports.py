"""跨模块端口协议（Clean Architecture：application 只依赖这些抽象）。

基础设施实现位于 app.infrastructure.ai / app.infrastructure.rag，
通过各自模块的工厂函数获取（按配置切换真实/mock 实现）。
"""
from typing import Any, AsyncIterator, Dict, List, Protocol


class LLMGateway(Protocol):
    """大模型网关：OpenAI 兼容 chat/completions 传输层。"""

    async def acomplete(
        self,
        messages: List[Dict[str, Any]],
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> str:
        """异步对话补全；ASGI 请求链路应优先使用。"""
        ...

    async def acomplete_with_tools(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        tool_choice: Any = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> Dict[str, Any]:
        """异步工具调用补全，返回 assistant message 结构。"""
        ...

    def acomplete_stream(
        self,
        messages: List[Dict[str, Any]],
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> AsyncIterator[str]:
        """异步流式补全。"""
        ...

    # 兼容层：仅供非 ASGI 的离线脚本 / 旧测试使用。生产路由不得在 event loop 中调用。
    def complete(
        self,
        messages: List[Dict[str, Any]],
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> str:
        ...

    def complete_stream(
        self,
        messages: List[Dict[str, Any]],
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> Any:
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
