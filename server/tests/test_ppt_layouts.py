"""PPT 版式目录与选版器测试（P0 版式扩容）。

覆盖三层：
1. 目录完整性 —— 每个页型都有版式，id 规范、数量达标；
2. 选版规则 —— AI 意图采纳/降级、硬门槛（点数/配图/数据块）、相邻去重、旧模板别名；
3. 渲染兜底 —— 全部版式都能真实渲染出 pptx，且不污染调用方的大纲对象。

另含「工具协议」测试：35B 大纲里规定的 chart/table JSON，必须由后端确定性渲染成
原生（双击可改数据）的 PowerPoint 图表/表格对象，而不是一张静态图片。
"""
import io

import pytest
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE

from app.application.ppt import ppt_engine as E

TPL = dict(E.BUILTIN_TEMPLATES[0])


def _slide(t, points=None, layout=None, blocks=None, image=False,
           title="测试标题", subtitle=None):
    s = {"type": t, "title": title, "points": points or [], "blocks": blocks or {}}
    if subtitle is not None:
        s["subtitle"] = subtitle
    if layout:
        s["layout"] = layout
    if image:
        s["_image"] = {"file_path": "unused", "name": "x"}
    return s


class TestLayoutCatalog:
    def test_every_page_type_has_layouts(self):
        for t in E.PAGE_TYPES:
            assert E.layout_ids(t), f"页型 {t} 没有任何版式"

    def test_ids_unique_and_prefixed_by_type(self):
        seen = set()
        for t, specs in E.LAYOUT_CATALOG.items():
            for sp in specs:
                assert sp["id"].startswith(f"{t}."), sp["id"]
                assert sp["id"] not in seen, sp["id"]
                seen.add(sp["id"])

    def test_catalog_size_at_least_thirty(self):
        total = sum(len(v) for v in E.LAYOUT_CATALOG.values())
        assert total >= 30, f"版式库应不少于 30 个，当前 {total}"

    def test_content_has_enough_variants(self):
        assert len(E.layout_ids("content")) >= 6

    def test_normalize_layout_id(self):
        assert E._normalize_layout_id("two_col", "content") == "content.two_col"
        assert E._normalize_layout_id("content.two_col", "content") == "content.two_col"
        assert E._normalize_layout_id("cover.band", "content") == ""
        assert E._normalize_layout_id("nosuch", "content") == ""
        assert E._normalize_layout_id(None, "content") == ""


class TestChooseLayout:
    def test_ai_intent_respected_when_feasible(self):
        s = _slide("content", ["a", "b", "c"], layout="three_cards")
        assert E.choose_layout(s) == "content.three_cards"

    def test_ai_intent_dropped_when_points_mismatch(self):
        s = _slide("content", ["a", "b", "c", "d"], layout="three_cards")
        assert E.choose_layout(s) != "content.three_cards"

    def test_ai_intent_dropped_for_wrong_type_prefix(self):
        s = _slide("content", ["a", "b", "c"], layout="cover.minimal")
        assert E.choose_layout(s) != "cover.minimal"

    def test_image_right_requires_real_image(self):
        s = _slide("content", ["a", "b"], layout="image_right")
        assert E.choose_layout(s) != "content.image_right"
        s2 = _slide("content", ["a", "b"], layout="image_right", image=True)
        assert E.choose_layout(s2) == "content.image_right"

    def test_timeline_counts_blocks_not_points(self):
        s = _slide("timeline", blocks={"timeline": [{"time": "1月", "text": "a"}
                                                    for _ in range(5)]},
                   layout="vertical")
        assert E.choose_layout(s) == "timeline.vertical"

    def test_process_intent_respected_and_auto_prefers_chevron(self):
        s3 = _slide("process", blocks={"process": ["a", "b", "c"]}, layout="vertical")
        assert E.choose_layout(s3) == "process.vertical"
        s3_auto = _slide("process", blocks={"process": ["a", "b", "c"]})
        assert E.choose_layout(s3_auto) == "process.chevron"
        s6 = _slide("process", blocks={"process": [str(i) for i in range(6)]},
                    layout="vertical")
        assert E.choose_layout(s6) == "process.vertical"

    def test_data_table_requires_rows(self):
        s = _slide("data", blocks={"cards": [{"label": "a", "value": "1"}]}, layout="table")
        assert E.choose_layout(s) != "data.table"
        s2 = _slide("data", blocks={"table": {"headers": ["a"], "rows": [["1"], ["2"], ["3"]]}})
        assert E.choose_layout(s2) == "data.table"

    def test_chart_split_needs_points(self):
        s = _slide("chart", blocks={"chart": {"categories": ["a"], "series": [{"name": "x", "values": [1]}]}})
        assert E.choose_layout(s) == "chart.full"
        s2 = _slide("chart", points=["结论一"], layout="split",
                    blocks={"chart": {"categories": ["a"], "series": [{"name": "x", "values": [1]}]}})
        assert E.choose_layout(s2) == "chart.split"

    def test_avoid_repeating_recent_layout(self):
        s = _slide("content", ["a", "b", "c", "d"])
        chosen = E.choose_layout(s, recent=["content.two_col"])
        assert chosen != "content.two_col"

    def test_ai_layout_hint_does_not_make_every_content_page_identical(self):
        s = _slide("content", ["事项一", "事项二", "事项三"], layout="bullets")
        assert E.choose_layout(s, recent=["content.bullets"]) != "content.bullets"
        s["layout_locked"] = True
        assert E.choose_layout(s, recent=["content.bullets"]) == "content.bullets"

    def test_legacy_alias_applies_to_skin_pages(self):
        s = _slide("cover", title="封面")
        assert E.choose_layout(s, {"cover": "left_block"}) == "cover.side"

    def test_template_preference_not_forcing_content_pages(self):
        s = _slide("content", ["a", "b"])
        out = E.choose_layout(s, {"content": "top_band"})
        assert out in E.layout_ids("content")

    def test_statement_favored_for_single_short_point(self):
        s = _slide("content", ["把矛盾化解在基层、化解在萌芽状态"])
        assert E.choose_layout(s) == "content.statement"

    def test_fallback_when_nothing_fits(self):
        # 无图且唯一 image 版式不可用时仍要返回一个可用版式
        s = _slide("content", ["a", "b"])
        assert E.choose_layout(s) in E.layout_ids("content")


class TestRenderAllLayouts:
    """整篇覆盖全部版式的渲染兜底：形状不炸、页数正确、调用方对象不被污染。"""

    @pytest.fixture()
    def tiny_png(self, tmp_path):
        from PIL import Image
        p = tmp_path / "img.png"
        Image.new("RGB", (64, 48), "#336699").save(p)
        return str(p)

    def _outline(self, png_path):
        def pts(n, prefix="要点"):
            return [f"{prefix}{i + 1}，这是一条用于渲染测试的完整要点内容" for i in range(n)]

        chart = {"chart_type": "bar", "categories": ["一", "二", "三"],
                 "series": [{"name": "数量", "values": [10, 20, 30]}]}
        cards = [{"label": f"指标{i + 1}", "value": f"{(i + 1) * 10}件"} for i in range(4)]
        return {"title": "渲染测试", "subtitle": "副标题", "slides": [
            _slide("cover", title="渲染测试", subtitle="副标题", layout="minimal"),
            _slide("cover", title="渲染测试", layout="band"),
            _slide("cover", title="渲染测试", layout="side"),
            _slide("toc", pts(5, "章节"), layout="grid"),
            _slide("toc", pts(4, "章节"), layout="cards"),
            _slide("section", title="一、测试", layout="number"),
            _slide("section", title="二、测试", layout="side"),
            _slide("section", title="三、测试", layout="center"),
            _slide("content", pts(4), layout="bullets"),
            _slide("content", pts(5), layout="two_col"),
            _slide("content", pts(3), layout="three_cards"),
            _slide("content", pts(2), layout="compare"),
            _slide("content", pts(4), layout="icon_grid"),
            _slide("content", pts(3, "居中"), layout="center"),
            _slide("content", pts(2, "对称"), layout="symmetric"),
            _slide("content", pts(1, "核心判断"), layout="statement"),
            _slide("content", pts(2, "引用"), layout="quote"),
            _slide("content", pts(2), layout="image_right", image=True),
            _slide("data", pts(1), blocks={"cards": cards}),
            _slide("data", pts(1), blocks={"cards": cards}, layout="kpi"),
            _slide("data", pts(1), layout="table",
                   blocks={"table": {"headers": ["项目", "数量", "占比"],
                                     "rows": [["A", "10", "50%"], ["B", "8", "40%"],
                                              ["C", "2", "10%"]]}}),
            _slide("chart", pts(2), blocks={"chart": chart}, layout="split"),
            _slide("chart", pts(2), blocks={"chart": dict(chart, chart_type="pie")}),
            _slide("case", pts(3), layout="split"),
            _slide("case", pts(2)),
            _slide("timeline", layout="vertical",
                   blocks={"timeline": [{"time": f"{i + 1}月", "text": "事项"} for i in range(6)]}),
            _slide("timeline", layout="horizontal",
                   blocks={"timeline": [{"time": f"{i + 1}月", "text": "事项"} for i in range(4)]}),
            _slide("process", layout="vertical",
                   blocks={"process": [f"步骤{i + 1}" for i in range(6)]}),
            _slide("process", blocks={"process": [f"步骤{i + 1}" for i in range(4)]}),
            _slide("summary", pts(3), layout="list"),
            _slide("summary", pts(4)),
            _slide("closing", title="谢谢聆听", layout="band"),
            _slide("closing", title="谢谢聆听", layout="center"),
        ]}

    def test_all_layouts_render(self, tiny_png):
        outline = self._outline(tiny_png)
        # image_right 版式指向真实文件
        for s in outline["slides"]:
            if s.get("layout") == "image_right":
                s["_image"] = {"file_path": tiny_png, "name": "test.png"}
        expected = len(outline["slides"])
        data = E.build_pptx(outline, TPL)
        assert data[:2] == b"PK"
        prs = Presentation(io.BytesIO(data))
        assert len(prs.slides) == expected
        for i, sl in enumerate(prs.slides, 1):
            assert len(sl.shapes) >= 3, f"第 {i} 页形状过少"

    def test_build_pptx_does_not_mutate_outline(self, tiny_png):
        outline = self._outline(tiny_png)
        for s in outline["slides"]:
            if s.get("layout") == "image_right":
                s["_image"] = {"file_path": tiny_png, "name": "test.png"}
        E.build_pptx(outline, TPL)
        for s in outline["slides"]:
            assert "_layout" not in s
            assert "_sec_no" not in s

    def test_selected_layouts_are_diverse(self, tiny_png):
        outline = self._outline(tiny_png)
        for s in outline["slides"]:
            if s.get("layout") == "image_right":
                s["_image"] = {"file_path": tiny_png, "name": "test.png"}
        data = E.build_pptx(outline, TPL)
        prs = Presentation(io.BytesIO(data))
        # 31 页里如果出现 8 页以上完全相同的形状数量，说明版式选择塌缩
        counts = [len(sl.shapes) for sl in prs.slides]
        from collections import Counter
        top = Counter(counts).most_common(1)[0][1]
        assert top <= 5, f"版式疑似塌缩：出现相同形状数的页过多 {counts}"

    def test_statement_with_long_text_still_renders(self):
        s = _slide("content", ["这是一条超过了三十个字的核心结论，用来验证大字版式在长文本下仍然可以完整渲染不会异常"],
                   layout="statement")
        data = E.build_pptx({"title": "t", "slides": [s,
            _slide("closing", title="谢谢")]}, TPL)
        assert data[:2] == b"PK"


class TestCenteredAndSymmetricLayouts:
    """内置骨架扩容：居中正文 / 左右对称（回应「不选模板就永远左对齐」）。"""

    def test_new_layouts_registered(self):
        ids = E.layout_ids("content")
        assert "content.center" in ids
        assert "content.symmetric" in ids

    def test_ai_intent_selects_new_layouts(self):
        assert E.choose_layout(_slide("content", ["依法履职", "服务群众"],
                                     layout="center")) == "content.center"
        assert E.choose_layout(_slide("content", ["依法履职", "服务群众"],
                                     layout="symmetric")) == "content.symmetric"

    def test_center_prefers_short_points(self):
        spec = next(sp for sp in E.LAYOUT_CATALOG["content"]
                    if sp["id"] == "content.center")
        short = {"points": ["依法履职", "服务群众", "守正创新"]}
        long_ = {"points": ["这是一段很长的正文" * 6, "另一段很长的正文" * 6]}
        assert E._layout_score(spec, short, [], {}) > \
            E._layout_score(spec, long_, [], {})

    def test_symmetric_prefers_balanced_pairs(self):
        spec = next(sp for sp in E.LAYOUT_CATALOG["content"]
                    if sp["id"] == "content.symmetric")
        balanced = {"points": ["依法履职", "服务群众"]}
        lopsided = {"points": ["依法履职", "这一段比另一段长出很多很多很多很多的内容，"
                                          "用于验证长度明显失衡时不选左右对称版式"]}
        assert E._layout_score(spec, balanced, [], {}) > \
            E._layout_score(spec, lopsided, [], {})

    def test_center_body_text_is_centered(self):
        from pptx.enum.text import PP_ALIGN
        outline = {"title": "t", "slides": [
            _slide("content", ["依法履职", "服务群众"], layout="center")]}
        data = E.build_pptx(outline, TPL)
        prs = Presentation(io.BytesIO(data))
        body = [sh for sh in prs.slides[0].shapes
                if sh.has_text_frame and "依法履职" in sh.text_frame.text]
        assert body, "居中正文页应保留全部要点文字"
        assert body[0].text_frame.paragraphs[0].alignment == PP_ALIGN.CENTER

    def test_symmetric_columns_mirror_around_axis(self):
        outline = {"title": "t", "slides": [
            _slide("content", ["依法履职", "服务群众"], layout="symmetric")]}
        data = E.build_pptx(outline, TPL)
        prs = Presentation(io.BytesIO(data))
        width, height = prs.slide_width, prs.slide_height
        panels = [sh for sh in prs.slides[0].shapes
                  if sh.shape_type == MSO_SHAPE_TYPE.AUTO_SHAPE
                  and sh.width > width * 0.35 and sh.height > height * 0.5]
        assert len(panels) >= 2, "应有左右两块等宽面板"
        panels.sort(key=lambda sh: sh.left)
        left, right = panels[0], panels[-1]
        assert abs(left.width - right.width) < width * 0.01
        assert abs((left.left + left.width / 2) +
                   (right.left + right.width / 2) - width) < width * 0.01


class TestNativeDataObjectProtocol:
    """35B 大纲里的 chart/table JSON → 后端原生可编辑对象（非图片）。

    这正是「大脑+手脚」架构的契约：模型只负责提取结构化数据，
    坐标与绘图全部由后端确定性完成，用户拿到后能双击改数据。
    """

    def _chart_outline(self, chart_type="bar"):
        chart = {"chart_type": chart_type,
                 "categories": ["1月", "2月", "3月"],
                 "series": [{"name": "咨询量", "values": [120, 150, 90]}]}
        return {"title": "测试", "slides": [
            _slide("cover", title="测试封面", subtitle="副标题"),
            _slide("chart", points=["2月环比上升", "3月回落"], blocks={"chart": chart}),
            _slide("closing", title="谢谢"),
        ]}

    def _table_outline(self):
        table = {"headers": ["项目", "数量", "占比"],
                 "rows": [["信访", "120", "40%"], ["调解", "150", "50%"],
                          ["其他", "30", "10%"]]}
        return {"title": "测试", "slides": [
            _slide("cover", title="测试封面", subtitle="副标题"),
            _slide("data", points=["明细见下表"], blocks={"table": table}, layout="table"),
            _slide("closing", title="谢谢"),
        ]}

    def _find_chart_shape(self, prs):
        for sl in prs.slides:
            for sh in sl.shapes:
                if sh.shape_type == MSO_SHAPE_TYPE.CHART:
                    return sh
        return None

    def _find_table_shape(self, prs):
        for sl in prs.slides:
            for sh in sl.shapes:
                if sh.has_table:
                    return sh
        return None

    def test_chart_json_grows_native_chart_not_image(self):
        data = E.build_pptx(self._chart_outline("bar"), TPL)
        assert data[:2] == b"PK"
        prs = Presentation(io.BytesIO(data))
        chart_shape = self._find_chart_shape(prs)
        assert chart_shape is not None, "chart JSON 未长出原生 CHART 对象"
        # 原生图表：双击可编辑，而非一张 PNG
        plot = chart_shape.chart
        assert plot.chart_type is not None
        # 数据可回读 —— 证明用户能改数
        cats = list(plot.plots[0].categories)
        assert list(cats) == ["1月", "2月", "3月"], f"类目未正确映射：{list(cats)}"
        vals = list(plot.series[0].values)
        assert vals == [120, 150, 90], f"数值未正确映射：{vals}"

    def test_pie_json_grows_native_pie(self):
        data = E.build_pptx(self._chart_outline("pie"), TPL)
        prs = Presentation(io.BytesIO(data))
        sh = self._find_chart_shape(prs)
        assert sh is not None
        assert "PIE" in str(sh.chart.chart_type)

    def test_table_json_grows_native_table(self):
        data = E.build_pptx(self._table_outline(), TPL)
        assert data[:2] == b"PK"
        prs = Presentation(io.BytesIO(data))
        tbl_shape = self._find_table_shape(prs)
        assert tbl_shape is not None, "table JSON 未长出原生 TABLE 对象"
        tbl = tbl_shape.table
        # 表头 + 3 行数据
        assert len(tbl.rows) == 4, f"表格行数异常：{len(tbl.rows)}"
        assert [c.text for c in tbl.rows[0].cells] == ["项目", "数量", "占比"]
        assert [c.text for c in tbl.rows[1].cells] == ["信访", "120", "40%"]


class TestAutoDiagramEnrichment:
    """流程页在大纲阶段自动挂 drawio 原生图示（固化 blocks.drawio_xml）。

    验证「大脑+手脚」编排：开启时流程页拿到 drawio_xml、其余页不动；
    未配置/已存在时静默跳过，绝不拖垮整份大纲。
    """

    def _process_outline(self):
        return {"title": "t", "slides": [
            {"type": "cover", "title": "封面"},
            {"type": "process", "title": "办理流程", "blocks": {"process": ["受理", "审查", "决定"]}},
            {"type": "content", "title": "正文", "points": ["要点一"]},
            {"type": "closing", "title": "谢谢"},
        ]}

    def _fake_service(self, monkeypatch, enabled=True, hits=None):
        class _Fake:
            def __init__(self, *a, **k):
                pass

            def generate_native_diagram(self, assistant, slide, kind="process", style=None):
                if hits is not None:
                    hits.append(slide.get("title"))
                updated = dict(slide)
                updated["blocks"] = {
                    "drawio_xml": "<mxGraphModel><root/></mxGraphModel>",
                    "drawio_kind": "process",
                    "process": slide.get("blocks", {}).get("process")
                    or slide.get("points") or [],
                }
                return updated
        _Fake.enabled = enabled
        import app.application.ppt.drawio_service as dsmod
        monkeypatch.setattr(dsmod, "DrawioService", _Fake)

    def test_process_slide_gets_diagram_when_enabled(self, monkeypatch):
        hits = []
        self._fake_service(monkeypatch, enabled=True, hits=hits)
        res = E.enrich_outline_with_diagrams(object(), self._process_outline())
        proc = res["slides"][1]
        assert proc["blocks"].get("drawio_xml"), "流程页未挂接 drawio_xml"
        assert proc["blocks"]["drawio_kind"] == "process"
        # 非流程页不受影响
        assert "drawio_xml" not in res["slides"][2].get("blocks", {})
        assert hits == ["办理流程"]

    def test_no_change_when_drawio_disabled(self, monkeypatch):
        self._fake_service(monkeypatch, enabled=False)
        res = E.enrich_outline_with_diagrams(object(), self._process_outline())
        assert "drawio_xml" not in res["slides"][1].get("blocks", {})

    def test_existing_drawio_xml_not_regenerated(self, monkeypatch):
        self._fake_service(monkeypatch, enabled=True)
        outline = self._process_outline()
        outline["slides"][1]["blocks"]["drawio_xml"] = "<old-diagram/>"
        res = E.enrich_outline_with_diagrams(object(), outline)
        assert res["slides"][1]["blocks"]["drawio_xml"] == "<old-diagram/>"

    def test_process_slide_without_content_skipped(self, monkeypatch):
        hits = []
        self._fake_service(monkeypatch, enabled=True, hits=hits)
        outline = {"title": "t", "slides": [
            {"type": "process", "title": "空流程", "blocks": {}, "points": []},
        ]}
        E.enrich_outline_with_diagrams(object(), outline)
        assert hits == [], "无内容的流程页不应触发 drawio 生成"




