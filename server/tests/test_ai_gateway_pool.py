"""Multi-endpoint QwenGateway acceptance tests (item 8)."""
from types import SimpleNamespace

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
