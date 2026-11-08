"""Edit selected text paragraphs without rebuilding unrelated PPTX package parts."""
from __future__ import annotations

import copy
import io
import zipfile

from lxml import etree
from pptx import Presentation

from app.application.ppt import ppt_engine

NS = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main",
      "p": "http://schemas.openxmlformats.org/presentationml/2006/main"}


def read_source(data: bytes) -> tuple[dict, list]:
    presentation = Presentation(io.BytesIO(data))
    slides, manifest = [], []
    for index, slide in enumerate(presentation.slides):
        paragraphs = slide._element.xpath(".//p:sp/p:txBody/a:p")
        entries = []
        for position, paragraph in enumerate(paragraphs):
            value = "".join(
                node.text or "" for node in paragraph.iter(f"{{{NS['a']}}}t"))
            if value.strip():
                sizes = [int(node.get("sz")) for node in paragraph.iter()
                         if node.get("sz", "").isdigit()]
                entries.append((max(sizes, default=0), position, value.strip()))
        entries.sort(key=lambda item: -item[0])
        title = entries[0] if entries else (0, None, "")
        body = sorted(entries[1:], key=lambda item: item[1])[:6]
        page = {"id": f"native{index}", "type": "content",
                "title": title[2][:60], "points": [entry[2][:150] for entry in body]}
        slides.append(page)
        manifest.append({"part": str(slide.part.partname).lstrip("/"),
                         "title": title[1], "points": [entry[1] for entry in body]})
    outline = ppt_engine.normalize_outline(
        {"title": slides[0]["title"] if slides else "导入的PPT", "slides": slides},
        require_bookends=False)
    for source, page in zip(manifest, outline["slides"]):
        source["baseline"] = copy.deepcopy(page)
    return outline, manifest


def render(data: bytes, manifest: list, outline: dict) -> bytes:
    slides = outline.get("slides") or []
    if [page.get("id") for page in slides] != [item["baseline"]["id"] for item in manifest]:
        raise ValueError("保留原版式编辑暂支持原页文字修改，请保留页面数量和顺序")
    updates = {}
    with zipfile.ZipFile(io.BytesIO(data)) as source:
        for item, page in zip(manifest, slides):
            baseline = item["baseline"]
            for key in ("type", "layout", "blocks", "image_id", "image_name"):
                if page.get(key) != baseline.get(key):
                    raise ValueError("保留原版式编辑暂支持文字修改，请保留原页类型、图片和图表")
            points = page.get("points") or []
            if len(points) != len(baseline["points"]):
                raise ValueError("保留原版式编辑请保持正文条目数量，通过修改各条文字更新内容")
            changes = [(item["title"], baseline["title"], page.get("title") or "")]
            changes += list(zip(item["points"], baseline["points"], points))
            changes = [(position, after) for position, before, after in changes if before != after]
            if not changes:
                continue
            root = etree.fromstring(source.read(item["part"]),
                                    etree.XMLParser(resolve_entities=False, no_network=True))
            paragraphs = root.xpath(".//p:sp/p:txBody/a:p", namespaces=NS)
            for position, value in changes:
                if position is None:
                    raise ValueError("该页没有可修改的原始标题对象")
                runs = paragraphs[position].xpath(".//a:t", namespaces=NS)
                if not runs:
                    raise ValueError("原文字对象无法定位")
                remaining = str(value)
                for index, run in enumerate(runs):
                    count = len(run.text or "") if index < len(runs) - 1 else len(remaining)
                    run.text, remaining = remaining[:count], remaining[count:]
            updates[item["part"]] = etree.tostring(root, xml_declaration=True,
                                                    encoding="UTF-8", standalone=True)
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as target:
            for entry in source.infolist():
                target.writestr(entry, updates.get(entry.filename, source.read(entry.filename)))
    return output.getvalue()
