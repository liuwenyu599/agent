"""文种分类与分节骨架的单一来源。

此前「讲话类文种」元组在 sectioned / task_service / quality_gate / grounded 各写一份，
``_DEFAULT_SECTIONS`` 也只活在分节服务里；改一处忘一处就会出现「测试验的骨架和生产
跑的骨架不是一套」。所有按文种判断的地方统一从这里取。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

# 现场宣读类文种：致辞、讲话、发言、主持词。它们按自然段推进，不套公文小标题。
SPEECH_KINDS: tuple[str, ...] = ("致辞", "讲话", "发言", "主持词")

# 需要按章节分别检索、生成的长篇文种。
LONG_DOC_TYPES = {
    "报告", "工作报告", "工作情况报告", "工作总结", "总结", "方案", "实施方案",
    "工作方案", "调研报告",
}

# 事务性公文（一事一文）的常规正文篇幅，单位：字，不含标题/主送/落款/日期。
# 用户不指定字数时，模型对「通知」没有任何篇幅锚点，会按训练语料里的长篇模板
# 铺成年度方案（实测 35B 常出 1000+ 字）。这里给出文种惯例区间作为锚点，
# 让「能合并的事项不拆分、说清即收束」成为默认行为，而不是等用户来纠。
# 只收录短篇事务文种；报告、方案、总结等长篇文种不设默认，保持自由篇幅。
BRIEF_LENGTH_RANGES: Dict[str, Tuple[int, int]] = {
    "通知": (450, 650),
    "请示": (400, 600),
    "批复": (300, 500),
    "通报": (500, 800),
    "会议纪要": (600, 900),
    "纪要": (600, 900),
}


def brief_length_range(document_type: str) -> Optional[Tuple[int, int]]:
    """事务性公文的常规篇幅区间；长篇文种或未知文种返回 None（不擅自限长）。"""
    dt = (document_type or "").strip()
    if not dt or dt in LONG_DOC_TYPES:
        return None
    for key, rng in BRIEF_LENGTH_RANGES.items():
        if key in dt:
            return rng
    return None


# 分节计划模型不可用时的确定性兜底骨架。heading 一律为空：不硬塞报告式小标题，
# 只声明「本节写什么」，层次交给模型按文种体例决定。
DEFAULT_SECTIONS: Dict[str, List[tuple[str, str]]] = {
    "讲话稿": [
        ("", "面向听众自然开场，点明活动场合、主题和来宾，表达欢迎或感谢"),
        ("", "结合本次主题说明背景、意义和与听众有关的实际经历"),
        ("", "围绕主题谈具体体会、共同愿景或倡议，保持现场讲话语气"),
        ("", "自然收束，表达祝愿、感谢或期待，适合现场口头宣读"),
    ],
    "主持词": [
        ("", "宣布会议开始，说明会议名称、时间和参加人员"),
        ("", "按议程串联各环节，介绍发言单位和议题"),
        ("", "小结会议成效并提出贯彻要求，自然收束"),
    ],
    "工作总结": [
        ("一、工作开展情况", "概括阶段工作主线、推进过程和主要完成情况"),
        ("二、主要做法和成效", "按重点工作提炼做法、机制和有依据的成效"),
        ("三、存在问题", "客观分析短板及原因，不虚构问题数据"),
        ("四、下一步工作安排", "结合问题提出具体、可执行的后续举措"),
    ],
    "报告": [
        ("一、基本情况", "交代背景、范围和总体情况"),
        ("二、主要工作情况", "展开工作过程、主要做法和有依据的成效"),
        ("三、存在问题", "归纳当前问题和制约因素"),
        ("四、下一步工作", "提出下一阶段具体工作安排"),
    ],
    "方案": [
        ("一、总体要求", "说明工作目标、原则和总体安排"),
        ("二、主要任务", "分层展开核心任务和具体举措"),
        ("三、实施步骤", "明确阶段安排、时间逻辑和推进方式"),
        ("四、保障措施", "明确责任、协同、督导和风险控制"),
    ],
}


def is_speech_type(document_type: str) -> bool:
    """该文种是否属于现场宣读类（致辞/讲话/发言/主持词）。"""
    return any(kind in (document_type or "") for kind in SPEECH_KINDS)


def needs_sectioning(document_type: str, word_count_target: int = 0) -> bool:
    """是否走分节生成：长篇材料默认分节，讲话类只在篇幅够长时分节。"""
    target = int(word_count_target or 0)
    if is_speech_type(document_type):
        # 短篇现场材料用带文种约束的单次起草，避免先等一次完整 JSON 章节规划；
        # 未给字数时沿用长篇路径，避免把用户期望的完整讲话压成短稿。
        return target == 0 or target > 1200
    return (document_type or "") in LONG_DOC_TYPES and (target >= 1800 or target == 0)


def default_section_plan(document_type: str, word_count_target: int = 0) -> List[Dict[str, Any]]:
    """模型规划失败时的兜底分节计划；无法匹配文种时返回空（不硬塞报告骨架）。"""
    if "主持词" in document_type:
        key = "主持词"
    elif is_speech_type(document_type):
        key = "讲话稿"
    elif "方案" in document_type:
        key = "方案"
    elif "总结" in document_type:
        key = "工作总结"
    elif document_type in LONG_DOC_TYPES:
        key = "报告"
    else:
        return []
    items = DEFAULT_SECTIONS[key]
    total = int(word_count_target or 2200)
    # 短稿不该被硬拆成 4 节：800 字发言稿分 4 节每节只有 200 字，切得太碎反而破坏
    # 「连续行文」的连贯感（讲话是顺着讲的，不是分段念的）。讲话类短稿缩到 3 节。
    if key in ("讲话稿", "主持词") and total < 1200:
        items = items[:3]
    # 下限不用固定 350：短稿分 3~4 节时 350×N 会把全文强行拉长近一倍，产出水文。
    # 取 min(350, 平均的一半)，保证下限不超过实际平均。
    per = max(min(350, total // len(items) // 2), total // len(items))
    return [
        {"heading": "", "focus": focus, "target_chars": per}
        for _heading, focus in items
    ]
