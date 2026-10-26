"""URL 导入只能访问公开网页；跳转与建连均需再次校验。"""
import socket

import pytest

from app.application.knowledge import web_fetcher
from urllib3.connection import HTTPConnection


@pytest.mark.parametrize("url", [
    "http://127.0.0.1/", "http://10.0.0.2/", "http://169.254.169.254/latest/meta-data",
    "http://[::1]/", "http://localhost/", "file:///etc/passwd",
    "http://example.com:8001/", "http://user:pass@example.com/",
])
def test_private_or_non_web_targets_are_rejected_before_request(url, monkeypatch):
    real_resolve = socket.getaddrinfo
    monkeypatch.setattr(web_fetcher.socket, "getaddrinfo",
                        lambda host, *a, **kw: ([(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0))]
                                                 if host == "localhost" else real_resolve(host, *a, **kw)))
    result = web_fetcher.fetch_webpage(url)
    assert not result["ok"]
    assert result["error"]


def test_dns_answer_containing_private_ip_is_rejected(monkeypatch):
    monkeypatch.setattr(web_fetcher.socket, "getaddrinfo", lambda *_a, **_kw: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 0)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", 0)),
    ])
    with pytest.raises(web_fetcher.UnsafeWebAddress):
        web_fetcher._validate_web_url("https://example.gov.cn/page")


def test_redirect_to_private_target_is_blocked(monkeypatch):
    monkeypatch.setattr(web_fetcher, "_public_address", lambda _host: "8.8.8.8")
    requests_seen = []

    class Response:
        is_redirect = True
        headers = {"Location": "http://127.0.0.1/admin"}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    class Session:
        trust_env = False

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def mount(self, *_args):
            pass

        def get(self, url, **_kwargs):
            requests_seen.append(url)
            return Response()

    monkeypatch.setattr(web_fetcher.requests, "Session", Session)
    # 第二跳真实 URL 校验，不使用首跳已通过的判断结果。
    original_validate = web_fetcher._validate_web_url
    def validate(url):
        if "127.0.0.1" in url:
            raise web_fetcher.UnsafeWebAddress("private")
        return original_validate(url)
    monkeypatch.setattr(web_fetcher, "_validate_web_url", validate)
    with pytest.raises(web_fetcher.UnsafeWebAddress):
        web_fetcher._fetch_html("https://example.gov.cn/page")
    assert requests_seen == ["https://example.gov.cn/page"]


def test_connection_uses_the_checked_ip_without_second_dns_lookup(monkeypatch):
    seen = []
    monkeypatch.setattr(web_fetcher, "_public_address", lambda host: "8.8.8.8")
    monkeypatch.setattr(HTTPConnection, "_new_conn", lambda self: seen.append(self._dns_host))
    connection = web_fetcher._PublicHTTPConnection("example.gov.cn")
    connection._new_conn()
    assert seen == ["8.8.8.8"]
    assert connection.host == "example.gov.cn"
