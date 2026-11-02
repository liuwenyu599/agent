"""Use the pinned drawio-skill layout engine for model-planned page graphs."""
from __future__ import annotations

import os
import re
import shutil
import math
from xml.etree import ElementTree as ET

from app.application.ppt.drawio_native import validate_generated_layout
from app.application.ppt.third_party.drawio_skill import autolayout


def ensure_dot() -> str | None:
    """Return the dot executable path, or None when Graphviz is unavailable.

    Resolution order: system PATH first, then ``GRAPHVIZ_DOT`` from settings
    (a dot.exe path or its bin directory). The executable is passed directly
    to the subprocess without changing the process environment.
    """
    found = shutil.which("dot")
    if found:
        return found
    from app.core.config import settings
    configured = (getattr(settings, "GRAPHVIZ_DOT", "") or "").strip()
    if not configured:
        return None
    if os.path.isdir(configured):
        dot = os.path.join(configured, "dot.exe" if os.name == "nt" else "dot")
    else:
        dot = configured
    if not os.path.isfile(dot):
        return None
    return dot


def layout_slide_graph(slide: dict, kind: str, colors: dict) -> str | None:
    """Return a bounded editable mxGraphModel, or None for the existing path.

    The model chooses graph semantics; drawio-skill places the nodes. We do not
    pass user supplied IDs, styles, file paths or shell text to Graphviz.
    """
    dot_path = ensure_dot()
    if not dot_path:
        return None
    blocks = slide.get("blocks") or {}
    raw_nodes = blocks.get("diagram_nodes") or []
    raw_edges = blocks.get("diagram_edges") or []
    if not raw_nodes and kind == "process":
        steps = blocks.get("process") or slide.get("points") or []
        raw_nodes = [{"id": str(i), "label": text}
                     for i, text in enumerate(steps)]
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
        if not source_id or source_id in ids or not label:
            return None
        ids[source_id] = f"n{index + 1}"
        labels.append(label[:19] + "…" if len(label) > 20 else label)
    primary = str(colors.get("primary") or "17365D").lstrip("#")
    accent = str(colors.get("accent") or "4A78AD").lstrip("#")
    light = str(colors.get("light") or "E8F0FA").lstrip("#")
    dark = str(colors.get("dark") or "15365D").lstrip("#")
    palette = [v if re.fullmatch(r"[0-9A-Fa-f]{6}", v) else fallback
               for v, fallback in ((primary, "17365D"), (accent, "4A78AD"), (light, "E8F0FA"),
                                   (dark, "15365D"))]
    primary, accent, light, dark = palette
    incoming = {str(edge.get("target")) for edge in raw_edges if isinstance(edge, dict)}
    outgoing = {str(edge.get("source")) for edge in raw_edges if isinstance(edge, dict)}

    def node_style(source_id: str) -> str:
        root = source_id not in incoming
        terminal = source_id not in outgoing
        if kind in ("organization", "architecture") and root:
            fill, stroke, foreground = primary, primary, "FFFFFF"
        elif kind == "process" and (root or terminal):
            fill, stroke, foreground = accent, primary, "FFFFFF"
        else:
            fill, stroke, foreground = light, accent if kind == "architecture" else primary, dark
        return ("rounded=1;whiteSpace=wrap;html=1;"
                f"fillColor=#{fill};strokeColor=#{stroke};"
                f"fontColor=#{foreground};fontSize=12;")
    graph = {
        "direction": "LR" if kind == "process" else "TB",
        "nodes": [{"id": ids[str(node["id"])], "label": labels[i],
                   "width": max(145, min(210, len(labels[i]) * 18 + 34)),
                   "height": 90,
                   "style": node_style(str(node["id"]))}
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
    height, positions, edge_points = autolayout.layout(
        autolayout.build_dot(graph), dot_path=dot_path)
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
    grid = len(vertices) >= 6 or any(
        width * scale < 110 or node_height * scale < 55
        for _x, _y, width, node_height in boxes)
    if grid:
        columns = 3 if len(vertices) <= 6 else 4
        ordered = vertices
        if kind != "process":
            depth = {node_id: 0 for node_id in ids.values()}
            for _ in range(len(depth)):
                changed = False
                for edge in graph["edges"]:
                    new = min(len(depth) - 1, depth[edge["source"]] + 1)
                    if new > depth[edge["target"]]:
                        depth[edge["target"]] = new
                        changed = True
                if not changed:
                    break
            ordered = sorted(vertices, key=lambda cell: (depth.get(cell.get("id"), 0),
                                                          int(cell.get("id", "n0")[1:] or 0)))
        rows = (len(ordered) + columns - 1) // columns
        slot_w = 880 / columns
        slot_h = 450 / rows
        for index, cell in enumerate(ordered):
            row, column = divmod(index, columns)
            if kind == "process" and row % 2:
                column = columns - 1 - column
            geom = cell.find("mxGeometry")
            for key, value in (("x", 60 + column * slot_w + 12),
                               ("y", 50 + row * slot_h + 10),
                               ("width", slot_w - 24), ("height", slot_h - 20)):
                geom.set(key, str(round(value, 2)))
    else:
        for cell, (x, y, width, node_height) in zip(vertices, boxes):
            geom = cell.find("mxGeometry")
            for key, value in (("x", 60 + (x - x0) * scale),
                               ("y", 50 + (y - y0) * scale),
                               ("width", width * scale), ("height", node_height * scale)):
                geom.set(key, str(round(value, 2)))
    for cell in vertices:
        geom = cell.find("mxGeometry")
        width, node_height = float(geom.get("width")), float(geom.get("height"))
        label = str(cell.get("value") or "")
        font_size = 10
        for candidate in (16, 14, 12, 10):
            chars_per_line = max(1, int((width - 20) / (candidate * 1.1)))
            lines = math.ceil(len(label) / chars_per_line)
            if lines * candidate * 1.35 <= node_height - 12:
                font_size = candidate
                break
        cell.set("style", re.sub(r"fontSize=\d+", f"fontSize={font_size}",
                                 cell.get("style") or ""))
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
