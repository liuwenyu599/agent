"""行为冻结测试：重构后的 ``_layout_score`` 必须与重构前逐分一致。

基准由 tests/_capture_layout_baseline.py 在重构前导出（layout_baseline.json）。
覆盖 LAYOUT_CATALOG 全部版式 × 一组典型 slide，确保选版打分结果不变。
"""
import json
from pathlib import Path

from app.application.ppt.ppt_engine import LAYOUT_CATALOG, _layout_score


def _mk(points=None, blocks=None, has_image=False):
    slide = {"points": points or [], "blocks": blocks or {}}
    if has_image:
        slide["_image"] = {"file_path": "/tmp/fake.png"}
    return slide


_BASE = {
    "empty": _mk(),
    "one_short": _mk(["短句"]),
    "one_long": _mk(["一" * 50]),
    "two_balanced": _mk(["一" * 10, "二" * 10]),
    "two_gap": _mk(["一" * 50, "二" * 5]),
    "three": _mk(["甲", "乙", "丙"]),
    "four_short": _mk(["x", "y", "z", "w"]),
    "four_long": _mk(["x" * 30, "y" * 30, "z" * 30, "w" * 30]),
    "five": _mk(["x"] * 5),
    "image_two": _mk(["一", "二"], has_image=True),
    "quote_match": _mk(["“引用句”", "普通"]),
    "quote_no": _mk(["普通", "文字"]),
    "cards3": _mk(blocks={"cards": [1, 2, 3]}),
    "cards2": _mk(blocks={"cards": [1, 2]}),
    "table3": _mk(blocks={"table": {"rows": [1, 2, 3]}}),
    "timeline4": _mk(blocks={"timeline": [1, 2, 3, 4]}),
    "process5": _mk(blocks={"process": [1, 2, 3, 4, 5]}),
    "sym2_ok": _mk(["一" * 10, "二" * 10]),
    "sym2_bad": _mk(["一" * 10, "二" * 30]),
}


def _expected():
    p = Path(__file__).resolve().parent / "layout_baseline.json"
    return {(d["sid"], d["slide"]): d["score"]
            for d in json.loads(p.read_text(encoding="utf-8"))}


def test_layout_score_matches_frozen_baseline():
    expected = _expected()
    mismatches = []
    for specs in LAYOUT_CATALOG.values():
        for spec in specs:
            sid = spec["id"]
            for key, slide in _BASE.items():
                got = round(_layout_score(spec, slide, recent=[], used={}), 6)
                exp = expected.get((sid, key))
                if exp is None:
                    mismatches.append(f"{sid}/{key}: 基准缺失")
                elif abs(got - exp) > 1e-9:
                    mismatches.append(f"{sid}/{key}: got={got} exp={exp}")
    assert not mismatches, "打分与基准不一致:\n" + "\n".join(mismatches)


def test_unknown_layout_falls_back_to_weight():
    """兜底：未在 _LAYOUT_AFFINITY 声明的版式，仅以 weight 计分（不崩溃、中性）。"""
    spec = {"id": "content.brand_new_variant", "weight": 1.2}
    slide = _mk(["任意", "要点"])
    assert _layout_score(spec, slide, recent=[], used={}) == 1.2
    # 仍受相邻/整篇惩罚影响（与历史无分支版式行为一致）
    assert _layout_score(spec, slide, recent=["content.brand_new_variant"],
                         used={}) == 1.2 - 1.3
