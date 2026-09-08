"""写作任务上下文解析（规则解析，不依赖 LLM，绝不虚构字段）。

从用户自然语言中抽取结构化任务要素；解析不出的字段保持 None，
由 missing_fields 显式列出，交给对话逐步补全。
"""
import re
from datetime import date
from typing import Any, Dict, List, Optional

# 文种关键词（长词优先，避免"总结报告"误判）
DOC_TYPE_KEYWORDS = [
    ("工作总结", ["工作总结", "总结"]),
    ("情况报告", ["情况报告"]),
    ("工作报告", ["工作报告"]),
    ("通知", ["通知"]),
    ("请示", ["请示"]),
    ("报告", ["报告"]),
    ("函", ["函件", "公函", "函"]),
    ("讲话稿", ["讲话稿", "讲话", "发言稿"]),
    ("方案", ["工作方案", "实施方案", "方案"]),
    ("意见", ["指导意见", "实施意见", "意见"]),
    ("通报", ["通报"]),
    ("会议纪要", ["会议纪要", "纪要"]),
]

# 需要文号的概率较高的正式文种（仅用于 missing 提示，不自动开启）
DOCNUM_TYPICAL = {"通知", "请示", "报告", "函", "通报", "意见"}

DOCNUM_RE = re.compile(r"([一-鿿]{2,8})〔\s*(\d{4})\s*〕\s*(\d+)\s*号")
_DOCNUM_PREFIX_STRIP = re.compile(r"^(文号|编号|发文号)?(是|为|：|:)?")
YEAR_RE = re.compile(r"(20\d{2})\s*年(?:度)?")
WORD_COUNT_RE = re.compile(r"(\d{3,5})\s*字")
DATE_RE = re.compile(r"(20\d{2}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日)")

DOCNUM_OFF_RE = re.compile(r"(不需要|不要|不用|无需|不加|去掉|取消).{0,6}文号|文号.{0,4}(不需要|不要|不用|取消|去掉)")
DOCNUM_ON_RE = re.compile(r"(需要|要|加|加上|使用).{0,4}文号|文号.{0,2}(是|为)")
TODAY_DATE_RE = re.compile(r"(使用|用|按).{0,4}今天|今天.{0,2}的?日期|当前日期")

RECIPIENT_RE = re.compile(r"(?:发给|主送|报送|呈报|发送给|提交给|面向)\s*[：:]?([^，。；\n]{2,30})")
AUTHORITY_RE = re.compile(r"(?:以|由|落款是|署名|发文机关是?|单位是?)\s*[：:]?([一-鿿]{2,20}(?:局|厅|部|委|办|所|中心|政府|委员会|办公室))")
TOPIC_ABOUT_RE = re.compile(r"关于(?:开展|加强|做好|规范|推进)?([^，。；的\n]{2,30}?)(?:的)?(通知|请示|报告|方案|意见|通报|函|总结|讲话)")

# 修改意图（相对当前文档），区别于新起草
REVISE_HINTS = ["改", "扩写", "润色", "精简", "缩写", "补充", "增加", "删除", "去掉",
                "调整", "换", "重写", "规范", "详细", "控制", "口吻", "语气", "第二部分",
                "第一部分", "第三部分", "这段", "那段", "这一", "那段", "最后一段", "开头", "结尾"]
DRAFT_HINTS = ["起草", "写一版", "先写", "生成", "出初稿", "开始写", "出稿", "写吧", "先搭", "框架", "提纲"]


def empty_context() -> Dict[str, Any]:
    return {
        "document_type": None,
        "title": None,
        "topic": None,
        "purpose": None,
        "time_range": None,
        "recipient": None,
        "authority": None,
        "key_facts": [],
        "requirements": None,
        "tone": None,
        "word_count_target": None,
        "document_number_enabled": False,
        "document_number": None,
        "document_date": None,
        "signature": None,
        "missing_fields": [],
    }


def parse_message(message: str) -> Dict[str, Any]:
    """从一句话中抽取任务要素增量（只返回识别到的字段）。"""
    msg = message.strip()
    upd: Dict[str, Any] = {}

    for dtype, kws in DOC_TYPE_KEYWORDS:
        if any(k in msg for k in kws):
            upd["document_type"] = dtype
            break

    m = YEAR_RE.search(msg)
    if m:
        upd["time_range"] = f"{m.group(1)}年度" if "度" in msg[m.end()-1:m.end()+1] or "年度" in msg else f"{m.group(1)}年"

    m = TOPIC_ABOUT_RE.search(msg)
    if m:
        upd["topic"] = m.group(1).strip()
    elif upd.get("document_type") and "topic" not in upd:
        # “帮我写一份2026年度司法行政工作总结” → 主题取文种前的修饰语
        m2 = re.search(r"(?:写|起草|拟)(?:一份|个|篇)?([^，。；\n]{2,30}?)("
                       + "|".join(k for _, ks in DOC_TYPE_KEYWORDS for k in ks) + ")", msg)
        if m2:
            t = re.sub(r"^20\d{2}年度?", "", m2.group(1)).strip()
            if t and t not in ("工作", "一个", "一份"):
                upd["topic"] = t

    m = RECIPIENT_RE.search(msg)
    if m:
        upd["recipient"] = m.group(1).strip()

    m = AUTHORITY_RE.search(msg)
    if m:
        upd["authority"] = m.group(1).strip()

    m = DOCNUM_RE.search(msg)
    if m:
        daizi = _DOCNUM_PREFIX_STRIP.sub("", m.group(1))
        upd["document_number_enabled"] = True
        upd["document_number"] = f"{daizi}〔{m.group(2)}〕{m.group(3)}号"
    elif DOCNUM_OFF_RE.search(msg):
        upd["document_number_enabled"] = False
        upd["document_number"] = None
    elif DOCNUM_ON_RE.search(msg):
        upd["document_number_enabled"] = True

    m = DATE_RE.search(msg)
    if m:
        upd["document_date"] = re.sub(r"\s+", "", m.group(1))
    elif TODAY_DATE_RE.search(msg):
        today = date.today()
        upd["document_date"] = f"{today.year}年{today.month}月{today.day}日"

    m = WORD_COUNT_RE.search(msg)
    if m and not re.search(r"第[一二三四五六七八九十0-9]+(部分|段|章)|这段|那段|一段", msg):
        upd["word_count_target"] = int(m.group(1))

    m = re.search(r"主要是([^，。；\n]{2,60})", msg)
    if m:
        facts = [x.strip() for x in re.split(r"[、，,和及]", m.group(1)) if len(x.strip()) >= 2]
        if facts:
            upd["key_facts"] = facts

    if "语气" in msg or "口吻" in msg:
        if "正式" in msg:
            upd["tone"] = "正式"
        elif "口语" in msg or "通俗" in msg:
            upd["tone"] = "通俗"

    return upd


def merge_context(ctx: Dict[str, Any], upd: Dict[str, Any]) -> List[str]:
    """把增量合并进任务上下文，返回可读变更说明。"""
    changes: List[str] = []
    labels = {
        "document_type": "文种", "title": "标题", "topic": "主题",
        "purpose": "用途", "time_range": "时间", "recipient": "主送机关",
        "authority": "发文机关", "requirements": "写作要求", "tone": "语气",
        "word_count_target": "字数目标", "document_number": "文号",
        "document_date": "成文日期",
    }
    for k, v in upd.items():
        if k == "document_number_enabled":
            if ctx.get(k) != v:
                ctx[k] = v
                changes.append("文号：" + ("启用" if v else "不使用"))
            continue
        if v is None:
            continue
        if k == "document_number" and not ctx.get("document_number_enabled"):
            continue
        old = ctx.get(k)
        if old != v:
            ctx[k] = v
            if k in labels:
                changes.append(f"{labels[k]}：{v}")
    return changes


def compute_missing(ctx: Dict[str, Any]) -> List[str]:
    """按文种计算缺失的关键信息（提示追问，不阻塞）。"""
    missing: List[str] = []
    dt = ctx.get("document_type")
    if not dt:
        missing.append("文种（通知/总结/报告/请示…）")
        return missing
    if not ctx.get("topic") and not ctx.get("title"):
        missing.append("主题（关于什么事）")
    if dt == "工作总结":
        if not ctx.get("time_range"):
            missing.append("时间范围（哪个年度/阶段）")
        if not ctx.get("key_facts"):
            missing.append("主要工作内容/年度数据或重点成果")
    else:
        if not ctx.get("recipient"):
            missing.append("主送对象")
        if not ctx.get("authority"):
            missing.append("发文机关（落款单位）")
    if not ctx.get("document_number_enabled") and dt in DOCNUM_TYPICAL:
        pass  # 文号默认关闭属正常状态，不算缺失
    ctx["missing_fields"] = missing
    return missing


def looks_like_revise(message: str) -> bool:
    return any(h in message for h in REVISE_HINTS)


def looks_like_draft(message: str) -> bool:
    return any(h in message for h in DRAFT_HINTS)


def build_title(ctx: Dict[str, Any]) -> Optional[str]:
    """由结构化要素推导标题（仅在要素齐备时）。"""
    if ctx.get("title"):
        return ctx["title"]
    topic = ctx.get("topic")
    dt = ctx.get("document_type")
    tr = ctx.get("time_range")
    if dt == "工作总结" and topic:
        return f"{tr or ''}{topic}工作总结"
    if topic and dt:
        return f"关于{topic}的{dt}"
    return None
