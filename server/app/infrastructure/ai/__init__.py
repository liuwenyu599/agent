"""AI Gateway 工厂：按配置返回模型适配器（Qwen / Mock）。"""
from app.application.ports import LLMGateway
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_gateway: LLMGateway = None


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


def reset_gateway() -> None:
    """测试用：重置缓存的网关实例。"""
    global _gateway
    _gateway = None
