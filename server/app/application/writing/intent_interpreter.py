"""Writing instruction interpreter.

Production routing prefers a real OpenAI-compatible function call. The model chooses one
explicit operation (set fields / patch one section / rewrite document / draft / answer), while
deterministic code validates arguments and executes the mutation. A legacy JSON-v2 path remains
as a compatibility fallback for model endpoints that do not expose tool calling yet.

Regex/keyword parsers never decide whether a message means draft/revise/change-title/etc.
If both tool calling and JSON interpretation fail, callers receive ``None`` and must not mutate.
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
OPERATIONS = (
    "set_fields",
    "patch_section",
    "append_to_section",
    "insert_paragraph",
    "delete_range",
    "rewrite_document",
    "draft_document",
    "outline",
    "answer",
    "clarify",
)

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

LEGACY_JSON_SCHEMA = """
兼容 JSON 输出格式（仅当工具调用不可用时使用）：
{
  "_schema":"writing_intent_v2",
  "side_effect":"none|workspace",
  "intent":"update_context|revise_content|draft|outline|answer|clarify",
  "operation":"set_fields|patch_section|append_to_section|insert_paragraph|delete_range|rewrite_document|draft_document|outline|answer|clarify",
  "target":null,
  "position":"before|after",
  "end_target":null,
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
JSON 兼容模式与工具调用采用相同操作边界。局部修改必须输出 operation 和 target，
revision_instruction 填该局部要求；不要把补一句、改某节升级成 rewrite_document。
"""

SYSTEM_PROMPT = """你是司法行政公文写作工作台的“指令理解器”。
你的职责只有一个：理解用户此刻真正想做什么，并转换成结构化操作。不要执行写作本身。
不要靠关键词机械匹配，要结合当前任务、是否已有正文、最近对话和用户最新消息进行语义判断。

【操作边界】
- set_fields：只修改标题、主送、落款、日期、文号、文种、字数等结构字段，不重写正文。
- patch_section：用户只要求修改某一段、某一节或明确局部。target 必须描述唯一目标，优先保留用户给出的原文；instruction 只写该局部怎么改。
- append_to_section：在指定章节末尾补充文字，target 可只写章节名称，instruction 描述新增内容。
- insert_paragraph：在唯一段落或章节之前/之后插入新段落，用 position 指定 before/after。
- delete_range：删除唯一目标段落、章节或原文；跨段删除时 end_target 指定结束目标，包含两端。
- rewrite_document：只有用户明确要求“全文重写/重新写一版/整体改写”时使用。普通润色、补一句、改某段不得升级成全文重写。
- draft_document：生成完整初稿。
- outline：只生成提纲。
- answer：只咨询/解释/评价，不改变工作台。
- clarify：确实无法安全定位或缺少关键条件时才用。

同一句既改结构字段又改正文时，field_updates 与正文 operation 可以同时存在；不要把字段修改塞进正文 instruction。
数字、日期、单位、人名按用户原文抽取，不得自行换算或改写。未知字段留空，不得猜。
reply 只说明理解到的操作，不要声称尚未执行的修改已经完成。
""" + LEGACY_JSON_SCHEMA

_FIELD_PROPERTIES: Dict[str, Any] = {
    "document_type": {"type": "string"},
    "title": {"type": "string"},
    "topic": {"type": "string"},
    "purpose": {"type": "string"},
    "time_range": {"type": "string"},
    "recipient": {"type": "string"},
    "authority": {"type": "string"},
    "key_facts": {"type": "array", "items": {"type": "string"}},
    "requirements": {"type": "string"},
    "tone": {"type": "string"},
    "word_count_target": {"type": "integer", "minimum": 50, "maximum": 100000},
    "document_number_enabled": {"type": "boolean"},
    "document_number": {"type": "string"},
    "document_date": {"type": "string"},
}

WRITING_OPS_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "route_writing_ops",
        "description": "把用户写作指令路由成后端可执行操作；不要直接生成正文。",
        "parameters": {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": list(OPERATIONS),
                    "description": "本轮正文/对话主操作。结构字段可同时放在 field_updates。",
                },
                "field_updates": {
                    "type": "object",
                    "properties": _FIELD_PROPERTIES,
                    "additionalProperties": False,
                    "description": "只放用户本轮明确补充或修改的结构字段。",
                },
                "target": {
                    "type": "string",
                    "description": "局部操作的唯一目标，如‘第二段’、‘工作措施’、‘三、工作措施’或用户引用的原文。",
                },
                "instruction": {
                    "type": "string",
                    "description": "局部修改、追加、插入或全文改写的要求，不含结构字段修改；删除可省略。",
                },
                "position": {"type": "string", "enum": ["before", "after"]},
                "end_target": {"type": "string", "description": "delete_range 可选的结束目标，包含该目标。"},
                "revision_mode": {
                    "type": "string",
                    "enum": ["expand", "polish", "condense", "normalize", "complete", "rewrite", "revise"],
                },
                "needs_clarification": {"type": "boolean"},
                "clarification_question": {"type": "string"},
                "reply": {"type": "string"},
            },
            "required": ["operation", "field_updates", "reply"],
            "additionalProperties": False,
        },
    },
}


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
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
        "operation": "answer",
        "patch_target": None,
        "routing": "json_fallback",
    }
    for f in SEMANTIC_FIELDS:
        out[f] = [] if f == "key_facts" else None
    return out


def _sanitize(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Sanitize legacy writing_intent_v1/v2 JSON and synthesize a safe operation."""
    out = _blank_result("")
    intent = str(raw.get("intent") or "").strip()
    if intent in INTENTS:
        out["intent"] = intent

    side = str(raw.get("side_effect") or "").strip()
    if side in SIDE_EFFECTS:
        out["side_effect"] = side
    else:
        out["side_effect"] = "none" if out["intent"] in ("answer", "clarify") else "workspace"
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

    out["operation"] = {
        "update_context": "set_fields",
        "revise_content": "rewrite_document",
        "draft": "draft_document",
        "outline": "outline",
        "answer": "answer",
        "clarify": "clarify",
    }[out["intent"]]

    if not out["reply"]:
        if out["intent"] == "update_context":
            out["reply"] = "已理解你的结构调整要求，我会更新对应字段，不把它重复写进正文。"
        elif out["intent"] == "revise_content":
            out["reply"] = "已理解你的正文修改要求。"
        elif out["intent"] == "draft":
            out["reply"] = "已理解，开始生成完整初稿。"
        elif out["intent"] == "outline":
            out["reply"] = "已理解，先生成提纲。"
        elif out["intent"] == "clarify":
            out["reply"] = out["clarification_question"] or "还缺一个关键信息，请补充后我再继续。"
    return out


def _sanitize_tool_args(raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    operation = str(raw.get("operation") or "").strip()
    if operation not in OPERATIONS:
        return None

    field_updates = raw.get("field_updates")
    if not isinstance(field_updates, dict):
        field_updates = {}

    legacy: Dict[str, Any] = {"_schema": "writing_intent_v2"}
    for key in SEMANTIC_FIELDS:
        if key in field_updates:
            legacy[key] = field_updates[key]

    intent_map = {
        "set_fields": "update_context",
        "patch_section": "revise_content",
        "append_to_section": "revise_content",
        "insert_paragraph": "revise_content",
        "delete_range": "revise_content",
        "rewrite_document": "revise_content",
        "draft_document": "draft",
        "outline": "outline",
        "answer": "answer",
        "clarify": "clarify",
    }
    legacy["intent"] = intent_map[operation]
    legacy["side_effect"] = "none" if operation in ("answer", "clarify") else "workspace"
    legacy["reply"] = raw.get("reply") or ""
    legacy["needs_clarification"] = bool(raw.get("needs_clarification", False))
    legacy["clarification_question"] = raw.get("clarification_question")

    instruction = raw.get("instruction")
    target = raw.get("target")
    mode = raw.get("revision_mode")
    if operation in ("patch_section", "append_to_section", "insert_paragraph", "rewrite_document"):
        if not isinstance(instruction, str) or not instruction.strip():
            return None
        legacy["revision_instruction"] = instruction.strip()
        legacy["revision_mode"] = (
            mode if mode in ("expand", "polish", "condense", "normalize", "complete", "rewrite", "revise")
            else ("rewrite" if operation == "rewrite_document" else "revise")
        )
    if operation in ("patch_section", "append_to_section", "insert_paragraph", "delete_range"):
        if not isinstance(target, str) or not target.strip():
            return None

    out = _sanitize(legacy)
    out["operation"] = operation
    out["patch_target"] = target.strip() if isinstance(target, str) and target.strip() else None
    out["position"] = raw.get("position") if raw.get("position") in ("before", "after") else "after"
    end_target = raw.get("end_target")
    out["end_target"] = end_target.strip() if isinstance(end_target, str) and end_target.strip() else None
    out["routing"] = "tool_call"
    return out


def _sanitize_legacy_args(raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Use the same validated operations on endpoints without tool calling."""
    if raw.get("operation"):
        result = _sanitize_tool_args({
            **raw,
            "field_updates": raw.get("field_updates") if isinstance(raw.get("field_updates"), dict)
            else {key: raw.get(key) for key in SEMANTIC_FIELDS},
            "instruction": raw.get("instruction") or raw.get("revision_instruction"),
            "target": raw.get("target") or raw.get("patch_target"),
        })
        if result:
            result["routing"] = "json_fallback"
        return result
    result = _sanitize(raw)
    if result["intent"] == "revise_content" and result.get("revision_mode") != "rewrite":
        result = _blank_result("")
        result.update(intent="clarify", operation="clarify", side_effect="none",
                      reply="请指出需要修改的段落或章节；如果要调整全文，也请说明。")
    return result


def _tool_args_from_message(message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    calls = message.get("tool_calls") if isinstance(message, dict) else None
    if not isinstance(calls, list) or len(calls) != 1:
        return None
    fn = (calls[0] or {}).get("function") or {}
    if fn.get("name") != "route_writing_ops":
        return None
    args = fn.get("arguments")
    if isinstance(args, dict):
        return args
    if not isinstance(args, str):
        return None
    try:
        parsed = json.loads(args)
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


class WritingIntentInterpreter:
    """Tool-first semantic router with one legacy JSON repair fallback."""

    def __init__(self, assistant) -> None:
        self.assistant = assistant

    @staticmethod
    def _safe_failure(reason: str) -> None:
        logger.warning("[意图解释] %s；为避免误改正文，本轮不执行工作台变更", reason)
        return None

    def _messages(
        self,
        message: str,
        context: Optional[Dict[str, Any]],
        has_draft: bool,
        history: Optional[List[Dict[str, str]]],
    ) -> List[Dict[str, str]]:
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
        return messages

    def interpret(
        self,
        message: str,
        context: Optional[Dict[str, Any]] = None,
        has_draft: bool = False,
        history: Optional[List[Dict[str, str]]] = None,
    ) -> Optional[Dict[str, Any]]:
        if not self.assistant:
            return self._safe_failure("模型未配置")

        messages = self._messages(message, context, has_draft, history)

        tool_complete = getattr(self.assistant, "complete_with_tools", None)
        if callable(tool_complete):
            try:
                tool_message = tool_complete(
                    messages,
                    tools=[WRITING_OPS_TOOL],
                    tool_choice={"type": "function", "function": {"name": "route_writing_ops"}},
                    temperature=0.0,
                    max_tokens=1200,
                )
                tool_args = _tool_args_from_message(tool_message)
                result = _sanitize_tool_args(tool_args or {}) if tool_args else None
                if result:
                    logger.info(
                        "[意图解释] tool operation=%s intent=%s target=%s",
                        result["operation"], result["intent"], result.get("patch_target"),
                    )
                    return result
                logger.warning("[意图解释] tool call arguments 非法，降级到 JSON v2")
            except Exception as exc:
                logger.warning("[意图解释] tool calling 不可用，降级到 JSON v2: %s", exc)

        try:
            raw = self.assistant.complete(messages, temperature=0.0, max_tokens=1400)
        except Exception as exc:
            return self._safe_failure(f"模型调用失败: {exc}")

        obj = _extract_json(raw or "")
        if obj is None or obj.get("_schema") not in ("writing_intent_v2", "writing_intent_v1"):
            repair_messages = messages + [
                {"role": "assistant", "content": (raw or "")[:3000]},
                {"role": "user", "content": (
                    "上一条输出不是合法的 writing_intent_v2 JSON。请重新理解原始用户消息，"
                    "只输出符合 system 中兼容 schema 的单个 JSON 对象，不要解释。"
                )},
            ]
            try:
                repaired = self.assistant.complete(repair_messages, temperature=0.0, max_tokens=1400)
            except Exception as exc:
                return self._safe_failure(f"JSON 修复调用失败: {exc}")
            obj = _extract_json(repaired or "")

        if obj is None or obj.get("_schema") not in ("writing_intent_v2", "writing_intent_v1"):
            return self._safe_failure("模型连续两次未返回合法意图 JSON")

        result = _sanitize_legacy_args(obj)
        if not result:
            return self._safe_failure("JSON 操作参数不完整")
        logger.info(
            "[意图解释] json-fallback side_effect=%s intent=%s topic=%s dtype=%s",
            result["side_effect"], result["intent"], result.get("topic"), result.get("document_type"),
        )
        return result
