"""生成质量门：公文结构 + 硬伤检测。

规则全部来自 V1.2/V1.3 验收验证过的实现：
- 硬伤（level D）：占位符、提纲式退化、退化循环、机械重复、截断、乱码
- 待完善（level B）：结构缺失、偏短、相关性弱
- A：结构完整无硬伤，可直接使用
"""
import re
from typing import Any, Dict, List, Optional

from app.application.writing.postprocessor import (
    detect_degeneration,
    detect_garbled,
    detect_outline_degeneration,
    detect_placeholders,
    detect_repetition,
    detect_truncation,
)
from app.application.writing.section_policy import brief_length_range, is_speech_type

MIN_BODY_CHARS = 800


class QualityGate:
    """对（已后处理的）生成稿做自动质量检查。"""

    def evaluate(
        self, text: str, topic: Optional[str] = None, *,
        body_only: bool = False, document_type: str = "",
        word_count_target: Optional[int] = None,
    ) -> Dict[str, Any]:
        critical: List[str] = []
        review: List[str] = []

        ph = detect_placeholders(text)
        if ph:
            critical.append(f"占位符：{ph[:3]}")

        # 提纲式退化：只有章节骨架、正文被「略」式说明顶替，
        # 是反虚构规则过度约束时的典型退化，按硬伤处理（触发自动重写）
        od = detect_outline_degeneration(text)
        if od:
            critical.append(f"提纲式退化：{od}")

        dg = detect_degeneration(text)
        if dg:
            critical.append(f"退化循环：{dg}")

        rp = detect_repetition(text)
        if rp:
            critical.append(rp)

        tr = detect_truncation(text)
        if tr:
            critical.append(f"截断：{tr}")

        gb = detect_garbled(text)
        if gb:
            critical.append(f"乱码：{gb}")

        # 结构完整性
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        if not lines:
            critical.append("空输出")
        elif not body_only:
            first = lines[0]
            if not (4 <= len(first) <= 60 and not first.endswith("。")):
                review.append("缺少规范标题行")
            head = "\n".join(lines)[:800]
            if not any(
                l.endswith("：") and 2 <= len(l) <= 60
                for l in head.split("\n")
            ):
                review.append("缺少主送机关")
            if not any(
                re.search(r"(政府|办公厅|办公室|委员会|局|厅|部|署)$", l)
                and len(l) <= 30
                for l in lines
            ):
                review.append("缺少落款单位")
            if not re.search(
                r"20\d{2}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日", text
            ):
                review.append("缺少成文日期")

        char_count = len(re.sub(r"\s+", "", text))
        brief = brief_length_range(document_type)
        min_chars = MIN_BODY_CHARS
        if "函" in document_type:
            min_chars = 200
        # 讲话类（致辞/讲话/发言/主持词）体裁天生短，且用户往往不给字数。
        # 用 800 这个「报告级」下限去卡它，会把一篇合适的 600 字会前表态
        # 判成"偏短"——而偏短本是 B 级提示，不该在这种文种上无端触发。
        elif is_speech_type(document_type):
            min_chars = 300
        elif brief:
            # 通知/请示/批复同理：一文一事，500 字可能是完全合格的稿子。
            min_chars = brief[0]
        if word_count_target:
            min_chars = max(100, int(word_count_target * 0.8))
        if char_count < min_chars:
            review.append(f"正文偏短（{char_count} 字 < {min_chars}）")
        if word_count_target and char_count > int(word_count_target * 1.3):
            review.append(f"正文偏长（{char_count} 字 > 目标 {word_count_target} 字的 130%）")
        elif brief and char_count > int(brief[1] * 1.3):
            # 未指定字数时按文种惯例区间判长：通知写到 1000+ 属于把通知
            # 写成了年度方案，提示改用可核对的成果口径压缩。
            review.append(
                f"正文偏长（{char_count} 字，{document_type}通常 {brief[0]}-{brief[1]} 字）"
            )

        # 主题相关性：主题词至少出现 2 次
        if topic and not body_only:
            topic_key = re.sub(r"[的地得了呢吧啊哦呀么吗？?！!，,。.、\s]", "",
                               topic)
            hits = 0
            for size in (2, 3, 4):
                for i in range(0, max(len(topic_key) - size + 1, 0)):
                    gram = topic_key[i:i + size]
                    if gram and gram in text:
                        hits += 1
                        break
            if topic_key and topic_key not in text and hits == 0:
                review.append("主题相关性弱")

        if critical:
            level = "D"
        elif review:
            level = "B"
        else:
            level = "A"

        issues = [
            {"source": "quality", "severity": "critical", "message": m}
            for m in critical
        ] + [
            {"source": "quality", "severity": "review", "message": m}
            for m in review
        ]
        return {
            "passed": level != "D",
            "level": level,
            "char_count": char_count,
            "issues": issues,
        }


def merge_level(*levels: str) -> str:
    rank = {"A": 0, "B": 1, "D": 2}
    return max(levels, key=lambda l: rank.get(l, 0), default="B")
