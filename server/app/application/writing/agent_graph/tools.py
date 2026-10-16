"""Function-calling loop with allowlists, budgets and duplicate suppression."""
from __future__ import annotations

import hashlib
import inspect
import json
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Mapping, Sequence


class ToolExecutionError(RuntimeError):
    pass


class ToolAccessError(ToolExecutionError):
    pass


class ToolBudgetExceeded(ToolExecutionError):
    pass


@dataclass(frozen=True)
class ToolCallRecord:
    name: str
    arguments: dict[str, Any]
    result: Any
    cached: bool
    duration_seconds: float


@dataclass(frozen=True)
class ToolLoopResult:
    content: str
    calls: list[ToolCallRecord]


ToolFn = Callable[[dict[str, Any]], Any | Awaitable[Any]]


class BoundedToolExecutor:
    """Run an OpenAI-compatible tool loop under a strict server-owned policy."""

    def __init__(self, *, model: Any, tools: Mapping[str, ToolFn],
                 schemas: Sequence[dict[str, Any]], max_rounds: int = 4):
        self.model = model
        self.tools = dict(tools)
        self.schemas = list(schemas)
        self.max_rounds = max(1, int(max_rounds))

    @staticmethod
    def _arguments(call: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
        function = call.get("function") or {}
        name = str(function.get("name") or "").strip()
        raw = function.get("arguments") or "{}"
        try:
            args = raw if isinstance(raw, dict) else json.loads(raw)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ToolExecutionError(f"工具 {name or '<unknown>'} 参数不是有效 JSON") from exc
        if not isinstance(args, dict):
            raise ToolExecutionError(f"工具 {name or '<unknown>'} 参数必须是对象")
        return name, args

    @staticmethod
    def _cache_key(name: str, args: dict[str, Any]) -> str:
        raw = json.dumps([name, args], ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    async def run(self, messages: Sequence[dict[str, Any]]) -> ToolLoopResult:
        conversation = [dict(item) for item in messages]
        cache: dict[str, Any] = {}
        records: list[ToolCallRecord] = []
        tool_rounds = 0
        while True:
            response = await self.model.acomplete_with_tools(
                conversation,
                tools=self.schemas,
                tool_choice=None,
                temperature=0.0,
                max_tokens=1200,
            )
            tool_calls = response.get("tool_calls") or []
            content = str(response.get("content") or "")
            if not tool_calls:
                return ToolLoopResult(content=content.strip(), calls=records)
            if tool_rounds >= self.max_rounds:
                raise ToolBudgetExceeded(f"工具调用超过 {self.max_rounds} 轮上限")
            tool_rounds += 1
            conversation.append({
                "role": "assistant",
                "content": content,
                "tool_calls": tool_calls,
            })
            for call in tool_calls:
                name, args = self._arguments(call)
                if name not in self.tools:
                    raise ToolAccessError(f"智能体无权调用工具：{name or '<unknown>'}")
                key = self._cache_key(name, args)
                cached = key in cache
                if cached:
                    result = cache[key]
                    duration_seconds = 0.0
                else:
                    started = time.monotonic()
                    result = self.tools[name](args)
                    if inspect.isawaitable(result):
                        result = await result
                    duration_seconds = time.monotonic() - started
                    cache[key] = result
                records.append(ToolCallRecord(
                    name, args, result, cached, duration_seconds))
                conversation.append({
                    "role": "tool",
                    "tool_call_id": str(call.get("id") or key[:12]),
                    "name": name,
                    "content": json.dumps(result, ensure_ascii=False, default=str)[:12000],
                })
