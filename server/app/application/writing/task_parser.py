"""写作任务上下文解析（规则解析，不依赖 LLM，绝不虚构字段）。

从用户自然语言中抽取结构化任务要素；解析不出的事实字段保持 None。
missing_fields 仅供提示补充，不阻断一句话直接起草。
"""
import re
from typing import Any, Dict, List, Optional

from app.core.timeutil import now_local

# 文种关键词（长词优先，避免"总结报告"误判）
DOC_TYPE_KEYWORDS = [
    ("工作总结", ["工作总结", "总结"]),
    ("情况报告", ["情况报告"]),
    ("工作报告", ["工作报告"]),
    ("通知", ["通知"]),
    ("请示", ["请示"]),
    ("报告", ["报告"]),
    ("函", ["函件", "公函", "函"]),
    ("致辞稿", ["致辞稿", "致辞"]),
    ("讲话稿", ["讲话稿", "讲话", "发言稿", "发言"]),
    ("方案", ["工作方案", "实施方案", "方案"]),
    ("意见", ["指导意见", "实施意见", "意见"]),
    ("通报", ["通报"]),
    ("会议纪要", ["会议纪要", "纪要"]),
]
FORMAL_DOC_TYPES = {"通知", "请示", "报告", "情况报告", "工作报告", "函", "方案", "意见", "通报"}


def explicit_document_type(message: str) -> Optional[str]:
    """Only override model genre when the user names a known form as the requested output.

    A keyword inside a topic (e.g. 方案 in '方案发布会新闻稿') is not the genre.
    Unknown forms remain the model's decision instead of being coerced into this list.
    """
    message = (message or "").strip()
    for dtype, keywords in DOC_TYPE_KEYWORDS:
        for keyword in sorted(keywords, key=len, reverse=True):
            if re.search(re.escape(keyword) + r"(?:稿)?(?=$|[，。；,;\n]|\s*(?:给|面向|用于|字|左右|以上|以下))", message):
                return dtype
    return None


def resolved_document_type(message: str, model_type: Optional[str]) -> Optional[str]:
    """Keep a precise model genre if the user actually requested that full name.

    The lexical fallback protects against a wrong model guess for known forms, but
    must not shorten 调研报告 to 报告 or 活动方案 to 方案.
    """
    model_type = str(model_type or "").strip()
    if model_type and re.search(
        re.escape(model_type) + r"(?=$|[，。；,;\n]|\s*(?:给|面向|用于|字|左右|以上|以下))",
        message or "",
    ):
        return model_type
    return explicit_document_type(message) or model_type or None

# 需要文号的概率较高的正式文种（仅用于 missing 提示，不自动开启）
DOCNUM_TYPICAL = {"通知", "请示", "报告", "函", "通报", "意见"}

DOCNUM_RE = re.compile(r"([一-鿿]{2,8})〔\s*(\d{4})\s*〕\s*(\d+)\s*号")
_DOCNUM_PREFIX_STRIP = re.compile(r"^(文号|编号|发文号)?(是|为|用|使用|：|:)?")
YEAR_RE = re.compile(r"(20\d{2})\s*年(?:度)?")
WORD_COUNT_RE = re.compile(r"(\d{3,5})\s*字")
DATE_RE = re.compile(r"(20\d{2}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日)")
# 只有用户明确表达"落款/成文/署名/签发日期"意图时，日期才是 document_date；
# 内容中的时间（如"下半年的工作计划""2026 年 7 月前完成"）属于 time_range/正文，不得占用落款日期
DATE_CUE_RE = re.compile(
    r"(落款|成文|署名|签发|发文).{0,4}(日期|时间)"
    # "日期再填 2026年10月10日" / "日期改成…" / "时间定为…" 等都要算落款日期，
    # 否则年份会被下面的 YEAR_RE 误当成"时间范围"，用户要改的日期一个都落不了地
    r"|(日期|时间)\s*(?:再|又|另外)?\s*"
    r"(?:是|为|：|:|定为|写成|改用|改成|改为|换成|设为|填|填上|填成|写|按|用)"
    r"|(用|按|以).{0,6}(这个|该)?日期"
)

DOCNUM_OFF_RE = re.compile(r"(不需要|不要|不用|无需|不加|去掉|取消).{0,6}文号|文号.{0,4}(不需要|不要|不用|取消|去掉)")
DOCNUM_ON_RE = re.compile(r"(需要|要|加|加上|使用).{0,4}文号|文号.{0,2}(是|为)")
# "落款是今天" / "日期用今天" / "按今天" 都要能识别成"今天"；
# 旧写法只认「(使用|用|按)…今天」「今天的日期」「当前日期」，用户说"落款是今天"时完全落空
TODAY_DATE_RE = re.compile(
    r"(?:落款|成文|署名|签发|发文|日期|时间)\s*"
    r"(?:是|为|用|按|填|写成|改成|改为|设为|取)?\s*"
    r"(?:今天|今日|当天|当前日期)"
    r"|(?:使用|用|按|取).{0,4}(?:今天|今日|当前日期)"
    r"|当前日期"
)

RECIPIENT_RE = re.compile(r"(?:发给|主送|报送|呈报|发送给|提交给|面向)\s*[：:]?([^，。；\n]{2,30})")
# 旧写法只认「落款是」「发文机关是」「单位是」这类"是"字结构，
# 用户说「落款改成广州市白云区司法局」时一个字都匹配不上 → 落款单位永远改不动。
# 这里把常见动词（改成/改为/换成/填/写成/设为…）补上，名词也允许省略（"以…局"）
AUTHORITY_RE = re.compile(
    r"(?:以|由|落款|署名|发文机关|发文单位|机关|单位)\s*"
    r"(?:是|为|改成|改为|换成|改作|填|填写|写成|用|设为|定为)?\s*[：:]?\s*"
    r"([一-鿿]{2,20}(?:局|厅|部|委|办|所|中心|政府|委员会|办公室))"
)
# "标题改成关于XXX的函" —— 标题是结构化字段，正文里的标题会被剥离，
# 必须写进 ctx 才会真的变；"标题换一个"这种没给内容的不能当标题（靠长度+是否"关于"过滤）
TITLE_RE = re.compile(
    r"标题\s*(?:是|为|改成|改为|换成|写成|填|设为|用|取|定为)?\s*[：:]?\s*"
    r"([^\s，。；：:\n]{4,60})"
)
TOPIC_ABOUT_RE = re.compile(r"关于(?:开展|加强|做好|规范|推进)?([^，。；的\n]{2,30}?)(?:的)?(通知|请示|报告|方案|意见|通报|函|总结|讲话|致辞|发言)")

# 修改意图（相对当前文档），区别于新起草
REVISE_HINTS = ["改", "扩写", "润色", "精简", "缩写", "补充", "增加", "删除", "去掉",
                "调整", "换", "重写", "规范", "详细", "控制", "口吻", "语气", "第二部分",
                "第一部分", "第三部分", "这段", "那段", "这一", "那段", "最后一段", "开头", "结尾"]
DRAFT_HINTS = ["起草", "写一版", "先写", "生成", "出初稿", "开始写", "出稿", "写吧", "先搭", "框架", "提纲"]


def normalize_recipient_name(name: str) -> str:
    """司法局当前交付环境中的主送机关规范化。

    仅补全白云区机关的行政区划前缀，不改“各镇街、各部门”等集合称谓，
    也不猜测其他地区的机关全称。
    """
    s = (name or "").strip().rstrip("：:")
    if not s:
        return s
    if re.fullmatch(r"白云区[\u4e00-\u9fa5]{2,20}(?:局|委|办|院|中心|政府|委员会|办公室)", s):
        return "广州市" + s
    if s == "区财政局":
        return "广州市白云区财政局"
    return s


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
        "template_id": None,      # 关联写作模板（用户显式选择）
        "template_name": None,
        "kb_ids": [],             # 关联知识库（限定检索范围；空=全部可访问库）
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

    # 年份属于"落款日期"时不再当作时间范围
    date_span = None
    dm = DATE_RE.search(msg)
    if dm and DATE_CUE_RE.search(msg):
        date_span = dm.span(1)
    msg_for_year = msg if not date_span else msg[:date_span[0]] + msg[date_span[1]:]
    m = YEAR_RE.search(msg_for_year)
    if m:
        upd["time_range"] = f"{m.group(1)}年度" if "度" in msg[m.end()-1:m.end()+1] or "年度" in msg else f"{m.group(1)}年"

    m = TOPIC_ABOUT_RE.search(msg)
    if m:
        upd["topic"] = m.group(1).strip()
    elif upd.get("document_type") and "topic" not in upd:
        # “帮我写一份2026年度司法行政工作总结” → 主题取文种前的修饰语
        m2 = re.search(r"(?:写|起草|拟)(?:一份|一篇|一个|个|篇)?([^，。；\n]{2,30}?)("
                       + "|".join(k for _, ks in DOC_TYPE_KEYWORDS for k in ks) + ")", msg)
        if m2:
            t = re.sub(r"^20\d{2}年度?", "", m2.group(1)).strip()
            if t and t not in ("工作", "一个", "一份"):
                upd["topic"] = t

    m = RECIPIENT_RE.search(msg)
    if m:
        upd["recipient"] = normalize_recipient_name(m.group(1))

    m = TITLE_RE.search(msg)
    if m:
        t = m.group(1).strip()
        # 「标题换一个」没给具体内容，不能当成新标题
        confident = t.startswith("关于") or any(
            k in t for _, ks in DOC_TYPE_KEYWORDS for k in ks)
        if not confident and len(t) >= 6 and not re.search(
                r"(换|改|写|弄|来)(一个|一下|个)?$", t):
            confident = True
        if confident:
            upd["title"] = t

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
    if m and DATE_CUE_RE.search(msg):
        upd["document_date"] = re.sub(r"\s+", "", m.group(1))
    elif TODAY_DATE_RE.search(msg):
        today = now_local().date()
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
        "document_date": "落款日期", "template_name": "模板",
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
    elif dt in FORMAL_DOC_TYPES:
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
    if dt == "致辞稿" and topic:
        return f"在{topic}上的致辞"
    if dt == "讲话稿" and topic:
        return f"在{topic}上的讲话"
    if topic and dt in FORMAL_DOC_TYPES:
        return f"关于{topic}的{dt}"
    if topic and dt:
        return f"{topic}{dt}"
    return None
