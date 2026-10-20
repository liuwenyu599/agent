"""AI Gateway 工厂：按配置返回模型适配器（Qwen / Mock）。

多服务拆分：
- 文本模型（MODEL_*）：写作 / 问答 / 意图理解等全部文本链路；
- 视觉模型（VISION_*，可选）：对话中带图片附件时路由到视觉服务（Qwen2.5-VL 等）。
- PPT 模型（PPT_*，可选）：DeepPresenter-9B 独立服务，PPT 助手的大纲 / 逐页编辑专用。

MODEL_SERVICE_URLS / PPT_MODEL_URLS 可配置逗号分隔的同模型副本；未配置时完全
兼容原单 endpoint 变量。负载分配与失败切换由 QwenGateway 统一处理。
"""
import os
from typing import List, Optional

from app.application.ports import LLMGateway
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_gateway: LLMGateway = None
_vision_gateway: LLMGateway = None
_vision_loaded = False
_ppt_gateway: LLMGateway = None
_ppt_loaded = False
_long_form_gateway: LLMGateway = None
_long_form_loaded = False


def _endpoint_urls(env_name: str, fallback: str) -> List[str]:
    raw = os.getenv(env_name, "")
    values = raw.split(",") if raw.strip() else [fallback]
    out: List[str] = []
    for value in values:
        url = (value or "").strip().rstrip("/")
        if url and url not in out:
            out.append(url)
    return out


def get_llm_gateway() -> LLMGateway:
    global _gateway
    if _gateway is not None:
        return _gateway
    if os.getenv("AI_PROVIDER", "auto") == "mock":
        from app.infrastructure.ai.mock import MockLLMGateway
        _gateway = MockLLMGateway()
    else:
        from app.infrastructure.ai.qwen import QwenGateway
        _gateway = QwenGateway(
            api_urls=_endpoint_urls("MODEL_SERVICE_URLS", settings.MODEL_SERVICE_URL)
        )
    logger.info("[AI网关] 当前适配器: %s (%s, endpoints=%s)",
                type(_gateway).__name__, _gateway.model_name,
                getattr(_gateway, "endpoint_count", 1))
    return _gateway


def get_vision_gateway() -> LLMGateway:
    """视觉模型网关；未配置 VISION_MODEL_URL 时返回 None（不影响文本链路）。"""
    global _vision_gateway, _vision_loaded
    if _vision_loaded:
        return _vision_gateway
    _vision_loaded = True
    if not settings.VISION_MODEL_URL:
        return None
    if os.getenv("AI_PROVIDER", "auto") == "mock":
        from app.infrastructure.ai.mock import MockLLMGateway
        _vision_gateway = MockLLMGateway()
    else:
        from app.infrastructure.ai.qwen import QwenGateway
        _vision_gateway = QwenGateway(
            api_url=settings.VISION_MODEL_URL,
            model=settings.VISION_MODEL_NAME,
            api_key=settings.VISION_MODEL_API_KEY,
            timeout=settings.VISION_MODEL_TIMEOUT,
        )
    logger.info("[AI网关] 视觉适配器: %s (%s)",
                type(_vision_gateway).__name__, _vision_gateway.model_name)
    return _vision_gateway


def get_long_form_gateway() -> Optional[LLMGateway]:
    """长文生成专用模型网关（可选）。

    仅当 LONG_FORM_MODEL_URLS 配置时返回独立网关；否则返回 None，调用方回退主模型。
    长文网关默认关闭思考（enable_thinking=false），避免 35B 这类思考模型在正文里输出 CoT。
    """
    global _long_form_gateway, _long_form_loaded
    if _long_form_loaded:
        return _long_form_gateway
    _long_form_loaded = True
    urls = _endpoint_urls("LONG_FORM_MODEL_URLS", "")
    if not urls or not urls[0]:
        return None
    if os.getenv("AI_PROVIDER", "auto") == "mock":
        from app.infrastructure.ai.mock import MockLLMGateway
        _long_form_gateway = MockLLMGateway()
    else:
        from app.infrastructure.ai.qwen import QwenGateway
        _long_form_gateway = QwenGateway(
            api_urls=urls,
            model=settings.LONG_FORM_MODEL_NAME,
            timeout=settings.LONG_FORM_MODEL_TIMEOUT,
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        )
    logger.info("[AI网关] 长文适配器: %s (%s, endpoints=%s)",
                type(_long_form_gateway).__name__, _long_form_gateway.model_name,
                getattr(_long_form_gateway, "endpoint_count", 1))
    return _long_form_gateway


def get_ppt_gateway() -> LLMGateway:
    """PPT 助手专用模型网关（DeepPresenter-9B，OpenAI 兼容）。

    PPT_MODEL_URLS 可提供多个同模型副本；未配置时使用 PPT_MODEL_URL。
    两者都为空时返回 None，调用方回退主文本模型。
    """
    global _ppt_gateway, _ppt_loaded
    if _ppt_loaded:
        return _ppt_gateway
    _ppt_loaded = True
    urls = _endpoint_urls("PPT_MODEL_URLS", settings.PPT_MODEL_URL)
    if not urls:
        return None
    if os.getenv("AI_PROVIDER", "auto") == "mock":
        from app.infrastructure.ai.mock import MockLLMGateway
        _ppt_gateway = MockLLMGateway()
    else:
        from app.infrastructure.ai.qwen import QwenGateway
        _ppt_gateway = QwenGateway(
            api_urls=urls,
            model=settings.PPT_MODEL_NAME,
            api_key=settings.PPT_MODEL_API_KEY,
            timeout=settings.PPT_MODEL_TIMEOUT,
        )
    logger.info("[AI网关] PPT 适配器: %s (%s, endpoints=%s)",
                type(_ppt_gateway).__name__, _ppt_gateway.model_name,
                getattr(_ppt_gateway, "endpoint_count", 1))
    return _ppt_gateway


def reset_gateway() -> None:
    """测试用：重置缓存的网关实例。"""
    global _gateway, _vision_gateway, _vision_loaded, _ppt_gateway, _ppt_loaded
    global _long_form_gateway, _long_form_loaded
    _gateway = None
    _vision_gateway = None
    _vision_loaded = False
    _ppt_gateway = None
    _ppt_loaded = False
    _long_form_gateway = None
    _long_form_loaded = False