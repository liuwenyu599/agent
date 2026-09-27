"""流式生成中文编码回归测试。

覆盖两类回归：

1. **网关解码**：本地起一个 SSE 服务，故意返回不带 charset 的
   ``Content-Type: text/event-stream``（与真实模型网关一致），断言
   ``QwenGateway.complete_stream`` yield 出来的中文完全正确。
   requests 在此情况下默认按 ISO-8859-1 解码，会把 UTF-8 中文解成
   ``'è¿\\x9bä¸...'`` 乱码——本测试是该缺陷的守门用例。

2. **历史数据修复谓词**：校验 ``scripts/fix_mojibake.py`` 的判定逻辑，
   确保它既能还原乱码，又不会误伤正常中文/英文（幂等性前提）。
"""
from __future__ import annotations

import importlib.util
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Iterator, List

import pytest

from app.infrastructure.ai.qwen import QwenGateway

# ---- 测试数据 ----
CN_TEXT = "进一步加强新时代自动化建设的实施方案"
# 「UTF-8 字节被按 Latin-1 解开」的典型碎片
MOJIBAKE_MARKERS = ("Ã", "Â", "å", "æ", "è\x9b", "ä¸", "\x9b", "\x80")

# 每个 SSE 分片 3 个汉字，用于验证跨分片拼接不出错
CHUNK_SIZE = 3


def _build_events() -> List[bytes]:
    """构造 OpenAI 兼容 SSE 分片（UTF-8 编码）。"""
    events: List[bytes] = []
    for i in range(0, len(CN_TEXT), CHUNK_SIZE):
        delta = CN_TEXT[i:i + CHUNK_SIZE]
        body = {"choices": [{"delta": {"content": delta}, "finish_reason": None}]}
        events.append(f"data: {json.dumps(body, ensure_ascii=False)}\n\n".encode("utf-8"))
    events.append(b"data: [DONE]\n\n")
    return events


class _SSEHandler(BaseHTTPRequestHandler):
    """返回不带 charset 的 text/event-stream，复现真实模型网关的响应头。"""

    def do_POST(self) -> None:  # noqa: N802 - http.server 约定的方法名
        self.send_response(200)
        # 关键：故意不写 charset，触发 requests 的 ISO-8859-1 默认解码
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        try:
            for chunk in _build_events():
                self.wfile.write(chunk)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, *args: object) -> None:
        """静音：避免测试输出被访问日志刷屏。"""


@pytest.fixture(scope="module")
def sse_server() -> Iterator[str]:
    """起一个本地 SSE 服务，yield 其 base url（不含 /chat/completions）。"""
    server = HTTPServer(("127.0.0.1", 0), _SSEHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture
def gateway(sse_server: str) -> QwenGateway:
    """指向本地 SSE 服务的网关实例（不触碰真实模型服务）。"""
    return QwenGateway(
        api_url=sse_server,
        model="test-model",
        api_key="",
        timeout=10,
        ctx_limit=4096,
    )


def test_complete_stream_returns_correct_chinese(gateway: QwenGateway) -> None:
    """流式拼接结果与原文完全一致。"""
    chunks = list(gateway.complete_stream(
        [{"role": "user", "content": "写一份实施方案"}],
        temperature=0.7,
        max_tokens=512,
    ))
    assert chunks, "流式返回为空，SSE 未被正确消费"
    assert "".join(chunks) == CN_TEXT


def test_complete_stream_has_no_mojibake(gateway: QwenGateway) -> None:
    """不得出现 Latin-1 误解码产生的碎片字符。"""
    text = "".join(gateway.complete_stream(
        [{"role": "user", "content": "写一份实施方案"}],
        temperature=0.7,
        max_tokens=512,
    ))
    for marker in MOJIBAKE_MARKERS:
        assert marker not in text, f"输出含乱码碎片 {marker!r}: {text!r}"
    # 每个分片都应是可读中文
    for chunk in text.split("\n"):
        assert all(ord(ch) > 0x2000 or ch.isspace() for ch in chunk) or not chunk


def test_complete_stream_yields_multiple_chunks(gateway: QwenGateway) -> None:
    """确实是逐段 yield（而不是一次性返回），保证前端边收边显示。"""
    chunks = list(gateway.complete_stream(
        [{"role": "user", "content": "写一份实施方案"}],
        temperature=0.7,
        max_tokens=512,
    ))
    assert len(chunks) == len(range(0, len(CN_TEXT), CHUNK_SIZE)), (
        f"分片数不符: {len(chunks)}"
    )


# ---- 历史数据修复谓词 ----

def _load_fix_module():
    """按路径加载 scripts/fix_mojibake.py（该目录不是包，无法直接 import）。"""
    script = Path(__file__).resolve().parent.parent / "scripts" / "fix_mojibake.py"
    spec = importlib.util.spec_from_file_location("_fix_mojibake", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def fix_mojibake():
    return _load_fix_module().fix_mojibake


def test_fix_mojibake_restores_garbled_text(fix_mojibake) -> None:
    """乱码可逆：还原为正确中文。"""
    garbled = CN_TEXT.encode("utf-8").decode("latin-1")
    assert garbled != CN_TEXT
    assert fix_mojibake(garbled) == CN_TEXT


def test_fix_mojibake_is_idempotent(fix_mojibake) -> None:
    """二次执行不再改动，已修好的行不会被破坏（幂等性）。"""
    garbled = CN_TEXT.encode("utf-8").decode("latin-1")
    once = fix_mojibake(garbled)
    assert fix_mojibake(once) is None, "已还原的中文不得被再次处理"


@pytest.mark.parametrize("value", [
    "",                      # 空串
    None,                    # None
    "Hello, world!",         # 纯英文
    "1234567890",            # 纯数字
    CN_TEXT,                 # 正常中文（不满足 latin-1 可编码）
    "正常的中文内容 with mixed English",
])
def test_fix_mojibake_skips_normal_content(fix_mojibake, value) -> None:
    """正常内容一律跳过，避免误伤。"""
    assert fix_mojibake(value) is None
