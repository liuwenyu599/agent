"""Regression tests for two designed-mode rendering defects.

Bug 1 — "有框无字" (frames with no text): the model-composition path fills each
region with ``references(sdata)[ref]``. When a referenced body/title ref resolves
to empty content (e.g. an outline point that came back blank), ``run.text`` is set
to "" and the page ships as boxes with no text instead of falling back to the
reliable readable layout. ``_fill_model_regions_on_template`` now pre-checks that
every referenced region has real text before drawing anything.

Bug 2 — garbled diagram fragments: SmartArt/diagram leftovers cloned from the
source template carry ``<a:custGeom>`` nodes with corrupted names and no text.
``_drop_broken_template_shapes`` removes those at clone time.
"""
from __future__ import annotations

from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE
from pptx.oxml.ns import qn

from app.application.ppt import ppt_engine


def _build_regions_sdata(points, *, empty_index=None):
    """A content page whose design.regions reference title + every point.

    ``explain`` requires ``len(regions) == len(references)`` and every region ref
    to resolve, so the only way the fill can be empty is an empty *value* — which
    is exactly the Bug 1 scenario.
    """
    regions = [{"ref": "title", "x": .055, "y": .05, "w": .89, "h": .12}]
    pts = list(points)
    for i in range(len(pts)):
        regions.append({"ref": f"point:{i}", "x": .10,
                        "y": .245 + i * .20, "w": .80, "h": .20})
    return {
        "type": "content",
        "title": "上半年工作总结",
        "points": pts,
        "design": {"regions": regions},
    }


def test_model_regions_reject_empty_body_content():
    # 中间一条要点为空：references() 仍会给出 point:1（空串），explain 能通过
    # （空文字装得下），但预检必须拦下并退回可读兜底，不能造出有框无字的空页。
    points = ["这是正文要点一", "", "这是正文要点三"]
    sdata = _build_regions_sdata(points)
    prs = Presentation()
    page = prs.slides.add_slide(prs.slide_layouts[6])
    colors = {"primary": "C00000", "accent": "E25858", "dark": "303030"}
    reason = []
    ok = ppt_engine._fill_model_regions_on_template(
        page, sdata, colors, "微软雅黑", prs.slide_width, prs.slide_height,
        .025, .89, reason_out=reason)
    assert ok is False
    assert any("无对应文字" in r for r in reason), reason
    assert "point:1" in "；".join(reason)
    # 预检在画任何文本框之前就返回，所以 slide 上不应出现模型填的空文本框。
    model_boxes = [s for s in page.shapes if s.has_text_frame and s.text == ""]
    assert model_boxes == [], "不应留下有框无字的模型文本框"


def test_model_regions_accept_real_body_content():
    points = ["这是正文要点一", "这是正文要点二", "这是正文要点三"]
    sdata = _build_regions_sdata(points)
    prs = Presentation()
    page = prs.slides.add_slide(prs.slide_layouts[6])
    colors = {"primary": "C00000", "accent": "E25858", "dark": "303030"}
    ok = ppt_engine._fill_model_regions_on_template(
        page, sdata, colors, "微软雅黑", prs.slide_width, prs.slide_height,
        .025, .89)
    assert ok is True
    texts = {s.text for s in page.shapes if s.has_text_frame}
    assert "这是正文要点一" in texts
    assert "这是正文要点二" in texts
    assert "这是正文要点三" in texts
    assert "上半年工作总结" in texts


def _inject_custgeom(shape, *, with_text: bool):
    """Replace a shape's preset geometry with a custom <a:custGeom> node."""
    sp = shape._element
    sppr = sp.find(qn("p:spPr"))
    prst = sppr.find(qn("a:prstGeom"))
    if prst is not None:
        sppr.remove(prst)
    cust = sppr.makeelement(qn("a:custGeom"), {})
    path_lst = cust.makeelement(qn("a:pathLst"), {})
    path = cust.makeelement(qn("a:path"), {"w": "100", "h": "100"})
    move = path.makeelement(qn("a:moveTo"), {})
    pt = move.makeelement(qn("a:pt"), {"x": "0", "y": "0"})
    move.append(pt)
    path.append(move)
    path_lst.append(path)
    cust.append(path_lst)
    sppr.append(cust)
    if with_text:
        # 给自绘图形加一段文字，确保「带字的自绘图形」被保留。
        txbody = sp.find(qn("p:txBody"))
        if txbody is None:
            txbody = sp.makeelement(qn("p:txBody"), {})
            sp.append(txbody)
        p = txbody.makeelement(qn("a:p"), {})
        r = p.makeelement(qn("a:r"), {})
        t = r.makeelement(qn("a:t"), {})
        t.text = "保留我"
        r.append(t)
        p.append(r)
        txbody.append(p)


def test_drop_broken_template_shapes_only_drops_grouped_custgeom():
    prs = Presentation()
    page = prs.slides.add_slide(prs.slide_layouts[6])

    # 1) 顶层无文字的自绘图形（如 BrandLogo）→ 必须保留（合法模板装饰）。
    logo = page.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, 100, 100)
    logo.name = "BrandLogo"
    _inject_custgeom(logo, with_text=False)

    # 2) 有文字的自绘图形 → 必须保留（误删会吃掉真实内容）。
    keep = page.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, 100, 100)
    _inject_custgeom(keep, with_text=True)

    # 3) 普通预设图形（无 custGeom）→ 必须保留。
    normal = page.shapes.add_shape(MSO_SHAPE.OVAL, 0, 0, 50, 50)

    # 4) 组里全是空自绘图形（SmartArt/图示残片）→ 组及其子节点应被删除。
    spTree = page.shapes._spTree
    grp = spTree.makeelement(qn("p:grpSp"), {})
    inner = page.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, 10, 10)
    _inject_custgeom(inner, with_text=False)
    grp.append(inner._element)
    spTree.append(grp)

    ppt_engine._drop_broken_template_shapes(page)

    remaining_names = {s.name for s in page.shapes}
    # 顶层无文字的自绘图形（BrandLogo）应被保留，不能当残片删。
    assert "BrandLogo" in remaining_names, "顶层无文字自绘装饰应保留"
    # 带字的自绘图形：其 <a:t> 文本仍在。
    remaining_texts = [n.text for n in page._element.iter(qn("a:t"))]
    assert "保留我" in remaining_texts, "带文字的自绘图形不应被删除"
    # 普通预设图形仍在（用元素身份判断，避免 AUTO_SHAPE 类型名干扰）。
    assert normal._element.getparent() is not None, "普通预设图形应保留"
    # 组（及其空自绘子节点）应被移除。
    assert len(list(page._element.iter(qn("p:grpSp")))) == 0, "含空自绘的组应被删除"


def test_drop_broken_template_shapes_keeps_image_only_group():
    prs = Presentation()
    page = prs.slides.add_slide(prs.slide_layouts[6])
    spTree = page.shapes._spTree
    # 纯图组：组里只有一个 p:pic，没有 p:sp / graphicFrame。
    grp = spTree.makeelement(qn("p:grpSp"), {})
    pic = spTree.makeelement(qn("p:pic"), {})
    grp.append(pic)
    spTree.append(grp)
    ppt_engine._drop_broken_template_shapes(page)
    # 只含图片的组必须保留，不能误删。
    assert len(list(page._element.iter(qn("p:grpSp")))) == 1, "纯图组应保留"
    assert len(list(page._element.iter(qn("p:pic")))) == 1, "组内图片应保留"


def test_rejected_composition_keeps_template_decorations():
    # 空正文预检必须在「删除模板重叠形状」之前：构图被拒时模板装饰不应被提前删掉。
    points = ["", "这是正文要点二", "这是正文要点三"]  # point:0 为空 → 预检拒
    sdata = _build_regions_sdata(points)
    prs = Presentation()
    page = prs.slides.add_slide(prs.slide_layouts[6])
    colors = {"primary": "C00000", "accent": "E25858", "dark": "303030"}
    # 在 point:0 模型区域(约 x=.10,y=.245,w=.80,h=.20)下放一个模板装饰色块。
    deco = page.shapes.add_shape(
        MSO_SHAPE.RECTANGLE,
        int(.10 * prs.slide_width), int(.245 * prs.slide_height),
        int(.79 * prs.slide_width), int(.19 * prs.slide_height))
    deco.name = "TemplateColorBlock"
    reason = []
    ok = ppt_engine._fill_model_regions_on_template(
        page, sdata, colors, "微软雅黑", prs.slide_width, prs.slide_height,
        .025, .89, reason_out=reason)
    assert ok is False
    assert any("无对应文字" in r for r in reason), reason
    # 被拒后，模板装饰色块必须仍在（修复前会被提前删除）。
    remaining = {s.name for s in page.shapes}
    assert "TemplateColorBlock" in remaining, "构图被拒时模板装饰不应被删除"
