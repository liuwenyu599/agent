"""Async tool-first writing intent interpreter."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.application.writing.intent_interpreter import (
    WRITING_OPS_TOOL,
    WritingIntentInterpreter,
    _extract_json,
    _sanitize_legacy_args,
    _sanitize_tool_args,
    _tool_args_from_message,
)


class AsyncWritingIntentInterpreter(WritingIntentInterpreter):
    async def interpret_async(
        self,
        message: str,
        context: Optional[Dict[str, Any]] = None,
        has_draft: bool = False,
        history: Optional[List[Dict[str, str]]] = None,
    ) -> Optional[Dict[str, Any]]:
        if not self.assistant:
            return self._safe_failure("模型未配置")
        messages = self._messages(message, context, has_draft, history)

        tool_complete = getattr(self.assistant, "acomplete_with_tools", None)
        if callable(tool_complete):
            try:
                tool_message = await tool_complete(
                    messages,
                    tools=[WRITING_OPS_TOOL],
                    tool_choice={"type": "function", "function": {"name": "route_writing_ops"}},
                    temperature=0.0,
                    max_tokens=1200,
                )
                tool_args = _tool_args_from_message(tool_message)
                result = _sanitize_tool_args(tool_args or {}) if tool_args else None
                if result:
                    return result
            except Exception:
                # The legacy JSON path below is intentionally retained for model endpoints that
                # expose chat/completions but not OpenAI tool calling.
                pass

        try:
            raw = await self.assistant.acomplete(
                messages, temperature=0.0, max_tokens=1400)
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
                repaired = await self.assistant.acomplete(
                    repair_messages, temperature=0.0, max_tokens=1400)
            except Exception as exc:
                return self._safe_failure(f"JSON 修复调用失败: {exc}")
            obj = _extract_json(repaired or "")

        if obj is None or obj.get("_schema") not in ("writing_intent_v2", "writing_intent_v1"):
            return self._safe_failure("模型连续两次未返回合法意图 JSON")
        return _sanitize_legacy_args(obj)
