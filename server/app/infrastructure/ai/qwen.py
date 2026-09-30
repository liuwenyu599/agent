"""AI Gateway：Qwen 适配器（OpenAI 兼容 chat/completions）。

业务模块一律通过 application.ports.LLMGateway 调用，禁止直接 HTTP 调模型服务。
"""
import json
from typing import Any, Dict, Iterator, List, Optional, Tuple

import requests

from app.core.config import settings
from app.core.exceptions import AIServiceError
from app.core.logging import get_logger

logger = get_logger(__name__)

# 多模态消息中每张图片按固定额度计入上下文预算（无法本地精确计算 patch 数）
_IMAGE_TOKEN_ALLOWANCE = 1200


class QwenGateway:
    """Qwen Model Service 适配器（vLLM / 任何 OpenAI 兼容端点）。

    默认读取全局 MODEL_* 配置；也可通过构造参数指向另一套服务
    （如独立的视觉模型服务 VISION_MODEL_URL，Qwen2.5-VL 等）。

    包含上下文预算保护：估算输入 token，超限时依次砍历史、截断 system，
    保证 max_tokens >= 1（移植自旧 llm_service._call_vllm）。
    消息 content 支持多模态列表形态（text + image_url）。
    """

    def __init__(self, api_url: Optional[str] = None, model: Optional[str] = None,
                 api_key: Optional[str] = None, timeout: Optional[int] = None,
                 ctx_limit: Optional[int] = None) -> None:
        self.api_url = (api_url or settings.MODEL_SERVICE_URL).rstrip("/")
        self.model = model or settings.MODEL_NAME
        self.api_key = api_key if api_key is not None else settings.MODEL_API_KEY
        self.timeout = timeout or settings.MODEL_TIMEOUT
        self.ctx_limit = ctx_limit or settings.MODEL_CTX_LIMIT

    @property
    def model_name(self) -> str:
        return self.model

    # ---- 请求准备（complete / tool call / complete_stream 共用） ----

    def _prepare(self, messages: List[Dict[str, str]],
                 temperature: Optional[float],
                 max_tokens: Optional[int]) -> Tuple[List[Dict[str, str]], int, float]:
        """上下文预算保护：返回 (裁剪后消息, 安全 max_tokens, 温度)。"""
        if temperature is None:
            temperature = settings.MODEL_TEMPERATURE
        if max_tokens is None:
            max_tokens = settings.MODEL_MAX_TOKENS

        messages = [m for m in messages if m.get("content")]
        ctx_limit = self.ctx_limit

        estimated = self._estimate(messages)
        safe_max_tokens = min(max_tokens, ctx_limit - estimated - 50)

        if safe_max_tokens < 256:
            messages = self._trim_messages(messages)
            estimated = self._estimate(messages)
            safe_max_tokens = min(max_tokens, ctx_limit - estimated - 50)

        if safe_max_tokens < 256:
            messages = self._shrink_system(messages, ctx_limit)
            estimated = self._estimate(messages)
            safe_max_tokens = min(max_tokens, ctx_limit - estimated - 50)

        if safe_max_tokens < 1:
            messages = self._trim_messages(messages, keep_rounds=1)
            messages = self._shrink_system(messages, ctx_limit)
            estimated = self._estimate(messages)
            safe_max_tokens = max(1, min(256, ctx_limit - estimated - 50))

        logger.info("[AI网关] 估算输入: ~%d tokens, max_tokens: %d", estimated, safe_max_tokens)
        return messages, safe_max_tokens, temperature

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _post(self, payload: Dict, stream: bool = False) -> requests.Response:
        try:
            response = requests.post(
                f"{self.api_url}/chat/completions",
                headers=self._headers(),
                json=payload,
                timeout=self.timeout,
                stream=stream,
            )
            response.raise_for_status()
            return response
        except requests.exceptions.ConnectionError:
            raise AIServiceError(f"模型服务不可用，请检查 {self.api_url}")
        except requests.exceptions.Timeout:
            raise AIServiceError("模型服务响应超时")
        except requests.exceptions.HTTPError as e:
            detail = e.response.text[:500] if e.response is not None else str(e)
            logger.error("[AI网关] HTTP 错误: %s", detail)
            raise AIServiceError("模型调用失败")

    @staticmethod
    def _log_choice(result: Dict[str, Any], choice: Dict[str, Any]) -> None:
        logger.info(
            "[AI网关] finish_reason: %s, usage: %s",
            choice.get("finish_reason"), result.get("usage"),
        )
        if choice.get("finish_reason") == "length":
            logger.warning("[AI网关] 输出被 max_tokens 截断")

    def complete(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        messages, safe_max_tokens, temperature = self._prepare(
            messages, temperature, max_tokens)

        response = self._post({
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": safe_max_tokens,
            "top_p": 0.9,
        })

        result = response.json()
        choice = result["choices"][0]
        self._log_choice(result, choice)
        return choice["message"]["content"]

    def complete_with_tools(
        self,
        messages: List[Dict[str, str]],
        tools: List[Dict[str, Any]],
        tool_choice: Optional[Dict[str, Any]] = None,
        temperature: Optional[float] = 0.0,
        max_tokens: Optional[int] = None,
    ) -> Dict[str, Any]:
        """一次 OpenAI-compatible function/tool completion，返回原始 assistant message。

        业务层负责校验 tool name 与 arguments。这里不执行工具，也不偷偷把 tool call
        转成普通文本，避免“看起来结构化、实际仍靠自然语言解析”的假工具调用。
        若生产 vLLM 未启用相应 tool parser，HTTP 错误会按统一 AIServiceError 抛出，
        上层可显式降级到旧 JSON schema，不影响现网写作。
        """
        messages, safe_max_tokens, temperature = self._prepare(
            messages, temperature, max_tokens)
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": safe_max_tokens,
            "top_p": 0.9,
            "tools": tools,
        }
        if tool_choice is not None:
            payload["tool_choice"] = tool_choice

        response = self._post(payload)
        result = response.json()
        choice = result["choices"][0]
        self._log_choice(result, choice)
        message = choice.get("message") or {}
        return {
            "role": message.get("role") or "assistant",
            "content": message.get("content") or "",
            "tool_calls": message.get("tool_calls") or [],
        }

    def complete_stream(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> Iterator[str]:
        """流式补全：逐段 yield 增量文本（OpenAI 兼容 SSE）。

        供写作工作台「流式生成」使用：前端边收边显示，不再整段等待。
        失败抛 app.core.exceptions.AIServiceError。
        """
        messages, safe_max_tokens, temperature = self._prepare(
            messages, temperature, max_tokens)

        response = self._post({
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": safe_max_tokens,
            "top_p": 0.9,
            "stream": True,
        }, stream=True)

        response.encoding = "utf-8"

        finish_reason = None
        for raw in response.iter_lines(decode_unicode=True):
            if not raw:
                continue
            line = raw.strip()
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload == "[DONE]":
                break
            try:
                data = json.loads(payload)
            except ValueError:
                continue
            for choice in data.get("choices") or []:
                if choice.get("finish_reason"):
                    finish_reason = choice["finish_reason"]
                delta = (choice.get("delta") or {}).get("content")
                if delta:
                    yield delta
        if finish_reason == "length":
            logger.warning("[AI网关] 流式输出被 max_tokens 截断")

    # ---- 上下文预算（移植自旧 llm_service）----
    @staticmethod
    def _estimate(msgs: List[Dict[str, str]]) -> int:
        chars = 0
        images = 0
        for m in msgs:
            c = m.get("content", "")
            if isinstance(c, list):
                for part in c:
                    if part.get("type") == "text":
                        chars += len(part.get("text", ""))
                    elif part.get("type") == "image_url":
                        images += 1
            else:
                chars += len(c)
        return int(chars / 0.75) + images * _IMAGE_TOKEN_ALLOWANCE

    @staticmethod
    def _trim_messages(messages: List[Dict[str, str]], keep_rounds: int = 3) -> List[Dict[str, str]]:
        system = [m for m in messages if m.get("role") == "system"][:1]
        others = [m for m in messages if m.get("role") != "system"]
        return system + others[-keep_rounds * 2:]

    @staticmethod
    def _shrink_system(messages: List[Dict[str, str]], ctx_limit: int) -> List[Dict[str, str]]:
        system = [m for m in messages if m.get("role") == "system"]
        others = [m for m in messages if m.get("role") != "system"]
        if not system:
            return messages
        sys_char_budget = int((ctx_limit - 512) * 0.75 * 0.5)
        content = system[0].get("content", "")
        if not isinstance(content, str):
            return messages
        if len(content) > sys_char_budget:
            content = content[:sys_char_budget] + "\n（上下文过长，参考材料已按长度截断）"
        return [{"role": "system", "content": content}] + others
