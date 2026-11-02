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
import time


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
        self._reference_cache: dict[str, str] = {}
        self._reference_retry_at = 0.0

    @property
    def enabled(self) -> bool:
        """是否配置了 drawio-mcp；False 时调用方应走本地原生渲染。"""
        return self._enabled

    @property
    def native_available(self) -> bool:
        """MCP or the vendored skill's local Graphviz layout can draw a page."""
        if self._enabled:
            return True
        from app.application.ppt.drawio_skill_layout import ensure_dot
        return bool(ensure_dot())

    def _client(self) -> DrawioMcpClient:
        return DrawioMcpClient(
            self.base_url, timeout=self.timeout, client=self._client_override
        )

    def get_reference(self, fmt: str = "xml") -> Optional[str]:
        """draw.io 语法参考（xml/mermaid），模型画第一张图前读一次。"""
        if not self._enabled:
            return None
        if fmt in self._reference_cache:
            return self._reference_cache[fmt]
        if time.monotonic() < self._reference_retry_at:
            return None
        try:
            # A reference is advisory; do not spend the full page timeout on it.
            with DrawioMcpClient(self.base_url, timeout=min(self.timeout, 8),
                                 client=self._client_override) as c:
                reference = c.get_reference(fmt=fmt)
            if reference:
                self._reference_cache[fmt] = reference
            else:
                self._reference_retry_at = time.monotonic() + 60
            return reference
        except DrawioMcpError as e:
            logger.warning("drawio get_reference 失败，降级本地渲染: %s", e)
            self._reference_retry_at = time.monotonic() + 60
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
        if time.monotonic() < self._reference_retry_at:
            return None
        try:
            with DrawioMcpClient(self.base_url, timeout=min(self.timeout, 8),
                                 client=self._client_override) as c:
                return c.create_diagram(xml=xml, mermaid=mermaid)
        except DrawioMcpError as e:
            logger.warning("drawio create_diagram 失败: %s", e)
            self._reference_retry_at = time.monotonic() + 60
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
        """Build an editable diagram with MCP first, then local Graphviz.

        Invalid graph data remains subject to the same node and edge checks.
        """
        import json
        import re
        from app.application.ppt.drawio_native import validate_generated_layout
        from app.application.ppt.drawio_skill_layout import layout_slide_graph
        from app.core.llm_json import loads_lenient

        if kind not in {"process", "relationship", "organization", "architecture"}:
            raise ValueError("不支持的图示类型")
        source_slide = slide
        blocks = slide.get("blocks") or {}
        from app.application.ppt.drawio_skill_layout import ensure_dot
        if (not (blocks.get("diagram_nodes") or blocks.get("process"))
                and (slide.get("title") or slide.get("points"))):
            if (ensure_dot() or
                    (self.enabled and time.monotonic() >= self._reference_retry_at and
                     (len(slide.get("points") or []) >= 2 or
                      len(blocks.get("diagram_labels") or []) >= 2))):
                # Page-level user actions need a small semantic plan first. The
                # vendored skill then positions the planned graph deterministically.
                try:
                    raw_plan = assistant.complete(
                        [{"role": "system", "content": "你是PPT图示规划助手，只输出JSON。"},
                         {"role": "user", "content": (
                             f"根据本页内容规划{kind}图。只输出JSON："
                             '{"diagram_nodes":[{"id":"a","label":"名称"}],'
                             '"diagram_edges":[{"source":"a","target":"b"}]}。'
                             "节点2至12个、标签不超过20字；关系只能来自页面内容，"
                             "不得凭空添加事实或数字。\n"
                             + json.dumps(slide, ensure_ascii=False)[:3500]
                             + "\n补充要求：" + instruction[:500])}],
                        temperature=0.2, max_tokens=1000)
                    plan = loads_lenient(raw_plan or "")
                    if isinstance(plan, dict) and isinstance(plan.get("diagram_nodes"), list):
                        source_slide = {**slide, "blocks": {**blocks,
                            "diagram_nodes": plan["diagram_nodes"],
                            "diagram_edges": plan.get("diagram_edges") or []}}
                except Exception as exc:
                    logger.warning("图示语义规划失败，改走基础版式: %s", type(exc).__name__)
        # MCP lays out the 35B-planned graph first; the local skill is the
        # bounded fallback if MCP is unavailable or its output is invalid.
        planned = (source_slide.get("blocks") or {})
        raw_nodes = planned.get("diagram_nodes") or []
        raw_edges = planned.get("diagram_edges") or []
        if not raw_nodes and kind == "process":
            steps = planned.get("process") or source_slide.get("points") or []
            raw_nodes = [{"id": str(index), "label": str(step)}
                         for index, step in enumerate(steps)]
            raw_edges = [{"source": str(index), "target": str(index + 1)}
                         for index in range(max(0, len(raw_nodes) - 1))]
        mcp_rejected = False
        if (self.enabled and time.monotonic() >= self._reference_retry_at
                and 2 <= len(raw_nodes) <= 12):
            aliases = {str(node.get("id")): f"n{index}" for index, node in enumerate(raw_nodes)
                       if isinstance(node, dict) and node.get("id") is not None}
            if len(aliases) == len(raw_nodes):
                def short_label(value):
                    label = str(value or "").strip()
                    return label[:19] + "…" if len(label) > 20 else label
                direction = "LR" if kind == "process" else "TB"
                mermaid = [f"flowchart {direction}"]
                for node in raw_nodes:
                    label = short_label(node.get("label"))
                    # Escape Mermaid delimiters; user text must remain a label.
                    label = re.sub(r'["\[\]{}<>|\\\r\n]', " ", label)
                    mermaid.append(f'{aliases[str(node["id"])]}["{label}"]')
                for edge in raw_edges:
                    if (isinstance(edge, dict) and
                            str(edge.get("source")) in aliases and
                            str(edge.get("target")) in aliases):
                        mermaid.append(f'{aliases[str(edge["source"])]} --> '
                                       f'{aliases[str(edge["target"])]}')
                try:
                    raw_mcp = self.create_diagram(mermaid="\n".join(mermaid))
                    obj = loads_lenient(raw_mcp) if raw_mcp and raw_mcp.lstrip().startswith("{") else None
                    mcp_xml = obj.get("xml") if isinstance(obj, dict) else raw_mcp
                    from app.application.ppt.drawio_native import apply_diagram_theme
                    from app.core.fonts import DEFAULT_CJK_FONT
                    mcp_xml = apply_diagram_theme(
                        mcp_xml, (style or {}).get("colors"),
                        str((style or {}).get("font") or DEFAULT_CJK_FONT))
                    diagram = validate_generated_layout(mcp_xml)
                    from collections import Counter
                    expected = Counter(short_label(node.get("label")) for node in raw_nodes)
                    actual = Counter(node["label"] for node in diagram["nodes"])
                    if any(actual[label] < count for label, count in expected.items()):
                        raise ValueError("MCP 图示遗漏规划节点")
                    labels_by_id = {node["id"]: node["label"] for node in diagram["nodes"]}
                    actual_edges = {(labels_by_id[edge["source"]], labels_by_id[edge["target"]])
                                    for edge in diagram["edges"]}
                    planned_labels = {str(node["id"]): short_label(node.get("label"))
                                      for node in raw_nodes}
                    required_edges = {(planned_labels[str(edge["source"])],
                                       planned_labels[str(edge["target"])])
                                      for edge in raw_edges if isinstance(edge, dict) and
                                      str(edge.get("source")) in planned_labels and
                                      str(edge.get("target")) in planned_labels}
                    if not required_edges.issubset(actual_edges):
                        raise ValueError("MCP 图示遗漏规划连线")
                    labels = [node["label"] for node in diagram["nodes"] if node["label"]]
                    details = [str(node.get("label") or "") for node in raw_nodes
                               if len(str(node.get("label") or "")) > 20]
                    updated = dict(source_slide)
                    updated["type"] = "process"
                    updated["blocks"] = {**planned, "drawio_xml": mcp_xml,
                        "drawio_kind": kind, "diagram_engine": "mcp",
                        "diagram_details": details,
                        "process" if kind == "process" else "diagram_labels": labels}
                    return updated
                except (ValueError, TypeError, AttributeError, DrawioMcpError,
                        httpx.TimeoutException) as exc:
                    logger.warning("MCP 排版结果未通过校验，改用本地布局: %s",
                                   type(exc).__name__)
                    mcp_rejected = isinstance(exc, (ValueError, TypeError, AttributeError))
        # No MCP output, timeout, or rejected layout: keep the graph and its
        # source facts, then lay it out locally without another model call.
        try:
            skill_xml = layout_slide_graph(
                source_slide, kind, (style or {}).get("colors") or {})
        except (RuntimeError, ValueError) as exc:
            logger.warning("Draw.io Skill 布局失败，改用模型路径: %s", type(exc).__name__)
            skill_xml = None
        if skill_xml:
            from app.application.ppt.drawio_native import parse_diagram
            nodes = parse_diagram(skill_xml)["nodes"]
            updated = dict(source_slide)
            updated["type"] = "process"
            labels = [node["label"] for node in nodes if node["label"]]
            original_nodes = (source_slide.get("blocks") or {}).get("diagram_nodes") or []
            original_labels = ([str(node.get("label") or "") for node in original_nodes
                                if isinstance(node, dict)] if original_nodes else
                               [str(value) for value in
                                ((source_slide.get("blocks") or {}).get("process") or
                                 source_slide.get("points") or [])])
            details = [label for label in original_labels if len(label) > 20]
            updated["blocks"] = {**(source_slide.get("blocks") or {}),
                "drawio_xml": skill_xml, "drawio_kind": kind,
                "diagram_engine": "graphviz",
                "diagram_details": details,
                "process" if kind == "process" else "diagram_labels": labels}
            return updated
        if mcp_rejected:
            # An invalid MCP graph must not be replaced by a model graph that
            # may silently drop the planned entities or relationships.
            return None
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
        primary = str(colors.get("primary", "2A5CAA")).lstrip("#")
        accent = str(colors.get("accent", "4A78AD")).lstrip("#")
        primary = primary if re.fullmatch(r"[0-9a-fA-F]{6}", primary) else "2A5CAA"
        accent = accent if re.fullmatch(r"[0-9a-fA-F]{6}", accent) else "4A78AD"
        from app.core.fonts import DEFAULT_CJK_FONT
        font = str(style.get("font") or DEFAULT_CJK_FONT)[:40]
        prompt = (
            f"根据页面内容生成简洁的{diagram_names[kind]}。只输出 JSON 对象 {{\"xml\": \"...\"}}。"
            "xml 必须是未压缩的单页 mxGraphModel，根节点 id=0、图层 id=1。"
            "所有节点 parent=1，使用绝对 mxGeometry 坐标，仅允许 rectangle、ellipse、"
            "rhombus、text；最多12个节点，每个标签不超过20字。"
            "连线 edge=1，source/target 指向已有节点，parent=1。"
            "禁止图片、图标、自定义 stencil、嵌套分组和外部资源。"
            "页面坐标范围 0..1000 × 0..550；主要内容放在 x=40..960、y=30..520 的安全区。"
            "节点之间至少留20坐标单位，节点不得重叠；文字放进节点 value，不另叠文字框。"
            "样式示例：节点 style=\"rounded=1;shadow=1;fillColor=#2A5CAA;"
            "fontColor=#FFFFFF;fontFamily=Microsoft YaHei;whiteSpace=wrap;\"；"
            "连线 style=\"edgeStyle=orthogonalEdgeStyle;rounded=1;"
            "strokeColor=#6C757D;strokeWidth=2;endArrow=block;\"。"
            "若本页提供 diagram_nodes 和 diagram_edges，完整表达这些节点与连线，"
            "不得自行添加未经材料支持的关系。"
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
            from app.application.ppt.drawio_native import apply_diagram_theme
            xml = apply_diagram_theme(xml, colors, font)
            diagram = validate_generated_layout(xml)
            source_blocks = slide.get("blocks") or {}
            expected_nodes = {
                str(node["id"]): str(node["label"]).strip()
                for node in (source_blocks.get("diagram_nodes") or [])
                if isinstance(node, dict) and node.get("id") and node.get("label")
            }
            if expected_nodes:
                actual_nodes = {node["id"]: node["label"].strip()
                                for node in diagram["nodes"]}
                if not set(expected_nodes.values()).issubset(actual_nodes.values()):
                    raise ValueError("图示遗漏了已规划的节点")
                actual_edges = {
                    (actual_nodes[edge["source"]], actual_nodes[edge["target"]])
                    for edge in diagram["edges"]
                }
                expected_edges = {
                    (expected_nodes[edge["source"]], expected_nodes[edge["target"]])
                    for edge in (source_blocks.get("diagram_edges") or [])
                    if isinstance(edge, dict) and edge.get("source") in expected_nodes
                    and edge.get("target") in expected_nodes
                }
                if not expected_edges.issubset(actual_edges):
                    raise ValueError("图示遗漏了已规划的连线")
        except Exception as exc:
            logger.warning("原生图示生成或验证失败: %s", type(exc).__name__)
            raise RuntimeError("AI 图示未通过结构检查，页面未修改，请重试") from exc
        updated = dict(slide)
        updated["type"] = "process"
        labels = [node["label"] for node in diagram["nodes"] if node["label"]]
        updated["blocks"] = {**(slide.get("blocks") or {}),
            "drawio_xml": xml,
            "drawio_kind": kind,
            "process" if kind == "process" else "diagram_labels": labels,
        }
        return updated
