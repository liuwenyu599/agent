"""Multi-endpoint async QwenGateway acceptance tests (items 6, 8 and 11)."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import threading
import time

import httpx

from app.infrastructure.ai.qwen import (QwenGateway, _ModelCapacity,
                                        model_request_class, set_model_request_user)


def test_model_admission_round_robins_users_and_limits_per_user():
    async def run():
        pool = _ModelCapacity(1)
        order = []
        release = asyncio.Event()

        async def job(user, label, hold=False):
            set_model_request_user(user)
            async with pool.slot():
                order.append(label)
                if hold:
                    await release.wait()

        first = asyncio.create_task(job("a", "a1", True))
        await asyncio.sleep(0.01)
        second = asyncio.create_task(job("a", "a2"))
        await asyncio.sleep(0.01)
        other = asyncio.create_task(job("b", "b1"))
        await asyncio.sleep(0.01)
        release.set()
        await asyncio.gather(first, second, other)
        assert order == ["a1", "b1", "a2"]

    asyncio.run(run())


def test_model_admission_enforces_user_inflight_quota():
    async def run():
        pool = _ModelCapacity(3)
        pool.user_limit = 1
        release = asyncio.Event()
        active = []

        async def job(user):
            set_model_request_user(user)
            async with pool.slot():
                active.append(user)
                await release.wait()

        first = asyncio.create_task(job("a"))
        second = asyncio.create_task(job("a"))
        other = asyncio.create_task(job("b"))
        await asyncio.sleep(0.03)
        assert active.count("a") == 1
        assert active.count("b") == 1
        release.set()
        await asyncio.gather(first, second, other)
        assert active.count("a") == 2

    asyncio.run(run())


def _response(status_code=200, *, tool=False):
    message = {"role": "assistant", "content": "ok"}
    finish = "stop"
    if tool:
        message = {"role": "assistant", "content": "", "tool_calls": []}
        finish = "tool_calls"
    return httpx.Response(
        status_code,
        request=httpx.Request("POST", "http://test/chat/completions"),
        json={"choices": [{"finish_reason": finish, "message": message}], "usage": {}},
    )


class _StreamResponse:
    def __init__(self, status_code=200):
        self.status_code = status_code
        self._body = b""
        self.request = httpx.Request("POST", "http://test/chat/completions")

    @property
    def text(self):
        return self._body.decode("utf-8", errors="ignore")

    async def aread(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            response = httpx.Response(self.status_code, request=self.request)
            raise httpx.HTTPStatusError("error", request=self.request, response=response)

    async def aiter_lines(self):
        yield 'data: {"choices":[{"delta":{"content":"ok"},"finish_reason":"stop"}]}'
        yield "data: [DONE]"


class _StreamContext:
    def __init__(self, response):
        self.response = response

    async def __aenter__(self):
        return self.response

    async def __aexit__(self, *args):
        return False


class _Client:
    def __init__(self, *, post_handler=None, get_handler=None, stream_handler=None, **kwargs):
        self.post_handler = post_handler
        self.get_handler = get_handler
        self.stream_handler = stream_handler

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, **kwargs):
        return await self.post_handler(url, **kwargs)

    async def get(self, url, **kwargs):
        return await self.get_handler(url, **kwargs)

    def stream(self, method, url, **kwargs):
        return _StreamContext(self.stream_handler(url, **kwargs))


def _gateway(max_concurrency=4):
    return QwenGateway(
        api_urls=["http://model-a/v1", "http://model-b/v1"],
        model="same-model", timeout=3, ctx_limit=4096,
        max_concurrency=max_concurrency,
    )


def _install_client(monkeypatch, *, post=None, get=None, stream=None):
    async def default_post(url, **kwargs):
        return _response()

    async def default_get(url, **kwargs):
        return httpx.Response(200, request=httpx.Request("GET", url), json={})

    def default_stream(url, **kwargs):
        return _StreamResponse()

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: _Client(
            post_handler=post or default_post,
            get_handler=get or default_get,
            stream_handler=stream or default_stream,
            **kwargs,
        ),
    )


def test_round_robin_breaks_ties_between_equally_loaded_endpoints(monkeypatch):
    calls = []

    async def post(url, **kwargs):
        calls.append(url)
        return _response()

    _install_client(monkeypatch, post=post)
    gateway = _gateway()

    async def run():
        for _ in range(4):
            assert await gateway.acomplete(
                [{"role": "user", "content": "hello"}], max_tokens=32) == "ok"

    asyncio.run(run())
    assert calls == [
        "http://model-a/v1/chat/completions",
        "http://model-b/v1/chat/completions",
        "http://model-a/v1/chat/completions",
        "http://model-b/v1/chat/completions",
    ]


def test_connection_failure_switches_to_next_endpoint(monkeypatch):
    calls = []

    async def post(url, **kwargs):
        calls.append(url)
        if "model-a" in url:
            request = httpx.Request("POST", url)
            raise httpx.ConnectError("down", request=request)
        return _response()

    _install_client(monkeypatch, post=post)
    gateway = _gateway()
    result = asyncio.run(gateway.acomplete(
        [{"role": "user", "content": "hello"}], max_tokens=32))
    assert result == "ok"
    assert calls == [
        "http://model-a/v1/chat/completions",
        "http://model-b/v1/chat/completions",
    ]


def test_5xx_switches_but_4xx_does_not(monkeypatch):
    calls = []

    async def post(url, **kwargs):
        calls.append(url)
        return _response(503) if "model-a" in url else _response(200)

    _install_client(monkeypatch, post=post)
    assert asyncio.run(_gateway().acomplete(
        [{"role": "user", "content": "hello"}], max_tokens=32)) == "ok"
    assert len(calls) == 2


def test_rate_limit_retries_without_switching_model_endpoint(monkeypatch):
    from app.infrastructure.ai import qwen

    calls = []

    async def post(url, **kwargs):
        calls.append(url)
        return _response(429 if len(calls) == 1 else 200)

    monkeypatch.setattr(qwen, "_RETRY_BACKOFF", 0)
    _install_client(monkeypatch, post=post)
    gateway = _gateway()
    assert asyncio.run(gateway.acomplete(
        [{"role": "user", "content": "hello"}], max_tokens=32)) == "ok"
    assert calls == ["http://model-a/v1/chat/completions"] * 2


def test_health_probes_every_endpoint(monkeypatch):
    calls = []

    async def get(url, **kwargs):
        calls.append(url)
        status = 200 if "model-a" in url else 503
        return httpx.Response(status, request=httpx.Request("GET", url), json={})

    _install_client(monkeypatch, get=get)
    result = asyncio.run(_gateway().ahealth())
    assert calls == ["http://model-a/v1/models", "http://model-b/v1/models"]
    assert result[0]["healthy"] is True
    assert result[1]["healthy"] is False


def test_repetition_penalty_is_sent_for_normal_tool_and_stream_calls(monkeypatch):
    payloads = []

    async def post(url, **kwargs):
        payloads.append(kwargs["json"])
        return _response(tool=bool(kwargs["json"].get("tools")))

    def stream(url, **kwargs):
        payloads.append(kwargs["json"])
        return _StreamResponse()

    monkeypatch.setenv("MODEL_REPETITION_PENALTY", "1.12")
    _install_client(monkeypatch, post=post, stream=stream)
    gateway = _gateway()
    messages = [{"role": "user", "content": "hello"}]

    async def run():
        await gateway.acomplete(messages, max_tokens=32)
        await gateway.acomplete_with_tools(messages, tools=[{
            "type": "function",
            "function": {"name": "noop", "parameters": {"type": "object", "properties": {}}},
        }], max_tokens=32)
        chunks = []
        async for chunk in gateway.acomplete_stream(messages, max_tokens=32):
            chunks.append(chunk)
        assert "".join(chunks) == "ok"

    asyncio.run(run())
    assert len(payloads) == 3
    assert all(p["repetition_penalty"] == 1.12 for p in payloads)


def test_async_concurrency_cap_waits_without_exceeding_limit(monkeypatch):
    active = 0
    peak = 0
    lock = asyncio.Lock()

    async def post(url, **kwargs):
        nonlocal active, peak
        async with lock:
            active += 1
            peak = max(peak, active)
        await asyncio.sleep(0.02)
        async with lock:
            active -= 1
        return _response()

    _install_client(monkeypatch, post=post)
    gateway = _gateway(max_concurrency=2)

    async def run():
        await asyncio.gather(*[
            gateway.acomplete([{"role": "user", "content": f"hello {i}"}], max_tokens=32)
            for i in range(6)
        ])

    asyncio.run(run())
    assert peak == 2


def test_concurrency_cap_is_shared_across_threads_and_gateway_instances(monkeypatch):
    active = 0
    peak = 0
    lock = threading.Lock()

    async def post(url, **kwargs):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        await asyncio.sleep(0.04)
        with lock:
            active -= 1
        return _response()

    _install_client(monkeypatch, post=post)
    gateways = [_gateway(max_concurrency=2), _gateway(max_concurrency=2)]
    with ThreadPoolExecutor(max_workers=6) as workers:
        results = list(workers.map(
            lambda i: gateways[i % 2].complete(
                [{"role": "user", "content": str(i)}], max_tokens=32),
            range(6),
        ))
    assert results == ["ok"] * 6
    assert peak == 2


def test_background_calls_leave_capacity_for_interactive_requests(monkeypatch):
    entered = threading.Event()
    release = threading.Event()
    lock = threading.Lock()
    active_background = 0
    peak_background = 0

    async def post(url, **kwargs):
        nonlocal active_background, peak_background
        content = kwargs["json"]["messages"][-1]["content"]
        if content == "background":
            with lock:
                active_background += 1
                peak_background = max(peak_background, active_background)
                entered.set()
            while not release.is_set():
                await asyncio.sleep(0.005)
            with lock:
                active_background -= 1
        return _response()

    _install_client(monkeypatch, post=post)
    gateway = _gateway(max_concurrency=2)

    def background_call():
        with model_request_class("background"):
            return gateway.complete([{"role": "user", "content": "background"}], max_tokens=32)

    with ThreadPoolExecutor(max_workers=3) as workers:
        first = workers.submit(background_call)
        assert entered.wait(1)
        second = workers.submit(background_call)
        try:
            interactive = workers.submit(
                gateway.complete, [{"role": "user", "content": "interactive"}],
                max_tokens=32,
            )
            assert interactive.result(timeout=1) == "ok"
            time.sleep(0.05)
            assert peak_background == 1
        finally:
            release.set()
        assert first.result(timeout=1) == "ok"
        assert second.result(timeout=1) == "ok"


def test_sync_bridge_refuses_to_block_running_event_loop():
    gateway = _gateway()

    async def run():
        try:
            gateway.complete([{"role": "user", "content": "hello"}], max_tokens=32)
        except RuntimeError as exc:
            assert "event loop" in str(exc)
        else:
            raise AssertionError("sync gateway call should be rejected inside event loop")

    asyncio.run(run())
