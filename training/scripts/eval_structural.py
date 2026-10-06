#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""非 loss 的结构化验收：判断这个模型「能不能上线」，而不是「loss 降了多少」。

为什么不用 loss
---------------
loss 只能说明「更拟合训练集」，说明不了三件事：

1. 同一份输入生成两次，格式会不会一次有落款一次没有——用户遇到的是后者。
2. 换个文种/换个主送机关，它会不会还是套同一个模板——几百条样本 SFT
   最容易的就是记忆成固定格式，loss 会很好看。
3. 那张 1100 字风格卡到底能不能撤——这才是这次训练真正的目的。

所以这里的三条验收线全部是**结构层面的可观测行为**：

  A. 自洽（self-consistency）  同一输入跑两次，结构必须一致
  B. 敏感（responsiveness）    不同输入，结构必须跟着变（防止塌缩成模板）
  C. 撤卡等价（parity）        有卡/无卡两份输出结构等价 → 风格已进权重，卡可撤

判定办法是把公文压成一组「结构槽位」（标题、主送机关、层级编号序列、
是否落款、成文日期、结语），逐槽位比对算相似度。不看措辞。
措辞本来就该有差别，格式才不应该有差别。

两种跑法
--------
① 离线分析（不需要 GPU，CI 里跑这个）：

    python training/scripts/eval_structural.py \\
        --cases training/data/eval_cases.jsonl

    cases 每行形如：
      {"id":"...", "variant":[{"tag":"run1","output":"..."},
                              {"tag":"run2","output":"..."}],
       "expected_differs_from": "other_case_id"}
    实际更常用的是下面 ② 生成出来的结果文件。

② 连推理服务自己生成再判（本机 8003 或内网 vLLM 都可以）：

    python training/scripts/eval_structural.py \\
        --endpoint http://10.128.85.133:8003/v1 \\
        --model Qwen2.5-14B-Instruct \\
        --prompts training/data/eval_prompts.jsonl \\
        --style-card /path/to/style_card.txt \\
        --save-cases training/data/eval_cases.jsonl

三条线的含义（重要）
--------------------
A、B 通过 + C 不过  → 可以上线，但**别撤卡**，风格还得靠那条 prompt 兜着
A、B、C 全通过      → 可以撤卡（把 WRITING_STYLE_ADAPTER 配上即可）
A 或 B 不过         → 别上线。这个模型会让用户「有时有落款有时没有」

退出码：全通过 0；任何一条不过 1；参数或数据不足无法判 2。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

# ---------------------------------------------------------------- 结构抽取

_LEVEL1 = re.compile(r"^\s*([一二三四五六七八九十]{1,3})[、]")          # 一、xxx
_LEVEL2 = re.compile(r"^\s*[（(]([一二三四五六七八九十]{1,3})[)）]")     # （一）xxx
_LEVEL3 = re.compile(r"^\s*([0-9]{1,2})[.．、]")                        # 1. xxx
_CHINESE_DATE = re.compile(r"([二〇○一二三四五六七八九]{2,6}年\s*[一二〇○十0-9]{1,3}月\s*[一二〇○十0-9]{1,4}日)")
_ARABIC_DATE = re.compile(r"((?:19|20)\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")
_ORG = re.compile(r"([\u4e00-\u9fa5]{2,20}?(?:司法局|人民政府|政法委|司法所|办公室|管理局|委员会|办事处|领导小组))\s*$")
_CLOSING_PHRASE = ("特此通知", "特此报告", "特此函复", "特此请示", "妥否，请批示",
                   "以上报告，请审阅", "以上请示，请批示", "请予审批")
_TITLE_TYPES = ("通知", "报告", "请示", "函", "意见", "批复", "通报", "决定",
                "方案", "纪要", "总结", "答复")
_MARKDOWN = re.compile(r"^[>#*\s`]+")


def _lines(doc: str) -> List[str]:
    out = []
    for raw in (doc or "").splitlines():
        line = _MARKDOWN.sub("", raw).replace("**", "").strip()
        if line:
            out.append(line)
    return out


def _pick_title(lines: Sequence[str]) -> str:
    """公文标题要么独立成行，要么内含「关于…的通知」这种文种尾巴。"""
    for line in lines[:3]:
        if len(line) > 60:
            continue
        if any(t in line for t in _TITLE_TYPES) and "，" not in line:
            return line
    return lines[0][:60] if lines else ""


def _pick_addressee(lines: Sequence[str]) -> str:
    """主送机关形如「各司法所：」，是唯一的顶格+冒号收尾行。"""
    for line in lines[:8]:
        if line.startswith("附件"):
            continue
        if line.endswith("：") or line.endswith(":"):
            body = line.rstrip("：:")
            if 2 <= len(body) <= 40 and "，" not in body:
                return body
    return ""


def _pick_date(lines: Sequence[str]) -> str:
    tail = "\n".join(lines[-5:])
    m = _ARABIC_DATE.search(tail) or _CHINESE_DATE.search(tail)
    return m.group(0) if m else ""


def _pick_org(lines: Sequence[str]) -> str:
    for line in list(reversed(lines[-4:])):
        m = _ORG.search(line)
        if m:
            return m.group(1)
    return ""


def structure_fingerprint(doc: str) -> Dict[str, Any]:
    """把一篇公文压成一组结构槽位。措辞不进 SHAPE，只看格式。"""
    lines = _lines(doc)
    l1, l2, l3 = [], 0, 0
    has_attachment = False
    for line in lines:
        if line.startswith("附件"):
            has_attachment = True
        m1 = _LEVEL1.match(line)
        if m1:
            l1.append(m1.group(1))
            continue
        if _LEVEL2.match(line):
            l2 += 1
            continue
        if _LEVEL3.match(line):
            l3 += 1

    text = "\n".join(lines)
    return {
        "title": _pick_title(lines),
        "addressee": _pick_addressee(lines),
        "level1": l1,
        "level2_count": l2,
        "level3_count": l3,
        "has_attachment": has_attachment,
        "closing_org": _pick_org(lines),
        "closing_date": _pick_date(lines),
        "closing_phrase": next((p for p in _CLOSING_PHRASE if p in text), ""),
        "paragraph_count": len(lines),
    }


# ---------------------------------------------------------------- 结构比对

# 权重说明：层级编号和落款是「格式对不对」的核心，标题/主送是必须跟着输入变的
_WEIGHTS = {
    "level1": 0.24,          # 一级标题序列（一、二、三…有还是没有，几段）
    "addressee": 0.16,       # 主送机关
    "closing_org": 0.16,     # 落款单位
    "closing_date": 0.12,    # 成文日期（用户这次反馈最痛的就是它）
    "closing_phrase": 0.10,  # 结语
    "has_attachment": 0.06,
    "title_type": 0.10,      # 标题里的文种（通知/报告/请示…）
    "shape_bucket": 0.06,    # 篇幅量级，别一篇 300 字一篇 3000 字还算等价
}


def _title_type(title: str) -> str:
    for t in _TITLE_TYPES:
        if t in title:
            return t.strip()
    return ""


def _bucket(n: int) -> str:
    if n <= 4:
        return "极短"
    if n <= 10:
        return "短"
    if n <= 25:
        return "中"
    return "长"


def _same(a: Any, b: Any) -> float:
    if isinstance(a, list):
        return 1.0 if a == b else (0.5 if bool(a) == bool(b) else 0.0)
    if isinstance(a, bool):
        return 1.0 if a == b else 0.0
    if isinstance(a, str):
        return 1.0 if a == b else (0.0 if bool(a) != bool(b) else 0.35)
    return 1.0 if a == b else 0.0


def compare_structure(a: Dict[str, Any], b: Dict[str, Any]) -> Tuple[float, List[str]]:
    """返回 (相似度 0~1, 具体哪些槽位不一样)。"""
    fields = {
        "level1": _same(a["level1"], b["level1"]),
        "addressee": _same(a["addressee"], b["addressee"]),
        "closing_org": _same(a["closing_org"], b["closing_org"]),
        "closing_date": _same(a["closing_date"], b["closing_date"]),
        "closing_phrase": _same(a["closing_phrase"], b["closing_phrase"]),
        "has_attachment": _same(a["has_attachment"], b["has_attachment"]),
        "title_type": _same(_title_type(a["title"]), _title_type(b["title"])),
        "shape_bucket": _same(_bucket(a["paragraph_count"]),
                              _bucket(b["paragraph_count"])),
    }
    score = sum(_WEIGHTS[k] * v for k, v in fields.items())
    diffs = [k for k, v in fields.items() if v < 1.0]
    # 主送、落款、日期是公文的关键槽位。单靠加权平均会让漏掉日期的
    # 文本仍得 0.88，通过默认的 0.85 验收线。
    if any(fields[k] < 1.0 for k in ("addressee", "closing_org", "closing_date")):
        score = min(score, 0.5)
    return round(score, 4), diffs


_FIELD_LABEL = {
    "level1": "一级标题编号",
    "addressee": "主送机关",
    "closing_org": "落款单位",
    "closing_date": "成文日期",
    "closing_phrase": "结语",
    "has_attachment": "附件行",
    "title_type": "标题文种",
    "shape_bucket": "篇幅量级",
}


# ---------------------------------------------------------------- 三条验收线

class Gate:
    def __init__(self, name: str, key: str, threshold: float, hint: str) -> None:
        self.name = name
        self.key = key
        self.threshold = threshold
        self.hint = hint
        self.scores: List[float] = []
        self.failures: List[str] = []

    def add(self, score: float, label: str, detail: str = "") -> None:
        self.scores.append(score)
        if score < self.threshold:
            line = f"    · {label}：{score:.2f}"
            if detail:
                line += f"  [{detail}]"
            self.failures.append(line)

    @property
    def ran(self) -> bool:
        return bool(self.scores)

    @property
    def passed(self) -> bool:
        return self.ran and not self.failures

    def report(self) -> str:
        if not self.ran:
            return f"  {self.name}：— 未跑（数据不足，无法判定）"
        avg = sum(self.scores) / len(self.scores)
        mark = "✅" if self.passed else "❌"
        head = f"  {mark} {self.name}：均值 {avg:.2f} / 阈值 {self.threshold:.2f}" \
               f"（{len(self.scores)} 组）"
        if not self.failures:
            return head
        return head + "\n" + "\n".join(self.failures) + f"\n    → {self.hint}"


# with_card / without_card 是「有卡 / 无卡」两个不同条件，哪怕 case 文件里没写
# condition 字段也不能和 run1/run2 混在一组比。
_TAG_CONDITION = {"with_card": "card", "without_card": "no_card"}


def _condition_of(item: Dict[str, Any]) -> str:
    explicit = item.get("condition")
    if explicit:
        return str(explicit)
    return _TAG_CONDITION.get(item.get("tag", ""), "default")


def gate_a_consistency(cases: List[Dict[str, Any]], threshold: float) -> Gate:
    """同一份输入生成两次，结构必须一致。

    只在同一 condition 内比。with_card / without_card 是**故意不同**的条件，
    把它们和 run1/run2 混在一起比等于拿苹果比橘子，A 线会永远假失败。
    """
    gate = Gate("A 自洽：同一输入两次生成的结构一致", "A", threshold,
                "模型还没学到稳定的格式，继续练，或者提高 target 质量的一致性")
    for case in cases:
        groups: Dict[str, List[Tuple[str, str]]] = {}
        for i, item in enumerate(case.get("variants") or []):
            groups.setdefault(_condition_of(item), []).append(
                (item.get("tag", f"#{i}"), item.get("output", "")))
        for members in groups.values():
            if len(members) < 2:
                continue  # 只生成一次无从判断稳定性，宁可不判
            tags = [m[0] for m in members]
            fps = [structure_fingerprint(m[1]) for m in members]
            worst, diffs = 1.0, []
            for i in range(1, len(fps)):
                score, diff = compare_structure(fps[0], fps[i])
                if score < worst:
                    worst, diffs = score, diff
            missing = [key for key in ("closing_org", "closing_date")
                       if any(not fp[key] for fp in fps)]
            if missing:
                worst = 0.0
                diffs = list(dict.fromkeys(diffs + missing))
            gate.add(worst, f"{case.get('id', '?')} {' vs '.join(tags)}",
                     "、".join(_FIELD_LABEL[d] for d in diffs))
    return gate


def gate_b_responsiveness(cases: List[Dict[str, Any]], threshold: float) -> Gate:
    """不同输入必须产出不同结构——专门抓「loss 很好看但塌缩成模板」。"""
    gate = Gate("B 敏感：换输入结构要跟着变", "B", threshold,
                "疑似塌缩成模板：不同文种/主送机关却套出同样的格式，先查数据是不是只有一种写法")
    by_id = {c.get("id"): c for c in cases}
    for case in cases:
        other_id = case.get("expected_differs_from")
        if not other_id or other_id not in by_id:
            continue
        base_out = ((case.get("variants") or [{}])[0]).get("output", "")
        other_out = ((by_id[other_id].get("variants") or [{}])[0]).get("output", "")
        if not base_out or not other_out:
            continue
        score, _ = compare_structure(structure_fingerprint(base_out),
                                     structure_fingerprint(other_out))
        gate.add(1.0 - score, f"{case.get('id')} 应与 {other_id} 不同（结构差异 {1 - score:.2f}）")
    return gate


def gate_c_parity(cases: List[Dict[str, Any]], threshold: float) -> Gate:
    """有风格卡 / 无风格卡两份输出结构等价 → 风格已经进权重，卡可以撤。"""
    gate = Gate("C 撤卡等价：不带那 1100 字卡也能写出同样的格式", "C", threshold,
                "风格还没进权重，可以先上线但别撤卡（别配 WRITING_STYLE_ADAPTER）")
    for case in cases:
        with_card = next((o.get("output", "") for o in (case.get("variants") or [])
                          if o.get("tag") == "with_card"), "")
        without = next((o.get("output", "") for o in (case.get("variants") or [])
                        if o.get("tag") == "without_card"), "")
        if not with_card or not without:
            continue
        fps = (structure_fingerprint(with_card), structure_fingerprint(without))
        score, diffs = compare_structure(*fps)
        missing = [key for key in ("closing_org", "closing_date")
                   if any(not fp[key] for fp in fps)]
        if missing:
            score = 0.0
            diffs = list(dict.fromkeys(diffs + missing))
        gate.add(score, f"{case.get('id')} 有卡 vs 无卡",
                 "、".join(_FIELD_LABEL[d] for d in diffs))
    return gate


# ---------------------------------------------------------------- 生成（可选）

def _read_jsonl(path: str) -> List[Dict[str, Any]]:
    items = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            items.append(json.loads(line))
    return items


def generate_cases(endpoint: str, model: str, prompts_path: str,
                   style_card_path: Optional[str], repeat: int,
                   temperature: float, max_tokens: int,
                   api_key: str = "") -> List[Dict[str, Any]]:
    """对着推理服务跑一批用例。没装 openai 包就给出明确报错，不要静默退化。"""
    try:
        from openai import OpenAI
    except ImportError:
        raise SystemExit("[生成] 需要 openai 包：pip install openai\n"
                         "      只想离线分析已有结果的话用 --cases，不需要这个依赖。")

    prompts = _read_jsonl(prompts_path)
    card = Path(style_card_path).read_text(encoding="utf-8") if style_card_path else ""
    client = OpenAI(base_url=endpoint, api_key=api_key or "EMPTY")

    def ask(system: str, user: str) -> str:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return resp.choices[0].message.content or ""

    cases = []
    for item in prompts:
        prompt = item.get("prompt") or item.get("instruction") or ""
        if not prompt:
            continue
        variants = [{"tag": f"run{i + 1}", "condition": "default",
                     "output": ask("", prompt)}
                    for i in range(repeat)]
        base = item.get("system") or ""
        if card:
            variants.append({"tag": "with_card", "condition": "card",
                             "output": ask(base + card, prompt)})
            variants.append({"tag": "without_card", "condition": "no_card",
                             "output": ask(base, prompt)})
        cases.append({
            "id": item.get("id") or f"case-{len(cases) + 1}",
            "prompt": prompt,
            "variants": variants,
            "expected_differs_from": item.get("expected_differs_from", ""),
        })
        print(f"[生成] {cases[-1]['id']} 完成")
    return cases


# ---------------------------------------------------------------- 入口

def evaluate(cases: List[Dict[str, Any]], thresholds: Dict[str, float]) -> Tuple[List[Gate], str]:
    gates = [
        gate_a_consistency(cases, thresholds["A"]),
        gate_b_responsiveness(cases, thresholds["B"]),
        gate_c_parity(cases, thresholds["C"]),
    ]
    ran = [g for g in gates if g.ran]
    if not ran:
        return gates, "没有任何一条验收线跑起来——数据不足，无法判断能否上线。"
    passed = [g.key for g in ran if g.passed]
    failed = [g.key for g in ran if not g.passed]

    if not failed:
        if len(ran) < len(gates):
            missing = "、".join(g.key for g in gates if not g.ran)
            verdict = (f"⚠ {'、'.join(passed)} 已通过，但 {missing} 未跑；"
                       "尚不能判定整体达标，也不能据此撤卡。")
        else:
            verdict = ("✅ A、B、C 全部通过 —— 风格已经进权重，可以配 "
                       "WRITING_STYLE_ADAPTER 把那张 1100 字风格卡撤掉。")
    elif "A" in failed or "B" in failed:
        blocked = "、".join(failed)
        verdict = (f"❌ {blocked} 未通过 —— 先别上线。"
                   "A 不过说明格式还不稳定（用户会遇到有时有落款有时没有）；"
                   "B 不过说明塌缩成模板了，换文种也套同一个壳。")
    else:
        online = "A、B 都过了，可以上线" if {"A", "B"} <= set(passed) else "看 A/B 结果决定是否上线"
        verdict = (f"⚠ {online}；但 C 不过 —— 风格还没进权重，**先别撤卡**，"
                   "那 1100 字 prompt 还得继续兜着（别配 WRITING_STYLE_ADAPTER）。")
    return gates, verdict


def main() -> int:
    parser = argparse.ArgumentParser(
        description="非 loss 的结构化验收：自洽 / 敏感 / 撤卡等价")
    parser.add_argument("--cases", help="已有结果文件（JSONL）")
    parser.add_argument("--endpoint", help="推理服务地址，如 http://10.128.85.133:8003/v1")
    parser.add_argument("--model", default="Qwen2.5-14B-Instruct")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--prompts", help="提示词文件（JSONL），配 --endpoint 用")
    parser.add_argument("--style-card", help="风格卡文本，用于跑 C 线")
    parser.add_argument("--repeat", type=int, default=2, help="每条输入重复生成几次（A 线）")
    parser.add_argument("--temperature", type=float, default=0.7)
    parser.add_argument("--max-tokens", type=int, default=2048)
    parser.add_argument("--save-cases", help="把生成结果存下来，供下次离线复跑")
    parser.add_argument("--threshold-a", type=float, default=0.85)
    parser.add_argument("--threshold-b", type=float, default=0.30,
                        help="B 线期望「不同」，这里设的是差异度的下限")
    parser.add_argument("--threshold-c", type=float, default=0.85)
    parser.add_argument("--json", dest="json_out", help="把报告写成 JSON")
    args = parser.parse_args()

    if args.endpoint:
        if not args.prompts:
            print("[错误] 用 --endpoint 生成时必须给 --prompts", file=sys.stderr)
            return 2
        cases = generate_cases(args.endpoint, args.model, args.prompts,
                               args.style_card, args.repeat,
                               args.temperature, args.max_tokens, args.api_key)
        if args.save_cases:
            Path(args.save_cases).write_text(
                "\n".join(json.dumps(c, ensure_ascii=False) for c in cases),
                encoding="utf-8")
            print(f"[生成] 已存到 {args.save_cases}")
    elif args.cases:
        cases = _read_jsonl(args.cases)
    else:
        print("[错误] 二选一：--cases（离线分析）或 --endpoint + --prompts（先生成再分析）",
              file=sys.stderr)
        return 2

    thresholds = {"A": args.threshold_a, "B": args.threshold_b, "C": args.threshold_c}
    gates, verdict = evaluate(cases, thresholds)

    print("\n" + "=" * 60)
    print(f"结构化验收  用例 {len(cases)} 组")
    print("=" * 60)
    for gate in gates:
        print(gate.report())
    print("-" * 60)
    print(verdict)
    print("=" * 60)

    if args.json_out:
        Path(args.json_out).write_text(json.dumps({
            "cases": len(cases),
            "gates": [{"key": g.key, "name": g.name, "ran": g.ran,
                       "passed": g.passed,
                       "avg": round(sum(g.scores) / len(g.scores), 4) if g.scores else None,
                       "failures": g.failures} for g in gates],
            "verdict": verdict,
        }, ensure_ascii=False, indent=2), encoding="utf-8")

    return 0 if all(g.passed for g in gates) else 1


if __name__ == "__main__":
    sys.exit(main())
