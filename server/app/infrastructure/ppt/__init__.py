"""PPT 相关基础设施：PPTAgent Host 渲染客户端。"""

from app.infrastructure.ppt.ppt_agent_client import (  # noqa: F401
    PPTAgentClient,
    PPTAgentError,
    looks_like_pptx,
)

__all__ = ["PPTAgentClient", "PPTAgentError", "looks_like_pptx"]
