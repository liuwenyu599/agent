"""DrawioService：把 drawio-mcp 的三个工具封装成业务友好的同步方法。

设计要点：
- 未配置 ``DRAWIO_MCP_URL`` 时，所有方法静默返回 ``None``（不抛异常），调用方据此走
  本地原生 PPTX 渲染，零侵入。
- 配置后，方法返回文本/结构；任何调用异常都被吞掉并返回 ``None``——PPT 是增强层，
  绝不允许它把整条 PPT 链路拖垮成 500。
- 本服务只负责「模型工具调用」后端代理（get_drawio_reference / search_shapes /
  create_diagram）。XML → PNG 的转换由后端本地独立完成（python-pptx 原生渲染 +
  图转 PNG 嵌入），不依赖 drawio-mcp。
"""
from typing import Optional

import httpx

from app.core.config import settings
from app.core.logging import get_logger
from app.infrastructure.drawio.mcp_client import DrawioMcpClient, DrawioMcpError

logger = get_logger(__name__)


class DrawioService:
    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: Optional[int] = None,
        client: Optional[httpx.Client] = None,
    ) -> None:
        self.base_url = (base_url or settings.DRAWIO_MCP_URL or "").strip()
        self.timeout = timeout or settings.DRAWIO_MCP_TIMEOUT
        self._client_override = client
        self._enabled = bool(self.base_url)

    @property
    def enabled(self) -> bool:
        """是否配置了 drawio-mcp；False 时调用方应走本地原生渲染。"""
        return self._enabled

    def _client(self) -> DrawioMcpClient:
        return DrawioMcpClient(
            self.base_url, timeout=self.timeout, client=self._client_override
        )

    def get_reference(self, fmt: str = "xml") -> Optional[str]:
        """draw.io 语法参考（xml/mermaid），模型画第一张图前读一次。"""
        if not self._enabled:
            return None
        try:
            with self._client() as c:
                return c.get_reference(fmt=fmt)
        except DrawioMcpError as e:
            logger.warning("drawio get_reference 失败，降级本地渲染: %s", e)
            return None

    def search_shapes(self, query: str, limit: int = 20) -> Optional[str]:
        """按关键词检索形状样式，返回可直接塞进 XML 的 style 字符串。"""
        if not self._enabled:
            return None
        try:
            with self._client() as c:
                return c.search_shapes(query, limit=limit)
        except DrawioMcpError as e:
            logger.warning("drawio search_shapes 失败，降级本地渲染: %s", e)
            return None

    def create_diagram(
        self, xml: Optional[str] = None, mermaid: Optional[str] = None
    ) -> Optional[str]:
        """把 .drawio XML（或 Mermaid）渲染为内联图文本（预览/校验，非 PNG）。"""
        if not self._enabled:
            return None
        try:
            with self._client() as c:
                return c.create_diagram(xml=xml, mermaid=mermaid)
        except DrawioMcpError as e:
            logger.warning("drawio create_diagram 失败: %s", e)
            return None

    def health(self) -> bool:
        """探活：未配置直接 False；配置后打 /health。"""
        if not self._enabled:
            return False
        try:
            with self._client() as c:
                return c.health()
        except DrawioMcpError:
            return False
