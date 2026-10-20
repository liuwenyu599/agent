"""drawio-mcp 客户端与服务层测试（httpx MockTransport，无需真服务）。

覆盖：
- DrawioMcpClient 按 jgraph/drawio-mcp app-server 实测契约解析 initialize / 工具结果
  （含纯 JSON 与 SSE 两种响应形态）；
- 会话 ID 在 initialize 时回发并被后续请求回显；
- DrawioService 在 URL 未配置时静默降级（返回 None），配置后正常返回，调用异常时降级。
"""
import json

import httpx
import pytest

from app.application.ppt.drawio_service import DrawioService
from app.infrastructure.drawio.mcp_client import DrawioMcpClient, DrawioMcpError


def _json_rpc(result, req_id=3):
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _make_handler(use_sse: bool = False):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200, text="ok")
        if request.method != "POST":
            return httpx.Response(405)
        body = json.loads(request.content)
        method = body.get("method")

        if method == "initialize":
            return httpx.Response(
                200,
                json=_json_rpc(
                    {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "serverInfo": {"name": "drawio-mcp", "version": "1.0.0"},
                    }
                ),
                headers={"Mcp-Session-Id": "ui-test-session"},
            )
        if method == "notifications/initialized":
            return httpx.Response(202)
        if method == "tools/call":
            name = body["params"]["name"]
            if name == "get_drawio_reference":
                content = [{"type": "text", "text": "<mxGraphModel>REFERENCE</mxGraphModel>"}]
            elif name == "search_shapes":
                content = [{"type": "text", "text": "rounded;whiteSpace=wrap;html=1;"}]
            elif name == "create_diagram":
                content = [{"type": "text", "text": '{"xml":"<mxGraphModel></mxGraphModel>"}'}]
            else:
                content = []
            payload = _json_rpc({"content": content, "isError": False})
            if use_sse:
                sse = f"event: message\ndata: {json.dumps(payload)}\n\n"
                return httpx.Response(
                    200, text=sse, headers={"content-type": "text/event-stream"}
                )
            return httpx.Response(200, json=payload)
        return httpx.Response(404)

    return handler


@pytest.fixture
def client() -> DrawioMcpClient:
    transport = httpx.MockTransport(_make_handler())
    return DrawioMcpClient("http://test", client=httpx.Client(transport=transport))


class TestDrawioMcpClient:
    def test_session_id_captured_on_initialize(self, client: DrawioMcpClient):
        client._ensure_initialized()
        assert client._session_id == "ui-test-session"

    def test_get_reference(self, client: DrawioMcpClient):
        assert "REFERENCE" in client.get_reference("xml")

    def test_search_shapes(self, client: DrawioMcpClient):
        assert "whiteSpace=wrap" in client.search_shapes("rounded rectangle", limit=5)

    def test_create_diagram(self, client: DrawioMcpClient):
        assert "mxGraphModel" in client.create_diagram(xml="<mxGraphModel></mxGraphModel>")

    def test_health_ok(self, client: DrawioMcpClient):
        assert client.health() is True

    def test_sse_response_parsed(self):
        transport = httpx.MockTransport(_make_handler(use_sse=True))
        c = DrawioMcpClient("http://test", client=httpx.Client(transport=transport))
        assert "REFERENCE" in c.get_reference("xml")

    def test_create_diagram_requires_input(self):
        c = DrawioMcpClient("http://test")
        with pytest.raises(DrawioMcpError):
            c.create_diagram()


class TestDrawioService:
    def test_disabled_when_url_empty(self, monkeypatch):
        monkeypatch.setattr(
            "app.application.ppt.drawio_service.settings.DRAWIO_MCP_URL", ""
        )
        svc = DrawioService()
        assert svc.enabled is False
        assert svc.get_reference() is None
        assert svc.search_shapes("x") is None
        assert svc.create_diagram(xml="<x/>") is None
        assert svc.health() is False

    def test_enabled_returns_text(self, monkeypatch):
        monkeypatch.setattr(
            "app.application.ppt.drawio_service.settings.DRAWIO_MCP_URL",
            "http://drawio-mcp:3001",
        )
        transport = httpx.MockTransport(_make_handler())
        svc = DrawioService(client=httpx.Client(transport=transport))
        assert svc.enabled is True
        assert "REFERENCE" in (svc.get_reference() or "")
        assert "whiteSpace=wrap" in (svc.search_shapes("box") or "")
        assert "mxGraphModel" in (svc.create_diagram(xml="<mxGraphModel/>") or "")

    def test_degrades_on_connection_error(self, monkeypatch):
        # 指向不可达端口，触发真实网络错误 → 服务层静默降级为 None（不抛 500）
        monkeypatch.setattr(
            "app.application.ppt.drawio_service.settings.DRAWIO_MCP_URL",
            "http://127.0.0.1:1/mcp",
        )
        svc = DrawioService(timeout=2)
        assert svc.get_reference() is None
        assert svc.health() is False
