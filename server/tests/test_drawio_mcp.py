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

NATIVE_XML = '''<mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/>
<mxCell id="a" value="受理" vertex="1" parent="1" style="rounded=1;fillColor=#E8F0FA;">
<mxGeometry x="0" y="0" width="150" height="70" as="geometry"/></mxCell>
<mxCell id="b" value="审核" vertex="1" parent="1" style="rhombus;">
<mxGeometry x="250" y="0" width="150" height="70" as="geometry"/></mxCell>
<mxCell id="edge" edge="1" parent="1" source="a" target="b"/>
</root></mxGraphModel>'''

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


def test_drawio_native_export_contains_editable_nodes_and_connector():
    import io
    from pptx import Presentation
    from pptx.enum.shapes import MSO_SHAPE_TYPE
    from app.application.ppt.ppt_engine import build_pptx, DEFAULT_COLORS, DEFAULT_LAYOUTS

    outline = {"title": "业务流程", "slides": [{
        "type": "process", "title": "业务流程", "points": [],
        "blocks": {"drawio_xml": NATIVE_XML},
    }]}
    data = build_pptx(outline, {"colors": DEFAULT_COLORS, "layouts": DEFAULT_LAYOUTS})
    presentation = Presentation(io.BytesIO(data))
    slide = presentation.slides[0]
    assert {"受理", "审核"} <= {shape.text for shape in slide.shapes if shape.has_text_frame}
    assert sum(shape.shape_type == MSO_SHAPE_TYPE.LINE for shape in slide.shapes) == 1
    assert not any(shape.shape_type == MSO_SHAPE_TYPE.PICTURE for shape in slide.shapes)
    assert all(shape.left >= 0 and shape.top >= 0 for shape in slide.shapes)
    node = next(shape for shape in slide.shapes if shape.has_text_frame and shape.text == "受理")
    node.text = "已修改"
    output = io.BytesIO()
    presentation.save(output)
    assert any(shape.has_text_frame and shape.text == "已修改"
               for shape in Presentation(io.BytesIO(output.getvalue())).slides[0].shapes)


@pytest.mark.parametrize("learned", [False, True])
@pytest.mark.parametrize("partial_failure", [False, True])
def test_one_failed_diagram_keeps_other_pages_and_reports_fallback(monkeypatch, learned, partial_failure):
    import io
    from pptx import Presentation
    from pptx.util import Inches, Pt
    from app.application.ppt import ppt_engine
    from app.application.ppt import drawio_native

    if partial_failure:
        def fail_after_adding_shape(slide, *_args):
            slide.shapes.add_textbox(0, 0, Inches(1), Inches(1)).text = "未完成图形残片"
            raise RuntimeError("simulated drawing failure")
        monkeypatch.setattr(drawio_native, "render_diagram", fail_after_adding_shape)
    steps = ["受理", "审核", *[f"流程环节{number}" for number in range(3, 9)]]
    outline = {"title": "导出测试", "slides": [
        {"type": "process", "title": "办理流程", "points": [], "note": "原演讲备注",
         "blocks": {"drawio_xml": NATIVE_XML if partial_failure else "invalid XML",
                    "process": steps}},
        {"type": "content", "title": "工作要求", "points": ["其他页面应当完整导出"]},
    ]}
    template = {"colors": ppt_engine.DEFAULT_COLORS, "layouts": ppt_engine.DEFAULT_LAYOUTS}
    warnings = []
    if learned:
        base = Presentation()
        slide = base.slides.add_slide(base.slide_layouts[6])
        title = slide.shapes.add_textbox(Inches(.5), Inches(.3), Inches(8), Inches(1))
        title.text = "模板标题"
        title.text_frame.paragraphs[0].runs[0].font.size = Pt(30)
        body = slide.shapes.add_textbox(Inches(.5), Inches(2), Inches(8), Inches(4))
        body.text = "模板示例正文"
        body.text_frame.paragraphs[0].runs[0].font.size = Pt(16)
        buffer = io.BytesIO()
        base.save(buffer)
        base_bytes = buffer.getvalue()
        library = ppt_engine.analyze_template(base_bytes)["layouts"]
        # A one-slide fixture is classified as a cover by position; bind it as
        # the content layout whose title/body regions this export test exercises.
        library[0]["detected_type"] = "content"
        data = ppt_engine.build_pptx_learned(outline, template, base_bytes, library, warnings=warnings)
    else:
        data = ppt_engine.build_pptx(outline, template, warnings=warnings)
    exported = Presentation(io.BytesIO(data))
    assert len(exported.slides) == 2
    text = "\n".join(shape.text for slide in exported.slides for shape in slide.shapes
                     if shape.has_text_frame)
    assert all(value in text for value in [*steps, "工作要求", "其他页面应当完整导出"]), text
    assert "未完成图形残片" not in text
    assert len(warnings) == 1 and "基础流程版式" in warnings[0]
    assert "基础流程版式" in exported.slides[0].notes_slide.notes_text_frame.text


@pytest.mark.parametrize("xml", [
    '<!DOCTYPE x [<!ENTITY x "value">]><mxGraphModel/>',
    NATIVE_XML.replace('width="150"', 'width="NaN"'),
    NATIVE_XML.replace('target="b"', 'target="missing"'),
    NATIVE_XML.replace('style="rhombus;"', 'style="shape=image;image=http://example.com/image.png;"'),
])
def test_drawio_native_rejects_unsupported_diagrams(xml):
    from app.application.ppt.drawio_native import parse_diagram
    with pytest.raises(ValueError):
        parse_diagram(xml)


def test_drawio_native_generation_uses_mcp_and_validates_before_return(monkeypatch):
    svc = DrawioService(base_url="http://drawio-mcp:3001")
    calls = []
    monkeypatch.setattr(svc, "get_reference", lambda: calls.append("reference") or "mxCell reference")

    class Assistant:
        def complete(self, messages, **_kwargs):
            calls.append("model")
            assert "mxCell reference" in messages[-1]["content"]
            return json.dumps({"xml": NATIVE_XML}, ensure_ascii=False)

    result = svc.generate_native_diagram(Assistant(), {"title": "审批流程"})
    assert calls == ["reference", "model"]
    assert result["blocks"]["drawio_xml"] == NATIVE_XML
    assert result["blocks"]["process"] == ["受理", "审核"]

class TestDrawioServiceConfigured:
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
