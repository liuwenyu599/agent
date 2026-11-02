"""drawio-mcp 客户端与服务层测试（httpx MockTransport，无需真服务）。

覆盖：
- DrawioMcpClient 按 jgraph/drawio-mcp app-server 实测契约解析 initialize / 工具结果
  （含纯 JSON 与 SSE 两种响应形态）；
- 会话 ID 在 initialize 时回发并被后续请求回显；
- DrawioService 在 URL 未配置时静默降级（返回 None），配置后正常返回，调用异常时降级。
"""
import json
import os

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


def test_drawio_native_export_uses_template_palette_for_unspecified_colors():
    import io
    from pptx import Presentation
    from app.application.ppt.ppt_engine import build_pptx, DEFAULT_COLORS, DEFAULT_LAYOUTS

    outline = {"title": "业务流程", "slides": [{
        "type": "process", "title": "业务流程", "points": [],
        "blocks": {"drawio_xml": NATIVE_XML},
    }]}
    colors = {**DEFAULT_COLORS, "light": "F2EADB", "primary": "123456"}
    data = build_pptx(outline, {"colors": colors, "layouts": DEFAULT_LAYOUTS})
    shapes = Presentation(io.BytesIO(data)).slides[0].shapes
    unstyled = next(shape for shape in shapes if shape.has_text_frame and shape.text == "审核")
    assert str(unstyled.fill.fore_color.rgb) == "F2EADB"
    assert str(unstyled.line.color.rgb) == "123456"


def test_drawio_native_export_keeps_text_size_weight_and_alignment():
    import io
    from pptx import Presentation
    from pptx.enum.text import PP_ALIGN
    from app.application.ppt.drawio_native import render_diagram

    xml = NATIVE_XML.replace(
        'rounded=1;fillColor=#E8F0FA;',
        'rounded=1;fillColor=#E8F0FA;fontSize=22;fontStyle=1;align=left;'
    )
    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    render_diagram(slide, xml, 0, 0, presentation.slide_width,
                   presentation.slide_height)
    node = next(shape for shape in slide.shapes if shape.has_text_frame
                and shape.text == "受理")
    run = node.text_frame.paragraphs[0].runs[0]

    assert run.font.size.pt == 22
    assert run.font.bold is True
    assert node.text_frame.paragraphs[0].alignment == PP_ALIGN.LEFT


def test_drawio_source_keeps_each_diagram_as_an_editable_page():
    from xml.etree import ElementTree as ET
    from app.application.ppt.drawio_native import build_drawio_source

    outline = {"slides": [
        {"title": "封面", "blocks": {}},
        {"title": "受理流程", "blocks": {"drawio_xml": NATIVE_XML}},
        {"title": "审核流程", "blocks": {"drawio_xml": NATIVE_XML}},
    ]}
    source = build_drawio_source(outline)
    root = ET.fromstring(source)
    pages = root.findall("diagram")
    assert [page.get("name") for page in pages] == ["受理流程", "审核流程"]
    assert all(page.find("mxGraphModel") is not None for page in pages)


@pytest.mark.parametrize("box", ["-1,0,150,70", "990,0,150,70"])
def test_generated_diagram_rejects_out_of_canvas_nodes(box):
    from app.application.ppt.drawio_native import validate_generated_layout

    x, y, width, height = box.split(",")
    xml = NATIVE_XML.replace('x="0" y="0" width="150" height="70"',
                             f'x="{x}" y="{y}" width="{width}" height="{height}"', 1)
    with pytest.raises(ValueError, match="画布"):
        validate_generated_layout(xml)


def test_generated_diagram_rejects_overlapping_nodes():
    from app.application.ppt.drawio_native import validate_generated_layout

    xml = NATIVE_XML.replace('x="250" y="0"', 'x="20" y="10"')
    with pytest.raises(ValueError, match="重叠"):
        validate_generated_layout(xml)


def test_generated_diagram_rejects_labels_too_long_for_a_node():
    from app.application.ppt.drawio_native import validate_generated_layout

    xml = NATIVE_XML.replace('value="受理"', f'value="{"办理要求" * 6}"')
    with pytest.raises(ValueError, match="文字"):
        validate_generated_layout(xml)


def test_generated_diagram_limits_nodes_to_twelve():
    from app.application.ppt.drawio_native import validate_generated_layout

    cells = "".join(
        f'<mxCell id="n{index}" value="节点{index}" vertex="1" parent="1">'
        f'<mxGeometry x="{index * 70}" y="0" width="60" height="50" as="geometry"/>'
        '</mxCell>' for index in range(13)
    )
    xml = f'<mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/>{cells}</root></mxGraphModel>'
    with pytest.raises(ValueError, match="12"):
        validate_generated_layout(xml)


@pytest.mark.parametrize("learned", [False, True])
@pytest.mark.parametrize("partial_failure", [False, True])
@pytest.mark.parametrize("diagram_kind,legacy", [
    ("process", False), ("relationship", False), ("relationship", True),
])
def test_one_failed_diagram_keeps_other_pages_and_reports_fallback(
        monkeypatch, learned, partial_failure, diagram_kind, legacy):
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
    blocks = {"drawio_xml": NATIVE_XML if partial_failure else "invalid XML",
              "drawio_kind": diagram_kind}
    blocks["process" if diagram_kind == "process" or legacy else "diagram_labels"] = steps
    outline = {"title": "导出测试", "slides": [
        {"type": "process", "title": "办理流程", "points": [], "note": "原演讲备注",
         "blocks": blocks},
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
    expected_layout = "基础流程版式" if diagram_kind == "process" else "基础文字版式"
    assert len(warnings) == 1 and expected_layout in warnings[0]
    assert expected_layout in exported.slides[0].notes_slide.notes_text_frame.text
    if diagram_kind != "process":
        assert "第1步" not in text and "1. 受理" not in text


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


def test_agents365_skill_layout_turns_planned_graph_into_editable_nodes(monkeypatch):
    from app.application.ppt import drawio_skill_layout
    from app.application.ppt.drawio_native import parse_diagram

    monkeypatch.setattr(drawio_skill_layout.shutil, "which", lambda _name: "dot")
    monkeypatch.setattr(drawio_skill_layout.autolayout, "layout", lambda _source:
                        (4.0, {"n1": (1.0, 2.0), "n2": (4.0, 2.0)}, {}))
    slide = {"title": "办理流程", "blocks": {
        "diagram_nodes": [{"id": "a", "label": "受理"},
                          {"id": "b", "label": "审核"}],
        "diagram_edges": [{"source": "a", "target": "b"}],
    }}

    xml = drawio_skill_layout.layout_slide_graph(
        slide, "process", {"primary": "123456"})
    parsed = parse_diagram(xml)
    assert [node["label"] for node in parsed["nodes"]] == ["受理", "审核"]
    assert len(parsed["edges"]) == 1
    assert parsed["nodes"][0]["style"]["strokeColor"] == "#123456"

    svc = DrawioService(base_url="")
    class NoModel:
        def complete(self, *_args, **_kwargs):
            pytest.fail("planned graph must not call the model twice")
    result = svc.generate_native_diagram(
        NoModel(), slide, kind="process", style={"colors": {"primary": "123456"}})
    assert result["blocks"]["drawio_xml"] == xml
    from pptx import Presentation
    from app.application.ppt.drawio_native import render_diagram
    deck = Presentation()
    page = deck.slides.add_slide(deck.slide_layouts[6])
    render_diagram(page, xml, 0, 0, 8_000_000, 4_000_000)
    assert len(page.shapes) >= 3
    assert all(shape.shape_type != 13 for shape in page.shapes)  # no raster picture


def test_graphviz_dot_setting_enables_skill_without_system_path(monkeypatch, tmp_path):
    """GRAPHVIZ_DOT 指向 dot 后，本机无需改系统 PATH 即可走 skill 布局。"""
    from app.application.ppt import drawio_skill_layout
    from app.core.config import settings

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    dot = fake_bin / ("dot.exe" if os.name == "nt" else "dot")
    dot.write_bytes(b"")
    # ensure_dot 会改写 PATH；换成副本，避免污染同进程其他测试
    monkeypatch.setattr(drawio_skill_layout.os, "environ", {**os.environ})
    monkeypatch.setattr(settings, "GRAPHVIZ_DOT", str(dot))
    monkeypatch.setattr(drawio_skill_layout.autolayout, "layout", lambda _src:
                        (4.0, {"n1": (1.0, 2.0), "n2": (4.0, 2.0)}, {}))

    resolved = drawio_skill_layout.ensure_dot()
    assert resolved and resolved.lower() == str(dot).lower()
    assert str(fake_bin).lower() in drawio_skill_layout.os.environ["PATH"].lower()
    assert DrawioService(base_url="").native_available

    xml = drawio_skill_layout.layout_slide_graph(
        {"title": "办理流程", "blocks": {
            "diagram_nodes": [{"id": "a", "label": "受理"}, {"id": "b", "label": "审核"}],
            "diagram_edges": [{"source": "a", "target": "b"}]}},
        "process", {"primary": "123456"})
    assert xml and "受理" in xml


def test_graphviz_dot_setting_ignores_missing_file(monkeypatch, tmp_path):
    from app.application.ppt import drawio_skill_layout
    from app.core.config import settings

    monkeypatch.setattr(settings, "GRAPHVIZ_DOT", str(tmp_path / "nope" / "dot.exe"))
    assert drawio_skill_layout.ensure_dot() is None
    assert not DrawioService(base_url="").native_available


def test_agents365_linter_rejects_duplicate_root_cells():
    from app.application.ppt.drawio_native import validate_generated_layout
    duplicate = NATIVE_XML.replace('<mxCell id="1" parent="0"/>',
                                   '<mxCell id="1" parent="0"/><mxCell id="1" parent="0"/>')
    with pytest.raises(ValueError, match="E-DUP-ID"):
        validate_generated_layout(duplicate)


def test_page_action_uses_35b_plan_then_skill_layout_without_mcp(monkeypatch):
    from app.application.ppt import drawio_skill_layout
    monkeypatch.setattr(drawio_skill_layout.shutil, "which", lambda _name: "dot")
    monkeypatch.setattr(drawio_skill_layout.autolayout, "layout", lambda _source:
                        (4.0, {"n1": (1.0, 2.0), "n2": (4.0, 2.0)}, {}))
    calls = []
    class Assistant:
        def complete(self, messages, **_kwargs):
            calls.append(messages[-1]["content"])
            return json.dumps({
                "diagram_nodes": [{"id": "a", "label": "受理"},
                                  {"id": "b", "label": "审核"}],
                "diagram_edges": [{"source": "a", "target": "b"}],
            }, ensure_ascii=False)

    svc = DrawioService(base_url="")
    result = svc.generate_native_diagram(
        Assistant(), {"title": "案件办理", "points": ["受理后审核"]},
        kind="process")

    assert len(calls) == 1
    assert result["blocks"]["diagram_nodes"][0]["label"] == "受理"
    assert result["blocks"]["drawio_xml"].startswith("<mxGraphModel")


def test_drawio_reference_is_reused_across_pages(monkeypatch):
    svc = DrawioService(base_url="http://drawio-mcp:3001")
    calls = []

    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def get_reference(self, fmt):
            calls.append(fmt)
            return "mxGraphModel reference"

    monkeypatch.setattr(svc, "_client", lambda: FakeClient())

    assert svc.get_reference() == "mxGraphModel reference"
    assert svc.get_reference() == "mxGraphModel reference"
    assert calls == ["xml"]


def test_drawio_generation_uses_template_style_and_relation_kind(monkeypatch):
    svc = DrawioService(base_url="http://drawio-mcp:3001")
    monkeypatch.setattr(svc, "get_reference", lambda: "mxGraphModel reference")
    prompts = []

    class Assistant:
        def complete(self, messages, **_kwargs):
            prompts.append(messages[-1]["content"])
            return json.dumps({"xml": NATIVE_XML}, ensure_ascii=False)

    result = svc.generate_native_diagram(
        Assistant(), {"title": "单位关系", "points": ["受理", "审核"]},
        kind="relationship", style={"colors": {"primary": "123456", "accent": "ABCDEF"},
                                    "font": "思源黑体"})
    assert "关系图" in prompts[0]
    assert "#123456" in prompts[0] and "#ABCDEF" in prompts[0]
    assert "思源黑体" in prompts[0]
    assert result["blocks"]["drawio_kind"] == "relationship"
    assert result["blocks"]["diagram_labels"] == ["受理", "审核"]
    assert "process" not in result["blocks"]


def test_drawio_generation_rejects_missing_explicit_relationship(monkeypatch):
    svc = DrawioService(base_url="http://drawio-mcp:3001")
    monkeypatch.setattr(svc, "get_reference", lambda: "mxGraphModel reference")

    class Assistant:
        def complete(self, *_args, **_kwargs):
            return json.dumps({"xml": NATIVE_XML}, ensure_ascii=False)

    slide = {"type": "process", "title": "部门协作", "blocks": {
        "drawio_kind": "relationship",
        "diagram_nodes": [{"id": "a", "label": "司法局"},
                          {"id": "b", "label": "司法所"}],
        "diagram_edges": [{"source": "a", "target": "b"}],
    }}

    with pytest.raises(RuntimeError, match="未通过结构检查"):
        svc.generate_native_diagram(Assistant(), slide, kind="relationship")


def test_drawio_generation_keeps_explicit_nodes_and_edge(monkeypatch):
    svc = DrawioService(base_url="http://drawio-mcp:3001")
    monkeypatch.setattr(svc, "get_reference", lambda: "mxGraphModel reference")

    class Assistant:
        def complete(self, *_args, **_kwargs):
            return json.dumps({"xml": NATIVE_XML}, ensure_ascii=False)

    slide = {"type": "process", "title": "办理关系", "blocks": {
        "diagram_nodes": [{"id": "first", "label": "受理"},
                          {"id": "second", "label": "审核"}],
        "diagram_edges": [{"source": "first", "target": "second"}],
    }}

    result = svc.generate_native_diagram(Assistant(), slide, kind="relationship")

    assert result["blocks"]["drawio_kind"] == "relationship"
    assert result["blocks"]["diagram_edges"] == slide["blocks"]["diagram_edges"]


def test_outline_enrichment_uses_model_selected_diagram_kind(monkeypatch):
    from app.application.ppt import ppt_engine

    calls = []

    class FakeDrawio:
        enabled = True
        native_available = True

        def generate_native_diagram(self, _assistant, slide, kind="process"):
            calls.append((slide["title"], kind))
            return {**slide, "blocks": {**slide["blocks"], "drawio_xml": NATIVE_XML}}

    monkeypatch.setattr("app.application.ppt.drawio_service.DrawioService", FakeDrawio)
    outline = {"slides": [
        {"type": "process", "title": "审批链", "blocks": {"process": ["受理", "审核"]}},
        {"type": "process", "title": "部门关系", "blocks": {
            "drawio_kind": "relationship", "diagram_nodes": [
                {"id": "a", "label": "司法局"}, {"id": "b", "label": "司法所"}],
            "diagram_edges": [{"source": "a", "target": "b"}]}},
    ]}

    ppt_engine.enrich_outline_with_diagrams(object(), outline)

    assert calls == [("审批链", "process"), ("部门关系", "relationship")]


def test_relationship_page_keeps_node_labels_when_mcp_is_unavailable():
    import io
    from pptx import Presentation
    from app.application.ppt.ppt_engine import build_pptx, DEFAULT_COLORS, DEFAULT_LAYOUTS

    outline = {"title": "部门协作", "slides": [{
        "type": "process", "title": "部门关系", "points": [],
        "blocks": {"drawio_kind": "relationship", "diagram_nodes": [
            {"id": "a", "label": "司法局"}, {"id": "b", "label": "司法所"}],
            "diagram_edges": [{"source": "a", "target": "b"}]},
    }]}

    data = build_pptx(outline, {"colors": DEFAULT_COLORS, "layouts": DEFAULT_LAYOUTS})
    visible = " ".join(shape.text for shape in Presentation(io.BytesIO(data)).slides[0].shapes
                       if shape.has_text_frame)

    assert "司法局" in visible and "司法所" in visible

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
