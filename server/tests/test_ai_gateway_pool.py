"""Multi-endpoint QwenGateway acceptance tests (items 8 and 11)."""
import requests

from app.infrastructure.ai.qwen import QwenGateway


class _Response:
    def __init__(self, status_code=200, content="ok"):
        self.status_code = status_code
        self.text = content
        self.encoding = "utf-8"

    def raise_for_status(self):
        if self.status_code >= 400:
            error = requests.HTTPError(f"HTTP {self.status_code}")
            error.response = self
            raise error

    def json(self):
        return {
            "choices": [{"finish_reason": "stop", "message": {"content": "ok"}}],
            "usage": {},
        }

    def iter_lines(self, decode_unicode=True):
        yield 'data: {"choices":[{"delta":{"content":"ok"},"finish_reason":"stop"}]}'
        yield "data: [DONE]"


def _gateway():
    return QwenGateway(
        api_urls=["http://model-a/v1", "http://model-b/v1"],
        model="same-model", timeout=3, ctx_limit=4096,
    )


def test_round_robin_breaks_ties_between_equally_loaded_endpoints(monkeypatch):
    calls = []

    def post(url, **kwargs):
        calls.append(url)
        return _Response()

    monkeypatch.setattr(requests, "post", post)
    gateway = _gateway()
    for _ in range(4):
        assert gateway.complete([{"role": "user", "content": "hello"}], max_tokens=32) == "ok"

    assert calls == [
        "http://model-a/v1/chat/completions",
        "http://model-b/v1/chat/completions",
        "http://model-a/v1/chat/completions",
        "http://model-b/v1/chat/completions",
    ]


def test_connection_failure_switches_to_next_endpoint(monkeypatch):
    calls = []

    def post(url, **kwargs):
        calls.append(url)
        if "model-a" in url:
            raise requests.ConnectionError("down")
        return _Response()

    monkeypatch.setattr(requests, "post", post)
    gateway = _gateway()
    assert gateway.complete([{"role": "user", "content": "hello"}], max_tokens=32) == "ok"
    assert calls == [
        "http://model-a/v1/chat/completions",
        "http://model-b/v1/chat/completions",
    ]


def test_5xx_switches_but_4xx_does_not(monkeypatch):
    calls = []

    def post_5xx(url, **kwargs):
        calls.append(url)
        return _Response(503) if "model-a" in url else _Response(200)

    monkeypatch.setattr(requests, "post", post_5xx)
    gateway = _gateway()
    assert gateway.complete([{"role": "user", "content": "hello"}], max_tokens=32) == "ok"
    assert len(calls) == 2


def test_health_probes_every_endpoint(monkeypatch):
    calls = []

    def get(url, **kwargs):
        calls.append(url)
        return _Response(200 if "model-a" in url else 503)

    monkeypatch.setattr(requests, "get", get)
    result = _gateway().health()
    assert calls == ["http://model-a/v1/models", "http://model-b/v1/models"]
    assert result[0]["healthy"] is True
    assert result[1]["healthy"] is False


def test_repetition_penalty_is_sent_for_normal_tool_and_stream_calls(monkeypatch):
    payloads = []

    def post(url, **kwargs):
        payloads.append(kwargs["json"])
        response = _Response()
        if kwargs["json"].get("tools"):
            response.json = lambda: {
                "choices": [{"finish_reason": "tool_calls", "message": {
                    "role": "assistant", "content": "", "tool_calls": []}}],
                "usage": {},
            }
        return response

    monkeypatch.setenv("MODEL_REPETITION_PENALTY", "1.12")
    monkeypatch.setattr(requests, "post", post)
    gateway = _gateway()
    messages = [{"role": "user", "content": "hello"}]

    gateway.complete(messages, max_tokens=32)
    gateway.complete_with_tools(messages, tools=[{
        "type": "function",
        "function": {"name": "noop", "parameters": {"type": "object", "properties": {}}},
    }], max_tokens=32)
    assert "".join(gateway.complete_stream(messages, max_tokens=32)) == "ok"

    assert len(payloads) == 3
    assert all(p["repetition_penalty"] == 1.12 for p in payloads)
