"""DrawioService：把 drawio-mcp 的三个工具封装成业务友好的同步方法。

设计要点：
- 未配置 ``DRAWIO_MCP_URL`` 时，所有方法静默返回 ``None``（不抛异常），调用方据此走
  本地原生 PPTX 渲染，零侵入。
- 配置后，方法返回文本/结构；任何调用异常都被吞掉并返回 ``None``——PPT 是增强层，
  绝不允许它把整条 PPT 链路拖垮成 500。
- 工具代理负责 get_drawio_reference / search_shapes / create_diagram；
  generate_native_diagram 为流程图入口提供参考并验证模型生成的 XML。
  drawio_native 负责在导出时将 XML 转成原生 PPTX 形状与连线。
"""
from typing import Optional

import httpx

from app.core.config import settings
from app.core.logging import get_logger
from app.infrastructure.drawio.mcp_client import DrawioMcpClient, DrawioMcpError

logger = get_logger(__name__)


class DrawioService:
    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: Optional[int] = None,
        client: Optional[httpx.Client] = None,
    ) -> None:
        self.base_url = (base_url or settings.DRAWIO_MCP_URL or "").strip()
        self.timeout = timeout or settings.DRAWIO_MCP_TIMEOUT
        self._client_override = client
        self._enabled = bool(self.base_url)

    @property
    def enabled(self) -> bool:
        """是否配置了 drawio-mcp；False 时调用方应走本地原生渲染。"""
        return self._enabled

    def _client(self) -> DrawioMcpClient:
        return DrawioMcpClient(
            self.base_url, timeout=self.timeout, client=self._client_override
        )

    def get_reference(self, fmt: str = "xml") -> Optional[str]:
        """draw.io 语法参考（xml/mermaid），模型画第一张图前读一次。"""
        if not self._enabled:
            return None
        try:
            with self._client() as c:
                return c.get_reference(fmt=fmt)
        except DrawioMcpError as e:
            logger.warning("drawio get_reference 失败，降级本地渲染: %s", e)
            return None

    def search_shapes(self, query: str, limit: int = 20) -> Optional[str]:
        """按关键词检索形状样式，返回可直接塞进 XML 的 style 字符串。"""
        if not self._enabled:
            return None
        try:
            with self._client() as c:
                return c.search_shapes(query, limit=limit)
        except DrawioMcpError as e:
            logger.warning("drawio search_shapes 失败，降级本地渲染: %s", e)
            return None

    def create_diagram(
        self, xml: Optional[str] = None, mermaid: Optional[str] = None
    ) -> Optional[str]:
        """把 .drawio XML（或 Mermaid）渲染为内联图文本（预览/校验，非 PNG）。"""
        if not self._enabled:
            return None
        try:
            with self._client() as c:
                return c.create_diagram(xml=xml, mermaid=mermaid)
        except DrawioMcpError as e:
            logger.warning("drawio create_diagram 失败: %s", e)
            return None

    def health(self) -> bool:
        """探活：未配置直接 False；配置后打 /health。"""
        if not self._enabled:
            return False
        try:
            with self._client() as c:
                return c.health()
        except DrawioMcpError:
            return False

    def generate_native_diagram(self, assistant, slide: dict, instruction: str = "",
                                kind: str = "process", style: Optional[dict] = None) -> Optional[dict]:
        """Return None on MCP outage so the caller can use the local visual generator.

        Invalid model output still raises: infrastructure fallback must not bypass XML checks.
        """
        import json
        import re
        from app.application.ppt.drawio_native import validate_generated_layout
        from app.core.llm_json import loads_lenient

        reference = self.get_reference()
        if not reference:
            return None
        diagram_names = {
            "process": "工作流程图", "relationship": "关系图",
            "organization": "组织架构图", "architecture": "系统架构图",
        }
        if kind not in diagram_names:
            raise ValueError("不支持的图示类型")
        style = style or {}
        colors = style.get("colors") or {}
        primary = str(colors.get("primary", "17365D")).lstrip("#")
        accent = str(colors.get("accent", "4A78AD")).lstrip("#")
        primary = primary if re.fullmatch(r"[0-9a-fA-F]{6}", primary) else "17365D"
        accent = accent if re.fullmatch(r"[0-9a-fA-F]{6}", accent) else "4A78AD"
        font = str(style.get("font") or "思源黑体")[:40]
        prompt = (
            f"根据页面内容生成简洁的{diagram_names[kind]}。只输出 JSON 对象 {{\"xml\": \"...\"}}。"
            "xml 必须是未压缩的单页 mxGraphModel，根节点 id=0、图层 id=1。"
            "所有节点 parent=1，使用绝对 mxGeometry 坐标，仅允许 rectangle、ellipse、"
            "rhombus、text；最多12个节点，每个标签不超过20字。"
            "连线 edge=1，source/target 指向已有节点，parent=1。"
            "禁止图片、图标、自定义 stencil、嵌套分组和外部资源。"
            "页面坐标范围 0..1000 × 0..550；主要内容放在 x=40..960、y=30..520 的安全区。"
            "节点之间至少留20坐标单位，节点不得重叠；文字放进节点 value，不另叠文字框。"
            f"模板主色 #{primary}、强调色 #{accent}、中文字体 {font}；"
            "节点优先使用模板配色，留出足够的文字空间。"
            "事实和步骤只来自本页和用户要求，不虚构数字。\n"
            "【MCP 语法参考】\n" + reference[:5000]
            + "\n【本页】\n" + json.dumps(slide, ensure_ascii=False)[:4000]
            + "\n【要求】\n" + instruction[:1000]
        )
        try:
            raw = assistant.complete(
                [{"role": "system", "content": "你是演示文稿流程图设计助手，只输出 JSON。"},
                 {"role": "user", "content": prompt}], temperature=0.2, max_tokens=3000)
            result = loads_lenient(raw or "")
            xml = result.get("xml") if isinstance(result, dict) else None
            diagram = validate_generated_layout(xml)
        except Exception as exc:
            logger.warning("原生图示生成或验证失败: %s", type(exc).__name__)
            raise RuntimeError("AI 图示未通过结构检查，页面未修改，请重试") from exc
        updated = dict(slide)
        updated["type"] = "process"
        labels = [node["label"] for node in diagram["nodes"] if node["label"]]
        updated["blocks"] = {
            "drawio_xml": xml,
            "drawio_kind": kind,
            "process" if kind == "process" else "diagram_labels": labels,
        }
        return updated
