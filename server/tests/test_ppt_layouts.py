"""PPT 版式目录与选版器测试（P0 版式扩容）。

覆盖三层：
1. 目录完整性 —— 每个页型都有版式，id 规范、数量达标；
2. 选版规则 —— AI 意图采纳/降级、硬门槛（点数/配图/数据块）、相邻去重、旧模板别名；
3. 渲染兜底 —— 全部版式都能真实渲染出 pptx，且不污染调用方的大纲对象。

另含「工具协议」测试：35B 大纲里规定的 chart/table JSON，必须由后端确定性渲染成
原生（双击可改数据）的 PowerPoint 图表/表格对象，而不是一张静态图片。
"""
import io
import json

import pytest
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE

from app.application.ppt import ppt_engine as E

TPL = dict(E.BUILTIN_TEMPLATES[0])


def _slide(t, points=None, layout=None, blocks=None, image=False,
           title="测试标题", subtitle=None, locked=False):
    s = {"type": t, "title": title, "points": points or [], "blocks": blocks or {}}
    if subtitle is not None:
        s["subtitle"] = subtitle
    if layout:
        s["layout"] = layout
    if locked:
        # 版式锁定 = 模板作者/用户指定，渲染必须照此执行（章节页统一除外）。
        s["layout_locked"] = True
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
            _slide("section", title="二、测试", layout="side", locked=True),
            _slide("section", title="三、测试", layout="center", locked=True),
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

    def test_section_pages_unified_even_if_layouts_differ(self):
        """章节页整篇统一：首张定版，后面即使给了不同版式也沿用。"""
        outline = {"title": "t", "slides": [
            _slide("section", title="一、测试", layout="number"),
            _slide("section", title="二、测试", layout="side"),
            _slide("section", title="三、测试", layout="center"),
            _slide("closing", title="谢谢"),
        ]}
        prs = Presentation(io.BytesIO(E.build_pptx(outline, TPL)))
        sig = [tuple((sh.left, sh.top, sh.width, sh.height) for sh in sl.shapes)
               for sl in list(prs.slides)[:3]]
        assert sig[0] == sig[1] == sig[2], "章节页几何不一致，说明没统一"

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


class TestVisualIntent:
    """规则层补齐 design 与页型，不依赖 35B 是否执行提示词契约。"""

    def test_model_intent_is_respected(self):
        s = {"design": {"relationship": "comparison"},
             "points": ["总之要抓好落实"]}
        assert E.infer_relationship(s, 0) is None

    def test_relationship_tracks_content_shape(self):
        assert E.infer_relationship({"points": ["总之要抓好落实"]}, 0) == "takeaway"
        assert E.infer_relationship(
            {"points": ["过去主要靠人工", "现在改为线上办理"]}, 0) == "comparison"
        assert E.infer_relationship(
            {"points": ["一是完善制度", "二是加强培训", "三是强化监督"]}, 0) == "grouped"

    def test_apply_intent_keeps_wording_and_marks_source(self):
        pts = ["完善公共法律服务体系", "加强基层队伍建设", "推进数字化转型"]
        outline = {"slides": [{"type": "content", "title": "重点任务",
                               "points": list(pts), "design": {}}]}
        s = E.apply_visual_intent(outline)["slides"][0]
        assert s["points"] == pts
        assert s["design"]["intent_source"] == "rule"
        assert s["design"]["relationship"] in ("parallel", "grouped")

    def test_sequence_content_becomes_process(self):
        pts = ["第一步 受理申请", "第二步 审核材料", "第三步 办结归档"]
        outline = {"slides": [{"type": "content", "title": "办理流程",
                               "points": list(pts), "blocks": {}}]}
        s = E.apply_visual_intent(outline)["slides"][0]
        assert s["type"] == "process"
        assert s["blocks"]["process"] == pts
        assert s["blocks"]["drawio_kind"] == "process"
        assert s["points"] == pts

    def test_page_count_filler_keeps_its_design(self):
        """页数补位页不是真实内容，不能因一条要点被判成「单一结论」。"""
        outline = {"slides": [{"type": "content", "title": "补充内容",
                               "points": ["本页内容待根据已确认材料补充"],
                               "note": "页数硬约束补位页；不得自行编造事实或数据",
                               "blocks": {}}]}
        s = E.apply_visual_intent(outline)["slides"][0]
        assert (s.get("design") or {}).get("intent_source") != "rule"
        assert s["type"] == "content"

    def test_enumerated_sections_are_not_turned_into_process(self):
        """「一、二、三」多为并列板块，不能被硬画成步骤箭头。"""
        pts = ["一、健全工作机制", "二、强化队伍建设", "三、压实主体责任"]
        outline = {"slides": [{"type": "content", "title": "重点工作",
                               "points": list(pts), "blocks": {}}]}
        assert E.apply_visual_intent(outline)["slides"][0]["type"] == "content"

    def test_numeric_content_not_stolen_from_data_pages(self):
        pts = ["完成审核 120 件", "开展评查 35 次", "整改问题 18 处"]
        outline = {"slides": [{"type": "content", "title": "数据",
                               "points": list(pts), "blocks": {}}]}
        assert E.apply_visual_intent(outline)["slides"][0]["type"] == "content"

    def test_idempotent(self):
        outline = {"slides": [{"type": "content", "title": "办理流程",
                               "points": ["首先受理", "其次审核", "最后办结"]}]}
        first = E.apply_visual_intent(outline)
        snapshot = json.dumps(first, ensure_ascii=False, sort_keys=True)
        E.apply_visual_intent(first)
        assert json.dumps(first, ensure_ascii=False, sort_keys=True) == snapshot

    def test_sanitize_outline_applies_intent(self):
        from app.application.ppt.service import PPTService
        out = PPTService.sanitize_outline(
            {"title": "x", "slides": [
                {"type": "content", "title": "办理流程",
                 "points": ["第一步 受理", "第二步 审核", "第三步 办结"]}]},
            ensure_toc=False, enforce_bookends=False)
        assert out["slides"][0]["type"] == "process"

    def test_decorative_layout_varies_but_is_stable_per_slide(self):
        seen = set()
        for i in range(12):
            s = {"type": "cover", "title": f"第{i}次汇报", "id": f"id{i:04d}",
                 "points": []}
            seen.add(E.choose_layout(s, TPL["layouts"]))
        assert len(seen) >= 2, "不同稿件的封面不应永远是同一个版式"
        s = {"type": "cover", "title": "同一页", "id": "fixed001", "points": []}
        assert E.choose_layout(s, TPL["layouts"]) == E.choose_layout(
            dict(s), TPL["layouts"])


class TestRuleLayoutRotation:
    """规则层推断出的关系整稿常相同，不能把同型页全锁到一个版式。"""

    @staticmethod
    def _pages(count=5):
        return [{"type": "content", "title": f"工作板块{i+1}",
                 "points": ["建成三级服务平台", "推广线上受理渠道",
                            "开展企业法治体检", "健全援助保障机制"],
                 "design": {}} for i in range(count)]

    def test_same_relationship_pages_do_not_share_one_skeleton(self):
        clean = E.apply_visual_intent(E.normalize_outline(
            {"title": "t", "slides": self._pages()}, require_bookends=False))
        used, recent, chosen = {}, [], []
        for slide in clean["slides"]:
            lid = E.choose_layout(slide, TPL["layouts"], recent=recent, used=used)
            used[lid] = used.get(lid, 0) + 1
            recent = (recent + [lid])[-2:]
            chosen.append(lid)
        assert len(set(chosen)) >= 4, chosen
        assert all(lid in E.layout_ids("content") for lid in chosen)

    def test_unusable_preferred_layout_uses_variant_pool(self):
        """4 条要点时 three_cards 硬门槛不通过，要换到另一个构图族。"""
        from app.application.ppt.page_scene import _LAYOUT_FAMILY
        slide = {"type": "content", "title": "重点任务",
                 "points": ["一是完善制度", "二是加强培训", "三是强化监督", "四是压实责任"],
                 "design": {"relationship": "parallel"}}
        lid = E.choose_layout(slide, TPL["layouts"],
                              recent=[], used={"content.three_cards": 1})
        assert lid in E.layout_ids("content")
        assert lid != "content.three_cards"
        assert _LAYOUT_FAMILY.get(lid.rsplit(".", 1)[-1]) != "grid"

    def test_first_rule_page_keeps_preferred(self):
        slide = {"type": "content", "title": "三项工作",
                 "points": ["完善制度", "加强培训", "强化监督"],
                 "design": {"relationship": "parallel"}}
        assert E.choose_layout(slide, TPL["layouts"]) == "content.three_cards"

    def test_explicit_model_layout_still_wins(self):
        slide = {"type": "content", "title": "两项对比",
                 "points": ["过去人工办理", "现在线上办理"],
                 "design": {"relationship": "comparison"},
                 "layout": "content.compare"}
        assert E.choose_layout(slide, TPL["layouts"]) == "content.compare"


class TestOfflineDefaults:
    """政务内网：默认配置里不得预置任何公网端点，误开开关也不能外联。"""

    def test_no_public_endpoint_in_defaults(self):
        from app.application.ppt.dto import CloudCfgIn
        from app.application.ppt.service import _CLOUD_DEFAULT
        assert CloudCfgIn().base_url == ""
        assert _CLOUD_DEFAULT["base_url"] == ""
        assert "http" not in (CloudCfgIn().base_url + _CLOUD_DEFAULT["base_url"])

    def test_cloud_generation_refuses_without_endpoint(self, monkeypatch):
        from app.application.ppt import service as S
        from app.core.exceptions import AppError
        monkeypatch.setattr(S.settings, "PPT_CLOUD_ALLOWED", True)
        svc = object.__new__(S.PPTService)
        monkeypatch.setattr(svc, "_load_cloud", lambda: {
            "enabled": True, "api_key": "dummy", "base_url": "",
            "mode": "general", "template_id": "summary_01"})
        body = type("Body", (), {"doc_id": "d1", "mode": "", "template_id": ""})()
        with pytest.raises(AppError):
            svc.generate_cloud(body, object())

class TestCompositionFamilyRotation:
    """关系候选池跨构图族；整稿去重按族而非版式 id。"""

    def test_rule_pool_spans_families(self):
        from app.application.ppt.page_scene import _LAYOUT_FAMILY
        for rel, ids in E._RULE_LAYOUT_POOL.items():
            families = {_LAYOUT_FAMILY.get(i.rsplit(".", 1)[-1], "other")
                        for i in ids}
            assert len(families) >= 3, (rel, families)

    def test_non_body_cards_do_not_claim_body_grid(self):
        assert E._layout_family("toc.cards") != E._layout_family("content.three_cards")
        assert E._layout_family("data.cards") != E._layout_family("content.three_cards")

    def test_summary_avoids_family_already_used_in_body(self):
        slide = {"type": "summary", "title": "结语与展望",
                 "points": ["坚持党建引领", "聚焦主责主业", "强化改革创新"],
                 "design": {"relationship": "grouped"}}
        lid = E.choose_layout(slide, TPL["layouts"], recent=[],
                              used={"content.three_cards": 1,
                                    "content.bullets": 1})
        assert E._layout_family(lid) not in ("grid", "bands")

class TestPageFontBottomLine:
    """字号底线：案例页 / 时间轴页不得再出现 11–13pt 的正文。

    用户 2026-11-09 实机反馈：第二节案例页的字号明显偏小。根因是这几类页不走
    page_scene 自适应排版，字号写死在 r_case / r_timeline 里。这里锁住下限，
    防止以后改回硬编码。
    """

    @staticmethod
    def _body_runs(slide):
        out = []
        for sh in slide.shapes:
            if not sh.has_text_frame:
                continue
            for para in sh.text_frame.paragraphs:
                for run in para.runs:
                    if run.font.size:
                        out.append((sh.text_frame.text.strip(), run.font.size.pt))
        return out

    def test_case_cards_use_readable_peer_size(self):
        outline = {"title": "t", "slides": [
            _slide("case", ["背景：基层调解力量不足，群众办事难。",
                            "做法：搭建全流程线上调解系统，实现视频调解。",
                            "成效：显著缩短办案周期，覆盖全市所有街道。"],
                   layout="split"),
            _slide("closing", title="谢谢")]}
        prs = Presentation(io.BytesIO(E.build_pptx(outline, TPL)))
        sizes = [pt for txt, pt in self._body_runs(prs.slides[0])
                 if txt.startswith(("背景", "做法", "成效"))]
        assert sizes, "案例卡片正文没渲染出来"
        assert min(sizes) >= 18, f"案例页正文仍然偏小：{sizes}"
        assert len(set(sizes)) == 1, f"同级三卡字号不一致：{sizes}"

    def test_timeline_falls_back_to_points_without_duplicates(self):
        point = "启动法治惠民专项行动，优化服务网点布局。"
        outline = {"title": "t", "slides": [
            _slide("timeline", [point, "完成全员轮训，提升专业素养。",
                                "建成二期工程，投入使用。"]),
            _slide("closing", title="谢谢")]}
        prs = Presentation(io.BytesIO(E.build_pptx(outline, TPL)))
        texts = [sh.text_frame.text.strip() for sh in prs.slides[0].shapes
                 if sh.has_text_frame]
        # 只给 points 没给 blocks.timeline 时，也要画成编号节点，不能整页空白。
        assert "01" in texts and "03" in texts
        assert texts.count(point) == 1, "兜底节点在页脚又被重复了一遍"
        body = [pt for txt, pt in self._body_runs(prs.slides[0]) if txt == point]
        assert body and min(body) >= 16, f"时间轴正文仍然偏小：{body}"


class TestSectionBalanceAndFooterRule:
    """章节页构图与页脚：不再出现失衡对角布局和通栏「残留线」。

    用户 2026-11-09 第二轮反馈：①章节页不对称；②有的页下面有莫名其妙的线条。
    根因：section.number 把 150pt 序号钉左上、标题右对齐钉右下；footer 画了
    0.91 宽通栏细灰线。这里锁住「居中同轴」和「页脚无通栏线」两个结论。
    """

    @staticmethod
    def _render(slides, **top):
        outline = {"title": "t", "slides": slides + [_slide("closing", title="谢谢")], **top}
        return Presentation(io.BytesIO(E.build_pptx(outline, TPL)))

    @staticmethod
    def _text_shapes(slide, needle):
        return [sh for sh in slide.shapes
                if sh.has_text_frame and needle in sh.text_frame.text]

    def test_section_number_is_centered_on_page_axis(self):
        prs = self._render([_slide("section", title="一、工作回顾与成效", layout="number")])
        slide = prs.slides[0]
        shapes = self._text_shapes(slide, "01") + self._text_shapes(slide, "工作回顾")
        assert len(shapes) == 2, "章节页的序号和标题没渲染出来"
        for sh in shapes:
            center = sh.left + sh.width / 2
            # 序号与标题同一中轴：都和页面中心对齐（容差 0.02 英寸）
            assert abs(center - prs.slide_width / 2) < 20000, "章节页内容没有居中"
            assert sh.text_frame.paragraphs[0].alignment is not None

    def test_section_style_can_be_overridden_per_deck(self):
        slides = [_slide("section", title=f"{n}、章节") for n in "一二三"]
        default = self._render([dict(s) for s in slides])
        forced = self._render([dict(s) for s in slides], section_style="side")

        def sidebar(prs, idx):
            slide = prs.slides[idx]
            return [sh for sh in slide.shapes
                    if abs(sh.width / prs.slide_width - .34) < .01
                    and abs(sh.height / prs.slide_height - 1.0) < .01]

        assert not sidebar(default, 0), "默认章节页不该是侧栏版式"
        for idx in range(3):
            assert sidebar(forced, idx), "section_style=side 未生效或未统一"

    def test_content_footer_has_no_full_width_rule(self):
        outline = {"title": "t", "slides": [
            _slide("content", ["要点一", "要点二"], layout="bullets"),
            _slide("toc", ["一、回顾", "二、计划"], layout="list"),
            _slide("closing", title="谢谢")]}
        prs = Presentation(io.BytesIO(E.build_pptx(outline, TPL)))
        for page in list(prs.slides)[:2]:
            for sh in page.shapes:
                near_bottom = sh.top / prs.slide_height > .94
                flat = sh.height / prs.slide_height < .006
                if near_bottom and flat:
                    assert sh.width / prs.slide_width < .20, (
                        "页脚又出现了通栏细线（用户反馈的「莫名其妙的线条」）")


class TestDataPromotion:
    """规则层「数据/表格主动化」：有数就该出图，没数就别装指标。

    用户 2026-11-09：成稿 15 页 0 图表 0 表格，「主动画图、做表的主动性差」。
    根因是决定权全交给模型——模型怕编数据就不写 blocks.chart。这里锁住
    promote_data_slides 的四条判据，避免以后又退化成纯文字要点。
    """

    @staticmethod
    def _outline(*slides):
        return {"slides": [dict(s) for s in slides]}

    def test_same_unit_metric_cards_become_chart(self):
        outline = self._outline(_slide("data", blocks={"cards": [
            {"label": "天河区调解成功率", "value": "96.2%"},
            {"label": "越秀区调解成功率", "value": "94.8%"},
            {"label": "白云区调解成功率", "value": "95.5%"}]}))
        E.promote_data_slides(outline)
        slide = outline["slides"][0]
        assert slide["type"] == "chart"
        chart = slide["blocks"]["chart"]
        # 公共后缀「调解成功率」被剥出来当系列名，类目只留区名
        assert chart["categories"] == ["天河区", "越秀区", "白云区"]
        assert chart["series"][0]["values"] == [96.2, 94.8, 95.5]
        assert "调解成功率" in chart["series"][0]["name"]

    def test_mixed_units_do_not_share_one_axis(self):
        outline = self._outline(_slide("data", blocks={"cards": [
            {"label": "受理量", "value": "3200件"},
            {"label": "成功率", "value": "98.5%"},
            {"label": "服务人次", "value": "12万人次"}]}))
        E.promote_data_slides(outline)
        # 件、%、人次同轴没有意义，整页保持指标卡
        assert outline["slides"][0]["type"] == "data"
        assert "chart" not in (outline["slides"][0].get("blocks") or {})

    def test_trend_words_in_metric_cards_are_demoted(self):
        outline = self._outline(_slide("data", blocks={"cards": [
            {"label": "法律援助案件受理量", "value": "稳步增长"},
            {"label": "矛盾纠纷调解成功率", "value": "保持高位"},
            {"label": "公共法律服务覆盖率", "value": "显著提升"},
            {"label": "群众满意度测评", "value": "持续向好"}]}))
        E.promote_data_slides(outline)
        slide = outline["slides"][0]
        # 形容词不是指标值：降级成结论宫格，不再渲染成大字假指标
        assert slide["type"] == "content"
        assert slide["layout"] == "icon_grid"
        assert slide["points"][0] == "法律援助案件受理量：稳步增长"
        assert not slide["blocks"]

    def test_points_with_same_unit_become_chart_and_drop_duplicate_points(self):
        outline = self._outline(_slide("content", points=[
            "一季度受理法律援助案件3200件", "二季度受理法律援助案件4100件",
            "三季度受理法律援助案件3800件", "四季度受理法律援助案件4600件"]))
        E.promote_data_slides(outline)
        slide = outline["slides"][0]
        assert slide["type"] == "chart"
        assert slide["blocks"]["chart"]["categories"] == [
            "一季度", "二季度", "三季度", "四季度"]
        # 原要点已搬进图表数据，留着会在页面底部重复渲染一遍
        assert not slide.get("points")

    def test_narrative_points_with_growth_rate_become_chart(self):
        """整句叙述（主值 + 同比增长）是模型最常见的写法，必须能成图。

        用户 2026-11-09：「没有主动作图」。原规则要求一条里只能有一个数，
        而真实大纲几乎总是「受理 12000 件，同比增长 12%」，于是整页退回文字。
        增长率是附注，不是并列类目，取主值上轴即可。
        """
        outline = self._outline(_slide("content", points=[
            "受理法律援助案件12000件，同比增长12%",
            "调解矛盾纠纷42600件，同比增长8%",
            "办理公证事项8600件，同比增长5%"]))
        E.promote_data_slides(outline)
        slide = outline["slides"][0]
        assert slide["type"] == "chart"
        chart = slide["blocks"]["chart"]
        assert chart["series"][0]["values"] == [12000, 42600, 8600]
        assert chart["unit_family"] == "count"

    def test_points_with_different_unit_families_stay_text(self):
        """三条主值分属件数/比率/金额时不能并排上同一根轴。"""
        outline = self._outline(_slide("content", points=[
            "受理法律援助案件12000件", "调解成功率96.2%", "投入经费380万元"]))
        E.promote_data_slides(outline)
        assert outline["slides"][0]["type"] == "content"

    def test_thousand_separated_values_are_parsed(self):
        """模型常写「32,180 件」，带千分位与空格也要认。"""
        outline = self._outline(_slide("data", blocks={"cards": [
            {"label": "受理量", "value": "32,180 件"},
            {"label": "办结量", "value": "31,500 件"},
            {"label": "咨询量", "value": "28,600 件"}]}))
        E.promote_data_slides(outline)
        slide = outline["slides"][0]
        assert slide["type"] == "chart"
        assert slide["blocks"]["chart"]["series"][0]["values"] == [32180, 31500, 28600]

    def test_count_words_share_one_axis_with_per_point_units(self):
        """件 / 人次 / 项 都是数量，同量级时同轴可比，但标签各带各的单位。"""
        outline = self._outline(_slide("content", points=[
            "受理法律援助案件32180件", "接待群众咨询28600人次", "办理公证事项18400项"]))
        E.promote_data_slides(outline)
        chart = outline["slides"][0]["blocks"]["chart"]
        assert chart["unit_family"] == "count"
        assert chart["point_units"] == ["件", "人次", "项"]

    def test_orders_of_magnitude_gap_falls_back_to_cards(self):
        """32180 件与 42 个同轴时小的那条只剩一条线，宁可退回文字。"""
        outline = self._outline(_slide("content", points=[
            "受理法律援助案件32180件", "接待群众咨询28600人次", "建成工作站42个"]))
        E.promote_data_slides(outline)
        assert outline["slides"][0]["type"] == "content"
        assert len(outline["slides"][0]["points"]) == 3

    def test_mixed_units_chart_the_count_and_keep_the_rest(self):
        outline = self._outline(_slide("data", blocks={"cards": [
            {"label": "受理量", "value": "32180件"},
            {"label": "办结量", "value": "31500件"},
            {"label": "咨询量", "value": "28600人次"},
            {"label": "满意度", "value": "96.8分"}]}))
        E.promote_data_slides(outline)
        slide = outline["slides"][0]
        assert slide["type"] == "chart"
        assert len(slide["blocks"]["chart"]["series"][0]["values"]) == 3
        assert slide["points"] == ["满意度：96.8分"]

    def test_pipe_rows_become_native_table(self):
        outline = self._outline(_slide("content", points=[
            "| 指标 | 年度目标 | 完成值 |", "| 法律援助案件 | 1.2万件 | 1.35万件 |",
            "| 矛盾纠纷调解 | 4万件 | 4.26万件 |"]))
        E.promote_data_slides(outline)
        slide = outline["slides"][0]
        assert slide["type"] == "data"
        assert slide["layout"] == "table"
        assert slide["blocks"]["table"]["headers"] == ["指标", "年度目标", "完成值"]
        assert slide["blocks"]["table"]["rows"][0] == ["法律援助案件", "1.2万件", "1.35万件"]
        assert not slide.get("points")

    def test_percentage_share_sums_to_pie(self):
        outline = self._outline(_slide("content", points=[
            "法律咨询占比42%", "法律援助占比28%", "人民调解占比20%", "公证服务占比10%"]))
        E.promote_data_slides(outline)
        assert outline["slides"][0]["blocks"]["chart"]["chart_type"] == "pie"

    def test_year_numbers_are_not_plotted(self):
        outline = self._outline(_slide("content", points=[
            "2026年建成公共法律服务中心", "2027年实现站点全覆盖",
            "2028年完成数字化改造"]))
        E.promote_data_slides(outline)
        # 年份不是可比较的量值，画成柱状图毫无意义
        assert outline["slides"][0]["type"] == "content"

    def test_unitless_numbers_are_not_plotted(self):
        outline = self._outline(_slide("content", points=[
            "第一项要求 3", "第二项要求 5", "第三项要求 7"]))
        E.promote_data_slides(outline)
        # 全无单位时抽到的多是序号，不拿编号当数据
        assert outline["slides"][0]["type"] == "content"

    def test_promoted_chart_is_really_rendered_as_native_chart(self):
        outline = self._outline(
            _slide("content", title="各季度受理量", points=[
                "一季度受理3200件", "二季度受理4100件",
                "三季度受理3800件", "四季度受理4600件"]),
            _slide("closing", title="谢谢"))
        outline["title"] = "测试"
        E.apply_visual_intent(outline)
        prs = Presentation(io.BytesIO(E.render_pptx(outline, TPL)))
        charts = [sh for sh in prs.slides[0].shapes if sh.has_chart]
        assert charts, "升级后的图表页没有渲染出原生图表对象"
        assert list(charts[0].chart.plots[0].categories) == [
            "一季度", "二季度", "三季度", "四季度"]


class TestGroupedCardsChrome:
    """分组多卡不得在卡外拉一条横贯整页的色带（用户 2026-11-09 实机反馈：
    「三张卡上挂着一条莫名其妙的横线，圆点正好串在线上」）。"""

    @staticmethod
    def _scene():
        boxes = [{"ref": f"point:{i}", "x": .055 + i * .315, "y": .30,
                  "w": .28, "h": .45} for i in range(3)]
        return {"layout": "content.cards", "elements": boxes}

    def test_grouped_bands_sit_on_card_edge_not_above(self):
        from app.application.ppt.visual_primitives import decorations

        scene = self._scene()
        items = decorations(scene, {"design": {"relationship": "grouped"}})
        bands = [i for i in items
                 if i["kind"] in ("rect", "gradient") and i["h"] < .02 and i["w"] > .05]
        assert bands, "分组卡片应当各自带一条色带"
        for band in bands:
            assert abs(band["y"] - .30) < .004, "色带悬在卡片上方会连成通栏横线"

    def test_grouped_bands_are_not_continuous_across_the_row(self):
        from app.application.ppt.visual_primitives import decorations

        items = decorations(self._scene(), {"design": {"relationship": "grouped"}})
        bands = sorted((i for i in items
                        if i["kind"] in ("rect", "gradient") and i["h"] < .02 and i["w"] > .05),
                       key=lambda i: i["x"])
        for left, right in zip(bands, bands[1:]):
            gap = right["x"] - (left["x"] + left["w"])
            assert gap > .02, "相邻色带几乎相连，投影上就是一条通栏横线"


class TestDemotedMetricsExplainThemselves:
    def test_trend_only_metrics_report_how_to_get_a_chart(self):
        outline = {"title": "t", "slides": [_slide(
            "data",
            title="年度核心业务指标概览",
            blocks={"cards": [
                {"label": "法律援助案件受理量", "value": "稳步增长"},
                {"label": "矛盾纠纷调解成功率", "value": "保持高位"},
                {"label": "公共法律服务覆盖率", "value": "显著提升"},
                {"label": "群众满意度测评", "value": "持续向好"}]})]}
        E.apply_visual_intent(outline)
        warnings = []
        E.build_pptx(outline, TPL, warnings=warnings)
        assert any("补充数字" in w for w in warnings), warnings


class TestMetricBackfill:
    """指标卡只有趋势词时，从材料/知识库把真实数值搬回来（用户 2026-11-09：
    「它缺的是数字，不是意愿，不能搜知识库吗」）。"""

    MATERIAL = (
        "2026年，全市司法行政系统共受理法律援助案件 32180 件，同比增长 12.4%。\n"
        "矛盾纠纷调解成功率达到 96.2%，全年调解矛盾纠纷 128450 件。\n"
        "公共法律服务覆盖率提升至 98.6%，建成公共法律服务中心 42 个。\n"
        "群众满意度测评得分 96.8 分，收到锦旗 35 面。")

    @staticmethod
    def _cards():
        return {"cards": [
            {"label": "法律援助案件受理量", "value": "稳步增长"},
            {"label": "矛盾纠纷调解成功率", "value": "保持高位"},
            {"label": "公共法律服务覆盖率", "value": "显著提升"},
            {"label": "群众满意度测评", "value": "持续向好"}]}

    def test_trend_words_are_replaced_with_values_from_material(self):
        outline = {"slides": [_slide("data", title="核心指标", blocks=self._cards())]}
        filled = E.backfill_metric_values(outline, self.MATERIAL, "本次材料")
        values = {f["label"]: f["value"] for f in filled}
        assert values == {"法律援助案件受理量": "32180件",
                          "矛盾纠纷调解成功率": "96.2%",
                          "公共法律服务覆盖率": "98.6%",
                          "群众满意度测评": "96.8分"}
        # 补完后不再是「只有趋势词」，成稿不该再降级成结论宫格
        assert E.unfilled_metric_labels(outline) == []
        assert outline["slides"][0]["sources"] == ["本次材料"]

    def test_short_material_wording_still_matches_long_label(self):
        """指标名比材料多一层修饰（矛盾纠纷调解成功率 vs 调解成功率）也要认。"""
        outline = {"slides": [_slide("data", blocks={"cards": [
            {"label": "矛盾纠纷调解成功率", "value": "保持高位"}]})]}
        filled = E.backfill_metric_values(outline, "调解成功率达到 96.2%。", "m")
        assert [f["value"] for f in filled] == ["96.2%"]

    def test_no_number_in_material_keeps_trend_word(self):
        """材料里没有该指标的数值时原样保留，绝不编造。"""
        outline = {"slides": [_slide("data", blocks={"cards": [
            {"label": "法律援助案件受理量", "value": "稳步增长"}]})]}
        assert E.backfill_metric_values(outline, "本年度工作稳步推进。", "m") == []
        assert outline["slides"][0]["blocks"]["cards"][0]["value"] == "稳步增长"

    def test_ambiguous_numbers_are_not_assigned(self):
        """同一指标名对上两个不同的数 → 放弃，不能张冠李戴。"""
        outline = {"slides": [_slide("data", blocks={"cards": [
            {"label": "调解成功率", "value": "保持高位"}]})]}
        material = "人民调解成功率 96.2%。行业性调解成功率 88.5%。"
        assert E.backfill_metric_values(outline, material, "m") == []

    def test_demoted_page_is_restored_and_promoted_to_chart(self):
        """已降级成「指标名：趋势词」的页，补到数字后要能重新成图。"""
        outline = {"slides": [_slide("content", points=[
            "法律援助案件受理量：稳步增长", "矛盾纠纷调解成功率：保持高位",
            "公共法律服务覆盖率：显著提升", "群众满意度测评：持续向好"])]}
        outline["slides"][0]["_promoted"] = "demote_fake_cards"
        E.backfill_metric_values(outline, self.MATERIAL, "m")
        E.apply_visual_intent(outline)
        slide = outline["slides"][0]
        assert slide["type"] in ("data", "chart")
        assert all("增长" not in p for p in (slide.get("points") or []))

    def test_mixed_units_chart_the_majority_group_and_keep_the_rest(self):
        """三个百分比 + 一个件数：率并排成图，件数转成图表下方结论行。"""
        material = ("调解成功率达到 96.2%。公共法律服务覆盖率达到 98.6%。"
                    "群众满意度达到 96.8%。\n全年受理法律援助案件 32180 件。")
        outline = {"slides": [_slide("data", title="核心指标", blocks={"cards": [
            {"label": "矛盾纠纷调解成功率", "value": "保持高位"},
            {"label": "公共法律服务覆盖率", "value": "显著提升"},
            {"label": "群众满意度", "value": "持续向好"},
            {"label": "法律援助案件受理量", "value": "稳步增长"}]})]}
        E.backfill_metric_values(outline, material, "m")
        E.apply_visual_intent(outline)
        slide = outline["slides"][0]
        assert slide["type"] == "chart"
        chart = slide["blocks"]["chart"]
        assert len(chart["series"][0]["values"]) == 3
        assert slide["points"] == ["法律援助案件受理量：32180件"]
