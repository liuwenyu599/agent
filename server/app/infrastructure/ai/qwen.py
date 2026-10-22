"""AI Gateway：Qwen 适配器（OpenAI 兼容 chat/completions）。

业务模块一律通过 application.ports.LLMGateway 调用，禁止直接 HTTP 调模型服务。
生产请求优先使用 acomplete / acomplete_with_tools / acomplete_stream；同步方法仅保留给
尚未迁移的离线脚本与兼容测试，并禁止在已有 event loop 内调用。
"""
from __future__ import annotations

import asyncio
import json
import os
import threading
import time
import weakref
from typing import Any, AsyncIterator, Dict, Iterator, List, Optional, Tuple

import httpx

from app.core.config import settings
from app.core.exceptions import AIServiceError
from app.core.logging import get_logger

logger = get_logger(__name__)

_IMAGE_TOKEN_ALLOWANCE = 1200
_DEFAULT_REPETITION_PENALTY = 1.08
_DEFAULT_MAX_CONCURRENCY = 4


class QwenGateway:
    """Qwen Model Service 适配器（vLLM / 任何 OpenAI 兼容端点）。"""

    def __init__(self, api_url: Optional[str] = None,
                 api_urls: Optional[List[str]] = None,
                 model: Optional[str] = None,
                 api_key: Optional[str] = None, timeout: Optional[int] = None,
                 ctx_limit: Optional[int] = None,
                 max_concurrency: Optional[int] = None,
                 extra_body: Optional[Dict[str, Any]] = None) -> None:
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
        configured_concurrency = (
            max_concurrency if max_concurrency is not None
            else getattr(settings, "MODEL_MAX_CONCURRENCY", _DEFAULT_MAX_CONCURRENCY)
        )
        self.max_concurrency = max(1, int(configured_concurrency))
        # 透传到每次 chat/completions 请求的额外字段（如关闭思考模型的
        # {"chat_template_kwargs": {"enable_thinking": False}}）。长文网关用它关掉 35B 的思考。
        self.extra_body = dict(extra_body) if extra_body else {}
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
        # AsyncClient 与 asyncio.Semaphore 都不应跨 event loop 复用。网关是进程级单例，
        # 测试和脚本可能反复 asyncio.run，因此按 loop 懒建 limiter。
        self._loop_limiters: "weakref.WeakKeyDictionary[Any, asyncio.Semaphore]" = (
            weakref.WeakKeyDictionary()
        )

    @property
    def model_name(self) -> str:
        return self.model

    @property
    def endpoint_count(self) -> int:
        return len(self.api_urls)

    def _limiter(self) -> asyncio.Semaphore:
        loop = asyncio.get_running_loop()
        with self._pool_lock:
            limiter = self._loop_limiters.get(loop)
            if limiter is None:
                limiter = asyncio.Semaphore(self.max_concurrency)
                self._loop_limiters[loop] = limiter
            return limiter

    @staticmethod
    def _run_sync(coro):
        """Compatibility bridge for non-async callers only.

        Blocking an ASGI event loop while a model may take hundreds of seconds is forbidden. Any
        async route must call the native async API instead of this bridge.
        """
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)
        if hasattr(coro, "close"):
            coro.close()
        raise RuntimeError("QwenGateway sync API cannot run inside an event loop; use acomplete()")

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
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "top_p": 0.9,
            "repetition_penalty": self.repetition_penalty,
        }
        if self.extra_body:
            payload.update(self.extra_body)
        return payload

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

    async def ahealth(self) -> List[Dict[str, Any]]:
        result: List[Dict[str, Any]] = []
        timeout = httpx.Timeout(self.health_timeout)
        async with httpx.AsyncClient(timeout=timeout) as client:
            for url in self.api_urls:
                started = time.monotonic()
                try:
                    response = await client.get(f"{url}/models", headers=self._headers())
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
                except httpx.HTTPError as exc:
                    self._mark_failed(url, type(exc).__name__)
                    result.append({
                        "url": url, "healthy": False, "status_code": None,
                        "latency_ms": int((time.monotonic() - started) * 1000),
                    })
        return result

    def health(self) -> List[Dict[str, Any]]:
        return self._run_sync(self.ahealth())

    async def _apost(self, payload: Dict[str, Any]) -> httpx.Response:
        failures: List[str] = []
        timeout = httpx.Timeout(self.timeout)
        queued_at = time.monotonic()
        async with self._limiter():
            logger.info("[模型耗时] 并发等待 %.3fs", time.monotonic() - queued_at)
            async with httpx.AsyncClient(timeout=timeout) as client:
                for url in self._endpoint_order():
                    self._acquire(url)
                    try:
                        request_at = time.monotonic()
                        response = await client.post(
                            f"{url}/chat/completions",
                            headers=self._headers(),
                            json=payload,
                        )
                        if response.status_code == 429 or response.status_code >= 500:
                            detail = response.text[:200]
                            self._mark_failed(url, f"HTTP {response.status_code}")
                            failures.append(f"{url}: HTTP {response.status_code} {detail}")
                            continue
                        response.raise_for_status()
                        logger.info("[模型耗时] 非流式响应 %.3fs", time.monotonic() - request_at)
                        if url != self.api_url:
                            logger.info("[AI网关] 请求由备用 endpoint 完成: %s", url)
                        return response
                    except (httpx.ConnectError, httpx.TimeoutException) as exc:
                        self._mark_failed(url, type(exc).__name__)
                        failures.append(f"{url}: {type(exc).__name__}")
                        continue
                    except httpx.HTTPStatusError as exc:
                        detail = exc.response.text[:500] if exc.response is not None else str(exc)
                        logger.error("[AI网关] HTTP 错误（不切换节点）: %s", detail)
                        raise AIServiceError("模型调用失败") from exc
                    except httpx.TransportError as exc:
                        self._mark_failed(url, type(exc).__name__)
                        failures.append(f"{url}: {type(exc).__name__}")
                        continue
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

    async def acomplete(self, messages: List[Dict[str, str]],
                        temperature: Optional[float] = None,
                        max_tokens: Optional[int] = None) -> str:
        messages, safe_max_tokens, temperature = self._prepare(messages, temperature, max_tokens)
        response = await self._apost(self._base_payload(messages, temperature, safe_max_tokens))
        result = response.json()
        choice = result["choices"][0]
        self._log_choice(result, choice)
        return choice["message"]["content"]

    def complete(self, messages: List[Dict[str, str]],
                 temperature: Optional[float] = None,
                 max_tokens: Optional[int] = None) -> str:
        return self._run_sync(self.acomplete(messages, temperature, max_tokens))

    async def acomplete_with_tools(self, messages: List[Dict[str, str]],
                                   tools: List[Dict[str, Any]],
                                   tool_choice: Optional[Dict[str, Any]] = None,
                                   temperature: Optional[float] = 0.0,
                                   max_tokens: Optional[int] = None) -> Dict[str, Any]:
        messages, safe_max_tokens, temperature = self._prepare(messages, temperature, max_tokens)
        payload = self._base_payload(messages, temperature, safe_max_tokens)
        payload["tools"] = tools
        if tool_choice is not None:
            payload["tool_choice"] = tool_choice
        response = await self._apost(payload)
        result = response.json()
        choice = result["choices"][0]
        self._log_choice(result, choice)
        message = choice.get("message") or {}
        return {
            "role": message.get("role") or "assistant",
            "content": message.get("content") or "",
            "tool_calls": message.get("tool_calls") or [],
        }

    def complete_with_tools(self, messages: List[Dict[str, str]],
                            tools: List[Dict[str, Any]],
                            tool_choice: Optional[Dict[str, Any]] = None,
                            temperature: Optional[float] = 0.0,
                            max_tokens: Optional[int] = None) -> Dict[str, Any]:
        return self._run_sync(self.acomplete_with_tools(
            messages, tools, tool_choice, temperature, max_tokens
        ))

    async def acomplete_stream(self, messages: List[Dict[str, str]],
                               temperature: Optional[float] = None,
                               max_tokens: Optional[int] = None) -> AsyncIterator[str]:
        messages, safe_max_tokens, temperature = self._prepare(messages, temperature, max_tokens)
        payload = self._base_payload(messages, temperature, safe_max_tokens)
        payload["stream"] = True
        failures: List[str] = []
        timeout = httpx.Timeout(self.timeout)
        queued_at = time.monotonic()
        async with self._limiter():
            logger.info("[模型耗时] 流式并发等待 %.3fs", time.monotonic() - queued_at)
            async with httpx.AsyncClient(timeout=timeout) as client:
                for url in self._endpoint_order():
                    self._acquire(url)
                    try:
                        request_at = time.monotonic()
                        first_chunk = True
                        async with client.stream(
                            "POST",
                            f"{url}/chat/completions",
                            headers=self._headers(),
                            json=payload,
                        ) as response:
                            if response.status_code == 429 or response.status_code >= 500:
                                await response.aread()
                                detail = response.text[:200]
                                self._mark_failed(url, f"HTTP {response.status_code}")
                                failures.append(f"{url}: HTTP {response.status_code} {detail}")
                                continue
                            response.raise_for_status()
                            if url != self.api_url:
                                logger.info("[AI网关] 流式请求由备用 endpoint 完成: %s", url)
                            finish_reason = None
                            async for raw in response.aiter_lines():
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
                                        if first_chunk:
                                            logger.info("[模型耗时] 流式首字 %.3fs",
                                                        time.monotonic() - request_at)
                                            first_chunk = False
                                        yield delta
                            if finish_reason == "length":
                                logger.warning("[AI网关] 流式输出被 max_tokens 截断")
                            return
                    except (httpx.ConnectError, httpx.TimeoutException) as exc:
                        self._mark_failed(url, type(exc).__name__)
                        failures.append(f"{url}: {type(exc).__name__}")
                        continue
                    except httpx.HTTPStatusError as exc:
                        detail = exc.response.text[:500] if exc.response is not None else str(exc)
                        logger.error("[AI网关] HTTP 错误（不切换节点）: %s", detail)
                        raise AIServiceError("模型调用失败") from exc
                    except httpx.TransportError as exc:
                        self._mark_failed(url, type(exc).__name__)
                        failures.append(f"{url}: {type(exc).__name__}")
                        continue
                    finally:
                        self._release(url)

        logger.error("[AI网关] 所有 endpoint 流式调用失败: %s", " | ".join(failures))
        if any("Timeout" in item for item in failures):
            raise AIServiceError("模型服务响应超时")
        raise AIServiceError("模型服务暂时不可用")

    async def _collect_stream(self, messages: List[Dict[str, str]],
                              temperature: Optional[float],
                              max_tokens: Optional[int]) -> List[str]:
        out: List[str] = []
        async for chunk in self.acomplete_stream(messages, temperature, max_tokens):
            out.append(chunk)
        return out

    def complete_stream(self, messages: List[Dict[str, str]],
                        temperature: Optional[float] = None,
                        max_tokens: Optional[int] = None) -> Iterator[str]:
        # Legacy compatibility only. Production SSE routes use acomplete_stream and stay streaming.
        chunks = self._run_sync(self._collect_stream(messages, temperature, max_tokens))
        yield from chunks

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
