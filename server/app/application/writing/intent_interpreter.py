"""Writing instruction interpreter.

Semantic routing belongs to the LLM. This module deliberately does not infer a user's
intent from keywords/regular expressions. Deterministic code may still validate exact
values later (for example an explicitly supplied document number), but it must not decide
whether a message means "draft", "revise", "change title", or "ask a question".

If the model is temporarily unavailable or returns malformed JSON, we fail closed with a
non-mutating response instead of falling back to regex heuristics. That is important for a
writing workbench: doing nothing is recoverable; applying the wrong edit is not.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

INTENTS = (
    "update_context",
    "revise_content",
    "draft",
    "outline",
    "answer",
    "clarify",
)
SIDE_EFFECTS = ("none", "workspace")

# Fields whose meaning must be understood semantically by the model. Exact formatting and
# validation can still be enforced later by deterministic code.
SEMANTIC_FIELDS = (
    "document_type",
    "title",
    "topic",
    "purpose",
    "time_range",
    "recipient",
    "authority",
    "key_facts",
    "requirements",
    "tone",
    "word_count_target",
    "document_number_enabled",
    "document_number",
    "document_date",
)

SYSTEM_PROMPT = """你是司法行政公文写作工作台的“指令理解器”。
你的职责只有一个：理解用户此刻真正想做什么，并把意图转换成结构化 JSON。
不要靠关键词机械匹配，要结合当前任务、是否已有正文、最近对话和用户最新消息进行语义判断。
只输出 JSON，不要输出 markdown 或额外解释。

【最重要的结构边界】
公文由“结构字段”和“正文主体”两层组成：
- 结构字段：标题、文种、主送机关、发文机关/落款单位、文号、成文日期、时间范围、字数等；
- 正文主体：正文段落、章节、措辞、事实、措施、结尾用语等。

用户只是在改结构字段时，必须 intent=update_context，不要把这些内容改写进正文。
例如：
- “标题改成《关于开展……的通知》” → update_context，title=对应标题；
- “主送改成广州市白云区财政局” → update_context，recipient=对应单位；
- “落款改成广州市白云区司法局” → update_context，authority=对应单位；
- “日期改成2026年10月10日” → update_context，document_date=对应日期；
- “不要文号” → update_context，document_number_enabled=false。

只有用户明确要求修改正文内容时才用 revise_content，例如：
“第二段精简”“把措施写具体”“删掉最后一段”“整体润色”“改成800字但保留事实”。
如果同一句既改结构字段又改正文，intent=revise_content，同时把结构字段也提取出来；
revision_instruction 只描述正文需要怎样修改，不要把“标题/主送/落款/日期/文号”写进正文修改指令。

【动作类型】
- answer：只问问题、咨询、解释、评价，不改变工作台；side_effect=none。
- update_context：只补充或修改结构化任务信息；side_effect=workspace。
- revise_content：修改已有正文主体；side_effect=workspace。
- draft：生成完整初稿；side_effect=workspace。
- outline：只生成提纲；side_effect=workspace。
- clarify：确实缺少无法合理默认的关键信息；原则上少用，最多问1个关键问题。

【行为要求】
1. “能不能帮我改成800字？”虽然是疑问句，实际是 revise_content。
2. “这份函哪里不规范？”如果只是询问，不自动改，answer。
3. 已经有正文时，用户说“重新写一版/重写全文”才允许 rewrite；普通修改不得擅自重写全文。
4. 一次包含多个要求必须全部保留，不能只取第一个。
5. 不知道的字段填 null，不得猜人名、单位、数字、日期、文号。
6. 数字和日期按用户原文抽取，禁止自行换算或改值。
7. reply 是给用户看的助手回复：要说明“我理解了什么/将改什么”；如果执行修改，简短列出改动范围，不能只回“已完成”。
8. 不得因为用户修改正文而把标题、主送、落款、日期复制到正文里。

输出字段：
{
  "_schema":"writing_intent_v2",
  "side_effect":"none|workspace",
  "intent":"update_context|revise_content|draft|outline|answer|clarify",
  "document_type":null,
  "title":null,
  "topic":null,
  "purpose":null,
  "time_range":null,
  "recipient":null,
  "authority":null,
  "key_facts":[],
  "requirements":null,
  "tone":null,
  "word_count_target":null,
  "document_number_enabled":null,
  "document_number":null,
  "document_date":null,
  "revision_instruction":null,
  "revision_mode":null,
  "needs_clarification":false,
  "clarification_question":null,
  "reply":""
}

revision_mode 仅可为 expand/polish/condense/normalize/complete/rewrite/revise。
"""


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    """Parse the first JSON object without using regex-based semantic heuristics."""
    if not text:
        return None
    s = text.strip()
    if s.startswith("```"):
        first_nl = s.find("\n")
        if first_nl >= 0:
            s = s[first_nl + 1:]
        if s.endswith("```"):
            s = s[:-3].rstrip()
    start = s.find("{")
    if start < 0:
        return None
    try:
        obj, _ = json.JSONDecoder().raw_decode(s[start:])
    except (json.JSONDecodeError, TypeError):
        return None
    return obj if isinstance(obj, dict) else None


def _blank_result(reply: str) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "intent": "answer",
        "side_effect": "none",
        "revision_instruction": None,
        "revision_mode": None,
        "needs_clarification": False,
        "clarification_question": None,
        "reply": reply,
    }
    for f in SEMANTIC_FIELDS:
        out[f] = [] if f == "key_facts" else None
    return out


def _sanitize(raw: Dict[str, Any]) -> Dict[str, Any]:
    out = _blank_result("")

    intent = str(raw.get("intent") or "").strip()
    if intent in INTENTS:
        out["intent"] = intent

    side = str(raw.get("side_effect") or "").strip()
    if side in SIDE_EFFECTS:
        out["side_effect"] = side
    else:
        out["side_effect"] = "none" if out["intent"] in ("answer", "clarify") else "workspace"

    # Safety invariant: a read-only classification can never mutate the workspace.
    if out["side_effect"] == "none" and out["intent"] not in ("answer", "clarify"):
        out["intent"] = "answer"

    for f in SEMANTIC_FIELDS:
        v = raw.get(f)
        if v is None or v == "" or v == "null":
            continue
        if f == "key_facts":
            if isinstance(v, list):
                out[f] = [str(x).strip() for x in v if str(x).strip()]
            elif isinstance(v, str) and v.strip():
                out[f] = [v.strip()]
        elif f == "word_count_target":
            try:
                n = int(v)
                if 50 <= n <= 100000:
                    out[f] = n
            except (TypeError, ValueError):
                pass
        elif f == "document_number_enabled":
            if isinstance(v, bool):
                out[f] = v
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

    # Structural-only changes must never enter the body-revision path.
    structural_values = any(
        out.get(k) is not None
        for k in (
            "document_type", "title", "topic", "purpose", "time_range", "recipient",
            "authority", "word_count_target", "document_number_enabled", "document_number",
            "document_date",
        )
    )
    if out["intent"] == "revise_content" and not out.get("revision_instruction") and structural_values:
        out["intent"] = "update_context"
        out["revision_mode"] = None

    if not out["reply"]:
        if out["intent"] == "update_context":
            out["reply"] = "已理解你的结构调整要求，我会更新对应字段，不把它重复写进正文。"
        elif out["intent"] == "revise_content":
            out["reply"] = "已理解你的正文修改要求，我会只改指定内容，并保留其他部分。"
        elif out["intent"] == "draft":
            out["reply"] = "已理解，开始生成完整初稿。"
        elif out["intent"] == "outline":
            out["reply"] = "已理解，先生成提纲。"
        elif out["intent"] == "clarify":
            out["reply"] = out["clarification_question"] or "还缺一个关键信息，请补充后我再继续。"
        else:
            out["reply"] = "我会直接回答这个问题，不修改当前文档。"
    return out


class WritingIntentInterpreter:
    """LLM-only semantic router with one JSON-repair retry and fail-closed behavior."""

    def __init__(self, assistant) -> None:
        self.assistant = assistant

    def _safe_failure(self, reason: str) -> Dict[str, Any]:
        logger.warning("[意图解释] %s；为避免误改正文，本轮不执行工作台变更", reason)
        return _blank_result("这条指令我没有可靠理解，因此没有改动文档。请换一种说法，我会重新理解后再执行。")

    def interpret(
        self,
        message: str,
        context: Optional[Dict[str, Any]] = None,
        has_draft: bool = False,
        history: Optional[List[Dict[str, str]]] = None,
    ) -> Optional[Dict[str, Any]]:
        # Keep Optional in the public signature for compatibility, but when an assistant exists
        # this method always returns a structured result. That prevents task_service from entering
        # its legacy regex intent fallback in production.
        if not self.assistant:
            return self._safe_failure("模型未配置")

        ctx_view = {
            k: v for k, v in (context or {}).items()
            if k in SEMANTIC_FIELDS + ("missing_fields",)
            and v not in (None, "", [], False)
        }
        payload = {
            "当前任务信息": ctx_view or "（空，新任务）",
            "是否已有正文草稿": has_draft,
            "用户最新消息": message,
        }

        messages: List[Dict[str, str]] = [{"role": "system", "content": SYSTEM_PROMPT}]
        for h in (history or [])[-8:]:
            if h.get("role") in ("user", "assistant") and h.get("content"):
                messages.append({"role": h["role"], "content": h["content"][:1200]})
        messages.append({"role": "user", "content": json.dumps(payload, ensure_ascii=False)})

        try:
            raw = self.assistant.complete(messages, temperature=0.0, max_tokens=1400)
        except Exception as exc:
            return self._safe_failure(f"模型调用失败: {exc}")

        obj = _extract_json(raw or "")
        if obj is None or obj.get("_schema") not in ("writing_intent_v2", "writing_intent_v1"):
            # One model-based repair attempt. We still do not infer the user's intent locally.
            repair_messages = messages + [
                {"role": "assistant", "content": (raw or "")[:3000]},
                {"role": "user", "content": (
                    "上一条输出不是合法的 writing_intent_v2 JSON。请重新理解原始用户消息，"
                    "只输出符合 schema 的单个 JSON 对象，不要解释。"
                )},
            ]
            try:
                repaired = self.assistant.complete(repair_messages, temperature=0.0, max_tokens=1400)
            except Exception as exc:
                return self._safe_failure(f"JSON 修复调用失败: {exc}")
            obj = _extract_json(repaired or "")

        if obj is None or obj.get("_schema") not in ("writing_intent_v2", "writing_intent_v1"):
            return self._safe_failure("模型连续两次未返回合法意图 JSON")

        result = _sanitize(obj)
        logger.info(
            "[意图解释] model-only side_effect=%s intent=%s topic=%s dtype=%s",
            result["side_effect"], result["intent"], result.get("topic"), result.get("document_type"),
        )
        return result
