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

from app.core.fonts import DEFAULT_CJK_FONT, apply_cjk_font
from app.application.ppt.third_party.drawio_skill.validate import check_page


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


def validate_generated_layout(xml: str, canvas_width: int = 1000,
                              canvas_height: int = 550) -> dict:
    """Check the editable diagram's page bounds and material node overlap."""
    diagram = parse_diagram(xml)
    # Reuse Agents365 drawio-skill's deterministic XML linter before the local
    # PPTX-specific checks. The upstream PPTX exporter rasterizes each page;
    # native PowerPoint shapes are still rendered by this module.
    model = ET.fromstring(xml)
    if model is not None:
        if model.tag != "mxGraphModel":
            model = next(model.iter("mxGraphModel"), None)
        if model is not None:
            page = ET.Element("diagram", {"name": "PPT 图示"})
            page.append(model)
            errors, _warnings = check_page(page)
            if errors:
                raise ValueError("图示结构错误：" + str(errors[0]["code"]))
    nodes = diagram["nodes"]
    if len(nodes) > 12:
        raise ValueError("AI 图示最多包含 12 个节点")
    for node in nodes:
        if len(node["label"]) > 20 or node["label"].count("\n") > 3:
            raise ValueError("图示节点文字过长，可能溢出")
        x, y, width, height = node["box"]
        if x < 0 or y < 0 or x + width > canvas_width or y + height > canvas_height:
            raise ValueError("图示节点超出页面画布")
    for index, first in enumerate(nodes):
        ax, ay, aw, ah = first["box"]
        for second in nodes[index + 1:]:
            bx, by, bw, bh = second["box"]
            shared = max(0, min(ax + aw, bx + bw) - max(ax, bx)) * max(
                0, min(ay + ah, by + bh) - max(ay, by))
            if shared > 0.1 * min(aw * ah, bw * bh):
                raise ValueError("图示节点明显重叠")
    return diagram


def apply_diagram_theme(xml: str, colors: dict | None = None,
                        font: str = DEFAULT_CJK_FONT) -> str:
    """Add editable PowerPoint-friendly styles to a validated MCP/model diagram."""
    diagram = parse_diagram(xml)
    palette = colors or {}
    def hex_color(key: str, fallback: str) -> str:
        value = str(palette.get(key) or "").lstrip("#")
        return value.upper() if re.fullmatch(r"[0-9a-fA-F]{6}", value) else fallback
    primary = hex_color("primary", "2A5CAA")
    accent = hex_color("accent", "4A78AD")
    light = hex_color("light", "E8F0FA")
    dark = hex_color("dark", "15365D")
    incoming = {edge["target"] for edge in diagram["edges"]}
    outgoing = {edge["source"] for edge in diagram["edges"]}
    model = ET.fromstring(xml)
    family = font if len(font) <= 48 and re.fullmatch(
        r"[\w\u4e00-\u9fff .-]+", font) else DEFAULT_CJK_FONT
    for cell in model.iter("mxCell"):
        if cell.get("vertex") != "1" and cell.get("edge") != "1":
            continue
        style = cell.get("style", "")
        bare = [part for part in style.split(";") if part and "=" not in part]
        values = dict(part.split("=", 1) for part in style.split(";") if "=" in part)
        if cell.get("edge") == "1":
            values.update({"edgeStyle": "orthogonalEdgeStyle", "rounded": "1",
                           "strokeColor": "#6C757D", "strokeWidth": "2",
                           "endArrow": "block"})
        elif values.get("shape") != "text" and "text" not in bare:
            root = cell.get("id") not in incoming
            terminal = cell.get("id") not in outgoing
            fill = primary if root else accent if terminal else light
            values.setdefault("fillColor", f"#{fill}")
            values["rounded"] = "1"
            values.setdefault("strokeColor", f"#{primary}")
            if values["fillColor"] != "none":
                actual = str(values["fillColor"]).lstrip("#")
                if not re.fullmatch(r"[0-9a-fA-F]{6}", actual):
                    actual = fill
                rgb = [int(actual[i:i + 2], 16) for i in (0, 2, 4)]
                bright = (0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]) >= 145
                values.setdefault("gradientColor", f"#{'FFFFFF' if bright else actual}")
                values["shadow"] = "1"
                values.setdefault("fontColor", f"#{dark if bright else 'FFFFFF'}")
            values.setdefault("strokeWidth", "1.6")
            values.setdefault("fontFamily", family)
        cell.set("style", ";".join(bare + [f"{key}={value}" for key, value in values.items()]) + ";")
    return ET.tostring(model, encoding="unicode")


def build_drawio_source(outline: dict) -> bytes:
    """Export validated diagram pages as one editable, uncompressed .drawio file."""
    source = ET.Element("mxfile", {"host": "app.diagrams.net"})
    for index, slide in enumerate((outline or {}).get("slides") or [], 1):
        xml = ((slide.get("blocks") or {}).get("drawio_xml"))
        if not xml:
            continue
        parse_diagram(xml)
        model = ET.fromstring(xml)
        if model.tag != "mxGraphModel":
            model = next(model.iter("mxGraphModel"))
        page = ET.SubElement(source, "diagram", {
            "id": f"page-{index}", "name": str(slide.get("title") or f"第{index}页")[:60],
        })
        page.append(model)
    if not len(source):
        raise ValueError("这份演示文稿没有可下载的 Draw.io 图示")
    return ET.tostring(source, encoding="utf-8", xml_declaration=True)


def render_diagram(slide, xml: str, left: int, top: int, width: int, height: int,
                   font: str = DEFAULT_CJK_FONT, colors: dict | None = None) -> None:
    diagram = parse_diagram(xml)
    palette = colors or {}
    fill_default = palette.get("light", "E8F0FA")
    line_default = palette.get("primary", "35649C")
    text_default = palette.get("dark", "15365D")
    nodes = diagram["nodes"]
    x0 = min(node["box"][0] for node in nodes)
    y0 = min(node["box"][1] for node in nodes)
    span_x = max(n["box"][0] + n["box"][2] for n in nodes) - x0
    span_y = max(n["box"][1] + n["box"][3] for n in nodes) - y0
    scale = min(width / span_x, height / span_y)
    offset_x = left + (width - span_x * scale) / 2
    offset_y = top + (height - span_y * scale) / 2

    def color(value, default):
        chosen = value if re.fullmatch(r"#?[0-9a-fA-F]{6}", value or "") else default
        chosen = str(chosen).lstrip("#")
        return RGBColor.from_string(chosen if re.fullmatch(r"[0-9a-fA-F]{6}", chosen)
                                    else "17365D")

    def line_width(style, default=1.5):
        try:
            requested = float(style.get("strokeWidth", default))
        except (TypeError, ValueError):
            requested = default
        return Pt(max(0.5, min(requested, 4.0)) if math.isfinite(requested) else default)

    def add_shadow(shape):
        # DrawingML effect is kept in the PPTX as an editable shape effect.
        sp_pr = shape._element.spPr
        if sp_pr.find("{http://schemas.openxmlformats.org/drawingml/2006/main}effectLst") is not None:
            return
        effects = OxmlElement("a:effectLst")
        shadow = OxmlElement("a:outerShdw")
        for key, value in (("blurRad", "50800"), ("dist", "25400"),
                           ("dir", "5400000"), ("algn", "ctr"),
                           ("rotWithShape", "0")):
            shadow.set(key, value)
        shade = OxmlElement("a:srgbClr")
        shade.set("val", "17365D")
        alpha = OxmlElement("a:alpha")
        alpha.set("val", "18000")
        shade.append(alpha)
        shadow.append(shade)
        effects.append(shadow)
        sp_pr.append(effects)

    def put_text(shape, value, style, kind: str = ""):
        shape.text_frame.text = value
        shape.text_frame.word_wrap = True
        shape.text_frame.vertical_anchor = {
            "top": MSO_ANCHOR.TOP,
            "bottom": MSO_ANCHOR.BOTTOM,
        }.get(style.get("verticalAlign"), MSO_ANCHOR.MIDDLE)
        try:
            requested_size = float(style.get("fontSize", 14))
            font_size = requested_size if math.isfinite(requested_size) else 14
        except (TypeError, ValueError):
            font_size = 14
        font_size = max(8, min(font_size, 32))
        if kind == "rhombus":
            # 菱形的可写区只有外接矩形的中间约一半，14pt 下四个字一行必被挤断
            # （实机成稿出现「需求评 / 估」竖排断字）。先清掉默认 0.1 英寸内边距，
            # 再按最长一行反推可用字号，宁可小 1–2pt 也不能断字。
            for side in ("margin_left", "margin_right", "margin_top", "margin_bottom"):
                try:
                    setattr(shape.text_frame, side, 0)
                except Exception:
                    pass
            inner = shape.width / 914400 * .46
            lines = [ln for ln in str(value).split("\n") if ln.strip()] or [""]
            need = max(len(ln) for ln in lines) * font_size / 72 * 1.04
            if need > inner:
                font_size = max(9.0, font_size * inner / need)
        try:
            font_style = int(style.get("fontStyle", 0))
        except (TypeError, ValueError):
            font_style = 0
        for paragraph in shape.text_frame.paragraphs:
            paragraph.alignment = {
                "left": PP_ALIGN.LEFT,
                "right": PP_ALIGN.RIGHT,
            }.get(style.get("align"), PP_ALIGN.CENTER)
            for run in paragraph.runs:
                family = str(style.get("fontFamily") or "").strip()
                # 中文节点标签与西文分开写：<a:ea> 用图示字体，<a:latin> 用
                # Times New Roman，避免节点里的数字落到 Arial/Calibri。
                apply_cjk_font(run, family if len(family) <= 48 and re.fullmatch(
                    r"[\w\u4e00-\u9fff .-]+", family) else font)
                run.font.size = Pt(font_size)
                run.font.bold = bool(font_style & 1)
                run.font.italic = bool(font_style & 2)
                run.font.color.rgb = color(style.get("fontColor"), text_default)

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
            elif re.fullmatch(r"#?[0-9a-fA-F]{6}", style.get("gradientColor") or ""):
                shape.fill.gradient()
                stops = shape.fill.gradient_stops
                stops[0].color.rgb = color(style.get("fillColor"), fill_default)
                stops[-1].color.rgb = color(style["gradientColor"], fill_default)
                shape.fill.gradient_angle = 90
            else:
                shape.fill.solid()
                shape.fill.fore_color.rgb = color(style.get("fillColor"), fill_default)
            shape.line.color.rgb = color(style.get("strokeColor"), line_default)
            shape.line.width = line_width(style)
            if style.get("shadow") == "1":
                add_shadow(shape)
        put_text(shape, node["label"], style, node["kind"])
        rendered[node["id"]] = shape
    for edge in diagram["edges"]:
        source, target = rendered[edge["source"]], rendered[edge["target"]]
        # 连接点必须按「两个框的实际间隙」选，不能只看中心偏移：中心略偏右的
        # 下层节点也会被判成左→右，折线于是先右后左地绕一圈，横段还从旁边的
        # 框里穿过去（实机成稿「中端调解」文字上压着一条竖线就是这样来的）。
        l1, t1 = source.left, source.top
        r1, b1 = l1 + source.width, t1 + source.height
        l2, t2 = target.left, target.top
        r2, b2 = l2 + target.width, t2 + target.height
        gap = max(2, int(min(source.width, target.width) * .02))
        clear_v = b1 <= t2 + gap or b2 <= t1 + gap
        clear_h = r1 <= l2 + gap or r2 <= l1 + gap
        overlap_y = min(b1, b2) - max(t1, t2) > gap
        overlap_x = min(r1, r2) - max(l1, l2) > gap
        if clear_v and not (clear_h and overlap_y):
            vertical = True
        elif clear_h:
            vertical = False
        else:
            vertical = clear_v or not overlap_x
        dx = (l2 + target.width / 2) - (l1 + source.width / 2)
        dy = (t2 + target.height / 2) - (t1 + source.height / 2)
        if vertical:
            start_site, end_site = (2, 0) if dy >= 0 else (0, 2)
        else:
            start_site, end_site = (3, 1) if dx >= 0 else (1, 3)
        connector = slide.shapes.add_connector(MSO_CONNECTOR.ELBOW, 0, 0, 1, 1)
        connector.begin_connect(source, start_site)
        connector.end_connect(target, end_site)
        connector.line.color.rgb = color(edge["style"].get("strokeColor"), line_default)
        connector.line.width = line_width(edge["style"], 2.0)
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
