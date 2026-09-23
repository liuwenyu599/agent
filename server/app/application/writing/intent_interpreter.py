"""LLM 意图/任务解释器：Writing Assistant 的自然语言理解核心。

架构定位：
    用户自然语言 → 本解释器（Qwen14B）→ 结构化 Action
    → task_parser（确定性抽取：日期/文号/字数）校验补充
    → Task Context → Orchestrator（task_service）

设计原则：
- 语义理解（文种/主题/意图/多要求拆解）交给 LLM；
- 确定性字段（文号、日期、字数）由 task_parser 最终裁定，LLM 结果仅作参考；
- 先判 side_effect（有没有副作用：只读问答 vs 会改内容），再判动作类型，
  从根上区分"分不清动作和询问"导致的答非所问；
- LLM 输出严格 JSON，解析失败/超时/不可用一律返回 None，由调用方回退规则路径；
- 不虚构：解释器只返回消息中明确或可合理推断的信息，不知道就是 null。
"""
import json
import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# 允许的动作
INTENTS = (
    "update_context",   # 补充/修改任务要素（标题、主题、对象、时间等）
    "revise_content",   # 修改当前正文（含改标题、删段落、调格式、扩写润色等）
    "draft",            # 生成初稿
    "outline",          # 只生成框架/提纲
    "answer",           # 普通提问/闲聊/查询说明
    "clarify",          # 信息不足，需要追问
)

# 副作用分级：none=只读问答；workspace=会在工作台产生/修改内容
SIDE_EFFECTS = ("none", "workspace")

# LLM 可返回的上下文字段（确定性字段除外，由 parser 裁定）
SEMANTIC_FIELDS = (
    "document_type", "title", "topic", "purpose", "time_range",
    "recipient", "authority", "key_facts", "requirements", "tone",
)

SYSTEM_PROMPT = """你是司法行政公文写作助手的意图判别模块。判断这条消息"要做什么""会不会改动内容"，只输出 JSON，不输出任何其他文字。

【第一步：判 side_effect】
- none：只提问、咨询、解释、查询、闲聊。不生成文档、不改正文、不动任务要素。
  例："行政处罚的追诉时效是多久""请示和报告有什么区别""这份通知哪里不规范"
- workspace：要在工作台产生或修改内容——起草、改正文、列提纲、扩写、精简、补充任务要素。
  例："帮我起草一份整改通知书""把第二段精简一下""主题改成社区矫正工作"

【第二步：判动作类型 intent】
- side_effect=none → intent=answer
- side_effect=workspace → 按语义选：
  - update_context：补充/修改写作任务信息（文种、主题、对象、时间、用途、要求等）
  - revise_content：修改当前已有正文（改标题、删改段落、调格式、扩写、润色、精简、换语气、控制字数等）
  - draft：生成初稿（如"先写一版""起草吧"）
  - outline：只要框架/提纲，不要正文
- 只有"缺了关键信息就做不出来"时 → clarify

【关键规则】
1. 疑问形式不等于提问。"能不能帮我改成 2000 字？"是 workspace 指令（revise_content），不是咨询。
2. 一句话里既有提问又有指令：intent 按指令判，但 reply 必须先回答提问，再说明将执行的操作，不要合并成一件事。
3. 不要因为谨慎而追问。只有"缺了关键信息就做不出来"时才追问，最多 1~2 个问题，
   并且必须同时给出默认处理方案，然后照默认做下去——追问不能停工。
   有合理默认值就直接做，不要问。
4. 不确定的字段一律 null，禁止编造人名、单位、文号、日期、数据。
5. 涉及数字、日期、比例、名次时，以用户消息和已有任务信息中的原文为准逐字引用；
   不得换算错误、不得前后不一（如前面说 25 后面说 24）；需要计算时按原文数字计算，不要凭印象给数。
6. 不得因用户指令扩大检索范围或输出其他科室资料。
7. 生成内容一律视为草稿，不要为此拦截执行。

同时从消息中抽取你确信的任务要素（不确定的一律 null，禁止编造）：
- document_type：文种（通知/请示/报告/工作总结/函/讲话稿/方案/意见/通报/会议纪要等）
- title：用户明确给出的标题（用户没给就 null，不要自拟）
- topic：主题（如"晋升""社区矫正工作"）
- purpose：用途
- time_range：时间范围（如"2026年度"）
- recipient：主送/报送对象
- authority：发文机关/落款单位
- key_facts：用户提到的具体工作内容/事实要点（数组）
- requirements：写作要求
- tone：语气风格
- revision_instruction：当 intent=revise_content 时，把用户的全部修改要求完整整理成一条指令（可包含多个要求）
- revision_mode：expand/polish/condense/normalize/complete/rewrite/revise 之一
- needs_clarification：是否需要追问
- clarification_question：需要追问时，问最关键的 1~2 个问题
- reply：用中文、简洁、像写作助手一样对用户的自然回复（追问、确认或说明你将做什么；混合消息先答问题再说操作）

输出 JSON 必须包含 "_schema":"writing_intent_v1" 标记。示例：
{"_schema":"writing_intent_v1","side_effect":"workspace","intent":"update_context","document_type":"报告","topic":"晋升","title":null,"purpose":null,"time_range":null,"recipient":null,"authority":null,"key_facts":[],"requirements":null,"tone":null,"revision_instruction":null,"revision_mode":null,"needs_clarification":true,"clarification_question":"这份晋升报告是用于干部晋升考察、职级晋升述职，还是其他内部工作场景？","reply":"可以。为了确定写作场景，我需要确认一下：这是用于晋升考察、晋升述职，还是其他内部审批材料？"}

补充规则：
1. 不要 markdown 代码块，不要解释；
2. 文种/主题要从语义理解，"写一个晋升报告"的主题是"晋升"而不是"一个晋升"；
3. 用户一次提多个要求时，全部理解并合并到 revision_instruction；
4. 已有任务信息会被提供给你，除非用户明确要改，不要推翻已确认的要素；
5. 日期语义必须区分：内容里的工作周期/计划时段（如"下半年""2026年度""第三季度"）属于 time_range；只有用户明确说"落款日期/成文日期/署名日期是X"时才是落款日期——落款日期由系统程序处理，你不要输出，只需在 reply 中确认已记录；
6. 用户说"用某某模板写"时，把模板名写进 requirements，不要编造模板内容。"""


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    """从 LLM 输出中稳健提取 JSON 对象。

    处理：markdown fence、前后多余文本、 trailing garbage。
    """
    if not text:
        return None
    s = text.strip()
    # 去 markdown fence
    s = re.sub(r"^```(?:json)?\s*", "", s)
    s = re.sub(r"\s*```$", "", s)
    # 找第一个平衡 {...}
    start = s.find("{")
    if start < 0:
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(s)):
        ch = s[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    obj = json.loads(s[start:i + 1])
                    return obj if isinstance(obj, dict) else None
                except json.JSONDecodeError:
                    return None
    return None


def _sanitize(raw: Dict[str, Any]) -> Dict[str, Any]:
    """字段白名单 + 类型校正，缺失字段补 None。

    side_effect 一致性裁决（宁可当提问直接答，也不要误当指令去改东西）：
    - side_effect=none → intent 强制 answer；
    - side_effect=workspace 而 LLM 给了 answer → 维持 answer（保守，不动内容）；
    - LLM 没给 side_effect → 由 intent 反推（answer/clarify → none，其余 → workspace）。
    """
    out: Dict[str, Any] = {
        "intent": "answer",
        "side_effect": "none",
        "revision_instruction": None,
        "revision_mode": None,
        "needs_clarification": False,
        "clarification_question": None,
        "reply": None,
    }
    for f in SEMANTIC_FIELDS:
        out[f] = None
    intent = str(raw.get("intent") or "").strip()
    if intent in INTENTS:
        out["intent"] = intent
    side_effect = str(raw.get("side_effect") or "").strip()
    if side_effect in SIDE_EFFECTS:
        out["side_effect"] = side_effect
    else:
        out["side_effect"] = "none" if out["intent"] in ("answer", "clarify") else "workspace"
    if out["side_effect"] == "none" and out["intent"] not in ("answer", "clarify"):
        logger.info("[意图解释] side_effect=none 与 intent=%s 冲突，按只读问答裁决", out["intent"])
        out["intent"] = "answer"
    for f in SEMANTIC_FIELDS:
        v = raw.get(f)
        if v is None or v == "" or v == "null":
            continue
        if f == "key_facts":
            if isinstance(v, list):
                facts = [str(x).strip() for x in v if str(x).strip()]
                if facts:
                    out[f] = facts
            elif isinstance(v, str) and v.strip():
                out[f] = [v.strip()]
        elif isinstance(v, str):
            out[f] = v.strip()
    for f in ("revision_instruction", "revision_mode", "clarification_question", "reply"):
        v = raw.get(f)
        if isinstance(v, str) and v.strip():
            out[f] = v.strip()
    if isinstance(raw.get("needs_clarification"), bool):
        out["needs_clarification"] = raw["needs_clarification"]
    if out["revision_mode"] not in (
        "expand", "polish", "condense", "normalize", "complete", "rewrite", "revise",
    ):
        out["revision_mode"] = "revise" if out["revision_instruction"] else None
    return out


class WritingIntentInterpreter:
    """调用 Qwen14B 完成自然语言理解；失败返回 None 交由规则回退。"""

    def __init__(self, assistant) -> None:
        self.assistant = assistant

    def interpret(
        self,
        message: str,
        context: Optional[Dict[str, Any]] = None,
        has_draft: bool = False,
        history: Optional[List[Dict[str, str]]] = None,
    ) -> Optional[Dict[str, Any]]:
        if not self.assistant:
            return None
        ctx_view = {
            k: v for k, v in (context or {}).items()
            if k in SEMANTIC_FIELDS + (
                "document_number_enabled", "document_number",
                "document_date", "word_count_target", "missing_fields",
            ) and v not in (None, "", [], False)
        }
        user_payload = {
            "当前任务信息": ctx_view or "（空，新任务）",
            "是否已有正文草稿": has_draft,
            "用户最新消息": message,
        }
        messages: List[Dict[str, str]] = [{"role": "system", "content": SYSTEM_PROMPT}]
        for h in (history or [])[-6:]:
            if h.get("role") in ("user", "assistant") and h.get("content"):
                messages.append({"role": h["role"], "content": h["content"][:800]})
        messages.append({"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)})
        try:
            raw = self.assistant.complete(messages, temperature=0.1, max_tokens=1024)
        except Exception as e:
            logger.warning("[意图解释] LLM 调用失败，回退规则解析: %s", e)
            return None
        obj = _extract_json(raw or "")
        if obj is None or obj.get("_schema") != "writing_intent_v1":
            logger.warning("[意图解释] LLM 输出无效（非 JSON 或缺少 schema 标记），回退规则解析: %s",
                           (raw or "")[:120])
            return None
        result = _sanitize(obj)
        logger.info("[意图解释] side_effect=%s intent=%s topic=%s dtype=%s",
                    result["side_effect"], result["intent"],
                    result.get("topic"), result.get("document_type"))
        return result
