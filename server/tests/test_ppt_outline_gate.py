"""确定性大纲闸的离线单测：不调模型、不碰 client/DB。"""
from __future__ import annotations

import json

from app.application.ppt import outline_gate
from app.application.ppt.service import PPTService


def _codes(report):
    return {item["code"] for item in report["issues"]}


def _content_page(index: int, layout=None):
    return {
        "type": "content",
        "title": f"第{index}部分工作进展",
        "points": [
            "全年办结法律援助案件并逐案回访",
            "完成人民调解员业务培训与考核",
            "推进公共法律服务站点规范化建设",
        ],
        "layout": layout,
    }


def test_homogeneous_twelve_pages_are_flagged() -> None:
    outline = {"title": "年度工作汇报", "slides": [_content_page(i) for i in range(1, 13)]}
    report = outline_gate.audit_outline(outline, "")
    codes = _codes(report)
    assert "repeated_shape_run" in codes
    assert "content_ratio_high" in codes
    assert report["stats"]["longest_shape_run"] == 12
    assert report["stats"]["content_ratio"] == 1.0
    # 规则层不删页、不改要点文字。
    assert len(report["outline"]["slides"]) == 12
    assert report["outline"]["slides"][0]["points"] == outline["slides"][0]["points"]


def test_mixed_structure_outline_has_no_diversity_warning() -> None:
    slides = [
        {"type": "cover", "title": "年度工作汇报", "points": []},
        {"type": "toc", "title": "目录", "points": ["一", "二", "三"]},
        {"type": "content", "title": "总体情况", "points": ["完成全部既定任务"]},
        {"type": "data", "title": "核心指标",
         "blocks": {"cards": [{"label": "办结", "value": "1234"}]}},
        {"type": "chart", "title": "趋势",
         "blocks": {"chart": {"categories": ["一月", "二月"],
                              "series": [{"name": "数量", "values": [1, 2]}]}}},
        {"type": "timeline", "title": "阶段安排",
         "blocks": {"timeline": [{"time": "1月", "text": "启动"}]}},
        {"type": "closing", "title": "谢谢聆听", "points": []},
    ]
    report = outline_gate.audit_outline({"title": "t", "slides": slides}, "")
    assert "repeated_shape_run" not in _codes(report)
    assert "content_ratio_high" not in _codes(report)
    assert "no_cover" not in _codes(report)
    assert "no_closing" not in _codes(report)
    assert report["stats"]["has_structure_page"] is True


def test_invalid_explicit_layout_is_cleared_without_touching_content() -> None:
    slide = _content_page(1, layout="content.three_cards")
    slide["points"] = ["一是完善工作机制", "二是压实工作责任"]  # 只有 2 条
    report = outline_gate.audit_outline({"title": "t", "slides": [slide]}, "")
    assert "unsupported_layout_cleared" in _codes(report)
    result = report["outline"]["slides"][0]
    assert result["layout"] is None
    assert result["points"] == slide["points"]
    assert result["title"] == slide["title"]


def test_locked_layout_is_never_cleared() -> None:
    slide = _content_page(1, layout="content.three_cards")
    slide["points"] = ["一是完善工作机制", "二是压实工作责任"]
    slide["layout_locked"] = True
    report = outline_gate.audit_outline({"title": "t", "slides": [slide]}, "")
    assert "unsupported_layout_cleared" not in _codes(report)
    assert report["outline"]["slides"][0]["layout"] == "content.three_cards"


def test_quote_layout_requires_an_actual_quotation() -> None:
    slide = {"type": "content", "title": "工作要求",
             "points": ["全面推进依法治理"], "layout": "quote"}
    report = outline_gate.audit_outline({"title": "t", "slides": [slide]}, "")
    assert "unsupported_layout_cleared" in _codes(report)
    assert report["outline"]["slides"][0]["layout"] is None


def test_material_numbers_without_data_page_are_flagged() -> None:
    material = ("2026年办结案件 1234 件，同比增长 12%，调解成功率 98.5%，"
                "覆盖率 90%，办结率 95%。")
    outline = {"title": "t", "slides": [_content_page(i) for i in range(1, 4)]}
    report = outline_gate.audit_outline(outline, material)
    assert "missing_data_page" in _codes(report)
    assert report["stats"]["material_number_hits"] >= 3


def test_boilerplate_and_duplicate_title_are_flagged() -> None:
    slides = [
        {"type": "content", "title": "重点工作推进情况",
         "points": ["加强领导，高度重视", "完成站点建设"]},
        {"type": "content", "title": "重点工作推进情况",
         "points": ["开展业务培训", "完善工作台账"]},
    ]
    report = outline_gate.audit_outline({"title": "t", "slides": slides}, "")
    assert "boilerplate" in _codes(report)
    assert "duplicate_title" in _codes(report)


def test_summary_for_prompt_is_actionable_and_bounded() -> None:
    report = outline_gate.audit_outline(
        {"title": "t", "slides": [_content_page(i) for i in range(1, 13)]}, "")
    text = outline_gate.summary_for_prompt(report)
    assert "确定性结构检查" in text
    assert "只修正被点名的页" in text
    assert len(text.splitlines()) <= 14


def test_model_review_receives_rule_diagnostics(monkeypatch) -> None:
    """规则诊断必须进入模型审查 prompt，且模型判「无需修正」时不回滚规则修复。"""
    seen = {}

    class ReviewingAssistant:
        def complete(self, messages, **kwargs):
            seen["prompt"] = messages[0]["content"]
            return json.dumps({"needs_fix": False, "issues": [], "outline": {}})

    monkeypatch.setattr(PPTService, "_ppt_assistant",
                        lambda self: ReviewingAssistant())
    svc = object.__new__(PPTService)
    slide = _content_page(1, layout="statement")
    out = svc._audit_and_repair_outline(
        {"title": "t", "slides": [slide]}, target_count=None, content="")
    assert "确定性结构检查" in seen["prompt"]
    assert "已清除不匹配的版式" in seen["prompt"]
    assert out["slides"][0]["layout"] is None


def test_model_failure_still_keeps_rule_layer_fix(monkeypatch) -> None:
    """模型审查不可用时不静默退回原始大纲：规则层清掉的坏 layout 必须保留。"""

    class OfflineAssistant:
        def complete(self, *args, **kwargs):
            raise RuntimeError("model offline")

    monkeypatch.setattr(PPTService, "_ppt_assistant",
                        lambda self: OfflineAssistant())
    svc = object.__new__(PPTService)
    slide = _content_page(1, layout="statement")  # 3 条要点，明显不匹配
    out = svc._audit_and_repair_outline(
        {"title": "t", "slides": [slide]}, target_count=None, content="")
    assert out["slides"][0]["layout"] is None
    assert out["slides"][0]["points"] == slide["points"]


# ---- 2026-11-09 真实验收：脱敏材料产出「XXXX 件」大字卡 + 无来源案例 ----

def _real_world_outline():
    return {
        "title": "2026年度司法行政工作总结",
        "slides": [
            {"type": "cover", "title": "2026年度司法行政工作总结",
             "subtitle": "XX市/县司法局 | 2026年11月", "points": []},
            {"type": "data", "title": "2026年度核心业务数据概览", "points": [],
             "blocks": {"cards": [
                 {"label": "调解纠纷总数", "value": "XXXX 件"},
                 {"label": "普法活动场次", "value": "XXX 场"},
                 {"label": "法律援助案件", "value": "XXX 件"},
                 {"label": "社区矫正对象", "value": "XXX 人"},
             ]}},
            {"type": "content", "title": "多元化解机制实战成效",
             "points": ["启动警调+诉调联动机制，3日内达成和解协议。"]},
        ],
    }


def test_placeholder_cards_and_unsourced_case_are_flagged() -> None:
    outline = _real_world_outline()
    report = outline_gate.audit_outline(outline, "")
    codes = _codes(report)
    assert "placeholder_value" in codes
    assert "unsourced_specific" in codes
    assert report["stats"]["placeholder_pages"] >= 2
    assert report["stats"]["unsourced_pages"] >= 1
    # 规则层只诊断：不删卡、不改要点、不改标题。
    result = report["outline"]["slides"]
    assert len(result[1]["blocks"]["cards"]) == 4
    assert result[1]["blocks"]["cards"][0]["value"] == "XXXX 件"
    assert result[2]["points"] == outline["slides"][2]["points"]


def test_sourced_numbers_do_not_trigger_unsourced_warning() -> None:
    outline = _real_world_outline()
    outline["slides"][2]["sources"] = ["司法行政工作总结（2026）"]
    report = outline_gate.audit_outline(outline, "")
    assert "unsourced_specific" not in _codes(report)
    assert "placeholder_value" in _codes(report)


def test_render_never_prints_placeholder_kpi_cards() -> None:
    """渲染层兜底：占位数值不放大成大字，明确显示「数据待填」。"""
    import io
    from pptx import Presentation
    from app.application.ppt import ppt_engine

    outline = ppt_engine.normalize_outline(
        {"title": "t", "slides": [
            {"type": "cover", "title": "t", "subtitle": "", "points": []},
            _real_world_outline()["slides"][1],
            {"type": "closing", "title": "谢谢聆听", "points": []},
        ]}, require_bookends=False)
    warnings = []
    data = ppt_engine.render_pptx(
        outline, ppt_engine.template_to_dict(ppt_engine.BUILTIN_TEMPLATES[0]),
        warnings=warnings, adaptive=True)
    prs = Presentation(io.BytesIO(data))
    texts = "\n".join(shape.text for slide in prs.slides
                      for shape in slide.shapes if shape.has_text_frame)
    assert "XXXX" not in texts
    assert "数据待填" in texts
    assert any("占位" in item for item in warnings)


def test_section_layouts_rotate_when_template_has_static_preference() -> None:
    """4 个章节页不能全用同一个静态偏好版式。"""
    from app.application.ppt import ppt_engine

    used = {}
    chosen = []
    for _ in range(4):
        layout = ppt_engine.choose_layout(
            {"type": "section", "title": "章节", "points": []},
            {"section": "section.side"}, used=used)
        chosen.append(layout)
        used[layout] = used.get(layout, 0) + 1
    # 装饰页按页面内容指纹确定性换版：首个章节页也不再被模板静态偏好锁死；
    # 同一页在成稿 / 预览 / 复检里必须得到同一个结果（指纹只取 slide 自身字段）。
    assert len(set(chosen)) >= 2
    same = {"type": "section", "title": "章节", "points": []}
    assert (ppt_engine.choose_layout(same, {"section": "section.side"}) ==
            ppt_engine.choose_layout(dict(same), {"section": "section.side"}))
