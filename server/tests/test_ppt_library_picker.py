"""图库学习模板自动选版（pick_library_template）的纯函数契约。"""
from app.application.ppt.ppt_engine import pick_library_template


def _row(name: str, layouts: int = 20, types=None, use: int = 0) -> dict:
    return {
        "id": f"tpl-{name}", "name": name, "category": "通用",
        "layout_library": [
            {"id": f"l{i}", "detected_type": t} for i, t in enumerate(types or
             ["cover", "toc", "content", "cards", "content_image", "two_col",
              "data", "closing"])
        ][:layouts] if layouts else [],
        "use_count": use, "is_official": True,
    }


def _rows(*names, **kw):
    return [_row(n, **kw) for n in names]


def test_hit_maps_topic_to_matching_library_template():
    rows = _rows("党课党建工作汇报", "大气部门年终工作总结")
    assert pick_library_template(
        rows, topic="党建引领基层治理专题党课") == "tpl-党课党建工作汇报"
    assert pick_library_template(
        rows, topic="司法局年度工作总结") == "tpl-大气部门年终工作总结"


def test_topic_scoring_beats_single_keyword_group():
    # 「司法」(普法组1词) 不敌「年度+总结+工作计划」(总结组3词)
    rows = _rows("法律法规司法普法教育宣传通用PPT模板", "大气部门年终工作总结")
    assert pick_library_template(
        rows, topic="司法局年度工作总结及下一步计划") == "tpl-大气部门年终工作总结"


def test_no_match_falls_back_to_builtin():
    rows = _rows("党课党建工作汇报")
    assert pick_library_template(rows, topic="一份普通材料") is None


def test_structural_gate_excludes_incomplete_templates():
    # 缺 toc → 结构不合格，即使主题命中也不选
    no_toc = _row("党课党建工作汇报",
                  types=["cover", "content", "cards", "content_image",
                         "data", "two_col", "section", "closing"])
    assert pick_library_template([no_toc], topic="党课") is None
    # 版式太少同样排除
    assert pick_library_template(
        [_row("党课党建工作汇报", layouts=5)], topic="党课") is None


def test_review_template_excluded_warn_downweighted():
    # REVIEW 套名字关键词最多但被排除；同组 PASS 套胜出
    rows = _rows("法律法规司法普法教育宣传通用PPT模板", "食品安全法实施条例")
    assert pick_library_template(
        rows, topic="普法教育宣传活动") == "tpl-食品安全法实施条例"


def test_pass_preferred_over_warn_on_tie():
    # 主题只命中「普法」时，PASS 套与 WARN 套同为 0 分 → WARN 扣 1 分让位
    rows = _rows("食品安全法实施条例", "中国首部民法典解读")
    assert pick_library_template(
        rows, topic="普法进校园活动方案") == "tpl-食品安全法实施条例"


def test_empty_or_missing_library_returns_none():
    assert pick_library_template([], topic="党课") is None
    assert pick_library_template([_row("党课党建工作汇报", layouts=0)],
                                 topic="党课") is None
