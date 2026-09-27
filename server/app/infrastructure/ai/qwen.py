"""AI Gateway：Qwen 适配器（OpenAI 兼容 chat/completions）。

业务模块一律通过 application.ports.LLMGateway 调用，禁止直接 HTTP 调模型服务。
"""
import json
from typing import Dict, Iterator, List, Optional, Tuple

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

    # ---- 请求准备（complete 与 complete_stream 共用） ----

    def _prepare(self, messages: List[Dict[str, str]],
                 temperature: Optional[float],
                 max_tokens: Optional[int]) -> Tuple[List[Dict[str, str]], int, float]:
        """上下文预算保护：返回 (裁剪后消息, 安全 max_tokens, 温度)。"""
        # 不传时取全局配置：温度与最大输出统一由 .env 调节，不再硬编码
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
        logger.info(
            "[AI网关] finish_reason: %s, usage: %s",
            choice.get("finish_reason"), result.get("usage"),
        )
        if choice.get("finish_reason") == "length":
            logger.warning("[AI网关] 输出被 max_tokens 截断")
        return choice["message"]["content"]

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

        # requests 在响应头未声明 charset 时按 ISO-8859-1 解码（HTTP 文本类型的历史默认），
        # 会把模型返回的 UTF-8 中文解成 'è¿\x9bä¸...' 乱码并随 delta 落库。
        # OpenAI 兼容端点的 SSE data 载荷是 JSON（RFC 8259 规定 UTF-8），故直接声明 UTF-8：
        # 不用 apparent_encoding，因为它会读 r.content 把整个响应缓冲进内存，
        # 使 stream=True 失去边收边发的意义（实测 _content_consumed=True）。
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
                # 多模态消息：统计文本部分字符，图片按固定额度计入
                for part in c:
                    if part.get("type") == "text":
                        chars += len(part.get("text", ""))
                    elif part.get("type") == "image_url":
                        images += 1
            else:
                chars += len(c)
        return int(chars / 0.75) + images * _IMAGE_TOKEN_ALLOWANCE  # 中文约 1 字 ≈ 1 token，偏保守按 0.75 字/token

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
            return messages  # 多模态 system 不截断（实际不会出现）
        if len(content) > sys_char_budget:
            content = content[:sys_char_budget] + "\n（上下文过长，参考材料已按长度截断）"
        return [{"role": "system", "content": content}] + others
