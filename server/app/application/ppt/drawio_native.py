"""Convert a bounded draw.io diagram into editable PowerPoint shapes and connectors."""
from __future__ import annotations

import html
import math
import re
from xml.etree import ElementTree as ET

from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.xmlchemy import OxmlElement
from pptx.util import Pt

from app.core.fonts import DEFAULT_CJK_FONT


def _label(value: str) -> str:
    value = re.sub(r"<(?:br\s*/?|/div|/p)>", "\n", value, flags=re.I)
    return html.unescape(re.sub(r"<[^>]*>", "", value)).strip()[:500]


def parse_diagram(xml: str) -> dict:
    """Accept one uncompressed page of basic vector shapes; reject unsupported content."""
    if (not isinstance(xml, str) or len(xml) > 50000
            or re.search(r"<!\s*(?:DOCTYPE|ENTITY)", xml, re.I)):
        raise ValueError("图示 XML 超出范围或包含不支持的声明")
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise ValueError("图示 XML 格式错误") from exc
    if root.tag == "mxGraphModel":
        model = root
    else:
        models = list(root.iter("mxGraphModel"))
        if len(models) != 1:
            raise ValueError("图示须包含一个未压缩的 mxGraphModel 页面")
        model = models[0]
    cells = list(model.iter("mxCell"))
    if len(cells) > 82:
        raise ValueError("单页图示最多包含 40 个节点及 40 条连线")
    nodes, edges, ids = [], [], set()
    for cell in cells:
        if cell.get("vertex") != "1" and cell.get("edge") != "1":
            continue
        cell_id = cell.get("id")
        if not cell_id or cell_id in ids:
            raise ValueError("图示节点 ID 缺失或重复")
        ids.add(cell_id)
        style = dict(part.split("=", 1) for part in cell.get("style", "").split(";")
                     if "=" in part)
        if cell.get("parent", "1") != "1":
            raise ValueError("图示暂不支持嵌套分组，请展开为平级节点")
        if cell.get("edge") == "1":
            edges.append({"id": cell_id, "source": cell.get("source"),
                          "target": cell.get("target"), "style": style,
                          "label": _label(cell.get("value", ""))})
            continue
        geom = cell.find("mxGeometry")
        if geom is None or geom.get("relative") == "1":
            raise ValueError("图示节点缺少绝对位置")
        try:
            box = [float(geom.get(key, "0")) for key in ("x", "y", "width", "height")]
        except ValueError as exc:
            raise ValueError("图示节点坐标必须为数值") from exc
        if not all(math.isfinite(value) and abs(value) <= 10000 for value in box):
            raise ValueError("图示节点坐标超出范围")
        if box[2] <= 0 or box[3] <= 0:
            raise ValueError("图示节点尺寸必须大于零")
        bare_styles = set(cell.get("style", "").split(";"))
        kind = style.get("shape") or next((k for k in ("ellipse", "rhombus", "text")
                                          if k in bare_styles), "rectangle")
        if kind not in {"rectangle", "rect", "ellipse", "rhombus", "text"} or "image" in style:
            raise ValueError("图示包含尚不支持转换为原生形状的节点")
        nodes.append({"id": cell_id, "box": box, "kind": kind,
                      "style": style, "label": _label(cell.get("value", ""))})
    if not nodes or len(nodes) > 40 or len(edges) > 40:
        raise ValueError("图示须包含 1–40 个节点，最多 40 条连线")
    node_ids = {node["id"] for node in nodes}
    if any(edge["source"] not in node_ids or edge["target"] not in node_ids for edge in edges):
        raise ValueError("图示连线引用了不存在的节点")
    return {"nodes": nodes, "edges": edges}


def render_diagram(slide, xml: str, left: int, top: int, width: int, height: int,
                   font: str = DEFAULT_CJK_FONT) -> None:
    diagram = parse_diagram(xml)
    nodes = diagram["nodes"]
    x0 = min(node["box"][0] for node in nodes)
    y0 = min(node["box"][1] for node in nodes)
    span_x = max(n["box"][0] + n["box"][2] for n in nodes) - x0
    span_y = max(n["box"][1] + n["box"][3] for n in nodes) - y0
    scale = min(width / span_x, height / span_y)
    offset_x = left + (width - span_x * scale) / 2
    offset_y = top + (height - span_y * scale) / 2

    def color(value, default):
        return RGBColor.from_string(value.lstrip("#")) if re.fullmatch(
            r"#?[0-9a-fA-F]{6}", value or "") else RGBColor.from_string(default)

    def put_text(shape, value, style):
        shape.text_frame.text = value
        shape.text_frame.word_wrap = True
        shape.text_frame.vertical_anchor = MSO_ANCHOR.MIDDLE
        for paragraph in shape.text_frame.paragraphs:
            paragraph.alignment = PP_ALIGN.CENTER
            for run in paragraph.runs:
                run.font.name = font
                run.font.size = Pt(14)
                run.font.color.rgb = color(style.get("fontColor"), "15365D")

    rendered = {}
    for node in nodes:
        x, y, w, h = node["box"]
        box = (int(offset_x + (x - x0) * scale), int(offset_y + (y - y0) * scale),
               int(w * scale), int(h * scale))
        style = node["style"]
        if node["kind"] == "text":
            shape = slide.shapes.add_textbox(*box)
        else:
            kind = {"ellipse": MSO_SHAPE.OVAL, "rhombus": MSO_SHAPE.DIAMOND}.get(
                node["kind"], MSO_SHAPE.ROUNDED_RECTANGLE if style.get("rounded") == "1"
                else MSO_SHAPE.RECTANGLE)
            shape = slide.shapes.add_shape(kind, *box)
            if style.get("fillColor") == "none":
                shape.fill.background()
            else:
                shape.fill.solid()
                shape.fill.fore_color.rgb = color(style.get("fillColor"), "E8F0FA")
            shape.line.color.rgb = color(style.get("strokeColor"), "35649C")
        put_text(shape, node["label"], style)
        rendered[node["id"]] = shape
    for edge in diagram["edges"]:
        source, target = rendered[edge["source"]], rendered[edge["target"]]
        horizontal = abs(target.left - source.left) >= abs(target.top - source.top)
        start_site, end_site = ((3, 1) if target.left >= source.left else (1, 3)) if horizontal else (
            (2, 0) if target.top >= source.top else (0, 2))
        connector = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, 0, 0, 1, 1)
        connector.begin_connect(source, start_site)
        connector.end_connect(target, end_site)
        connector.line.color.rgb = color(edge["style"].get("strokeColor"), "35649C")
        if edge["style"].get("endArrow") != "none":
            arrow = OxmlElement("a:tailEnd")
            arrow.set("type", "triangle")
            connector.line._get_or_add_ln().append(arrow)
        if edge["label"]:
            label = slide.shapes.add_textbox(
                int((source.left + source.width / 2 + target.left + target.width / 2) / 2 - width * .08),
                int((source.top + source.height / 2 + target.top + target.height / 2) / 2),
                int(width * .16), int(height * .08))
            put_text(label, edge["label"], edge["style"])
