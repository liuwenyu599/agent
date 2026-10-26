"""网页抓取与正文提取（移植自旧 services/web_fetcher.py，行为一致）。"""
import ipaddress
import re
import socket
from typing import Dict, Optional
from urllib.parse import urljoin, urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.connection import HTTPConnection, HTTPSConnection
from urllib3.connectionpool import HTTPConnectionPool, HTTPSConnectionPool

from app.core.logging import get_logger

logger = get_logger(__name__)

try:
    from bs4 import BeautifulSoup
    _HAS_BS4 = True
except ImportError:  # 未安装 bs4 时退化为正则提取，保证服务可用
    BeautifulSoup = None
    _HAS_BS4 = False

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

FETCH_TIMEOUT = 20
MAX_CONTENT_CHARS = 200000  # 入库正文上限

_ANTI_BOT_HINTS = ["环境异常", "验证", "操作频繁", "访问过于频繁", "captcha", "验证身份"]
MAX_REDIRECTS = 5


class UnsafeWebAddress(ValueError):
    """用户链接指向内网、非网页协议或不允许的端口。"""


def _public_address(host: str) -> str:
    """只连接公开可路由地址；返回实际要建连的 IP，避免校验后再次解析。"""
    try:
        addresses = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise UnsafeWebAddress("链接域名无法解析") from exc
    if not addresses:
        raise UnsafeWebAddress("链接域名无法解析")
    ips = [item[4][0] for item in addresses]
    if any(not ipaddress.ip_address(ip).is_global for ip in ips):
        raise UnsafeWebAddress("链接指向内网或非公开地址，禁止导入")
    return ips[0]


def _validate_web_url(url: str) -> None:
    parsed = urlparse(url)
    if (parsed.scheme not in ("http", "https") or not parsed.hostname or
            parsed.username or parsed.password or parsed.fragment):
        raise UnsafeWebAddress("仅允许公开网站的 http(s) 链接")
    try:
        port = parsed.port
    except ValueError as exc:
        raise UnsafeWebAddress("链接端口无效") from exc
    if port not in (None, 80, 443):
        raise UnsafeWebAddress("仅允许 80 或 443 端口的网页链接")
    _public_address(parsed.hostname)


class _PublicHTTPConnection(HTTPConnection):
    def _new_conn(self):
        original = self._dns_host
        try:
            self._dns_host = _public_address(original)
            return super()._new_conn()
        finally:
            self._dns_host = original


class _PublicHTTPSConnection(HTTPSConnection):
    def _new_conn(self):
        original = self._dns_host
        try:
            self._dns_host = _public_address(original)
            return super()._new_conn()
        finally:
            self._dns_host = original


class _PublicHTTPPool(HTTPConnectionPool):
    ConnectionCls = _PublicHTTPConnection


class _PublicHTTPSPool(HTTPSConnectionPool):
    ConnectionCls = _PublicHTTPSConnection


class _PublicOnlyAdapter(HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        super().init_poolmanager(*args, **kwargs)
        self.poolmanager.pool_classes_by_scheme = {
            "http": _PublicHTTPPool, "https": _PublicHTTPSPool,
        }


def _clean_text(text: str) -> str:
    text = text.replace("\r", "\n")
    text = re.sub(r"[ \t　]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _fetch_html(url: str) -> str:
    with requests.Session() as session:
        session.trust_env = False  # 环境代理不得绕过目标 IP 校验
        adapter = _PublicOnlyAdapter()
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        current = url
        for _ in range(MAX_REDIRECTS + 1):
            _validate_web_url(current)
            with session.get(current, headers={"User-Agent": UA}, timeout=FETCH_TIMEOUT,
                             allow_redirects=False, stream=True) as resp:
                if resp.is_redirect:
                    location = resp.headers.get("Location")
                    if not location:
                        raise UnsafeWebAddress("跳转链接缺少目标地址")
                    current = urljoin(current, location)
                    continue
                resp.raise_for_status()
                if not resp.encoding or resp.encoding.lower() in ("iso-8859-1",):
                    resp.encoding = resp.apparent_encoding or "utf-8"
                return resp.text
    raise UnsafeWebAddress("网页跳转次数过多")


def _looks_blocked(html: str) -> Optional[str]:
    head = html[:3000]
    for hint in _ANTI_BOT_HINTS:
        if hint in head:
            return f"页面触发反爬/验证（{hint}）"
    return None


def _parse_wechat(html: str, url: str) -> Dict:
    if not _HAS_BS4:
        return {"ok": False, "error": "服务器缺少 beautifulsoup4，无法解析公众号页面"}

    soup = BeautifulSoup(html, "lxml")

    title = ""
    og = soup.find("meta", attrs={"property": "og:title"})
    if og and og.get("content"):
        title = og["content"].strip()
    if not title:
        t = soup.find("h1", id="activity-name") or soup.title
        title = t.get_text(strip=True) if t else ""

    source_name = ""
    author_tag = soup.find("span", id="js_author_name") or soup.find("em", id="js_author_name")
    if author_tag:
        source_name = author_tag.get_text(strip=True)
    if not source_name:
        m = re.search(r'var\s+(?:nick_name|nickname)\s*=\s*[\'"]([^\'"]+)[\'"]', html)
        if m:
            source_name = m.group(1)

    publish_time = ""
    m = re.search(r'var\s+ct\s*=\s*"?(\d{9,11})"?', html)
    if m:
        from datetime import datetime
        publish_time = datetime.fromtimestamp(int(m.group(1))).strftime("%Y-%m-%d %H:%M:%S")

    body = soup.find("div", id="js_content")
    if not body:
        blocked = _looks_blocked(html)
        return {"ok": False,
                "error": blocked or "未找到公众号正文（可能已删除、需验证或链接已失效）"}
    content = _clean_text(body.get_text("\n"))
    if len(content) < 30:
        blocked = _looks_blocked(html)
        return {"ok": False,
                "error": blocked or "正文内容为空或过短（可能需微信环境访问）"}

    return {"ok": True, "title": title, "content": content[:MAX_CONTENT_CHARS],
            "publish_time": publish_time, "source_name": source_name}


def _parse_generic(html: str, url: str) -> Dict:
    if not _HAS_BS4:
        text = re.sub(r"(?is)<(script|style).*?</\1>", "", html)
        text = re.sub(r"(?s)<[^>]+>", "\n", text)
        m = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
        title = m.group(1).strip() if m else ""
        content = _clean_text(text)
        if len(content) < 30:
            return {"ok": False, "error": "未能提取到有效正文"}
        return {"ok": True, "title": title, "content": content[:MAX_CONTENT_CHARS],
                "publish_time": "", "source_name": urlparse(url).netloc}

    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript", "header", "footer", "nav", "aside"]):
        tag.decompose()

    title = ""
    og = soup.find("meta", attrs={"property": "og:title"})
    if og and og.get("content"):
        title = og["content"].strip()
    if not title and soup.title:
        title = soup.title.get_text(strip=True)

    node = soup.find("article") or soup.find("main") or soup.body or soup
    content = _clean_text(node.get_text("\n"))
    if len(content) < 30:
        blocked = _looks_blocked(html)
        return {"ok": False, "error": blocked or "未能提取到有效正文"}

    publish_time = ""
    m = re.search(r"(20\d{2}[-/年]\d{1,2}[-/月]\d{1,2})", html[:20000])
    if m:
        publish_time = m.group(1).replace("年", "-").replace("月", "-").replace("日", "").replace("/", "-")

    return {"ok": True, "title": title, "content": content[:MAX_CONTENT_CHARS],
            "publish_time": publish_time, "source_name": urlparse(url).netloc}


def fetch_webpage(url: str) -> Dict:
    """抓取并解析一个网页。返回统一结构，失败时 ok=False 且带明确 error。"""
    url = (url or "").strip()
    result = {"ok": False, "title": "", "content": "", "publish_time": "",
              "source_name": "", "url": url, "error": ""}

    if not re.match(r"^https?://", url):
        result["error"] = "不是合法的 http(s) 链接"
        return result

    try:
        html = _fetch_html(url)
    except UnsafeWebAddress as e:
        result["error"] = str(e)
        return result
    except requests.exceptions.Timeout:
        result["error"] = "访问超时"
        return result
    except requests.exceptions.HTTPError as e:
        code = e.response.status_code if e.response is not None else "?"
        result["error"] = f"HTTP {code}（页面不存在或拒绝访问）"
        return result
    except requests.exceptions.SSLError:
        result["error"] = "HTTPS 证书校验失败"
        return result
    except Exception as e:
        result["error"] = f"抓取失败: {e}"
        return result

    blocked = _looks_blocked(html)
    if blocked:
        result["error"] = blocked
        return result

    try:
        if "mp.weixin.qq.com" in url:
            parsed = _parse_wechat(html, url)
        else:
            parsed = _parse_generic(html, url)
    except Exception as e:
        result["error"] = f"解析失败: {e}"
        return result

    result.update(parsed)
    result["url"] = url
    return result


def looks_like_url(text: str) -> bool:
    return bool(re.match(r"^https?://\S+$", (text or "").strip()))


def extract_urls_from_text(text: str) -> list:
    """从任意文本中提取所有 http(s) 链接"""
    if not text:
        return []
    return re.findall(r"https?://[^\s，。；、\"'<>）)】\]]+", text)
