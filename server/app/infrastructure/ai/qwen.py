"""AI Gateway：Qwen 适配器（OpenAI 兼容 chat/completions）。

业务模块一律通过 application.ports.LLMGateway 调用，禁止直接 HTTP 调模型服务。
"""
import json
import os
import threading
import time
from typing import Any, Dict, Iterator, List, Optional, Tuple

import requests

from app.core.config import settings
from app.core.exceptions import AIServiceError
from app.core.logging import get_logger

logger = get_logger(__name__)

_IMAGE_TOKEN_ALLOWANCE = 1200
_DEFAULT_REPETITION_PENALTY = 1.08


class QwenGateway:
    """Qwen Model Service 适配器（vLLM / 任何 OpenAI 兼容端点）。"""

    def __init__(self, api_url: Optional[str] = None,
                 api_urls: Optional[List[str]] = None,
                 model: Optional[str] = None,
                 api_key: Optional[str] = None, timeout: Optional[int] = None,
                 ctx_limit: Optional[int] = None) -> None:
        if api_urls is not None:
            raw_urls = api_urls
        elif api_url is not None:
            raw_urls = [api_url]
        else:
            raw_urls = getattr(settings, "MODEL_SERVICE_URLS", None) or [settings.MODEL_SERVICE_URL]
        urls: List[str] = []
        for value in raw_urls:
            url = (value or "").strip().rstrip("/")
            if url and url not in urls:
                urls.append(url)
        if not urls:
            urls = [settings.MODEL_SERVICE_URL.rstrip("/")]

        self.api_urls = urls
        self.api_url = urls[0]
        self.model = model or settings.MODEL_NAME
        self.api_key = api_key if api_key is not None else settings.MODEL_API_KEY
        self.timeout = timeout or settings.MODEL_TIMEOUT
        self.ctx_limit = ctx_limit or settings.MODEL_CTX_LIMIT
        self.health_timeout = max(1, int(getattr(settings, "MODEL_HEALTH_TIMEOUT", 5)))
        self.failover_cooldown = max(1, int(getattr(settings, "MODEL_FAILOVER_COOLDOWN", 15)))
        try:
            self.repetition_penalty = float(
                os.getenv("MODEL_REPETITION_PENALTY", str(_DEFAULT_REPETITION_PENALTY)))
        except ValueError:
            self.repetition_penalty = _DEFAULT_REPETITION_PENALTY
        self.repetition_penalty = min(2.0, max(1.0, self.repetition_penalty))
        self._pool_lock = threading.Lock()
        self._inflight = {url: 0 for url in self.api_urls}
        self._unhealthy_until = {url: 0.0 for url in self.api_urls}
        self._rr_cursor = 0

    @property
    def model_name(self) -> str:
        return self.model

    @property
    def endpoint_count(self) -> int:
        return len(self.api_urls)

    def _prepare(self, messages: List[Dict[str, str]],
                 temperature: Optional[float],
                 max_tokens: Optional[int]) -> Tuple[List[Dict[str, str]], int, float]:
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

    def _base_payload(self, messages: List[Dict[str, str]],
                      temperature: float, max_tokens: int) -> Dict[str, Any]:
        return {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "top_p": 0.9,
            "repetition_penalty": self.repetition_penalty,
        }

    def _endpoint_order(self) -> List[str]:
        now = time.monotonic()
        with self._pool_lock:
            healthy = [u for u in self.api_urls if self._unhealthy_until[u] <= now]
            pool = healthy or list(self.api_urls)
            start = self._rr_cursor % len(self.api_urls)
            rank = {u: (self.api_urls.index(u) - start) % len(self.api_urls) for u in pool}
            ordered = sorted(pool, key=lambda u: (self._inflight[u], rank[u]))
            self._rr_cursor = (self._rr_cursor + 1) % len(self.api_urls)
            return ordered

    def _acquire(self, url: str) -> None:
        with self._pool_lock:
            self._inflight[url] += 1

    def _release(self, url: str) -> None:
        with self._pool_lock:
            self._inflight[url] = max(0, self._inflight[url] - 1)

    def _mark_failed(self, url: str, reason: str) -> None:
        with self._pool_lock:
            self._unhealthy_until[url] = time.monotonic() + self.failover_cooldown
        logger.warning("[AI网关] endpoint 暂时熔断 %ss: %s (%s)",
                       self.failover_cooldown, url, reason)

    def health(self) -> List[Dict[str, Any]]:
        result: List[Dict[str, Any]] = []
        for url in self.api_urls:
            started = time.monotonic()
            try:
                response = requests.get(
                    f"{url}/models", headers=self._headers(), timeout=self.health_timeout
                )
                ok = response.status_code < 500
                if ok:
                    with self._pool_lock:
                        self._unhealthy_until[url] = 0.0
                else:
                    self._mark_failed(url, f"HTTP {response.status_code}")
                result.append({
                    "url": url, "healthy": ok, "status_code": response.status_code,
                    "latency_ms": int((time.monotonic() - started) * 1000),
                })
            except requests.RequestException as exc:
                self._mark_failed(url, type(exc).__name__)
                result.append({
                    "url": url, "healthy": False, "status_code": None,
                    "latency_ms": int((time.monotonic() - started) * 1000),
                })
        return result

    def _post(self, payload: Dict, stream: bool = False) -> requests.Response:
        failures: List[str] = []
        for url in self._endpoint_order():
            self._acquire(url)
            try:
                response = requests.post(
                    f"{url}/chat/completions",
                    headers=self._headers(),
                    json=payload,
                    timeout=self.timeout,
                    stream=stream,
                )
                if response.status_code == 429 or response.status_code >= 500:
                    detail = response.text[:200]
                    self._mark_failed(url, f"HTTP {response.status_code}")
                    failures.append(f"{url}: HTTP {response.status_code} {detail}")
                    continue
                response.raise_for_status()
                if url != self.api_url:
                    logger.info("[AI网关] 请求由备用 endpoint 完成: %s", url)
                return response
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
                self._mark_failed(url, type(exc).__name__)
                failures.append(f"{url}: {type(exc).__name__}")
                continue
            except requests.exceptions.HTTPError as exc:
                detail = exc.response.text[:500] if exc.response is not None else str(exc)
                logger.error("[AI网关] HTTP 错误（不切换节点）: %s", detail)
                raise AIServiceError("模型调用失败")
            finally:
                self._release(url)

        logger.error("[AI网关] 所有 endpoint 调用失败: %s", " | ".join(failures))
        if any("Timeout" in item for item in failures):
            raise AIServiceError("模型服务响应超时")
        raise AIServiceError("模型服务暂时不可用")

    @staticmethod
    def _log_choice(result: Dict[str, Any], choice: Dict[str, Any]) -> None:
        logger.info("[AI网关] finish_reason: %s, usage: %s",
                    choice.get("finish_reason"), result.get("usage"))
        if choice.get("finish_reason") == "length":
            logger.warning("[AI网关] 输出被 max_tokens 截断")

    def complete(self, messages: List[Dict[str, str]],
                 temperature: Optional[float] = None,
                 max_tokens: Optional[int] = None) -> str:
        messages, safe_max_tokens, temperature = self._prepare(messages, temperature, max_tokens)
        response = self._post(self._base_payload(messages, temperature, safe_max_tokens))
        result = response.json()
        choice = result["choices"][0]
        self._log_choice(result, choice)
        return choice["message"]["content"]

    def complete_with_tools(self, messages: List[Dict[str, str]],
                            tools: List[Dict[str, Any]],
                            tool_choice: Optional[Dict[str, Any]] = None,
                            temperature: Optional[float] = 0.0,
                            max_tokens: Optional[int] = None) -> Dict[str, Any]:
        messages, safe_max_tokens, temperature = self._prepare(messages, temperature, max_tokens)
        payload = self._base_payload(messages, temperature, safe_max_tokens)
        payload["tools"] = tools
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

    def complete_stream(self, messages: List[Dict[str, str]],
                        temperature: Optional[float] = None,
                        max_tokens: Optional[int] = None) -> Iterator[str]:
        messages, safe_max_tokens, temperature = self._prepare(messages, temperature, max_tokens)
        payload = self._base_payload(messages, temperature, safe_max_tokens)
        payload["stream"] = True
        response = self._post(payload, stream=True)
        response.encoding = "utf-8"

        finish_reason = None
        for raw in response.iter_lines(decode_unicode=True):
            if not raw:
                continue
            line = raw.strip()
            if not line.startswith("data:"):
                continue
            payload_text = line[5:].strip()
            if payload_text == "[DONE]":
                break
            try:
                data = json.loads(payload_text)
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
