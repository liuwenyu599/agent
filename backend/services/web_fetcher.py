# -*- coding: utf-8 -*-
"""网页抓取与正文提取服务（新文件：backend/services/web_fetcher.py）

职责：给一个 URL，拿回 {ok, title, content, publish_time, source_name, url, error}。

设计要点：
- 普通网页：requests 抓取 HTML，BeautifulSoup 去脚本样式后提取正文；
- 微信公众号（mp.weixin.qq.com）：正文在 <div id="js_content">，
  标题取 og:title，来源取公众号名，刊发时间取页面内 ct 时间戳；
- 反爬/验证码/404/超时：返回 ok=False 和明确 error，绝不伪造正文；
- 编码自适应（微信公众号是 utf-8，部分老站是 gbk）。

依赖：requests、beautifulsoup4（requirements 里加 beautifulsoup4、lxml）。
"""
import re
from typing import Dict, Optional
from urllib.parse import urlparse

import requests

try:
    from bs4 import BeautifulSoup
    _HAS_BS4 = True
except ImportError:  # 未安装 bs4 时退化为正则提取，保证服务可用
    BeautifulSoup = None
    _HAS_BS4 = False

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

FETCH_TIMEOUT = 20
MAX_CONTENT_CHARS = 200000  # 入库正文上限，防止个别超长页面撑爆字段

_ANTI_BOT_HINTS = ["环境异常", "验证", "操作频繁", "访问过于频繁", "captcha", "验证身份"]


def _clean_text(text: str) -> str:
    """正文清洗：去多余空白、连续空行"""
    text = text.replace("\r", "\n")
    text = re.sub(r"[ \t　]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _fetch_html(url: str) -> str:
    resp = requests.get(url, headers={"User-Agent": UA}, timeout=FETCH_TIMEOUT,
                        allow_redirects=True)
    resp.raise_for_status()
    if not resp.encoding or resp.encoding.lower() in ("iso-8859-1",):
        resp.encoding = resp.apparent_encoding or "utf-8"
    return resp.text


def _looks_blocked(html: str) -> Optional[str]:
    head = html[:3000]
    for hint in _ANTI_BOT_HINTS:
        if hint in head:
            return f"页面触发反爬/验证（{hint}）"
    return None


def _parse_wechat(html: str, url: str) -> Dict:
    """微信公众号文章解析"""
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
    """普通网页解析"""
    if not _HAS_BS4:
        # 退化方案：去标签取纯文本
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

    # 优先 article/main，其次 body
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
    """从任意文本（如批量粘贴）中提取所有 http(s) 链接"""
    if not text:
        return []
    return re.findall(r"https?://[^\s，。；、\"'<>）)】\]]+", text)
