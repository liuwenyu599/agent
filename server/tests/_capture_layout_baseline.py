"""一次性脚本：冻结当前 _layout_score 的打分基准（重构前跑一次）。

遍历 LAYOUT_CATALOG 全部版式 × 一组典型 slide，把 (sid, slide_key, score) 导出 JSON。
重构后由 test_layout_score_characterization.py 读同一份逻辑重新计算并比对。
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.application.ppt.ppt_engine import LAYOUT_CATALOG, _layout_score, _slide_has_image  # noqa


def mk(points=None, blocks=None, has_image=False):
    slide = {"points": points or [], "blocks": blocks or {}}
    if has_image:
        slide["_image"] = {"file_path": "/tmp/fake.png"}
    return slide


# 一组覆盖各分支条件的典型 slide
BASE = {
    "empty": mk(),
    "one_short": mk(["短句"]),                       # n=1, total=2
    "one_long": mk(["一" * 50]),                     # n=1, total=50
    "two_balanced": mk(["一" * 10, "二" * 10]),       # n=2 等长
    "two_gap": mk(["一" * 50, "二" * 5]),            # n=2 大差
    "three": mk(["甲", "乙", "丙"]),                  # n=3
    "four_short": mk(["x", "y", "z", "w"]),          # n=4 短
    "four_long": mk(["x" * 30, "y" * 30, "z" * 30, "w" * 30]),  # n=4 长
    "five": mk(["x"] * 5),                           # n=5
    "image_two": mk(["一", "二"], has_image=True),    # 有图 n=2
    "quote_match": mk(["“引用句”", "普通"]),          # 以引号开头
    "quote_no": mk(["普通", "文字"]),                 # 无引号
    "cards3": mk(blocks={"cards": [1, 2, 3]}),       # 3 卡
    "cards2": mk(blocks={"cards": [1, 2]}),          # 2 卡
    "table3": mk(blocks={"table": {"rows": [1, 2, 3]}}),  # 3 行
    "timeline4": mk(blocks={"timeline": [1, 2, 3, 4]}),   # 4 节点
    "process5": mk(blocks={"process": [1, 2, 3, 4, 5]}),  # 5 步
    "sym2_ok": mk(["一" * 10, "二" * 10]),           # 对称 n=2 平衡
    "sym2_bad": mk(["一" * 10, "二" * 30]),          # 对称 n=2 不平衡
}


def main():
    out = []
    for stype, specs in LAYOUT_CATALOG.items():
        for spec in specs:
            sid = spec["id"]
            for key, slide in BASE.items():
                score = _layout_score(spec, slide, recent=[], used={})
                out.append({"sid": sid, "slide": key, "score": round(score, 6)})
    Path(sys.argv[1] if len(sys.argv) > 1 else "layout_baseline.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=0), encoding="utf-8")
    print(f"baseline entries: {len(out)} -> layout_baseline.json")


if __name__ == "__main__":
    main()
