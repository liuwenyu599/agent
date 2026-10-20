"""官方 drawio-mcp（app-server，HTTP）的 Streamable HTTP 客户端。

drawio-mcp 的 Docker 镜像 ``jgraph/drawio-mcp`` 跑的是 **app-server**：
  - 传输：MCP Streamable HTTP，端点 ``<base>/mcp``，默认容器内端口 ``3001``；
  - 健康检查：``GET <base>/health`` → 纯文本 ``ok``（HTTP 200）；
  - 默认绑回环（``LISTEN=127.0.0.1``），镜像内通过环境变量 ``LISTEN=0.0.0.0`` 改全网监听；
  - 无鉴权；内网部署靠端口绑回环 / 防火墙 / 反向代理约束可达范围；
  - ``DRAWIO_ICON_SERVICE_URL=off`` 关闭对 ``icons.diagrams.net`` 的出网补充查询。

本客户端已按仓库 ``mcp-app-server/src/index.js`` + ``test/lenient-input.test.js`` 实测的
工具契约实现（2026-10 校验）：

  get_drawio_reference(format)         format: "xml" | "mermaid"（必填）
  search_shapes(query, limit)         query 必填；limit 可选，默认 10，最大 50
  create_diagram(xml | mermaid, ...)  xml / mermaid 二选一；返回 **文本**（图数据 / 预览），
                                       非 MCP-Apps 宿主下不产出二进制，可作校验/预览。

协议细节（Streamable HTTP，stateless）：
  - POST ``/mcp``，``Content-Type: application/json``，
    ``Accept: application/json, text/event-stream``；
  - ``initialize`` 响应头回 ``Mcp-Session-Id``，后续请求回显该头（服务端无状态，回显无害）；
  - 响应既可能是纯 JSON，也可能是 SSE（``text/event-stream``，``data:`` 行里是 JSON-RPC），
    两种都解析；``notifications/initialized`` 收到 202 无响应体。
"""
from typing import Any, Dict, List, Optional

import httpx

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_PROTOCOL_VERSION = "2024-11-05"
_CLIENT_INFO = {"name": "justice-office", "version": "1.0.0"}

# 我们实际用到的三个工具名（与 jgraph/drawio-mcp app-server 对齐）
TOOL_GET_REFERENCE = "get_drawio_reference"
TOOL_SEARCH_SHAPES = "search_shapes"
TOOL_CREATE_DIAGRAM = "create_diagram"


class DrawioMcpError(Exception):
    """drawio-mcp 调用失败：网络、协议或工具返回 error。"""


class DrawioMcpClient:
    """Streamable HTTP JSON-RPC 2.0 客户端（同步，复用 ppt_agent_client 风格）。"""

    def __init__(
        self,
        base_url: str,
        timeout: int = 30,
        client: Optional[httpx.Client] = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.endpoint = f"{self.base_url}/mcp"
        self.timeout = timeout
        self._session_id: Optional[str] = None
        self._client: Optional[httpx.Client] = client
        self._owns_client = client is None
        self._initialized = False

    # ---- 生命周期 ----------------------------------------------------------
    def _ensure_client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=self.timeout, follow_redirects=True)
        return self._client

    def _post(self, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        client = self._ensure_client()
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        try:
            resp = client.post(self.endpoint, json=payload, headers=headers)
        except httpx.HTTPError as e:  # 网络层错误（连接拒绝 / 超时 / DNS）
            raise DrawioMcpError(f"drawio-mcp 请求失败: {e}") from e

        # 捕获服务端在 initialize 时回发的会话 ID（无状态服务端，回显无害）
        sid = resp.headers.get("mcp-session-id") or resp.headers.get("Mcp-Session-Id")
        if sid:
            self._session_id = sid

        # 通知类（initialized）通常返回 202 且无响应体
        if resp.status_code == 202:
            return None
        if resp.status_code >= 400:
            raise DrawioMcpError(
                f"drawio-mcp HTTP {resp.status_code}: {resp.text[:200]}"
            )
        return self._parse_body(resp)

    @staticmethod
    def _parse_body(resp: httpx.Response) -> Dict[str, Any]:
        ctype = resp.headers.get("content-type", "")
        text = resp.text
        if "text/event-stream" in ctype:
            # 取最后一个 data: 行的 JSON（SSE 可能含注释/心跳行）
            data: Optional[str] = None
            for line in text.splitlines():
                line = line.strip()
                if line.startswith("data:"):
                    data = line[len("data:"):].strip()
            if not data:
                raise DrawioMcpError("drawio-mcp SSE 响应无 data 行")
            try:
                return _loads_json(data)
            except ValueError as e:
                raise DrawioMcpError(f"drawio-mcp SSE data 解析失败: {e}") from e
        try:
            return resp.json()
        except ValueError as e:
            raise DrawioMcpError(f"drawio-mcp 响应非 JSON: {e}") from e

    def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        result = self._post({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": _PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": _CLIENT_INFO,
            },
        })
        if result and "error" in result:
            raise DrawioMcpError(f"initialize 失败: {result['error']}")
        # 发送 initialized 通知（无需响应体）
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        self._initialized = True

    # ---- 工具调用 ----------------------------------------------------------
    def list_tools(self) -> List[Dict[str, Any]]:
        self._ensure_initialized()
        result = self._post({
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list",
            "params": {},
        })
        if not result or "result" not in result:
            raise DrawioMcpError("tools/list 未返回 result")
        if "error" in result:
            raise DrawioMcpError(f"tools/list 失败: {result['error']}")
        return result["result"].get("tools", [])

    def call_tool(
        self, name: str, arguments: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        self._ensure_initialized()
        result = self._post({
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments or {}},
        })
        if not result or "result" not in result:
            raise DrawioMcpError(f"tools/call({name}) 未返回 result")
        if "error" in result:
            raise DrawioMcpError(f"tools/call({name}) 失败: {result['error']}")
        tool_result = result["result"]
        # 工具层业务错误（isError=true）也统一抛异常，便于上层降级
        if tool_result.get("isError"):
            raise DrawioMcpError(
                f"tools/call({name}) 返回业务错误: "
                f"{_text_of(tool_result.get('content', []))[:200]}"
            )
        return tool_result.get("content", [])

    # ---- 业务友好封装 ------------------------------------------------------
    def get_reference(self, fmt: str = "xml") -> str:
        """draw.io 语法参考（XML/Mermaid），模型画第一张图前读一次。"""
        content = self.call_tool(TOOL_GET_REFERENCE, {"format": fmt})
        return _text_of(content)

    def search_shapes(self, query: str, limit: int = 20) -> str:
        """按关键词检索形状样式，返回可直接塞进 XML 的 style 字符串。"""
        content = self.call_tool(TOOL_SEARCH_SHAPES, {"query": query, "limit": limit})
        return _text_of(content)

    def create_diagram(
        self,
        xml: Optional[str] = None,
        mermaid: Optional[str] = None,
    ) -> str:
        """把 .drawio XML（或 Mermaid）渲染为内联图。

        注意：app-server 在非 MCP-Apps 宿主下把图以**文本**形式返回（图数据 / 预览），
        不产出二进制 PNG。本方法返回该文本，可作渲染前的预览/校验，但不是主渲染路径
        （主路径由后端本地 python-pptx 负责）。
        """
        args: Dict[str, Any] = {}
        if xml is not None:
            args["xml"] = xml
        if mermaid is not None:
            args["mermaid"] = mermaid
        if not args:
            raise DrawioMcpError("create_diagram 至少需要 xml 或 mermaid 其一")
        content = self.call_tool(TOOL_CREATE_DIAGRAM, args)
        return _text_of(content)

    # ---- 健康检查（不走 MCP 协议） -----------------------------------------
    def health(self) -> bool:
        client = self._ensure_client()
        try:
            resp = client.get(
                f"{self.base_url}/health", timeout=min(self.timeout, 5)
            )
            return resp.status_code == 200 and "ok" in resp.text.lower()
        except httpx.HTTPError:
            return False

    def close(self) -> None:
        # 仅关闭由本客户端自己创建的 httpx.Client；被注入的客户端（如测试 / 共享连接池）
        # 由调用方负责生命周期，避免重复关闭导致后续复用报错。
        if self._client is not None and self._owns_client:
            self._client.close()
            self._client = None

    def __enter__(self) -> "DrawioMcpClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def _loads_json(s: str) -> Dict[str, Any]:
    import json

    return json.loads(s)


def _text_of(content: List[Dict[str, Any]]) -> str:
    """把 MCP content 数组里所有 text 块拼成字符串。"""
    parts = []
    for item in content:
        if isinstance(item, dict) and item.get("type") == "text":
            parts.append(item.get("text", ""))
    return "\n".join(p for p in parts if p)
