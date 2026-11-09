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


def test_drawio_native_keeps_editable_visual_styles_in_pptx():
    import io
    from pptx import Presentation
    from pptx.enum.dml import MSO_FILL_TYPE
    from app.application.ppt.drawio_native import render_diagram

    xml = (NATIVE_XML.replace(
        'rounded=1;fillColor=#E8F0FA;',
        'rounded=1;fillColor=#E8F0FA;gradientColor=#FFFFFF;'
        'strokeColor=#123456;strokeWidth=2.5;shadow=1;'
        'fontFamily=Noto Sans CJK SC;')
        .replace('id="edge" edge="1"',
                 'id="edge" style="strokeWidth=3;strokeColor=#123456;" edge="1"'))
    deck = Presentation()
    page = deck.slides.add_slide(deck.slide_layouts[6])
    render_diagram(page, xml, 0, 0, deck.slide_width, deck.slide_height)
    output = io.BytesIO()
    deck.save(output)
    reloaded = Presentation(io.BytesIO(output.getvalue()))
    shapes = reloaded.slides[0].shapes
    node = next(shape for shape in shapes if shape.has_text_frame and shape.text == "受理")
    edge = next(shape for shape in shapes if shape.shape_type == 9)

    assert node.fill.type == MSO_FILL_TYPE.GRADIENT
    assert str(node.fill.gradient_stops[0].color.rgb) == "E8F0FA"
    assert str(node.fill.gradient_stops[-1].color.rgb) == "FFFFFF"
    assert node.line.width.pt == 2.5
    assert node.text_frame.paragraphs[0].runs[0].font.name == "Times New Roman"
    assert "outerShdw" in node._element.xml
    assert edge.line.width.pt == 3
    assert all(shape.shape_type != 13 for shape in shapes)


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
    from app.application.ppt.drawio_native import parse_diagram
    nodes = parse_diagram(result["blocks"]["drawio_xml"])["nodes"]
    assert [node["label"] for node in nodes] == ["受理", "审核"]
    assert nodes[0]["style"]["shadow"] == "1"
    assert nodes[0]["style"]["fontColor"] == "#15365D"
    assert result["blocks"]["process"] == ["受理", "审核"]


def test_agents365_skill_layout_turns_planned_graph_into_editable_nodes(monkeypatch):
    from app.application.ppt import drawio_skill_layout
    from app.application.ppt.drawio_native import parse_diagram

    monkeypatch.setattr(drawio_skill_layout.shutil, "which", lambda _name: "dot")
    monkeypatch.setattr(drawio_skill_layout.autolayout, "layout", lambda _source, **_kwargs:
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
    # 扁平政务风：不要投影与渐变，节点字号不低于 14pt，连线用主题色细线。
    assert "shadow" not in parsed["nodes"][0]["style"]
    assert "gradientColor" not in parsed["nodes"][0]["style"]
    assert float(parsed["nodes"][0]["style"]["fontSize"]) >= 14
    assert parsed["edges"][0]["style"]["strokeColor"] == "#123456"
    assert float(parsed["edges"][0]["style"]["strokeWidth"]) <= 1.5

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
    render_diagram(page, xml, 0, 0, 8_000_000, 4_000_000, font="模板字体")
    assert len(page.shapes) >= 3
    assert all(shape.shape_type != 13 for shape in page.shapes)  # no raster picture
    first = next(shape for shape in page.shapes if shape.has_text_frame and shape.text == "受理")
    # 模板字体透传到 <a:ea>（中文），西文固定 Times New Roman
    from pptx.oxml.ns import qn
    run = first.text_frame.paragraphs[0].runs[0]
    assert run.font.name == "Times New Roman"
    assert run._r.get_or_add_rPr().find(qn("a:ea")).get("typeface") == "模板字体"


def test_graphviz_dot_setting_enables_skill_without_system_path(monkeypatch, tmp_path):
    """GRAPHVIZ_DOT 指向 dot 后，本机无需改系统 PATH 即可走 skill 布局。"""
    from app.application.ppt import drawio_skill_layout
    from app.core.config import settings

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    dot = fake_bin / ("dot.exe" if os.name == "nt" else "dot")
    dot.write_bytes(b"")
    # 配置绝对路径不应污染进程级 PATH。
    monkeypatch.setattr(drawio_skill_layout.os, "environ", {**os.environ})
    original_path = drawio_skill_layout.os.environ["PATH"]
    monkeypatch.setattr(settings, "GRAPHVIZ_DOT", str(dot))
    monkeypatch.setattr(drawio_skill_layout.autolayout, "layout", lambda _src, **_kwargs:
                        (4.0, {"n1": (1.0, 2.0), "n2": (4.0, 2.0)}, {}))

    resolved = drawio_skill_layout.ensure_dot()
    assert resolved and resolved.lower() == str(dot).lower()
    assert drawio_skill_layout.os.environ["PATH"] == original_path
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


@pytest.mark.parametrize("count", [6, 7, 8, 10, 12])
def test_skill_keeps_all_steps_for_dense_process_pages(count):
    from app.application.ppt.drawio_skill_layout import ensure_dot, layout_slide_graph
    from app.application.ppt.drawio_native import parse_diagram
    if not ensure_dot():
        pytest.skip("Graphviz dot is not installed")
    points = [f"第{i + 1}步办理事项" for i in range(count)]
    xml = layout_slide_graph({"title": "办理流程", "points": points}, "process", {})
    assert [node["label"] for node in parse_diagram(xml)["nodes"]] == points


def test_skill_retains_long_label_as_visible_detail():
    from app.application.ppt.drawio_skill_layout import ensure_dot
    if not ensure_dot():
        pytest.skip("Graphviz dot is not installed")
    original = "全流程办理期限不得超过五个工作日并须记录办理责任人"
    slide = {"title": "办理流程", "blocks": {"process": [original, "完成复核"]}}
    result = DrawioService(base_url="").generate_native_diagram(None, slide)
    assert result["blocks"]["diagram_details"] == [original]


def test_template_config_rejects_unknown_geometry_and_normalizes_hash_colors():
    from app.application.ppt import ppt_engine
    assert ppt_engine.normalize_template_colors({"primary": "#17365d"})["primary"] == "17365D"
    with pytest.raises(ValueError, match="模板颜色"):
        ppt_engine.normalize_template_colors({"primary": "red"})
    with pytest.raises(ValueError, match="版式"):
        ppt_engine.normalize_template_layouts({"content": "nonexistent"})
    assert ppt_engine.choose_layout(
        {"type": "content", "points": ["第一项", "第二项"]},
        {"content": "content.compare"}) == "content.compare"


def test_template_url_import_rejects_loopback_before_network(monkeypatch):
    import requests
    from app.application.knowledge.web_fetcher import UnsafeWebAddress, fetch_public_bytes
    monkeypatch.setattr(requests.Session, "get", lambda *_args, **_kwargs:
                        pytest.fail("private URL must never be requested"))
    with pytest.raises(UnsafeWebAddress):
        fetch_public_bytes("http://127.0.0.1:8001/models", max_bytes=100)


def test_template_url_import_rechecks_redirect_target(monkeypatch):
    import requests
    from app.application.knowledge import web_fetcher
    monkeypatch.setattr(web_fetcher, "_public_address", lambda host:
                        "93.184.215.14" if host == "example.com" else
                        (_ for _ in ()).throw(web_fetcher.UnsafeWebAddress("private")))
    calls = []
    class Redirect:
        is_redirect = True
        headers = {"Location": "http://127.0.0.1:8001/models"}
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            return None
    monkeypatch.setattr(requests.Session, "get", lambda _self, url, **_kwargs:
                        calls.append(url) or Redirect())
    with pytest.raises(web_fetcher.UnsafeWebAddress):
        web_fetcher.fetch_public_bytes("https://example.com/file.pptx", max_bytes=100)
    assert calls == ["https://example.com/file.pptx"]


def test_unavailable_mcp_reference_is_temporarily_short_circuited(monkeypatch):
    from app.infrastructure.drawio.mcp_client import DrawioMcpError
    calls = []
    class BrokenClient:
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            return None
        def get_reference(self, fmt):
            calls.append(fmt)
            raise DrawioMcpError("offline")
    monkeypatch.setattr("app.application.ppt.drawio_service.DrawioMcpClient",
                        lambda *_args, **_kwargs: BrokenClient())
    service = DrawioService(base_url="http://drawio-mcp:3001")
    assert service.get_reference() is None
    assert service.get_reference() is None
    assert calls == ["xml"]


def test_mcp_mermaid_layout_is_used_when_dot_is_unavailable(monkeypatch):
    from app.application.ppt import drawio_skill_layout
    monkeypatch.setattr(drawio_skill_layout, "ensure_dot", lambda: None)
    service = DrawioService(base_url="http://drawio-mcp:3001")
    requests = []
    monkeypatch.setattr(service, "create_diagram", lambda **kwargs:
                        requests.append(kwargs) or json.dumps({"xml": NATIVE_XML}))
    class NoModel:
        def complete(self, *_args, **_kwargs):
            pytest.fail("MCP layout should avoid model-generated coordinates")
    slide = {"title": "办理流程", "blocks": {
        "diagram_nodes": [{"id": "first", "label": "受理"},
                          {"id": "second", "label": "审核"}],
        "diagram_edges": [{"source": "first", "target": "second"}],
    }}
    result = service.generate_native_diagram(NoModel(), slide)
    from app.application.ppt.drawio_native import parse_diagram
    assert parse_diagram(result["blocks"]["drawio_xml"])["nodes"][0]["style"]["shadow"] == "1"
    assert "flowchart LR" in requests[0]["mermaid"]
    from io import BytesIO
    from pptx import Presentation
    from pptx.enum.dml import MSO_FILL_TYPE
    from app.application.ppt import ppt_engine
    result["title"] = "办理流程"
    data = ppt_engine.build_pptx(
        {"title": "办理流程", "slides": [result]},
        {"colors": ppt_engine.DEFAULT_COLORS, "layouts": ppt_engine.DEFAULT_LAYOUTS})
    node = next(shape for shape in Presentation(BytesIO(data)).slides[0].shapes
                if shape.has_text_frame and shape.text == "受理")
    assert node.fill.type == MSO_FILL_TYPE.GRADIENT
    assert "outerShdw" in node._element.xml


def test_points_already_in_diagram_are_not_repeated_below_it():
    from io import BytesIO
    from pptx import Presentation
    from app.application.ppt import ppt_engine
    outline = {"slides": [{"type": "process", "title": "办理流程",
                            "points": ["受理", "审核"],
                            "blocks": {"drawio_xml": NATIVE_XML,
                                       "drawio_kind": "process"}}]}
    data = ppt_engine.render_pptx(
        outline, ppt_engine.template_to_dict(ppt_engine.BUILTIN_TEMPLATES[0]))
    texts = [shape.text for shape in Presentation(BytesIO(data)).slides[0].shapes
             if shape.has_text_frame]
    assert texts.count("受理") == 1
    assert texts.count("审核") == 1


def test_agents365_linter_rejects_duplicate_root_cells():
    from app.application.ppt.drawio_native import validate_generated_layout
    duplicate = NATIVE_XML.replace('<mxCell id="1" parent="0"/>',
                                   '<mxCell id="1" parent="0"/><mxCell id="1" parent="0"/>')
    with pytest.raises(ValueError, match="E-DUP-ID"):
        validate_generated_layout(duplicate)


def test_page_action_uses_35b_plan_then_skill_layout_without_mcp(monkeypatch):
    from app.application.ppt import drawio_skill_layout
    monkeypatch.setattr(drawio_skill_layout.shutil, "which", lambda _name: "dot")
    monkeypatch.setattr(drawio_skill_layout.autolayout, "layout", lambda _source, **_kwargs:
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


def test_mcp_takes_priority_when_skill_is_also_available(monkeypatch):
    from app.application.ppt import drawio_skill_layout
    monkeypatch.setattr(drawio_skill_layout, "ensure_dot", lambda: "dot")
    monkeypatch.setattr(drawio_skill_layout, "layout_slide_graph",
                        lambda *_args: pytest.fail("MCP success must skip Graphviz"))
    svc = DrawioService(base_url="http://drawio-mcp:3001")
    calls = []
    monkeypatch.setattr(svc, "create_diagram", lambda **kwargs:
                        calls.append(kwargs) or json.dumps({"xml": NATIVE_XML}))

    class Assistant:
        def complete(self, _messages, **_kwargs):
            return json.dumps({"diagram_nodes": [
                {"id": "a", "label": "受理"}, {"id": "b", "label": "审核"}],
                "diagram_edges": [{"source": "a", "target": "b"}]},
                ensure_ascii=False)

    result = svc.generate_native_diagram(
        Assistant(), {"title": "办理流程", "points": ["受理后审核"]})
    assert result["blocks"]["diagram_engine"] == "mcp"
    assert calls and "flowchart LR" in calls[0]["mermaid"]
    from app.application.ppt.drawio_native import parse_diagram
    graph = parse_diagram(result["blocks"]["drawio_xml"])
    assert graph["nodes"][0]["style"]["shadow"] == "1"
    assert graph["edges"][0]["style"]["edgeStyle"] == "orthogonalEdgeStyle"
    assert graph["edges"][0]["style"]["strokeColor"] == "#6C757D"


def test_mcp_outage_falls_back_to_graphviz(monkeypatch):
    from app.application.ppt import drawio_skill_layout
    calls = []
    monkeypatch.setattr(drawio_skill_layout, "layout_slide_graph",
                        lambda *_args: calls.append("graphviz") or NATIVE_XML)
    svc = DrawioService(base_url="http://drawio-mcp:3001")
    monkeypatch.setattr(svc, "create_diagram", lambda **_kwargs: None)
    slide = {"title": "办理流程", "blocks": {
        "diagram_nodes": [{"id": "a", "label": "受理"},
                          {"id": "b", "label": "审核"}],
        "diagram_edges": [{"source": "a", "target": "b"}]}}
    result = svc.generate_native_diagram(object(), slide)
    assert calls == ["graphviz"]
    assert result["blocks"]["diagram_engine"] == "graphviz"


def test_mcp_mermaid_source_only_falls_back_without_validation_warning(monkeypatch, caplog):
    from app.application.ppt import drawio_skill_layout
    monkeypatch.setattr(drawio_skill_layout, "layout_slide_graph",
                        lambda *_args: NATIVE_XML)
    svc = DrawioService(base_url="http://drawio-mcp:3001")
    calls = []
    monkeypatch.setattr(svc, "create_diagram", lambda **kwargs:
                        calls.append(kwargs) or json.dumps({
                            "mermaid": kwargs["mermaid"], "_buildId": "test"})
                        + "\nOpen in draw.io: https://app.diagrams.net/#create=example")
    slide = {"title": "办理流程", "blocks": {
        "diagram_nodes": [{"id": "a", "label": "受理"},
                          {"id": "b", "label": "审核"}],
        "diagram_edges": [{"source": "a", "target": "b"}]}}
    assert svc.generate_native_diagram(object(), slide)["blocks"]["diagram_engine"] == "graphviz"
    assert svc.generate_native_diagram(object(), slide)["blocks"]["diagram_engine"] == "graphviz"
    assert len(calls) == 1
    assert "MCP 排版结果未通过校验" not in caplog.text


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

    monkeypatch.setattr("app.application.ppt.drawio_service.DrawioMcpClient",
                        lambda *_args, **_kwargs: FakeClient())

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
    assert "关系图" in prompts[-1]
    assert "#123456" in prompts[-1] and "#ABCDEF" in prompts[-1]
    assert "思源黑体" in prompts[-1]
    assert result["blocks"]["drawio_kind"] == "relationship"
    assert result["blocks"]["diagram_labels"] == ["受理", "审核"]
    assert "process" not in result["blocks"]


def test_drawio_generation_rejects_missing_explicit_relationship(monkeypatch):
    svc = DrawioService(base_url="http://drawio-mcp:3001")
    monkeypatch.setattr(svc, "get_reference", lambda: "mxGraphModel reference")
    monkeypatch.setattr(svc, "create_diagram", lambda **_kwargs: json.dumps({"xml": NATIVE_XML}))

    class Assistant:
        def complete(self, *_args, **_kwargs):
            return json.dumps({"xml": NATIVE_XML}, ensure_ascii=False)

    slide = {"type": "process", "title": "部门协作", "blocks": {
        "drawio_kind": "relationship",
        "diagram_nodes": [{"id": "a", "label": "司法局"},
                          {"id": "b", "label": "司法所"}],
        "diagram_edges": [{"source": "a", "target": "b"}],
    }}

    assert svc.generate_native_diagram(Assistant(), slide, kind="relationship") is None


def test_drawio_generation_keeps_explicit_nodes_and_edge(monkeypatch):
    svc = DrawioService(base_url="http://drawio-mcp:3001")
    monkeypatch.setattr(svc, "get_reference", lambda: "mxGraphModel reference")
    monkeypatch.setattr(svc, "create_diagram", lambda **_kwargs: json.dumps({"xml": NATIVE_XML}))

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


# ===== 节点文字适配：菱形加宽 + 长标签均衡断行（2026-11-09 实机反馈） =====

_FOUR_LEVEL_XML = '''<mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/>
<mxCell id="a" value="前端咨询&#10;12348+AI智能问答" vertex="1" parent="1"
 style="rounded=1;fillColor=#35649C;fontColor=#FFFFFF;fontSize=14;">
 <mxGeometry x="160" y="0" width="180" height="64" as="geometry"/></mxCell>
<mxCell id="b" value="需求评估&#10;分流处理" vertex="1" parent="1"
 style="rhombus;fillColor=#FDF3D8;fontSize=14;">
 <mxGeometry x="185" y="104" width="130" height="130" as="geometry"/></mxCell>
<mxCell id="c" value="中端调解&#10;一站式多元解纷" vertex="1" parent="1"
 style="rounded=1;fillColor=#E8F0FA;fontSize=14;">
 <mxGeometry x="20" y="270" width="180" height="64" as="geometry"/></mxCell>
<mxCell id="d" value="后端援助&#10;困难群体全覆盖" vertex="1" parent="1"
 style="rounded=1;fillColor=#EAF6E4;fontSize=14;">
 <mxGeometry x="300" y="270" width="180" height="64" as="geometry"/></mxCell>
<mxCell id="e" value="服务闭环&#10;反馈与优化" vertex="1" parent="1" style="ellipse;fontSize=14;">
 <mxGeometry x="160" y="340" width="180" height="64" as="geometry"/></mxCell>
<mxCell id="e1" edge="1" parent="1" source="a" target="b"/>
<mxCell id="e2" edge="1" parent="1" source="b" target="c"/>
<mxCell id="e3" edge="1" parent="1" source="b" target="d"/>
</root></mxGraphModel>'''


def _render_page(xml, width_ratio=.88):
    """按 r_process 的真实可用区（0.88 宽 × 0.64 高）渲染，而不是整页。"""
    from pptx import Presentation
    from app.application.ppt.drawio_native import render_diagram

    deck = Presentation()
    page = deck.slides.add_slide(deck.slide_layouts[6])
    width, height = deck.slide_width, deck.slide_height
    render_diagram(page, xml, int(width * .06), int(height * .23),
                   int(width * width_ratio), int(height * .64))
    return page, deck


def test_rhombus_is_widened_so_four_char_labels_stay_on_two_lines():
    """正方形菱形（130x130）等比缩放后只够放两字一行，渲染时必须拉扁。"""
    from pptx.enum.shapes import MSO_SHAPE

    page, _ = _render_page(_FOUR_LEVEL_XML)
    diamond = next(shape for shape in page.shapes
                   if getattr(shape, "auto_shape_type", None) == MSO_SHAPE.DIAMOND)
    assert diamond.width > diamond.height * 1.15, "菱形没被横向加宽"
    assert diamond.text_frame.text == "需求评估\n分流处理"


def test_balanced_split_breaks_between_cjk_and_ascii():
    """断点落在中英之间，且不切开「12348+AI」这种西文数字串。"""
    from app.application.ppt.drawio_native import _balanced_split

    assert _balanced_split("12348+AI智能问答") == ("12348+AI", "智能问答")
    assert _balanced_split("受理") is None


def test_long_mixed_label_never_leaves_an_orphan_line():
    """可用区变窄时宁可拆成两行，也不能让末行只剩一个「答」。"""
    page, _ = _render_page(_FOUR_LEVEL_XML, width_ratio=.45)
    node = next(shape for shape in page.shapes if shape.has_text_frame
                and shape.text.startswith("前端咨询"))
    lines = [line for line in node.text_frame.text.split("\n") if line.strip()]
    assert all(len(line) > 1 for line in lines), f"出现孤字行：{lines}"
