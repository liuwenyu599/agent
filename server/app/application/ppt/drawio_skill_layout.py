"""Use the pinned drawio-skill layout engine for model-planned page graphs."""
from __future__ import annotations

import re
import shutil
from xml.etree import ElementTree as ET

from app.application.ppt.drawio_native import validate_generated_layout
from app.application.ppt.third_party.drawio_skill import autolayout


def layout_slide_graph(slide: dict, kind: str, colors: dict) -> str | None:
    """Return a bounded editable mxGraphModel, or None for the existing path.

    The model chooses graph semantics; drawio-skill places the nodes. We do not
    pass user supplied IDs, styles, file paths or shell text to Graphviz.
    """
    if not shutil.which("dot"):
        return None
    blocks = slide.get("blocks") or {}
    raw_nodes = blocks.get("diagram_nodes") or []
    raw_edges = blocks.get("diagram_edges") or []
    if not raw_nodes and kind == "process":
        raw_nodes = [{"id": str(i), "label": text}
                     for i, text in enumerate(blocks.get("process") or [])]
        raw_edges = [{"source": str(i), "target": str(i + 1)}
                     for i in range(max(0, len(raw_nodes) - 1))]
    if not isinstance(raw_nodes, list) or not 2 <= len(raw_nodes) <= 12:
        return None
    if not isinstance(raw_edges, list) or len(raw_edges) > 20:
        return None
    labels, ids = [], {}
    for index, node in enumerate(raw_nodes):
        if not isinstance(node, dict):
            return None
        source_id = str(node.get("id") or "")
        label = str(node.get("label") or "").strip()
        if not source_id or source_id in ids or not label or len(label) > 20:
            return None
        ids[source_id] = f"n{index + 1}"
        labels.append(label)
    primary = str(colors.get("primary") or "17365D").lstrip("#")
    light = str(colors.get("light") or "E8F0FA").lstrip("#")
    dark = str(colors.get("dark") or "15365D").lstrip("#")
    palette = [v if re.fullmatch(r"[0-9A-Fa-f]{6}", v) else fallback
               for v, fallback in ((primary, "17365D"), (light, "E8F0FA"),
                                   (dark, "15365D"))]
    primary, light, dark = palette
    graph = {
        "direction": "LR" if kind == "process" and len(raw_nodes) <= 5 else "TB",
        "nodes": [{"id": ids[str(node["id"])], "label": labels[i],
                   "width": max(145, min(210, len(labels[i]) * 18 + 34)),
                   "height": 72,
                   "style": ("rounded=1;whiteSpace=wrap;html=1;"
                             f"fillColor=#{light};strokeColor=#{primary};"
                             f"fontColor=#{dark};fontSize=16;")}
                  for i, node in enumerate(raw_nodes)],
        "edges": [],
    }
    for edge in raw_edges:
        if not isinstance(edge, dict):
            return None
        source = ids.get(str(edge.get("source") or ""))
        target = ids.get(str(edge.get("target") or ""))
        if not source or not target or source == target:
            return None
        graph["edges"].append({"source": source, "target": target,
                               "label": str(edge.get("label") or "")[:20],
                               "style": f"html=1;strokeColor=#{primary};endArrow=block;"})
    height, positions, edge_points = autolayout.layout(autolayout.build_dot(graph))
    xml = autolayout.to_drawio(graph, height, positions, edge_points)
    model = ET.fromstring(xml).find(".//mxGraphModel")
    if model is None:
        raise ValueError("Draw.io Skill did not return a graph model")
    vertices = [cell for cell in model.iter("mxCell") if cell.get("vertex") == "1"]
    boxes = []
    for cell in vertices:
        geom = cell.find("mxGeometry")
        if geom is None:
            raise ValueError("Draw.io Skill returned a node without geometry")
        boxes.append(tuple(float(geom.get(name, "0"))
                           for name in ("x", "y", "width", "height")))
    x0, y0 = min(b[0] for b in boxes), min(b[1] for b in boxes)
    span_x = max(b[0] + b[2] for b in boxes) - x0
    span_y = max(b[1] + b[3] for b in boxes) - y0
    scale = min(880 / max(span_x, 1), 450 / max(span_y, 1))
    if any(width * scale < 90 or node_height * scale < 45
           for _x, _y, width, node_height in boxes):
        raise ValueError("Skill layout would make node labels too small")
    for cell, (x, y, width, node_height) in zip(vertices, boxes):
        geom = cell.find("mxGeometry")
        for key, value in (("x", 60 + (x - x0) * scale),
                           ("y", 50 + (y - y0) * scale),
                           ("width", width * scale), ("height", node_height * scale)):
            geom.set(key, str(round(value, 2)))
    # Upstream waypoints use its original coordinate space. Our PowerPoint
    # renderer attaches native connectors to shapes, so let draw.io auto-route.
    for edge in model.iter("mxCell"):
        if edge.get("edge") == "1":
            geom = edge.find("mxGeometry")
            if geom is not None:
                for points in list(geom):
                    if points.tag == "Array":
                        geom.remove(points)
    result = ET.tostring(model, encoding="unicode")
    validate_generated_layout(result)
    return result
