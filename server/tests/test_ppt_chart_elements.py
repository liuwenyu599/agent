# -*- coding: utf-8 -*-
"""克隆路径（learned）原生图表元素契约。

模型只出结构化数据（chart_type/categories/series），绘图由后端确定性完成：
柱状 bar、条形 bar_h、折线 line、饼图 pie 必须各自长成对应的原生可编辑
CHART 对象——不是一张静态图片，双击能改数。
"""
import sys
from pathlib import Path

import pytest
from pptx import Presentation
from pptx.util import Emu

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.application.ppt import ppt_engine  # noqa: E402

W, H = 12192000, 6858000

CHART = {"categories": ["1月", "2月", "3月"],
         "series": [{"name": "调解案件", "values": [120, 150, 90]}]}
REGION = {"x": .10, "y": .22, "w": .80, "h": .60}


def _blank_deck():
    prs = Presentation()
    prs.slide_width, prs.slide_height = Emu(W), Emu(H)
    return prs, prs.slide_layouts[6]


@pytest.mark.parametrize("chart_type,expected", [
    ("bar", "COLUMN_CLUSTERED"),
    ("bar_h", "BAR_CLUSTERED"),     # 条形图（横向柱状）
    ("line", "LINE"),                # 折线图
    ("pie", "PIE"),                  # 饼状图
    ("stacked", "COLUMN_STACKED"),
    ("area", "AREA"),
])
def test_learned_chart_types_grow_native_objects(chart_type, expected):
    prs, blank = _blank_deck()
    slide = prs.slides.add_slide(blank)
    ppt_engine._add_native_chart(
        slide, dict(CHART, chart_type=chart_type), REGION,
        ppt_engine.DEFAULT_COLORS, "思源黑体", W, H)
    chart_shape = next((sh for sh in slide.shapes if getattr(sh, "has_chart", False)), None)
    assert chart_shape is not None, f"{chart_type} 未生成原生图表对象"
    assert expected in str(chart_shape.chart.chart_type)
    # 数据可回读——证明用户能改数（原生可编辑，不是图片）
    assert list(chart_shape.chart.plots[0].categories) == ["1月", "2月", "3月"]
    assert list(chart_shape.chart.series[0].values) == [120, 150, 90]


def test_learned_unknown_chart_type_falls_back_to_column():
    prs, blank = _blank_deck()
    slide = prs.slides.add_slide(blank)
    ppt_engine._add_native_chart(
        slide, dict(CHART, chart_type="not-a-type"), REGION,
        ppt_engine.DEFAULT_COLORS, "思源黑体", W, H)
    chart = next(sh for sh in slide.shapes if getattr(sh, "has_chart", False)).chart
    assert "COLUMN_CLUSTERED" in str(chart.chart_type)
