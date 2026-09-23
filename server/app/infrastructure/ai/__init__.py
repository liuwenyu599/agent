"""AI Gateway 工厂：按配置返回模型适配器（Qwen / Mock）。

多服务拆分：
- 文本模型（MODEL_*）：写作 / 问答 / 意图理解等全部文本链路；
- 视觉模型（VISION_*，可选）：对话中带图片附件时路由到视觉服务（Qwen2.5-VL 等）。
  未配置 VISION_MODEL_URL 时返回 None，图片走原有 OCR 文本通道；
- PPT 模型（PPT_*，可选）：DeepPresenter-9B 独立服务，PPT 助手的大纲 / 逐页编辑专用。
  未配置 PPT_MODEL_URL 时返回 None，调用方回退主文本模型。
"""
from app.application.ports import LLMGateway
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_gateway: LLMGateway = None
_vision_gateway: LLMGateway = None
_vision_loaded = False
_ppt_gateway: LLMGateway = None
_ppt_loaded = False


def get_llm_gateway() -> LLMGateway:
    global _gateway
    if _gateway is not None:
        return _gateway
    if settings.AI_PROVIDER == "mock":
        from app.infrastructure.ai.mock import MockLLMGateway
        _gateway = MockLLMGateway()
    else:
        from app.infrastructure.ai.qwen import QwenGateway
        _gateway = QwenGateway()
    logger.info("[AI网关] 当前适配器: %s (%s)", type(_gateway).__name__, _gateway.model_name)
    return _gateway


def get_vision_gateway() -> LLMGateway:
    """视觉模型网关；未配置 VISION_MODEL_URL 时返回 None（不影响文本链路）。"""
    global _vision_gateway, _vision_loaded
    if _vision_loaded:
        return _vision_gateway
    _vision_loaded = True
    if not settings.VISION_MODEL_URL:
        return None
    if settings.AI_PROVIDER == "mock":
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


def get_ppt_gateway() -> LLMGateway:
    """PPT 助手专用模型网关（DeepPresenter-9B，OpenAI 兼容）。
    未配置 PPT_MODEL_URL 时返回 None，调用方回退主文本模型，保证功能可用。"""
    global _ppt_gateway, _ppt_loaded
    if _ppt_loaded:
        return _ppt_gateway
    _ppt_loaded = True
    if not settings.PPT_MODEL_URL:
        return None
    if settings.AI_PROVIDER == "mock":
        from app.infrastructure.ai.mock import MockLLMGateway
        _ppt_gateway = MockLLMGateway()
    else:
        from app.infrastructure.ai.qwen import QwenGateway
        _ppt_gateway = QwenGateway(
            api_url=settings.PPT_MODEL_URL,
            model=settings.PPT_MODEL_NAME,
            api_key=settings.PPT_MODEL_API_KEY,
            timeout=settings.PPT_MODEL_TIMEOUT,
        )
    logger.info("[AI网关] PPT 适配器: %s (%s)",
                type(_ppt_gateway).__name__, _ppt_gateway.model_name)
    return _ppt_gateway


def reset_gateway() -> None:
    """测试用：重置缓存的网关实例。"""
    global _gateway, _vision_gateway, _vision_loaded, _ppt_gateway, _ppt_loaded
    _gateway = None
    _vision_gateway = None
    _vision_loaded = False
    _ppt_gateway = None
    _ppt_loaded = False
