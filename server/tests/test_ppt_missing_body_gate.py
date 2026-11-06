"""_filled_page_issue 内容缺失检测：正文/图表数据大量丢失必须被拦下退可读版式。"""
from pptx import Presentation
from pptx.util import Emu

from app.application.ppt.ppt_engine import _filled_page_issue

SW, SH = 12192000, 6858000  # 16:9


def _slide_with(title: str = "标题", body_text: str = ""):
    prs = Presentation()
    prs.slide_width = SW
    prs.slide_height = SH
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    box = slide.shapes.add_textbox(Emu(int(SW * .06)), Emu(int(SW * .05)),
                                   Emu(int(SW * .6)), Emu(int(SW * .06)))
    box.text_frame.text = title
    if body_text:
        b = slide.shapes.add_textbox(Emu(int(SW * .08)), Emu(int(SW * .2)),
                                     Emu(int(SW * .8)), Emu(int(SH * .4)))
        b.text_frame.text = body_text
    return prs, slide


def test_chart_data_lost_flags_issue():
    # 图表页的数据全在 blocks.chart（points 为空）：chart 没被画出来时
    # 旧的 points 逐条检查循环零次直接放行——新检测必须拦下
    prs, slide = _slide_with()
    sdata = {"type": "data", "title": "核心指标完成情况概览", "points": [],
             "blocks": {"chart": {
                 "kind": "bar",
                 "categories": ["一月普法宣传", "二月法律援助", "三月人民调解", "四月社区矫正",
                               "五月行政复议", "六月行政执法"],
                 "series": [{"name": "全市司法行政重点业务量按月统计",
                             "values": [50, 80, 95, 120, 76, 88]},
                            {"name": "法治建设群众满意度季度调查结果",
                             "values": [92, 94, 96, 97]}]}}}
    issue = _filled_page_issue(slide, sdata, SW, SH)
    assert issue and "内容缺失" in issue, f"实际报错：{issue}"


def test_points_lost_flags_issue():
    prs, slide = _slide_with()
    sdata = {"type": "content", "title": "某页",
             "points": ["深化智慧普法工程，建成市级法治文化数字化基地，普法触达人次同比增长。",
                        "优化公共法律服务体系，实现乡村实体平台全覆盖，法律顾问指派率达标。"]}
    issue = _filled_page_issue(slide, sdata, SW, SH)
    assert issue, "正文丢失必须报错"


def test_full_body_passes():
    body = "深化智慧普法工程，建成市级法治文化数字化基地，普法触达人次同比增长五十个百分点。"
    prs, slide = _slide_with(body_text=body)
    sdata = {"type": "content", "title": "某页", "points": [body]}
    assert _filled_page_issue(slide, sdata, SW, SH) is None


def test_drawn_chart_exempts():
    # 图表真画出来了：页面有 chart 对象，数据不再按文字量判缺失
    from pptx.chart.data import CategoryChartData
    from pptx.enum.chart import XL_CHART_TYPE
    prs, slide = _slide_with()
    cd = CategoryChartData()
    cd.categories = ["1月", "2月", "3月", "4月"]
    cd.add_series("普法活动人次", (50, 80, 95, 120))
    slide.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Emu(int(SW * .2)), Emu(int(SW * .25)),
                           Emu(int(SW * .6)), Emu(int(SW * .5)), cd)
    sdata = {"type": "data", "title": "核心指标", "points": [],
             "blocks": {"chart": {
                 "kind": "bar", "categories": ["1月", "2月", "3月", "4月"],
                 "series": [{"name": "普法活动人次", "values": [50, 80, 95, 120]}]}}}
    assert _filled_page_issue(slide, sdata, SW, SH) is None


def test_section_and_cover_exempt():
    prs, slide = _slide_with(title="第一部分")
    sdata = {"type": "section", "title": "第一部分", "points": []}
    assert _filled_page_issue(slide, sdata, SW, SH) is None


def test_small_expectation_exempt():
    # 期望文字量很小（<80 字）不做缺失判定，避免误伤短页
    prs, slide = _slide_with()
    sdata = {"type": "data", "title": "小图页", "points": [],
             "blocks": {"chart": {"kind": "bar", "categories": ["1月", "2月"],
                                  "series": [{"name": "量", "values": [1, 2]}]}}}
    assert _filled_page_issue(slide, sdata, SW, SH) is None
