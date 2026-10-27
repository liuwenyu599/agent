# -*- coding: utf-8 -*-
from app.core.fonts import DEFAULT_CJK_FONT
"""智能 PPT 引擎（移植自旧系统 ppt_service，AI 调用改经 WritingAssistant）。

核心设计：内容与版式分离
- 文档 outline 只保存内容：页面类型、标题、要点、结构化数据块、图片名；
- 模板（PPTTemplate）保存视觉风格（colors/font）+ 版式体系（layouts）。
  同一份内容换模板 = 换渲染样式，内容不动。

页型体系（10 种）：
  cover 封面 / toc 目录 / section 章节页 / content 正文（可选配图）
  data 数据卡片页 / chart 图表页（原生可编辑图表）
  case 案例页 / timeline 时间轴 / process 流程图 / summary 总结页 / closing 结束页

导出：python-pptx 手工排版，文本/形状/图表均为可编辑元素。
"""
import io
import json
import os
import re
import uuid
from typing import Any, Dict, List, Optional

from app.core.llm_json import LLMJsonError, loads_lenient, truncate_for_log
from app.core.logging import get_logger

logger = get_logger(__name__)

# 首次解析失败后重试时追加的严格格式约束（temperature 同步降到 0.2）
_STRICT_JSON_RULE = """

【重要·输出格式硬性约束（本次必须严格遵守）】
1. 只输出一个 JSON 对象，前后不要有任何说明文字；
2. 不要用 markdown 代码块包裹（不要出现 ```）；
3. JSON 的最后一个 } 之后立即停止，不要追加"以上就是本次大纲"之类的话；
4. 不要出现尾随逗号（例如 ["a",] 或 {"a":1,}）；
5. 字符串内部不要出现真实换行，需要换行请写成 \\n；
6. 键名和字符串一律使用英文双引号（半角 "），不要用中文全角引号。"""

_OUTLINE_PARSE_FAILED_MSG = (
    "AI 这次返回的大纲格式不规范（已自动重试一次仍未成功）。"
    "本次没有生成任何文档，可以放心重试；若多次失败，可尝试缩短材料正文或减少页数要求。"
)

# ================= 内置官方模板（含完整版式体系） =================
BUILTIN_TEMPLATES = [
    {"id": "gov_report_blue", "name": "政务工作汇报（深蓝）", "category": "工作汇报", "is_official": True,
     "description": "庄重政务深蓝，适用：司法行政工作汇报、年度总结、专项汇报",
     "colors": {"primary": "17365D", "accent": "2F75B5", "light": "EEF3F8", "dark": "0E243E"},
     "layouts": {"cover": "band_bottom", "toc": "numbered_list", "section": "left_block",
                  "content": "bar_title", "data": "cards_row", "chart": "chart_area",
                  "case": "header_text", "timeline": "horizontal", "process": "chevron",
                  "summary": "cards", "closing": "center"}},
    {"id": "gov_report_red", "name": "政务工作汇报", "category": "工作汇报", "is_official": True,
     "description": "庄重政务红，适用：工作汇报、阶段总结",
     "colors": {"primary": "C00000", "accent": "E8B54D", "light": "FDF2F2", "dark": "7A0000"},
     "layouts": {"cover": "band_bottom", "toc": "numbered_list", "section": "left_block",
                  "content": "bar_title", "data": "cards_row", "chart": "chart_area",
                  "case": "header_text", "timeline": "horizontal", "process": "chevron",
                  "summary": "cards", "closing": "center"}},
    {"id": "policy_blue", "name": "政策解读", "category": "政策解读", "is_official": True,
     "description": "沉稳政策蓝，适用：政策解读、方案宣讲",
     "colors": {"primary": "1F4E9C", "accent": "5B9BD5", "light": "EEF4FC", "dark": "12325F"},
     "layouts": {"cover": "left_block", "toc": "numbered_list", "section": "center",
                  "content": "top_band", "data": "cards_row", "chart": "chart_area",
                  "case": "header_text", "timeline": "horizontal", "process": "chevron",
                  "summary": "cards", "closing": "brand_band"}},
    {"id": "training_blue", "name": "培训课件", "category": "培训课件", "is_official": True,
     "description": "明快培训蓝，适用：业务培训、知识讲座",
     "colors": {"primary": "2E75B6", "accent": "9DC3E6", "light": "F0F7FD", "dark": "1B4F82"},
     "layouts": {"cover": "band_bottom", "toc": "cards", "section": "left_block",
                  "content": "bar_title", "data": "cards_row", "chart": "chart_area",
                  "case": "header_text", "timeline": "horizontal", "process": "chevron",
                  "summary": "cards", "closing": "center"}},
    {"id": "exp_share_red", "name": "经验交流", "category": "经验交流", "is_official": True,
     "description": "热烈交流红，适用：经验交流、工作分享",
     "colors": {"primary": "B01E23", "accent": "F2C14E", "light": "FBF1F1", "dark": "6E1114"},
     "layouts": {"cover": "left_block", "toc": "cards", "section": "center",
                  "content": "bar_title", "data": "cards_row", "chart": "chart_area",
                  "case": "header_text", "timeline": "horizontal", "process": "chevron",
                  "summary": "cards", "closing": "center"}},
    {"id": "summary_brown", "name": "总结汇报", "category": "总结汇报", "is_official": True,
     "description": "厚重棕红，适用：年度总结、专项总结",
     "colors": {"primary": "8E1B1B", "accent": "D9A441", "light": "FAF3EE", "dark": "5C1010"},
     "layouts": {"cover": "band_bottom", "toc": "numbered_list", "section": "left_block",
                  "content": "top_band", "data": "cards_row", "chart": "chart_area",
                  "case": "header_text", "timeline": "horizontal", "process": "chevron",
                  "summary": "cards", "closing": "brand_band"}},
    {"id": "publicity_cyan", "name": "法治宣传", "category": "宣传展示", "is_official": True,
     "description": "清新宣传青，适用：法治宣传、普法教育",
     "colors": {"primary": "0F6E8C", "accent": "3FA7B8", "light": "ECF7F9", "dark": "0A4A5E"},
     "layouts": {"cover": "left_block", "toc": "cards", "section": "center",
                  "content": "bar_title", "data": "cards_row", "chart": "chart_area",
                  "case": "header_text", "timeline": "horizontal", "process": "chevron",
                  "summary": "cards", "closing": "center"}},
]

DEFAULT_LAYOUTS = BUILTIN_TEMPLATES[0]["layouts"]
DEFAULT_COLORS = BUILTIN_TEMPLATES[0]["colors"]
PAGE_TYPES = ["cover", "toc", "section", "content", "data", "chart",
              "case", "timeline", "process", "summary", "closing"]

# ================= 版式目录与选版器 =================
# 每个页型提供多个**结构不同**的版式（不是只换配色/页眉）。35B 在大纲里给
# ``layout`` 意图，规则引擎做可行性校验与整篇去重；模型给的值不可用
# （点数不符、缺图表数据）时自动降级到最贴合内容结构的版式。
#
# 字段约定：
#   min_points/max_points  该版式能装下的要点条数（硬门槛）
#   needs_image            必须有配图，否则不可用
#   requires               blocks 里必须存在的数据块
#   weight                 无结构差异时的基础偏好分
LAYOUT_CATALOG: Dict[str, List[Dict[str, Any]]] = {
    "cover": [
        {"id": "cover.band", "label": "底部色带封面", "weight": 1.0},
        {"id": "cover.side", "label": "左侧色块封面", "weight": 1.0},
        {"id": "cover.minimal", "label": "留白极简封面", "weight": 0.9},
    ],
    "toc": [
        {"id": "toc.list", "label": "编号列表目录", "weight": 1.0},
        {"id": "toc.cards", "label": "卡片目录", "weight": 1.0},
        {"id": "toc.grid", "label": "宫格目录", "min_points": 4, "max_points": 6, "weight": 1.1},
    ],
    "section": [
        {"id": "section.side", "label": "侧栏章节页", "weight": 1.0},
        {"id": "section.center", "label": "居中章节页", "weight": 1.0},
        {"id": "section.number", "label": "大序号章节页", "weight": 0.9},
    ],
    "content": [
        {"id": "content.bullets", "label": "编号要点", "min_points": 1, "max_points": 6,
         "weight": 1.0},
        {"id": "content.image_right", "label": "左文右图", "needs_image": True,
         "min_points": 1, "max_points": 4, "weight": 1.0},
        {"id": "content.two_col", "label": "双栏并列", "min_points": 4, "max_points": 6,
         "weight": 0.9},
        {"id": "content.three_cards", "label": "三卡并列", "min_points": 3, "max_points": 3,
         "weight": 0.9},
        {"id": "content.compare", "label": "左右对比", "min_points": 2, "max_points": 2,
         "weight": 0.8},
        {"id": "content.icon_grid", "label": "四宫格", "min_points": 3, "max_points": 4,
         "weight": 0.8},
        {"id": "content.statement", "label": "单句结论", "min_points": 1, "max_points": 1,
         "weight": 0.7},
        {"id": "content.quote", "label": "引言金句", "min_points": 1, "max_points": 2,
         "weight": 0.6},
    ],
    "data": [
        {"id": "data.cards", "label": "指标卡片", "requires": "cards", "weight": 1.0},
        {"id": "data.kpi", "label": "KPI 看板", "requires": "cards", "weight": 0.9},
        {"id": "data.table", "label": "数据表格", "requires": "table", "weight": 1.1},
    ],
    "chart": [
        {"id": "chart.full", "label": "整页图表", "requires": "chart", "weight": 1.0},
        {"id": "chart.split", "label": "图表加结论", "requires": "chart",
         "min_points": 1, "weight": 1.0},
    ],
    "case": [
        {"id": "case.block", "label": "整块案例", "weight": 1.0},
        {"id": "case.split", "label": "三段案例", "min_points": 3, "weight": 1.0},
    ],
    "timeline": [
        {"id": "timeline.horizontal", "label": "横向时间轴", "max_points": 5, "weight": 1.0},
        {"id": "timeline.vertical", "label": "纵向时间轴", "min_points": 3, "weight": 1.0},
    ],
    "process": [
        {"id": "process.chevron", "label": "横向箭头流程", "max_points": 5, "weight": 1.0},
        {"id": "process.vertical", "label": "纵向步骤条", "min_points": 3, "weight": 1.0},
    ],
    "summary": [
        {"id": "summary.cards", "label": "结论卡片", "weight": 1.0},
        {"id": "summary.list", "label": "大字结论", "min_points": 2, "max_points": 4,
         "weight": 1.0},
    ],
    "closing": [
        {"id": "closing.center", "label": "居中结束页", "weight": 1.0},
        {"id": "closing.band", "label": "色带结束页", "weight": 1.0},
    ],
}

# 旧模板配置里的版式名 → 目录 id（保持已有模板的选择继续生效）
_LEGACY_LAYOUT_ALIAS: Dict[tuple, str] = {
    ("cover", "band_bottom"): "cover.band",
    ("cover", "left_block"): "cover.side",
    ("toc", "numbered_list"): "toc.list",
    ("toc", "cards"): "toc.cards",
    ("section", "left_block"): "section.side",
    ("section", "center"): "section.center",
    ("content", "bar_title"): "content.bullets",
    ("content", "top_band"): "content.bullets",
    ("content", "image_right"): "content.image_right",
    ("data", "cards_row"): "data.cards",
    ("chart", "chart_area"): "chart.full",
    ("case", "header_text"): "case.block",
    ("timeline", "horizontal"): "timeline.horizontal",
    ("process", "chevron"): "process.chevron",
    ("summary", "cards"): "summary.cards",
    ("closing", "center"): "closing.center",
    ("closing", "brand_band"): "closing.band",
}


def layout_ids(slide_type: str) -> List[str]:
    """某页型可用的版式 id 列表（编辑器/测试用）。"""
    return [sp["id"] for sp in LAYOUT_CATALOG.get(slide_type, [])]


def _normalize_layout_id(raw: Any, slide_type: str) -> str:
    """把模型/模板给的版式名归一成 ``<type>.<name>``；不属于该页型则返回空串。"""
    value = str(raw or "").strip()
    if not value:
        return ""
    if "." in value:
        head, tail = value.split(".", 1)
        return f"{slide_type}.{tail}" if head == slide_type else ""
    candidate = f"{slide_type}.{value}"
    return candidate if candidate in layout_ids(slide_type) else ""


def _slide_has_image(slide: Dict) -> bool:
    img = slide.get("_image") or {}
    return bool(img.get("file_path"))


def _layout_point_count(slide: Dict) -> int:
    """版式容量用的"条目数"：时间轴/流程的数据在 blocks 里，不在 points。"""
    blocks = slide.get("blocks") or {}
    stype = slide.get("type")
    if stype == "timeline":
        return len(blocks.get("timeline") or [])
    if stype == "process":
        steps = blocks.get("process") or []
        if steps:
            return len(steps)
    return len(slide.get("points") or [])


def _layout_usable(spec: Dict, slide: Dict) -> bool:
    """版式硬门槛：要点条数、配图、数据块。不满足则该版式不可选。"""
    count = _layout_point_count(slide)
    lo, hi = spec.get("min_points"), spec.get("max_points")
    if lo is not None and count < lo:
        return False
    if hi is not None and count > hi:
        return False
    if spec.get("needs_image") and not _slide_has_image(slide):
        return False
    blocks = slide.get("blocks") or {}
    need = spec.get("requires")
    if need == "cards" and not (blocks.get("cards") or []):
        return False
    if need == "table" and not ((blocks.get("table") or {}).get("rows") or []):
        return False
    if need == "chart" and not ((blocks.get("chart") or {}).get("series") or []):
        return False
    if need == "timeline" and not (blocks.get("timeline") or []):
        return False
    if need == "process" and not (blocks.get("process") or []):
        return False
    return True


def _layout_score(spec: Dict, slide: Dict, recent: List[str], used: Dict[str, int]) -> float:
    """无明确偏好时的结构打分：内容形态越贴合得分越高，整篇重复出现要扣分。"""
    sid = spec["id"]
    points = [str(p) for p in (slide.get("points") or [])]
    n = len(points)
    total_chars = sum(len(p) for p in points)
    score = float(spec.get("weight", 1.0))

    if _slide_has_image(slide) and sid == "content.image_right":
        score += 2.0                     # 有图不用图等于白配
    if sid == "content.statement":
        score += 1.6 if (n == 1 and total_chars <= 40) else -1.5
    elif sid == "content.compare":
        if n == 2:
            gap = abs(len(points[0]) - len(points[1]))
            score += 1.2 if gap <= 12 else 0.3
        else:
            score -= 1.0
    elif sid == "content.three_cards":
        score += 1.0 if n == 3 else -1.0
    elif sid == "content.two_col":
        score += 0.9 if n >= 4 else -1.0
    elif sid == "content.icon_grid":
        score += 0.7 if 3 <= n <= 4 and all(len(p) <= 26 for p in points) else -0.8
    elif sid == "content.quote":
        quoted = any(p[:1] in "“\"「" for p in points)
        score += 1.2 if quoted else -1.2
    elif sid == "content.bullets":
        score += 0.6 if n >= 2 else 0.0
    elif sid == "data.kpi":
        cards = (slide.get("blocks") or {}).get("cards") or []
        score += 0.3 if 3 <= len(cards) <= 4 else -0.6
    elif sid == "data.cards":
        cards = (slide.get("blocks") or {}).get("cards") or []
        score += 0.6 if len(cards) >= 3 else 0.2
    elif sid == "data.table":
        rows = ((slide.get("blocks") or {}).get("table") or {}).get("rows") or []
        score += 1.2 if len(rows) >= 3 else -0.5
    elif sid == "chart.split":
        score += 0.8 if n >= 1 else -0.5
    elif sid == "timeline.vertical":
        items = (slide.get("blocks") or {}).get("timeline") or []
        score += 0.9 if len(items) >= 4 else -0.4
    elif sid == "process.vertical":
        steps = (slide.get("blocks") or {}).get("process") or []
        score += 0.9 if len(steps) >= 5 else -0.4
    elif sid in ("summary.list",):
        score += 0.7 if n >= 2 else -0.5

    if sid in recent:
        score -= 1.3                     # 相邻页同版式最容易显“模板感”
    score -= 0.30 * used.get(sid, 0)      # 整篇均衡使用
    return score


def choose_layout(slide: Dict, template_layouts: Optional[Dict] = None,
                  recent: Optional[List[str]] = None,
                  used: Optional[Dict[str, int]] = None) -> str:
    """为单页选版式。

    优先级：模型给的 ``layout`` → 模板配置的旧版式名 → 结构打分。
    前两者都要过 ``_layout_usable`` 硬门槛，不通过就落到打分兜底。
    """
    stype = slide.get("type") or "content"
    specs = LAYOUT_CATALOG.get(stype) or []
    if not specs:
        return ""
    recent = list(recent or [])[-2:]
    used = used or {}

    # 模板级版式偏好只用于"皮肤位"页型（每篇各一页）；内容页一律按结构打分，
    # 否则同一模板会把所有正文页钉死成同一种版式，正是"模板感"的来源。
    prefers = [slide.get("layout")]
    if stype in ("cover", "section", "closing"):
        prefers.append((template_layouts or {}).get(stype))
    for raw in prefers:
        want = _normalize_layout_id(raw, stype)
        if not want:
            want = _LEGACY_LAYOUT_ALIAS.get((stype, str(raw or "")), "")
        if want:
            spec = next((sp for sp in specs if sp["id"] == want), None)
            if spec and _layout_usable(spec, slide):
                if (stype == "content" and want in recent
                        and not slide.get("layout_locked")):
                    continue
                return want

    best, best_score = "", float("-inf")
    for spec in specs:
        if not _layout_usable(spec, slide):
            continue
        score = _layout_score(spec, slide, recent, used)
        if score > best_score:
            best, best_score = spec["id"], score
    if best:
        return best
    # 全部不可用（如无图但所有 content 版式都要求图）时退回首个纯文字版式
    return next((sp["id"] for sp in specs if not sp.get("needs_image")), specs[0]["id"])


def template_to_dict(t) -> Dict:
    """ORM 实体/字典 → 渲染用统一结构。"""
    if isinstance(t, dict):
        return {
            "id": t.get("id"), "name": t.get("name", "模板"), "category": t.get("category", "其他"),
            "colors": {**DEFAULT_COLORS, **(t.get("colors") or {})},
            "font": t.get("font") or DEFAULT_CJK_FONT,
            "layouts": {**DEFAULT_LAYOUTS, **(t.get("layouts") or {})},
            "layout_library": t.get("layout_library") or [],
        }
    return {
        "id": t.id, "name": t.name, "category": t.category,
        "colors": {**DEFAULT_COLORS, **(t.colors or {})},
        "font": t.font or DEFAULT_CJK_FONT,
        "layouts": {**DEFAULT_LAYOUTS, **(t.layouts or {})},
        "layout_library": t.layout_library or [],
    }


# ================= AI 大纲生成 =================

_OUTLINE_PROMPT = """你是司法行政机关的资深 PPT 策划专家。请根据材料设计演示文稿大纲。

【材料类型】{source_type}
【主题/要求】{topic}
【材料内容】
{content}

【用户素材库图片】（可按内容选用，选了就一定会在该页插入这张图片）
{image_list}

【页面类型】（按内容需要选用，不要全是 content）
- cover 封面（必有且仅第 1 页）：title、subtitle
- toc 目录页（超过 8 页时建议有）：points 为章节名（3~5 条）
- section 章节页：title
- content 正文页：title、points（3~5 条，每条 15~40 字的完整句子）
- data 数据页：title、blocks={{"cards":[{{"label":"指标名","value":"数值"}},...]}}（材料里有具体数据时用，3~4 张卡）
- chart 图表页：title、blocks={{"chart":{{"chart_type":"bar或pie或line","categories":["类别"...],"series":[{{"name":"系列名","values":[数值...]}}]}}}}（材料有对比/趋势数据时用）
- case 案例页：title、points（案例背景→做法→结果，3~4 条）
- timeline 时间轴页：title、blocks={{"timeline":[{{"time":"时间点","text":"事项"}},...]}}（有时间线内容时用）
- process 流程页：title、blocks={{"process":["步骤1","步骤2",...]}}（讲工作流程时用，3~5 步）
- summary 总结页：title、points（2~4 条结论/展望）
- closing 结束页（必有且仅最后一页）：title（如"谢谢聆听，请批评指正"）

【版式选择】每页可加 "layout" 字段指定版式；不写则系统按内容自动选。系统会做可行性校验，
点数不符或数据缺失时自动降级，所以只在有把握时指定：
- content：bullets 编号要点（默认）；two_col 双栏并列（4 条以上）；three_cards 三卡（正好 3 条）；
  compare 左右对比（正好 2 条，用于前后/正反对照）；icon_grid 四宫格（3~4 条短句，每条 ≤20 字）；
  statement 单句结论（只写 1 条且 ≤30 字，用于核心判断）；quote 引言金句（第 1 条为原文引用，
  第 2 条写出处）
- data：cards 指标卡（默认，3~4 个）；kpi 看板（最核心的指标放第 1 位 + 2~3 个次要指标）；
  table 表格（材料里有成组明细数据时用，blocks={{"table":{{"headers":["列名"],"rows":[["值"]]}}}}）
- chart：full 整页图表（默认）；split 图表加右侧结论（此时 points 写 2~3 条图表结论）
- timeline：horizontal 横向（≤5 项）；vertical 纵向（≥4 项）
- process：chevron 横向箭头（≤5 步）；vertical 纵向步骤条（≥5 步）
- summary：cards 卡片（默认）；list 大字结论（2~4 条）
- 相邻两页不要用同一版式；整篇 content 页尽量覆盖 3 种以上不同版式。

【输出要求】
1. 只输出 JSON，不要用 markdown 代码块包裹，不要输出其他文字：
{{"title":"PPT主标题（≤20字）","subtitle":"副标题（≤30字）","slides":[{{"type":"cover","title":"...","subtitle":"..."}},...]}}
2. 每页 slide 的字段：type、title、points、blocks、image_name、note（演讲备注，一句话）；
3. ⚠️ 页数硬约束：slides 数组必须严格等于 {slide_count} 页，不得多一页、少一页；封面和结束页均计入总页数；
4. 内容要实：要点是有信息量的完整句子，材料中的具体数据、做法、案例必须用起来，禁止"加强领导""高度重视"式空话；
5. 图片规则：仅当某页内容与素材库图片明显相关时设 image_name（必须严格等于素材库中的图片名称），否则为 null；
6. 不要虚构材料中没有的事实和数据。"""


def generate_outline(assistant, source_type: str, topic: str, content: str,
                     images: List[Dict], slide_count: int = 10,
                     audience: str = "", scene: str = "",
                     material_names: Optional[List[str]] = None,
                     enforce_exact_count: bool = True) -> Dict:
    image_list = "\n".join(f"- {im['name']}：{im.get('caption') or '（无说明）'}" for im in images) \
        or "（素材库为空）"
    extra = ""
    if audience:
        extra += f"\n【汇报对象】{audience}（据此把握详略和措辞层级）"
    if scene:
        extra += f"\n【场景用途】{scene}"
    prompt = _OUTLINE_PROMPT.format(
        source_type=source_type, topic=(topic or "（未指定，依据材料自拟）") + extra,
        content=(content or "")[:6000], image_list=image_list,
        slide_count=slide_count,
    )
    # 事实约束（provenance）：给出材料清单时，要求每页标注内容依据，
    # 防止模型把旧材料/记忆中的数据当作本次数据
    names = "、".join(str(n) for n in (material_names or []) if n)
    if names:
        prompt += (
            f"\n\n【来源标注】本次材料清单：{names}\n"
            "每页 slide 增加 \"sources\" 字段（字符串数组）：列出该页内容依据的材料名"
            "（从清单中选择，可多选；确实无依据则为空数组）。\n"
            "凡含数字、日期、排名的内容必须标注来源；"
            "禁止使用清单之外的旧数据充当本次数据。")
    raw = _call_outline_model(assistant, prompt, temperature=0.5)
    outline = _parse_outline(raw)
    if outline is None and _looks_truncated(raw):
        # 输出被 max_tokens 截断（常见于接入知识库材料后输入变长、
        # 或模型服务实际上下文小于 MODEL_CTX_LIMIT 配置）：不推倒重来，
        # 让模型从断点续写剩余 JSON，最多续两次，拼好后再解析
        logger.warning("[PPT] 大纲输出疑似被 max_tokens 截断，尝试断点续写。"
                       "已输出：%s", truncate_for_log(raw, 400))
        for _ in range(2):
            cont = _continue_outline_model(assistant, prompt, raw, temperature=0.2)
            raw = raw + cont
            outline = _parse_outline(raw)
            if outline is not None or not _looks_truncated(raw):
                break
    if outline is None:
        # 第一次解析失败：降温度 + 追加严格格式约束，自动重试一次（不重试第三次，
        # 大纲生成本就耗时 10~30s，重试超过一次会明显拖慢体感）
        logger.warning("[PPT] 大纲首次解析失败，自动重试一次（temperature=0.2）。"
                       "原始输出：%s", truncate_for_log(raw, 800))
        raw = _call_outline_model(assistant, prompt + _STRICT_JSON_RULE, temperature=0.2)
        outline = _parse_outline(raw)
        if outline is None and _looks_truncated(raw):
            cont = _continue_outline_model(assistant, prompt + _STRICT_JSON_RULE,
                                           raw, temperature=0.2)
            outline = _parse_outline(raw + cont)
        if outline is None:
            logger.warning("[PPT] 大纲重试后仍解析失败，原始输出：%s",
                           truncate_for_log(raw, 800))
            raise RuntimeError(_OUTLINE_PARSE_FAILED_MSG)
    return normalize_outline(
        outline,
        target_count=slide_count if enforce_exact_count else None,
    )


def enrich_outline_with_diagrams(assistant, outline: Dict) -> Dict:
    """大纲阶段自动为流程页生成 drawio 原生图示，并固化进 ``blocks.drawio_xml``。

    与「大脑+手脚」架构一致：35B 只决定“这是流程页、这几步”（已由大纲的
    ``type=process`` + ``blocks.process`` 表达），drawio 负责把语义翻译成可编辑的
    原生图示；本函数只做编排与兜底，不触碰任何绘图坐标。

    固化的 ``drawio_xml`` 随大纲落库，因此无论是编辑器同步渲染（``generate``）
    还是工作台异步作业（``submit_job`` → ``_render_local_and_store``），``r_process``
    都会优先渲染该原生图示，失败时回退原生步骤条——天然覆盖全部渲染链路。

    兜底纪律（绝不拖垮整份大纲）：
    - ``DRAWIO_MCP_URL`` 未配置 → 直接跳过（后续走原生步骤条）；
    - 任一页生成失败（MCP 断连 / 结构校验不过 / 超时）→ 仅跳过该页；
    - 已含 ``drawio_xml`` 的页不重复生成（支持编辑后局部重生成）。
    """
    from app.application.ppt.drawio_service import DrawioService
    drawio = DrawioService()
    if not drawio.enabled:
        return outline
    for s in (outline.get("slides") or []):
        if (s.get("blocks") or {}).get("drawio_xml"):
            continue
        # 大纲阶段 35B 仅产出 process 类型图示页；relationship/organization/
        # architecture 三类走手动 ai_visual（其生成逻辑会强制 type=process，不宜自动套用）。
        if s.get("type") != "process":
            continue
        blocks = s.get("blocks") or {}
        # 必须有可画内容：流程步骤 / 要点 / 图示标签
        if not (blocks.get("process") or s.get("points") or blocks.get("diagram_labels")):
            continue
        try:
            updated = drawio.generate_native_diagram(assistant, s, kind="process")
            if updated:
                s.clear()
                s.update(updated)
        except Exception as exc:  # noqa: BLE001 - 单页失败不影响整份大纲
            logger.warning("PPT 自动图示生成跳过页(type=process, title=%s): %s",
                           s.get("title"), type(exc).__name__)
    return outline


def _looks_truncated(raw: str) -> bool:
    """判断模型输出是否疑似被 max_tokens 截断（JSON 未闭合）。

    去掉代码围栏后，正常完整的大纲 JSON 应以 } 收尾；不以 } 收尾且
    内容以 { 开头，基本可判定为截断而非格式乱写。
    """
    s = (raw or "").strip()
    if not s:
        return False
    s = re.sub(r"^```[a-zA-Z]*\s*", "", s).rstrip("`").rstrip()
    return s.startswith("{") and not s.endswith("}")


def _continue_outline_model(assistant, prompt: str, partial: str,
                            temperature: float) -> str:
    """把已输出的半截 JSON 作为 assistant 消息回传，让模型从断点续写。

    Args:
        assistant: 模型助手（WritingAssistant）。
        prompt: 原始大纲提示词（保持上下文一致）。
        partial: 被截断的半截输出。
        temperature: 采样温度，续写用低温求稳。

    Returns:
        续写部分文本（已去掉开头可能重复带的代码围栏）。
    """
    try:
        cont = assistant.complete(
            [{"role": "system", "content": "你是 PPT 大纲策划模块，只输出 JSON。"},
             {"role": "user", "content": prompt},
             {"role": "assistant", "content": partial},
             {"role": "user", "content":
              "上次输出因长度限制被截断。请从截断位置继续输出剩余的 JSON 内容："
              "不要重复已输出的任何字符，不要加解释，不要加代码围栏，"
              "直接从断点接着写，直到 JSON 完整闭合。"}],
            temperature=temperature, max_tokens=8192,
        )
    except Exception as e:
        raise RuntimeError(f"调用模型失败: {e}")
    if cont.startswith("【系统错误】") or cont.startswith("调用模型失败"):
        raise RuntimeError(cont)
    return re.sub(r"^\s*```[a-zA-Z]*\s*", "", cont)


def _call_outline_model(assistant, prompt: str, temperature: float) -> str:
    """调用模型生成大纲原始文本，统一处理调用层错误。

    Args:
        assistant: 模型助手（WritingAssistant）。
        prompt: 完整用户提示词。
        temperature: 采样温度；重试时传 0.2 以提高格式稳定性。

    Returns:
        模型返回的原始文本。

    Raises:
        RuntimeError: 模型调用失败，或返回了系统错误占位文本。
    """
    try:
        raw = assistant.complete(
            [{"role": "system", "content": "你是 PPT 大纲策划模块，只输出 JSON。"},
             {"role": "user", "content": prompt}],
            temperature=temperature, max_tokens=8192,
        )
    except Exception as e:
        raise RuntimeError(f"调用模型失败: {e}")
    if raw.startswith("【系统错误】") or raw.startswith("调用模型失败"):
        raise RuntimeError(raw)
    return raw


def _parse_outline(raw: str) -> Optional[Dict]:
    """宽容解析模型返回的大纲 JSON。

    模型的 JSON 常常带尾随逗号、字符串内裸换行、代码围栏或收尾废话，
    这里统一交给 app.core.llm_json 逐级抢救；解析不出来返回 None，
    由调用方决定重试或报错，**原始输出只写日志不回传客户端**。

    Args:
        raw: 模型返回的原始文本。

    Returns:
        解析出的 dict；解析失败或不是对象时返回 None。
    """
    if not raw or not raw.strip():
        return None
    try:
        parsed = loads_lenient(raw)
    except LLMJsonError as e:
        logger.warning("[PPT] 大纲 JSON 解析失败：%s", e.message)
        return None
    return parsed if isinstance(parsed, dict) else None


def _loads_ai_json(raw: str, err_msg: str) -> Dict:
    """宽容解析 AI 单页 / 可视化 / 结构操作返回的 JSON。

    Args:
        raw: 模型返回的原始文本。
        err_msg: 解析失败时抛给调用方的用户可读文案。

    Returns:
        解析出的 dict。

    Raises:
        RuntimeError: 模型未返回内容，或内容无法解析为 JSON 对象。
    """
    if not raw or not raw.strip():
        raise RuntimeError("AI 未返回有效结果，请重试")
    try:
        parsed = loads_lenient(raw)
    except LLMJsonError as e:
        logger.warning("[PPT] AI 返回内容无法解析：%s", e.message)
        raise RuntimeError(err_msg)
    if not isinstance(parsed, dict):
        logger.warning("[PPT] AI 返回内容不是 JSON 对象：%s", truncate_for_log(raw, 300))
        raise RuntimeError(err_msg)
    return parsed


def normalize_outline(outline: Dict, target_count: Optional[int] = None) -> Dict:
    """规范化 + 兼容旧页型，并可强制最终页数。\n\n    target_count 用于新建 PPT 链路的页数硬约束。模型偶尔仍会多/少页：\n    - 多页：只裁中间正文，永远保留封面与结束页；\n    - 少页：补空的“补充内容”页，明确标记为待补充，不制造事实。\n    导入已有 PPT / 空白 PPT 等未传 target_count 的链路保持原行为。\n    """
    type_alias = {"bullets": "content", "image_text": "content"}
    norm = []
    for s in (outline.get("slides") or []):
        t = s.get("type") or "content"
        legacy_image = (t == "image_text")
        t = type_alias.get(t, t)
        if t not in PAGE_TYPES:
            t = "content"
        layout = s.get("layout") or ("image_right" if legacy_image or s.get("image_name") else None)
        norm.append({
            "id": s.get("id") or uuid.uuid4().hex[:8],
            "type": t,
            "layout": layout,
            "layout_locked": bool(s.get("layout_locked", False)),
            "title": (s.get("title") or "")[:60],
            "subtitle": (s.get("subtitle") or "")[:80],
            "points": [str(p)[:150] for p in (s.get("points") or [])][:6],
            "blocks": s.get("blocks") or {},
            "image_name": s.get("image_name") or None,
            "image_hint": s.get("image_hint") or "",
            "note": s.get("note") or "",
            # 内容依据（材料名清单），编辑器右侧 AI 面板可展示
            "sources": [str(x)[:80] for x in (s.get("sources") or [])][:4],
        })
    if not norm or norm[0]["type"] != "cover":
        norm.insert(0, {"id": uuid.uuid4().hex[:8], "type": "cover",
                        "title": outline.get("title", "演示文稿"),
                        "subtitle": outline.get("subtitle", ""), "layout": None,
                        "points": [], "blocks": {}, "image_name": None, "image_hint": "",
                        "note": "", "sources": []})
    if norm[-1]["type"] != "closing":
        norm.append({"id": uuid.uuid4().hex[:8], "type": "closing", "title": "谢谢聆听，请批评指正",
                     "subtitle": "", "layout": None, "points": [], "blocks": {},
                     "image_name": None, "image_hint": "", "note": "", "sources": []})

    if target_count is not None:
        target = max(2, min(int(target_count), 18))
        # 保留首尾页，只调整中间正文页。
        if len(norm) > target:
            norm = [norm[0]] + norm[1:-1][:max(0, target - 2)] + [norm[-1]]
        while len(norm) < target:
            norm.insert(-1, {
                "id": uuid.uuid4().hex[:8], "type": "content", "layout": None,
                "title": "补充内容", "subtitle": "",
                "points": ["本页内容待根据已确认材料补充"],
                "blocks": {}, "image_name": None, "image_hint": "",
                "note": "页数硬约束补位页；不得自行编造事实或数据", "sources": [],
            })
    outline["slides"] = norm
    outline.setdefault("title", norm[0]["title"])
    outline.setdefault("subtitle", norm[0].get("subtitle", ""))
    return outline


def resolve_slide_images(outline: Dict, images: List[Dict]) -> Dict:
    """只使用本次授权的素材；说明与页面主题明显相符时才自动配图。"""
    by_name = {str(im["name"]): im for im in images}

    def _grams(value: str) -> set[str]:
        value = re.sub(r"[^\w\u4e00-\u9fff]", "", value.lower())
        return {value[i:i + 2] for i in range(len(value) - 1)}

    def _relevant(hint: str) -> Optional[Dict]:
        query = _grams(hint)
        if len(query) < 2:
            return None
        best, best_score = None, 0.0
        for im in images:
            if im.get("id") in used_auto_ids:
                continue
            description = f"{im.get('caption') or ''} {im.get('name') or ''}"
            terms = _grams(description)
            common = len(query & terms)
            score = common / len(query) if query else 0.0
            if common >= 2 and score > best_score:
                best, best_score = im, score
        return best if best_score >= 0.55 else None

    used_auto_ids: set[str] = set()
    for s in outline.get("slides", []):
        img = None
        if s.get("image_name"):
            img = by_name.get(str(s["image_name"]))
        if not img and s.get("type") == "content":
            img = _relevant(str(s.get("image_hint") or s.get("title") or ""))
            if img:
                used_auto_ids.add(str(img.get("id")))
        s["_image"] = img
        if img and s.get("layout") is None and s.get("type") == "content":
            s["layout"] = "image_right"
    return outline


# ================= 已有 PPT 导入：解析为可编辑大纲 =================

def outline_from_pptx(data: bytes) -> Dict:
    """解析已有 .pptx 为可编辑大纲（「上传 PPT 继续修改」入口）。

    提取每页标题 / 正文要点 / 演讲备注，页型按规则分类（不依赖 LLM）。
    解析失败抛 RuntimeError，由调用方转成用户可读提示。
    """
    from pptx import Presentation
    try:
        prs = Presentation(io.BytesIO(data))
    except Exception as e:
        raise RuntimeError(f"无法解析该 PPT 文件：{e}")
    slides = list(prs.slides)
    if not slides:
        raise RuntimeError("该 PPT 没有任何页面")
    sw, sh = prs.slide_width, prs.slide_height
    total = len(slides)
    out = []
    for idx, slide in enumerate(slides):
        texts = []  # (max_font_size, top, left, text)
        for shape in slide.shapes:
            try:
                if not shape.has_text_frame:
                    continue
                t = shape.text_frame.text.strip()
            except Exception:
                continue
            if not t:
                continue
            size = 0
            try:
                for para in shape.text_frame.paragraphs:
                    for run in para.runs:
                        if run.font.size and run.font.size.pt > size:
                            size = run.font.size.pt
            except Exception:
                pass
            texts.append((size, shape.top or 0, shape.left or 0, t))
        if not texts:
            continue
        texts.sort(key=lambda x: (-x[0], x[1], x[2]))
        title = texts[0][3].split("\n")[0][:60]
        points = []
        for _, _, _, t in texts[1:]:
            for line in t.split("\n"):
                line = line.strip()
                if line and line != title:
                    points.append(line[:150])
        points = points[:6]
        try:
            dtype = _classify_slide(_slide_elements(slide, sw, sh), idx, total)
        except Exception:
            dtype = "content"
        if dtype in ("content_image", "two_col"):
            dtype = "content"
        if dtype not in PAGE_TYPES:
            dtype = "content"
        note = ""
        try:
            note = slide.notes_slide.notes_text_frame.text.strip()[:200]
        except Exception:
            pass
        out.append({"type": dtype, "title": title, "points": points,
                    "note": note, "sources": []})
    if not out:
        raise RuntimeError("未能从该 PPT 提取到文字内容")
    return normalize_outline({"title": out[0]["title"] or "导入的PPT",
                              "subtitle": "", "slides": out})


# ================= PPTX 构建 =================

def _try_drawio_render(slide, data: Dict, box: tuple, font: str, warnings: list,
                       colors: Optional[Dict] = None) -> bool:
    """Roll back a failed diagram so the page can safely use its basic layout."""
    original_shapes = {shape._element for shape in slide.shapes}
    try:
        from app.application.ppt.drawio_native import render_diagram
        render_diagram(slide, data["blocks"]["drawio_xml"], *box, font, colors)
        return True
    except Exception as exc:
        for shape in list(slide.shapes):
            if shape._element not in original_shapes:
                shape._element.getparent().remove(shape._element)
        blocks = data.get("blocks") or {}
        kind = blocks.get("drawio_kind") or "process"
        is_process = kind == "process"
        layout = "基础流程版式" if is_process else "基础文字版式"
        check = "流程内容" if is_process else "图示节点与连线关系"
        message = f"页面「{data.get('title') or '图示'}」图示渲染失败，已使用{layout}，请核对{check}。"
        warnings.append(message)
        logger.warning("PPT 图示回退基础版式: %s", type(exc).__name__)
        items = (blocks.get("process") if is_process else
                 (blocks.get("diagram_labels") or blocks.get("process"))) or data.get("points") or []
        label = "原流程内容" if is_process else "原图示节点"
        slide.notes_slide.notes_text_frame.text = message + f"\n{label}：\n" + "\n".join(map(str, items))
        return False


def build_pptx(outline: Dict, template: Dict, base_pptx: bytes = None,
               warnings: Optional[List[str]] = None) -> bytes:
    """按模板渲染。template 为 template_to_dict 的结果。所有元素可编辑。

    base_pptx：用户上传的原始 pptx 字节。提供时以其为底版渲染——
    保留原模板的母版背景、装饰图形、主题配色，仅清空页面后逐页绘制内容。
    """
    from pptx import Presentation
    from pptx.util import Inches, Pt, Emu
    from pptx.dml.color import RGBColor
    from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.oxml.ns import qn

    warnings = warnings if warnings is not None else []

    colors, layouts = template["colors"], template["layouts"]
    FONT = template.get("font") or DEFAULT_CJK_FONT
    C = lambda h: RGBColor.from_string(h)
    PRIMARY, ACCENT = C(colors["primary"]), C(colors["accent"])
    LIGHT, DARK = C(colors["light"]), C(colors["dark"])
    WHITE, GRAY, LINE = C("FFFFFF"), C("595959"), C("E7E6E6")

    if base_pptx:
        # 以用户上传的模板为底版：继承母版/主题/页面尺寸，清空原页面（连关系一起删，避免示例内容残留）
        prs = Presentation(io.BytesIO(base_pptx))
        sldIdLst = prs.slides._sldIdLst
        for sld in list(sldIdLst):
            rid = sld.get(qn('r:id'))
            sldIdLst.remove(sld)
            try:
                prs.part.drop_rel(rid)
            except Exception:
                pass
        # 选占位符最少的版式当空白页，避免母版占位符干扰自绘内容
        try:
            blank = min(prs.slide_layouts, key=lambda l: len(l.placeholders))
        except Exception:
            blank = prs.slide_layouts[0]
    else:
        prs = Presentation()
        prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
        blank = prs.slide_layouts[6]
    SW, SH = prs.slide_width, prs.slide_height

    # 底版母版为深色背景时，标题/正文文字自动改浅色，保证可读
    if base_pptx:
        try:
            mbg = prs.slide_masters[0].background.fill
            bgc = str(mbg.fore_color.rgb)
            br, bg_, bb = (int(bgc[i:i + 2], 16) for i in (0, 2, 4))
            if 0.299 * br + 0.587 * bg_ + 0.114 * bb < 110:
                GRAY = C("E6E6E6")
                DARK = C("FFFFFF")
        except Exception:
            pass

    def lx(f): return Emu(int(SW * f))
    def ly(f): return Emu(int(SH * f))

    def _font(run, size, bold=False, color=None):
        run.font.name = FONT
        run.font.size = Pt(size)
        run.font.bold = bold
        if color is not None:
            run.font.color.rgb = color
        rPr = run._r.get_or_add_rPr()
        ea = rPr.find(qn('a:ea'))
        if ea is None:
            ea = rPr.makeelement(qn('a:ea'), {})
            rPr.append(ea)
        ea.set('typeface', FONT)

    def _alpha(shape, pct):
        """给形状填充加透明度。pct=剩余不透明度（0~100）。"""
        spPr = shape._element.spPr
        fill = spPr.find(qn('a:solidFill'))
        if fill is None:
            return
        clr = fill.find(qn('a:srgbClr'))
        if clr is None:
            return
        a = clr.makeelement(qn('a:alpha'), {'val': str(int(pct * 1000))})
        clr.append(a)

    def rect(slide, x, y, w, h, color, round_=False, alpha=None):
        shp = slide.shapes.add_shape(
            MSO_SHAPE.ROUNDED_RECTANGLE if round_ else MSO_SHAPE.RECTANGLE, x, y, w, h)
        shp.fill.solid()
        shp.fill.fore_color.rgb = color
        shp.line.fill.background()
        shp.shadow.inherit = False
        if round_:
            try:
                shp.adjustments[0] = 0.08
            except Exception:
                pass
        if alpha is not None:
            _alpha(shp, alpha)
        return shp

    def circle(slide, cx, cy, r, color, alpha):
        shp = slide.shapes.add_shape(MSO_SHAPE.OVAL, Emu(int(cx - r)), Emu(int(cy - r)),
                                     Emu(int(2 * r)), Emu(int(2 * r)))
        shp.fill.solid()
        shp.fill.fore_color.rgb = color
        shp.line.fill.background()
        shp.shadow.inherit = False
        _alpha(shp, alpha)
        return shp

    def text(slide, x, y, w, h, s, size, bold=False, color=None,
             align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP):
        tb = slide.shapes.add_textbox(x, y, w, h)
        tf = tb.text_frame
        tf.word_wrap = True
        tf.vertical_anchor = anchor
        p = tf.paragraphs[0]
        p.alignment = align
        r = p.add_run()
        r.text = s
        _font(r, size, bold, color)
        return tb

    def picture_fit(slide, path, x, y, w, h):
        from PIL import Image
        with Image.open(path) as im:
            iw, ih = im.size
        box_ratio, img_ratio = w / h, iw / ih
        pic = slide.shapes.add_picture(path, x, y, w, h)
        if img_ratio > box_ratio:
            crop = (1 - box_ratio / img_ratio) / 2
            pic.crop_left = pic.crop_right = crop
        else:
            crop = (1 - img_ratio / box_ratio) / 2
            pic.crop_top = pic.crop_bottom = crop
        return pic

    def deco_circles(slide, light_on_dark=True):
        """封面/章节/结束页的装饰圆。"""
        base = ACCENT if light_on_dark else PRIMARY
        circle(slide, SW * 0.92, SH * 0.12, SH * 0.30, base, 18)
        circle(slide, SW * 0.98, SH * 0.55, SH * 0.18, base, 12)
        circle(slide, SW * 0.06, SH * 0.95, SH * 0.24, base, 14)

    def footer(slide, idx, total):
        """内容页页脚：细分隔线 + 页码。"""
        rect(slide, lx(0.045), ly(0.955), lx(0.91), Emu(9525), LINE)
        text(slide, lx(0.88), ly(0.962), lx(0.08), ly(0.03), f"{idx} / {total}", 9, False, GRAY,
             align=PP_ALIGN.RIGHT)

    def page_header(slide, title, variant=None):
        """内容页页眉：bar=左侧竖条 / band=顶部色带 / none=整页留白（大字报页）。"""
        v = variant or layouts.get("content", "bar_title")
        if v == "none":
            return
        if v in ("band", "top_band"):
            rect(slide, 0, 0, SW, ly(0.135), PRIMARY)
            rect(slide, 0, ly(0.135), SW, ly(0.006), ACCENT)
            text(slide, lx(0.05), ly(0.032), lx(0.9), ly(0.08), title, 24, True, WHITE)
        else:
            rect(slide, 0, 0, SW, ly(0.014), PRIMARY)
            rect(slide, lx(0.045), ly(0.07), lx(0.014), ly(0.082), PRIMARY, round_=True)
            text(slide, lx(0.072), ly(0.062), lx(0.85), ly(0.10), title, 26, True, DARK)
            rect(slide, lx(0.045), ly(0.175), lx(0.91), Emu(12700), LINE)

    def notes(slide, note):
        if note:
            frame = slide.notes_slide.notes_text_frame
            frame.text = "\n".join(part for part in (frame.text, note) if part)

    def numbered_points(slide, pts, x=0.06, y=0.26, w=0.86, size=17):
        """编号要点：彩色序号圆角块 + 文字。"""
        for i, p in enumerate(pts):
            chip = rect(slide, lx(x), ly(y), lx(0.034), lx(0.034), PRIMARY, round_=True)
            tf = chip.text_frame
            tf.word_wrap = False
            para = tf.paragraphs[0]
            para.alignment = PP_ALIGN.CENTER
            r = para.add_run()
            r.text = str(i + 1)
            _font(r, 13, True, WHITE)
            text(slide, lx(x + 0.048), ly(y - 0.012), lx(w - 0.05), ly(0.12), p, size, False, GRAY)
            y += 0.128 if len(pts) <= 4 else 0.108
        return y

    def lay_of(s):
        """当前页选中的版式短名（content.two_col → two_col）。"""
        raw = str(s.get("_layout") or "")
        return raw.split(".", 1)[1] if "." in raw else raw

    def native_table(slide, spec, x, y, w, h):
        """原生表格（导出后可编辑、可加行）。数据不足时返回 None 由调用方降级。"""
        headers = [str(v) for v in (spec.get("headers") or [])]
        rows = [r for r in (spec.get("rows") or []) if r]
        if not headers or not rows:
            return None
        n_cols = max([len(headers)] + [len(r) for r in rows])
        gf = slide.shapes.add_table(len(rows) + 1, n_cols, x, y, w, h)
        tbl = gf.table
        for ci in range(n_cols):
            tbl.columns[ci].width = Emu(int(w / n_cols))
        for ci in range(n_cols):
            cell = tbl.cell(0, ci)
            cell.text = headers[ci] if ci < len(headers) else ""
            cell.fill.solid()
            cell.fill.fore_color.rgb = PRIMARY
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            for para in cell.text_frame.paragraphs:
                para.alignment = PP_ALIGN.CENTER
                for run in para.runs:
                    _font(run, 13, True, WHITE)
        for ri, row in enumerate(rows, start=1):
            for ci in range(n_cols):
                cell = tbl.cell(ri, ci)
                cell.text = str(row[ci]) if ci < len(row) else ""
                cell.fill.solid()
                cell.fill.fore_color.rgb = WHITE if ri % 2 else LIGHT
                cell.vertical_anchor = MSO_ANCHOR.MIDDLE
                for para in cell.text_frame.paragraphs:
                    para.alignment = PP_ALIGN.LEFT if ci == 0 else PP_ALIGN.CENTER
                    for run in para.runs:
                        _font(run, 12, ci == 0, DARK)
        return gf

    # ---------- 页型渲染 ----------
    def r_cover(s):
        slide = prs.slides.add_slide(blank)
        v = lay_of(s) or "band"
        if v == "minimal":
            rect(slide, 0, 0, SW, SH, WHITE)
            rect(slide, 0, 0, SW, ly(0.012), PRIMARY)
            rect(slide, lx(0.10), ly(0.30), lx(0.06), ly(0.008), ACCENT)
            text(slide, lx(0.10), ly(0.34), lx(0.74), ly(0.26), s["title"], 40, True, DARK)
            if s.get("subtitle"):
                text(slide, lx(0.10), ly(0.60), lx(0.68), ly(0.09), s["subtitle"], 17, False, GRAY)
            rect(slide, lx(0.84), ly(0.80), lx(0.10), lx(0.10), PRIMARY, round_=True)
            rect(slide, lx(0.862), ly(0.837), lx(0.056), ly(0.006), ACCENT)
            return slide
        if v == "side":
            rect(slide, 0, 0, lx(0.40), SH, PRIMARY)
            circle(slide, SW * 0.34, SH * 0.18, SH * 0.22, ACCENT, 18)
            circle(slide, SW * 0.08, SH * 0.88, SH * 0.26, ACCENT, 12)
            rect(slide, lx(0.40), 0, lx(0.008), SH, ACCENT)
            rect(slide, lx(0.50), ly(0.36), lx(0.05), ly(0.010), ACCENT)
            text(slide, lx(0.50), ly(0.40), lx(0.44), ly(0.24), s["title"], 36, True, DARK)
            if s.get("subtitle"):
                text(slide, lx(0.50), ly(0.62), lx(0.44), ly(0.08), s["subtitle"], 17, False, GRAY)
        else:
            rect(slide, 0, 0, SW, SH, PRIMARY)
            deco_circles(slide)
            rect(slide, 0, ly(0.86), SW, ly(0.14), DARK, alpha=60)
            rect(slide, lx(0.10), ly(0.315), lx(0.055), ly(0.011), ACCENT)
            text(slide, lx(0.10), ly(0.36), lx(0.8), ly(0.20), s["title"], 40, True, WHITE)
            if s.get("subtitle"):
                text(slide, lx(0.10), ly(0.56), lx(0.8), ly(0.08), s["subtitle"], 18, False,
                     C("F2DCDB"))
        return slide

    def r_toc(s):
        slide = prs.slides.add_slide(blank)
        page_header(slide, s["title"] or "目录")
        items = s["points"][:6]
        v = lay_of(s) or "list"
        if v == "grid":
            for i, it in enumerate(items[:6]):
                cx = 0.06 + (i % 3) * 0.295
                cy = 0.285 + (i // 3) * 0.275
                rect(slide, lx(cx), ly(cy), lx(0.275), ly(0.215), LIGHT, round_=True)
                rect(slide, lx(cx), ly(cy), lx(0.275), ly(0.010), ACCENT)
                text(slide, lx(cx + 0.022), ly(cy + 0.032), lx(0.13), ly(0.09),
                     f"{i+1:02d}", 26, True, ACCENT)
                text(slide, lx(cx + 0.022), ly(cy + 0.122), lx(0.235), ly(0.08), it, 14, True, DARK)
        elif v == "cards":
            cols = 2
            cw, ch = 0.415, 0.155
            for i, it in enumerate(items[:4]):
                cx = 0.065 + (i % cols) * (cw + 0.035)
                cy = 0.28 + (i // cols) * (ch + 0.055)
                rect(slide, lx(cx), ly(cy), lx(cw), ly(ch), LIGHT, round_=True)
                rect(slide, lx(cx), ly(cy), lx(0.010), ly(ch), PRIMARY)
                text(slide, lx(cx + 0.03), ly(cy + 0.045), lx(0.07), ly(0.08), f"{i+1:02d}",
                     22, True, PRIMARY)
                text(slide, lx(cx + 0.105), ly(cy + 0.055), lx(cw - 0.13), ly(0.08), it,
                     17, True, DARK)
        else:
            y = 0.27
            for i, it in enumerate(items):
                chip = rect(slide, lx(0.07), ly(y), lx(0.042), lx(0.042), PRIMARY, round_=True)
                tf = chip.text_frame
                para = tf.paragraphs[0]
                para.alignment = PP_ALIGN.CENTER
                r = para.add_run()
                r.text = f"{i+1:02d}"
                _font(r, 14, True, WHITE)
                text(slide, lx(0.135), ly(y + 0.006), lx(0.75), ly(0.06), it, 19, True, DARK)
                if i < len(items) - 1:
                    rect(slide, lx(0.07), ly(y + 0.088), lx(0.82), Emu(9525), LINE)
                y += 0.128
        return slide

    def r_section(s):
        slide = prs.slides.add_slide(blank)
        v = lay_of(s) or "side"
        if v == "number":
            rect(slide, 0, 0, SW, SH, PRIMARY)
            deco_circles(slide)
            no = int(s.get("_sec_no") or 1)
            text(slide, lx(0.06), ly(0.10), lx(0.60), ly(0.52), f"{no:02d}", 150, True,
                 WHITE)
            rect(slide, lx(0.83), ly(0.57), lx(0.10), ly(0.008), ACCENT)
            text(slide, lx(0.40), ly(0.60), lx(0.50), ly(0.16), s["title"], 32, True, WHITE,
                 align=PP_ALIGN.RIGHT)
            return slide
        if v == "center":
            rect(slide, 0, 0, SW, SH, LIGHT)
            circle(slide, SW * 0.9, SH * 0.15, SH * 0.25, PRIMARY, 10)
            circle(slide, SW * 0.08, SH * 0.9, SH * 0.2, PRIMARY, 8)
            rect(slide, lx(0.43), ly(0.40), lx(0.14), ly(0.009), ACCENT)
            text(slide, 0, ly(0.45), SW, ly(0.16), s["title"], 36, True, DARK,
                 align=PP_ALIGN.CENTER)
        else:
            rect(slide, 0, 0, lx(0.34), SH, PRIMARY)
            circle(slide, SW * 0.28, SH * 0.2, SH * 0.2, ACCENT, 16)
            circle(slide, SW * 0.06, SH * 0.85, SH * 0.24, ACCENT, 10)
            rect(slide, lx(0.34), 0, lx(0.008), SH, ACCENT)
            rect(slide, lx(0.06), ly(0.40), lx(0.05), ly(0.010), ACCENT)
            text(slide, lx(0.06), ly(0.44), lx(0.26), ly(0.18), s["title"], 30, True, WHITE)
        return slide

    def _content_image(s):
        slide = prs.slides.add_slide(blank)
        page_header(slide, s["title"])
        img = s["_image"]
        points = s["points"]
        y = 0.26
        step = 0.125 if len(points) <= 4 else 0.105
        for p in points:
            rect(slide, lx(0.06), ly(y + 0.014), lx(0.013), lx(0.013), ACCENT)
            text(slide, lx(0.085), ly(y), lx(0.40), ly(0.13), p, 16, False, GRAY)
            y += step
        ix, iy, iw, ih = lx(0.53), ly(0.235), lx(0.43), ly(0.60)
        rect(slide, ix + lx(0.008), iy + ly(0.015), iw, ih, LIGHT, round_=True)
        picture_fit(slide, img["file_path"], ix, iy, iw, ih)
        text(slide, ix, iy + ih + ly(0.012), iw, ly(0.045),
             f"▲ {img.get('caption') or img['name']}", 11, False, GRAY, align=PP_ALIGN.CENTER)
        return slide

    def _content_bullets(s):
        slide = prs.slides.add_slide(blank)
        page_header(slide, s["title"])
        y0 = 0.22 if (layouts.get("content") or "") == "band" else 0.26
        numbered_points(slide, s["points"], y=y0, size=17)
        return slide

    def _content_two_col(s):
        """双栏并列：4~6 条按奇偶分栏，适合并列举措、多组要点。"""
        slide = prs.slides.add_slide(blank)
        page_header(slide, s["title"])
        pts = s["points"]
        half = (len(pts) + 1) // 2
        for ci, group in enumerate((pts[:half], pts[half:])):
            cx = 0.06 + ci * 0.465
            rect(slide, lx(cx), ly(0.252), lx(0.10), ly(0.008), ACCENT)
            y = 0.30
            size = 16 if len(group) <= 2 else 14
            step = 0.30 if len(group) <= 2 else 0.21
            for p in group:
                rect(slide, lx(cx), ly(y + 0.016), lx(0.012), lx(0.012), PRIMARY)
                text(slide, lx(cx + 0.028), ly(y), lx(0.395), ly(step), p, size, False, DARK)
                y += step
        return slide

    def _content_three_cards(s):
        """三卡并列：正好 3 条时最稳，每卡一个序号 + 一句话。"""
        slide = prs.slides.add_slide(blank)
        page_header(slide, s["title"])
        for i, p in enumerate(s["points"][:3]):
            cx = 0.055 + i * 0.297
            rect(slide, lx(cx), ly(0.295), lx(0.283), ly(0.47), LIGHT, round_=True)
            rect(slide, lx(cx), ly(0.295), lx(0.283), ly(0.012), PRIMARY)
            text(slide, lx(cx + 0.028), ly(0.34), lx(0.13), ly(0.10), f"{i+1:02d}",
                 30, True, ACCENT)
            text(slide, lx(cx + 0.028), ly(0.445), lx(0.232), ly(0.29), p, 15, False, DARK)
        return slide

    def _content_compare(s):
        """左右对比：正好 2 条时用，中间加对比标记。"""
        slide = prs.slides.add_slide(blank)
        page_header(slide, s["title"])
        pts = (s["points"] + ["", ""])[:2]
        for i, p in enumerate(pts):
            cx = 0.055 + i * 0.49
            rect(slide, lx(cx), ly(0.265), lx(0.40), ly(0.53), LIGHT if i == 0 else WHITE,
                 round_=True)
            rect(slide, lx(cx), ly(0.265), lx(0.40), ly(0.012), PRIMARY if i == 0 else ACCENT)
            text(slide, lx(cx + 0.03), ly(0.315), lx(0.08), ly(0.06), f"0{i+1}", 14, True, GRAY)
            text(slide, lx(cx + 0.03), ly(0.385), lx(0.34), ly(0.34), p, 16, False, DARK)
        rect(slide, lx(0.455), ly(0.495), lx(0.05), ly(0.05), PRIMARY, round_=True)
        text(slide, lx(0.455), ly(0.505), lx(0.05), ly(0.035), "对比", 10, True, WHITE,
             align=PP_ALIGN.CENTER)
        return slide

    def _content_icon_grid(s):
        """四宫格：3~4 条短句，强调并列关系而非先后顺序。"""
        slide = prs.slides.add_slide(blank)
        page_header(slide, s["title"])
        for i, p in enumerate(s["points"][:4]):
            cx = 0.055 + (i % 2) * 0.465
            cy = 0.27 + (i // 2) * 0.305
            rect(slide, lx(cx), ly(cy), lx(0.44), ly(0.265), LIGHT, round_=True)
            circle(slide, lx(cx + 0.045), ly(cy + 0.072), SH * 0.024, ACCENT, 100)
            text(slide, lx(cx + 0.078), ly(cy + 0.042), lx(0.33), ly(0.055),
                 f"0{i+1}", 12, True, PRIMARY)
            text(slide, lx(cx + 0.078), ly(cy + 0.105), lx(0.325), ly(0.14), p, 14, False, DARK)
        return slide

    def _content_statement(s):
        """单句结论：一条主张铺满页面，牺牲信息量换冲击力。"""
        slide = prs.slides.add_slide(blank)
        rect(slide, 0, 0, lx(0.016), SH, PRIMARY)
        rect(slide, lx(0.10), ly(0.235), lx(0.05), ly(0.008), ACCENT)
        text(slide, lx(0.10), ly(0.275), lx(0.78), ly(0.08), s["title"], 17, False, GRAY)
        text(slide, lx(0.10), ly(0.40), lx(0.80), ly(0.30), s["points"][0], 34, True, DARK)
        rect(slide, lx(0.10), ly(0.80), lx(0.86), Emu(9525), LINE)
        return slide

    def _content_quote(s):
        """引言金句：引用原文 + 出处，政策解读/动员场合适用。"""
        slide = prs.slides.add_slide(blank)
        rect(slide, 0, 0, SW, SH, LIGHT)
        text(slide, lx(0.09), ly(0.11), lx(0.10), ly(0.20), "“", 96, True, ACCENT)
        text(slide, lx(0.14), ly(0.30), lx(0.72), ly(0.30), s["points"][0], 26, True, DARK)
        src = s["points"][1] if len(s["points"]) > 1 else ""
        rect(slide, lx(0.145), ly(0.645), lx(0.06), ly(0.008), PRIMARY)
        if src:
            text(slide, lx(0.145), ly(0.675), lx(0.62), ly(0.06), f"—— {src}", 14, False, GRAY)
        text(slide, lx(0.72), ly(0.86), lx(0.22), ly(0.05), s["title"], 11, False, GRAY,
             align=PP_ALIGN.RIGHT)
        return slide

    def r_content(s):
        v = lay_of(s) or "bullets"
        if v == "image_right":
            img = s.get("_image") or {}
            if img.get("file_path"):
                return _content_image(s)
            v = "bullets"
        return {
            "two_col": _content_two_col,
            "three_cards": _content_three_cards,
            "compare": _content_compare,
            "icon_grid": _content_icon_grid,
            "statement": _content_statement,
            "quote": _content_quote,
        }.get(v, _content_bullets)(s)

    def r_data(s):
        blocks = s.get("blocks") or {}
        cards = blocks.get("cards") or []
        table = blocks.get("table") or {}
        points = [str(p) for p in (s.get("points") or [])]
        v = lay_of(s) or "cards"
        slide = prs.slides.add_slide(blank)

        if v == "table" and table.get("rows"):
            page_header(slide, s["title"])
            native_table(slide, table, lx(0.055), ly(0.235), lx(0.89), ly(0.58))
            for j, p in enumerate(points[:2]):
                text(slide, lx(0.06), ly(0.845 + j * 0.045), lx(0.88), ly(0.045), p, 12, False, GRAY)
            return slide

        if v == "kpi" and cards:
            page_header(slide, s["title"])
            main = cards[0]
            rect(slide, lx(0.055), ly(0.245), lx(0.36), ly(0.50), PRIMARY, round_=True)
            text(slide, lx(0.075), ly(0.315), lx(0.32), ly(0.20), str(main.get("value", "")),
                 50, True, WHITE, align=PP_ALIGN.CENTER)
            text(slide, lx(0.075), ly(0.545), lx(0.32), ly(0.08), str(main.get("label", "")),
                 16, False, C("D6E4F0"), align=PP_ALIGN.CENTER)
            for i, c in enumerate(cards[1:4]):
                cy = 0.245 + i * 0.175
                rect(slide, lx(0.45), ly(cy), lx(0.50), ly(0.15), LIGHT, round_=True)
                text(slide, lx(0.472), ly(cy + 0.015), lx(0.21), ly(0.11),
                     str(c.get("value", "")), 24, True, PRIMARY)
                text(slide, lx(0.685), ly(cy + 0.042), lx(0.245), ly(0.07),
                     str(c.get("label", "")), 14, False, GRAY)
            for j, p in enumerate(points[:2]):
                text(slide, lx(0.06), ly(0.80 + j * 0.05), lx(0.88), ly(0.05), p, 13, False, GRAY)
            return slide

        page_header(slide, s["title"])
        cards = cards[:4]
        if cards:
            n = len(cards)
            cw = 0.88 / n - 0.02
            for i, c in enumerate(cards):
                cx = 0.06 + i * (cw + 0.02)
                rect(slide, lx(cx), ly(0.33), lx(cw), ly(0.30), LIGHT, round_=True)
                rect(slide, lx(cx), ly(0.33), lx(cw), ly(0.014), PRIMARY)
                text(slide, lx(cx), ly(0.395), lx(cw), ly(0.12), str(c.get("value", "")),
                     32, True, PRIMARY, align=PP_ALIGN.CENTER)
                rect(slide, lx(cx + cw / 2 - 0.02), ly(0.535), lx(0.04), ly(0.006), ACCENT)
                text(slide, lx(cx), ly(0.555), lx(cw), ly(0.06), str(c.get("label", "")),
                     14, False, GRAY, align=PP_ALIGN.CENTER)
        for j, p in enumerate(points[:3]):
            rect(slide, lx(0.065), ly(0.735 + j * 0.068), lx(0.010), lx(0.010), ACCENT)
            text(slide, lx(0.088), ly(0.72 + j * 0.068), lx(0.84), ly(0.06), p, 14, False, GRAY)
        return slide

    def _draw_chart(slide, chart_spec, x, y, w, h):
        """画原生可编辑图表；数据不完整返回 False 交由调用方降级。"""
        from pptx.chart.data import CategoryChartData
        from pptx.enum.chart import XL_CHART_TYPE
        cats = chart_spec.get("categories") or []
        series = chart_spec.get("series") or []
        if not (cats and series):
            return False
        ct = (chart_spec.get("chart_type") or "bar").lower()
        chart_type = {"bar": XL_CHART_TYPE.COLUMN_CLUSTERED,
                      "column": XL_CHART_TYPE.COLUMN_CLUSTERED,
                      "bar_h": XL_CHART_TYPE.BAR_CLUSTERED,
                      "stacked": XL_CHART_TYPE.COLUMN_STACKED,
                      "line": XL_CHART_TYPE.LINE_MARKERS,
                      "pie": XL_CHART_TYPE.PIE,
                      "doughnut": XL_CHART_TYPE.DOUGHNUT,
                      "area": XL_CHART_TYPE.AREA}.get(ct, XL_CHART_TYPE.COLUMN_CLUSTERED)
        data = CategoryChartData()
        data.categories = [str(c) for c in cats]
        n_series = 0
        for se in series:
            try:
                data.add_series(str(se.get("name", "")), [float(v) for v in se.get("values", [])])
                n_series += 1
            except (TypeError, ValueError):
                continue
        if not n_series:
            return False
        rect(slide, x - lx(0.02), y - ly(0.02), w + lx(0.04), h + ly(0.04), LIGHT, round_=True)
        gf = slide.shapes.add_chart(chart_type, x, y, w, h, data)
        gf.chart.has_legend = n_series > 1
        try:
            palette = [PRIMARY, ACCENT, DARK, C("8FAADC")]
            for si, serie in enumerate(gf.chart.series):
                serie.format.fill.solid()
                serie.format.fill.fore_color.rgb = palette[si % len(palette)]
                serie.format.line.color.rgb = palette[si % len(palette)]
        except Exception:
            pass
        return True

    def r_chart(s):
        """图表页：原生 pptx 图表（导出后可双击编辑数据）。"""
        slide = prs.slides.add_slide(blank)
        page_header(slide, s["title"])
        chart_spec = (s.get("blocks") or {}).get("chart") or {}
        points = [str(p) for p in (s.get("points") or [])]
        if (lay_of(s) or "full") == "split":
            _draw_chart(slide, chart_spec, lx(0.065), ly(0.245), lx(0.575), ly(0.60))
            rect(slide, lx(0.685), ly(0.245), lx(0.07), ly(0.008), ACCENT)
            y = 0.295
            for p in points[:3]:
                rect(slide, lx(0.685), ly(y + 0.014), lx(0.012), lx(0.012), PRIMARY)
                text(slide, lx(0.712), ly(y - 0.006), lx(0.238), ly(0.17), p, 14, False, DARK)
                y += 0.195
            return slide
        _draw_chart(slide, chart_spec, lx(0.09), ly(0.25), lx(0.82), ly(0.60))
        for j, p in enumerate(points[:2]):
            text(slide, lx(0.07), ly(0.90 + j * 0.045), lx(0.86), ly(0.045), p, 12, False, GRAY)
        return slide

    def r_case(s):
        slide = prs.slides.add_slide(blank)
        page_header(slide, s["title"])
        pts = [str(p) for p in (s.get("points") or [])]
        if (lay_of(s) or "block") == "split" and len(pts) >= 3:
            base, extra = divmod(len(pts), 3)
            groups, start = [], 0
            for gi in range(3):
                take = base + (1 if gi < extra else 0)
                groups.append(pts[start:start + take])
                start += take
            for gi, group in enumerate(groups):
                cx = 0.055 + gi * 0.30
                rect(slide, lx(cx), ly(0.25), lx(0.278), ly(0.57), LIGHT, round_=True)
                rect(slide, lx(cx), ly(0.25), lx(0.278), ly(0.010), PRIMARY)
                text(slide, lx(cx + 0.022), ly(0.285), lx(0.10), ly(0.06), f"0{gi+1}",
                     16, True, ACCENT)
                y = 0.365
                step = 0.19 if len(group) <= 2 else 0.135
                for p in group:
                    text(slide, lx(cx + 0.022), ly(y), lx(0.235), ly(step), p,
                         13 if len(group) <= 2 else 12, False, DARK)
                    y += step
            return slide
        rect(slide, lx(0.055), ly(0.235), lx(0.89), ly(0.64), LIGHT, round_=True)
        rect(slide, lx(0.055), ly(0.235), lx(0.012), ly(0.64), ACCENT)
        y = 0.30
        for p in pts:
            text(slide, lx(0.10), ly(y), lx(0.80), ly(0.14), p, 17, False, DARK)
            y += 0.145
        return slide

    def r_timeline(s):
        slide = prs.slides.add_slide(blank)
        page_header(slide, s["title"])
        all_items = (s.get("blocks") or {}).get("timeline") or []
        if (lay_of(s) or "horizontal") == "vertical" and len(all_items) >= 3:
            items = all_items[:6]
            rect(slide, lx(0.175), ly(0.245), Emu(19050), ly(0.60), LINE)
            step = 0.60 / len(items)
            for i, it in enumerate(items):
                cy = 0.245 + step * (i + 0.5)
                text(slide, lx(0.04), ly(cy - 0.035), lx(0.115), ly(0.07),
                     str(it.get("time", "")), 13, True, PRIMARY, align=PP_ALIGN.RIGHT)
                circle(slide, lx(0.175), ly(cy - 0.006), SH * 0.012, PRIMARY, 100)
                text(slide, lx(0.215), ly(cy - 0.045), lx(0.70), ly(step), str(it.get("text", "")),
                     14, False, DARK)
            return slide
        items = all_items[:5]
        n = max(len(items), 1)
        yline = 0.52
        rect(slide, lx(0.08), ly(yline), lx(0.84), ly(0.009), ACCENT, round_=True)
        for i, it in enumerate(items):
            cx = 0.10 + i * (0.80 / max(n - 1, 1))
            dot = slide.shapes.add_shape(MSO_SHAPE.OVAL, lx(cx - 0.009), ly(yline - 0.014),
                                         lx(0.018), lx(0.018))
            dot.fill.solid()
            dot.fill.fore_color.rgb = PRIMARY
            dot.line.color.rgb = WHITE
            dot.line.width = Pt(2)
            up = (i % 2 == 0)
            text(slide, lx(cx - 0.07), ly(yline - 0.105 if up else yline + 0.035), lx(0.14),
                 ly(0.05), str(it.get("time", "")), 14, True, PRIMARY, align=PP_ALIGN.CENTER)
            text(slide, lx(cx - 0.07), ly(yline - 0.06 if up else yline + 0.08), lx(0.14),
                 ly(0.10), str(it.get("text", "")), 12, False, GRAY, align=PP_ALIGN.CENTER)
        for j, p in enumerate(s["points"][:2]):
            text(slide, lx(0.07), ly(0.80 + j * 0.06), lx(0.86), ly(0.05), p, 14, False, GRAY)
        return slide

    def r_process(s):
        slide = prs.slides.add_slide(blank)
        page_header(slide, s["title"])
        diagram_xml = (s.get("blocks") or {}).get("drawio_xml")
        if diagram_xml:
            if _try_drawio_render(slide, s, (lx(.06), ly(.23), lx(.88), ly(.64)), FONT, warnings, colors):
                return slide
            # A fallback must retain every supplied step, rather than silently
            # truncating a richer diagram to the five-chevron layout below.
            blocks = s.get("blocks") or {}
            is_process = (blocks.get("drawio_kind") or "process") == "process"
            items = (blocks.get("process") if is_process else
                     (blocks.get("diagram_labels") or blocks.get("process"))) or s.get("points") or []
            rows = max(1, (len(items) + 1) // 2)
            for index, value in enumerate(items):
                column, row = divmod(index, rows)
                text(slide, lx(.06 + column * .45), ly(.24 + row * .64 / rows),
                     lx(.42), ly(.64 / rows),
                     f"{index + 1}. {value}" if is_process else str(value),
                     14 if rows <= 8 else 11, False, DARK)
            if not items:
                text(slide, lx(.06), ly(.3), lx(.88), ly(.15),
                     "该页图示暂无法显示，请核对原内容。", 16, False, GRAY)
            return slide
        all_steps = (s.get("blocks") or {}).get("process") or s["points"]
        if (lay_of(s) or "chevron") == "vertical" and len(all_steps) >= 3:
            steps = all_steps[:7]
            step_h = 0.60 / len(steps)
            for i, st in enumerate(steps):
                cy = 0.25 + i * step_h
                rect(slide, lx(0.075), ly(cy + 0.008), lx(0.042), lx(0.042), PRIMARY, round_=True)
                text(slide, lx(0.075), ly(cy + 0.018), lx(0.042), ly(0.03), f"{i+1}",
                     13, True, WHITE, align=PP_ALIGN.CENTER)
                if i < len(steps) - 1:
                    rect(slide, lx(0.0955), ly(cy + 0.056), Emu(12700), ly(step_h - 0.056), LINE)
                text(slide, lx(0.14), ly(cy), lx(0.80), ly(step_h - 0.02), str(st),
                     15 if len(steps) <= 5 else 13, False, DARK)
            return slide
        steps = (all_steps)[:5]
        n = max(len(steps), 1)
        cw = 0.88 / n
        for i, st in enumerate(steps):
            cx = 0.06 + i * cw
            shp = slide.shapes.add_shape(MSO_SHAPE.CHEVRON, lx(cx), ly(0.36), lx(cw - 0.008),
                                         ly(0.13))
            shp.fill.solid()
            shp.fill.fore_color.rgb = PRIMARY if i % 2 == 0 else DARK
            shp.line.fill.background()
            shp.shadow.inherit = False
            tf = shp.text_frame
            tf.word_wrap = True
            p = tf.paragraphs[0]
            p.alignment = PP_ALIGN.CENTER
            r = p.add_run()
            r.text = str(st)
            _font(r, 13, True, WHITE)
            text(slide, lx(cx), ly(0.53), lx(cw - 0.008), ly(0.07), f"第{i+1}步", 12, False,
                 GRAY, align=PP_ALIGN.CENTER)
        for j, p in enumerate(s["points"][:3]):
            text(slide, lx(0.07), ly(0.70 + j * 0.06), lx(0.86), ly(0.05), p, 14, False, GRAY)
        return slide

    def r_summary(s):
        slide = prs.slides.add_slide(blank)
        page_header(slide, s["title"])
        pts = s["points"][:4]
        if (lay_of(s) or "cards") == "list":
            step = 0.60 / max(len(pts), 1)
            for i, p in enumerate(pts):
                cy = 0.27 + i * step
                text(slide, lx(0.07), ly(cy - 0.012), lx(0.11), ly(0.10), f"0{i+1}",
                     30, True, ACCENT)
                text(slide, lx(0.205), ly(cy + 0.01), lx(0.735), ly(step - 0.04), p, 20,
                     False, DARK)
                if i < len(pts) - 1:
                    rect(slide, lx(0.07), ly(cy + step - 0.025), lx(0.86), Emu(9525), LINE)
            return slide
        cw = 0.425
        for i, p in enumerate(pts):
            cx = 0.06 + (i % 2) * (cw + 0.04)
            cy = 0.26 + (i // 2) * 0.25
            rect(slide, lx(cx), ly(cy), lx(cw), ly(0.20), LIGHT, round_=True)
            rect(slide, lx(cx), ly(cy), lx(0.012), ly(0.20), ACCENT)
            text(slide, lx(cx + 0.032), ly(cy + 0.035), lx(cw - 0.06), ly(0.15), p, 15, False, DARK)
        return slide

    def r_closing(s):
        slide = prs.slides.add_slide(blank)
        rect(slide, 0, 0, SW, SH, PRIMARY)
        deco_circles(slide)
        if lay_of(s) == "band":
            rect(slide, 0, ly(0.86), SW, ly(0.14), DARK, alpha=60)
        rect(slide, lx(0.44), ly(0.50), lx(0.12), ly(0.010), ACCENT)
        text(slide, 0, ly(0.40), SW, ly(0.14), s["title"] or "谢谢聆听", 42, True, WHITE,
             align=PP_ALIGN.CENTER)
        return slide

    renderers = {"cover": r_cover, "toc": r_toc, "section": r_section, "content": r_content,
                 "data": r_data, "chart": r_chart, "case": r_case, "timeline": r_timeline,
                 "process": r_process, "summary": r_summary, "closing": r_closing}

    slides_list = [dict(s) for s in (outline.get("slides") or [])]
    total = len(slides_list)
    # 先统一选版：相邻页去重 + 整篇均衡，避免"每页长得一样"的模板感
    used_layouts: Dict[str, int] = {}
    recent_layouts: List[str] = []
    sec_no = 0
    for s in slides_list:
        if s.get("type") == "section":
            sec_no += 1
            s["_sec_no"] = sec_no
        chosen = choose_layout(s, layouts, recent=recent_layouts, used=used_layouts)
        s["_layout"] = chosen
        if chosen:
            used_layouts[chosen] = used_layouts.get(chosen, 0) + 1
            recent_layouts = (recent_layouts + [chosen])[-2:]
    for idx, s in enumerate(slides_list, 1):
        slide = renderers.get(s.get("type"), r_content)(s)
        if s.get("type") in ("content", "toc", "data", "chart", "case", "timeline",
                             "process", "summary"):
            footer(slide, idx, total)
        notes(slide, s.get("note"))

    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


# ================= AI 页面级操作（编辑器右侧 AI 助手用） =================

_SLIDE_SYSTEM = "你是 PPT 内容编辑模块，只输出 JSON，不要用 markdown 包裹。"


def _slide_json(slide: Dict) -> str:
    return json.dumps({k: v for k, v in slide.items() if not k.startswith("_")},
                      ensure_ascii=False)


def ai_slide_action(assistant, action: str, slide: Dict, instruction: str = "") -> Dict:
    """AI 重写 / 扩写 / 精简 / 自定义指令修改单页。返回更新后的 slide。"""
    action_desc = {
        "rewrite": "整体重写这一页：换更清晰有力的表达，保持事实不变",
        "expand": "扩写这一页：把要点展开为更充实的表述，每条不超过40字",
        "condense": "精简这一页：压缩要点数量与字数，保留核心信息",
        "custom": instruction or "优化这一页",
    }.get(action, instruction or "优化这一页")

    prompt = f"""请处理一页 PPT 内容。

【操作要求】{action_desc}
【页面类型】{slide.get('type')}
【当前页面 JSON】
{_slide_json(slide)}

【输出要求】
1. 只输出修改后的该页 JSON（保持相同字段结构，保留 id/type/layout/blocks/sources 结构，只改文字内容）；
2. 要点仍是 15~40 字的完整句子，有信息量；
3. 不要虚构事实和数据。"""
    raw = assistant.complete(
        [{"role": "system", "content": _SLIDE_SYSTEM},
         {"role": "user", "content": prompt}],
        temperature=0.5, max_tokens=1500)
    updated = _loads_ai_json(raw, "AI 这次返回的内容格式不规范，页面未被修改，请重试该操作")
    merged = {**slide, **updated, "id": slide.get("id") or uuid.uuid4().hex[:8]}
    merged.pop("_image", None)
    # 注意：normalize_outline() 会恒定保证"首屏 cover、末屏 closing"，对单页调用时
    # 会在 index 0 插入一页合成封面，因此**不能**按索引取 ["slides"][0]，
    # 必须按 id 取回真正被改写的那一页（merged["id"] 上面已保证非空）。
    slides = normalize_outline({"slides": [merged]})["slides"]
    return next((s for s in slides if s.get("id") == merged["id"]), merged)


def ai_generate_visual(assistant, kind: str, slide: Dict, instruction: str = "") -> Dict:
    """AI 生成图表 / 时间轴 / 流程图 / 数据卡片，写入 slide.blocks。

    kind: chart / timeline / process / data
    """
    spec_desc = {
        "chart": '{"chart":{"chart_type":"bar或pie或line","categories":["类别"...],"series":[{"name":"系列","values":[数值...]}]}}',
        "timeline": '{"timeline":[{"time":"时间点","text":"事项"},...]}（3~5 个节点）',
        "process": '{"process":["步骤1","步骤2",...]}（3~5 步）',
        "data": '{"cards":[{"label":"指标名","value":"数值"},...]}（3~4 张卡）',
    }
    prompt = f"""请根据页面内容生成"{kind}"可视化数据。

【页面内容】
{_slide_json(slide)}
【补充要求】{instruction or '无'}

【输出要求】
1. 只输出 JSON，格式：{{"blocks": {spec_desc[kind]}}}；
2. 数据必须来自页面内容或补充要求，不要虚构数字；
3. 页面内容不足以生成时，返回 {{"error": "原因"}}。"""
    raw = assistant.complete(
        [{"role": "system", "content": _SLIDE_SYSTEM},
         {"role": "user", "content": prompt}],
        temperature=0.4, max_tokens=1200)
    result = _loads_ai_json(raw, "AI 这次返回的可视化数据格式不规范，页面未被修改，请重试该操作")
    if result.get("error"):
        raise RuntimeError(result["error"])
    updated = dict(slide)
    updated["type"] = kind
    updated["blocks"] = result.get("blocks") or {}
    return updated


def ai_structure_action(assistant, action: str, slides: List[Dict], index: int,
                        instruction: str = "") -> List[Dict]:
    """AI 增加 / 拆分 / 合并页面，返回新的 slides 数组。

    action: add（在 index 后新增一页）/ split（把 index 页拆成两页）/ merge（合并 index 与下一页）
    """
    ctx = json.dumps([{k: v for k, v in s.items() if not k.startswith("_")} for s in slides],
                     ensure_ascii=False)[:3000]
    target = slides[index] if 0 <= index < len(slides) else None

    if action == "add":
        prompt = f"""这份 PPT 的大纲如下：
{ctx}
用户要求：在第 {index + 1} 页之后新增一页。{instruction or '内容与上下文衔接，补充有价值的信息。'}
只输出新增页面的 JSON（type/title/points/blocks 结构，内容要实，不要虚构数据）。"""
        raw = assistant.complete([{"role": "system", "content": _SLIDE_SYSTEM},
                                  {"role": "user", "content": prompt}],
                                 temperature=0.5, max_tokens=1200)
        new_slide = _loads_ai_json(
            raw, "AI 这次返回的内容格式不规范，没有新增页面，请重试该操作")
        new_slide["id"] = uuid.uuid4().hex[:8]
        new_slide.setdefault("type", "content")
        new_slide.setdefault("points", [])
        new_slide.setdefault("blocks", {})
        slides = slides[:index + 1] + [new_slide] + slides[index + 1:]

    elif action == "split":
        if not target:
            raise RuntimeError("目标页面不存在")
        pts = target.get("points") or []
        if len(pts) < 2:
            raise RuntimeError("该页内容太少，无法拆分")
        half = (len(pts) + 1) // 2
        a = dict(target, points=pts[:half])
        b = dict(target, id=uuid.uuid4().hex[:8],
                 title=(target.get("title") or "") + "（续）", points=pts[half:])
        slides = slides[:index] + [a, b] + slides[index + 1:]

    elif action == "merge":
        if not target or index + 1 >= len(slides):
            raise RuntimeError("没有可合并的下一页")
        nxt = slides[index + 1]
        merged = dict(target)
        merged["points"] = (target.get("points") or []) + (nxt.get("points") or [])
        merged["blocks"] = target.get("blocks") or nxt.get("blocks") or {}
        slides = slides[:index] + [merged] + slides[index + 2:]
    else:
        raise RuntimeError("不支持的操作")

    return normalize_outline({"title": "", "slides": slides})["slides"]


def ai_outline_adjust(assistant, outline: Dict, instruction: str) -> Dict:
    """AI 整体调整大纲：一句自然语言指令作用于整份大纲。

    适用场景是**跨页的整体调整**，例如「把目录页改成正文页」「合并第 3、4 页」
    「统一把章节页标题改成动宾结构」——这类需求用单页修改要点很多次，
    用结构增删又表达不了，所以把整份大纲交给模型一次性改写。

    页数不做硬性约束：指令本身可能要求增减页；normalize_outline 仍会
    恒定保证首屏封面、末屏结束页，并规整每个 slide 的字段结构。

    Args:
        assistant: 模型助手（PPT 专用或主模型）。
        outline: 当前完整大纲（title/subtitle/slides）。
        instruction: 用户的调整指令（自然语言一句话）。

    Returns:
        规范化后的完整大纲 dict。

    Raises:
        RuntimeError: 大纲为空、模型调用失败或返回内容无法解析。
    """
    clean = {
        "title": outline.get("title", ""),
        "subtitle": outline.get("subtitle", ""),
        "slides": [{k: v for k, v in s.items() if not k.startswith("_")}
                   for s in (outline.get("slides") or [])],
    }
    if not clean["slides"]:
        raise RuntimeError("大纲为空，请先生成大纲")
    prompt = f"""请按用户指令整体调整这份 PPT 大纲。

【用户指令】{instruction}
【当前大纲 JSON】
{json.dumps(clean, ensure_ascii=False)[:9000]}

【输出要求】
1. 只输出调整后的完整大纲 JSON（保持 title/subtitle/slides 结构，slide 字段与输入一致）；
2. 严格按指令调整，不动指令未涉及的页面与文字；
3. 页型只能从 cover/toc/section/content/data/chart/case/timeline/process/summary/closing 中选择；
4. 页数跟随指令（指令要求合并/拆分时才变），否则保持原页数；
5. 保留每页的 sources 内容依据字段；不要虚构事实和数据。"""
    try:
        raw = assistant.complete(
            [{"role": "system", "content": _SLIDE_SYSTEM},
             {"role": "user", "content": prompt}],
            temperature=0.3, max_tokens=8192)
    except Exception as e:
        raise RuntimeError(f"调用模型失败: {e}")
    if raw.startswith("【系统错误】") or raw.startswith("调用模型失败"):
        raise RuntimeError(raw)
    result = _loads_ai_json(raw, "AI 这次返回的内容格式不规范，大纲未被修改，请重试该操作")
    if not isinstance(result.get("slides"), list) or not result["slides"]:
        raise RuntimeError("AI 没有返回有效的页面列表，大纲未被修改，请重试")
    result.setdefault("title", clean["title"] or "演示文稿")
    result.setdefault("subtitle", clean["subtitle"])
    return normalize_outline(result)


# ================= 上传模板：从 pptx 提取视觉风格 =================

def _lighten(hex_color: str, factor: float = 0.92) -> str:
    """把颜色向白色混合，生成浅底色。"""
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
    f = lambda v: int(v + (255 - v) * factor)
    return f"{f(r):02X}{f(g):02X}{f(b):02X}"


def extract_style_from_pptx(file_bytes: bytes) -> Dict:
    """解析上传的 pptx，提取完整主题色板（accent1-6）、母版背景色和字体。

    颜色映射：primary=accent1，accent=accent2（无则 accent3/1），
    dark=dk2，light=lt2 或 primary 的浅色衍生。
    """
    import zipfile
    colors = {}
    font = DEFAULT_CJK_FONT
    try:
        with zipfile.ZipFile(io.BytesIO(file_bytes)) as z:
            theme_files = sorted(n for n in z.namelist() if n.startswith("ppt/theme/theme"))
            if theme_files:
                xml = z.read(theme_files[0]).decode("utf-8", "ignore")

                def _clr(tag, xml_text):
                    m = re.search(rf'<a:{tag}>.*?val="([0-9A-Fa-f]{{6}})"', xml_text, re.S)
                    if not m:
                        m = re.search(rf'<a:{tag}>.*?lastClr="([0-9A-Fa-f]{{6}})"', xml_text, re.S)
                    return m.group(1).upper() if m else None

                accents = [_clr(f"accent{i}", xml) for i in range(1, 7)]
                accents = [a for a in accents if a]
                if accents:
                    colors["primary"] = accents[0]
                    colors["accent"] = accents[1] if len(accents) > 1 else accents[0]
                dk2 = _clr("dk2", xml)
                if dk2:
                    colors["dark"] = dk2
                m = re.search(r'<a:ea typeface="([^"]+)"', xml)
                if m and m.group(1):
                    font = m.group(1)
                else:
                    m = re.search(r'<a:latin typeface="([^"]+)"', xml)
                    if m and m.group(1) and m.group(1) != "+mj-lt":
                        font = m.group(1)
            masters = sorted(n for n in z.namelist()
                             if re.match(r"ppt/slideMasters/slideMaster\d+\.xml$", n))
            for mf in masters:
                mxml = z.read(mf).decode("utf-8", "ignore")
                m = re.search(r'<p:bg>.*?val="([0-9A-Fa-f]{6})"', mxml, re.S)
                if m:
                    bg = m.group(1).upper()
                    if bg != "FFFFFF":
                        colors["light"] = bg
                    break
    except Exception as e:
        logger.warning("模板解析失败，使用默认风格: %s", e)
    if "primary" not in colors:
        colors = DEFAULT_COLORS.copy()
    else:
        base = DEFAULT_COLORS.copy()
        base.update(colors)
        if "light" not in base or base["light"] == DEFAULT_COLORS.get("light"):
            base["light"] = _lighten(base["primary"], 0.93)
        colors = base
    return {"colors": colors, "font": font, "layouts": DEFAULT_LAYOUTS.copy()}


# ================= 模板学习：分析上传模板的版式体系 =================

LAYOUT_TYPE_LABELS = {
    "cover": "封面", "toc": "目录", "section": "章节页", "content": "正文页",
    "content_image": "图文页", "two_col": "双栏页", "data": "数据页",
    "chart": "图表页", "case": "案例页", "timeline": "时间轴页",
    "process": "流程页", "summary": "总结页", "closing": "结束页",
}

# 大纲页型 → 版式库匹配的优先顺序（模板没有该版式时降级，不强行套用默认版式）
LEARNED_FALLBACK = {
    "cover": ["cover", "section", "content"],
    "toc": ["toc", "content", "two_col"],
    "section": ["section", "content", "cover"],
    "content": ["content", "content_image", "two_col", "section"],
    "data": ["data", "chart", "content", "two_col"],
    "chart": ["chart", "data", "content"],
    "case": ["case", "content_image", "content"],
    "timeline": ["timeline", "process", "content"],
    "process": ["process", "timeline", "content"],
    "summary": ["summary", "content", "section"],
    "closing": ["closing", "cover", "section", "content"],
}


def layout_applicable_slide_types(layout_type: str) -> List[str]:
    """Return outline slide types for which a learned layout is a valid choice."""
    return [slide_type for slide_type in LAYOUT_TYPE_LABELS
            if layout_type == slide_type
            or layout_type in LEARNED_FALLBACK.get(slide_type, ["content"])]


def _shape_kind(shape) -> str:
    """形状分类：text/picture/table/chart/shape。"""
    try:
        if shape.shape_type == 13:  # PICTURE
            return "picture"
    except Exception:
        pass
    try:
        if shape.has_table:
            return "table"
    except Exception:
        pass
    try:
        if shape.has_chart:
            return "chart"
    except Exception:
        pass
    try:
        if shape.has_text_frame and shape.text_frame.text.strip():
            return "text"
    except Exception:
        pass
    return "shape"


def _region_of(shape, sw, sh) -> Dict:
    """形状位置归一化为页面比例。"""
    return {"x": round(shape.left / sw, 4), "y": round(shape.top / sh, 4),
            "w": round(shape.width / sw, 4), "h": round(shape.height / sh, 4)}


def _text_meta(shape) -> Dict:
    """文本框的排版特征：最大字号/是否加粗/颜色/对齐/示例文本。"""
    size, bold, color, align, sample = 0, False, None, None, ""
    try:
        for para in shape.text_frame.paragraphs:
            for run in para.runs:
                if run.font.size and run.font.size.pt > size:
                    size = run.font.size.pt
                if run.font.bold:
                    bold = True
                if color is None:
                    try:
                        if run.font.color and run.font.color.type is not None:
                            color = str(run.font.color.rgb)
                    except Exception:
                        pass
            if align is None and para.alignment is not None:
                align = int(para.alignment)
        sample = shape.text_frame.text.strip()[:60]
    except Exception:
        pass
    return {"font_size": size or 18, "bold": bold, "color": color,
            "align": align, "sample": sample}


def _element_of(shape, sw, sh) -> Dict:
    """提取单个形状的结构信息；失败返回 None。"""
    try:
        kind = _shape_kind(shape)
        r = _region_of(shape, sw, sh)
        el = {"kind": kind, **r}
        if kind == "text":
            el.update(_text_meta(shape))
        elif kind == "picture":
            try:
                import hashlib
                el["hash"] = hashlib.md5(shape.image.blob).hexdigest()[:12]
            except Exception:
                el["hash"] = ""
        elif kind == "shape":
            try:
                el["shape_type"] = str(shape.auto_shape_type)
            except Exception:
                el["shape_type"] = ""
            try:
                if shape.fill.type is not None:
                    el["fill"] = str(shape.fill.fore_color.rgb)
            except Exception:
                pass
        return el
    except Exception:
        return None


def _slide_elements(slide, sw, sh) -> list:
    """提取一页的全部元素结构。"""
    els = []
    for shape in slide.shapes:
        el = _element_of(shape, sw, sh)
        if el:
            els.append(el)
    return els


def _classify_slide(els, idx, total) -> str:
    """规则分类页面版式。不依赖 LLM。"""
    texts = [e for e in els if e["kind"] == "text"]
    pics = [e for e in els if e["kind"] == "picture"]
    charts = [e for e in els if e["kind"] == "chart"]
    tables = [e for e in els if e["kind"] == "table"]
    shapes = [e for e in els if e["kind"] == "shape"]
    joined = " ".join(t.get("sample", "") for t in texts)
    max_size = max((t.get("font_size", 0) for t in texts), default=0)

    if idx == 0 and (max_size >= 28 or len(texts) <= 4):
        return "cover"
    if idx == total - 1 and re.search(r"谢|Thank|结束|致谢|汇报完毕", joined):
        return "closing"
    if re.search(r"目录|CONTENTS|Contents", joined) and len(texts) >= 3:
        return "toc"
    if charts:
        return "chart"
    if tables:
        return "data"
    arrows = [s for s in shapes if s.get("shape_type") and
              ("CHEVRON" in s["shape_type"] or "ARROW" in s["shape_type"])]
    if len(arrows) >= 3:
        return "process"
    if texts and len(texts) <= 3 and max_size >= 28 and len(joined) < 60 \
            and all(t.get("font_size", 0) >= max_size * 0.7 for t in texts):
        return "section"
    big_nums = [t for t in texts if t.get("font_size", 0) >= 24 and
                re.search(r"\d", t.get("sample", ""))]
    if len(big_nums) >= 2:
        return "data"
    if pics and texts:
        left = [t for t in texts if t["x"] < 0.45]
        right = [t for t in texts if t["x"] >= 0.45]
        if left and right and not pics:
            return "two_col"
        return "content_image"
    if texts:
        left = [t for t in texts if t["x"] < 0.45 and t["w"] < 0.5]
        right = [t for t in texts if t["x"] >= 0.45]
        if left and right:
            return "two_col"
    return "content"


def _layout_signature(els) -> tuple:
    """结构签名：用于去重。相同结构的页面只保留一个版式。"""
    sig = []
    for e in sorted(els, key=lambda e: (e["kind"], e["y"], e["x"])):
        sig.append((e["kind"], round(e["x"] * 6), round(e["y"] * 6),
                    round(e["w"] * 6), round(e["h"] * 6)))
    return tuple(sig)


def _mark_fixed(slides_els: list):
    """识别固定元素（logo/装饰/页脚）：在 >=60% 页面同一位置出现的形状/图片/相同文本。
    直接修改每个元素的 role 字段：fixed / content。"""
    from collections import Counter
    n = len(slides_els)
    counter = Counter()
    for els in slides_els:
        keys = set()
        for e in els:
            if e["kind"] == "picture":
                k = ("pic", e.get("hash", ""), round(e["x"] * 10), round(e["y"] * 10))
            elif e["kind"] == "shape":
                k = ("shape", round(e["x"] * 10), round(e["y"] * 10),
                     round(e["w"] * 10), round(e["h"] * 10), e.get("fill", ""))
            elif e["kind"] == "text" and len(e.get("sample", "")) <= 15:
                k = ("txt", e.get("sample", ""), round(e["x"] * 10), round(e["y"] * 10))
            else:
                continue
            keys.add(k)
        counter.update(keys)
    threshold = max(2, int(n * 0.6))
    for els in slides_els:
        for e in els:
            if e["kind"] == "picture":
                k = ("pic", e.get("hash", ""), round(e["x"] * 10), round(e["y"] * 10))
            elif e["kind"] == "shape":
                k = ("shape", round(e["x"] * 10), round(e["y"] * 10),
                     round(e["w"] * 10), round(e["h"] * 10), e.get("fill", ""))
            elif e["kind"] == "text" and len(e.get("sample", "")) <= 15:
                k = ("txt", e.get("sample", ""), round(e["x"] * 10), round(e["y"] * 10))
            else:
                k = None
            e["role"] = "fixed" if k and counter[k] >= threshold else "content"


def analyze_template(file_bytes: bytes) -> Dict:
    """模板学习主入口：解析上传的 pptx，自动建立版式库。

    返回 {slide_size, colors, font, layouts: [...]}；解析失败时 layouts 为空，
    调用方回退 DEFAULT_LAYOUTS。
    """
    from pptx import Presentation
    style = extract_style_from_pptx(file_bytes)
    result = {"colors": style["colors"], "font": style["font"],
              "slide_size": None, "layouts": []}
    try:
        prs = Presentation(io.BytesIO(file_bytes))
    except Exception as e:
        logger.warning("模板学习失败：%s", e)
        return result
    sw, sh = prs.slide_width, prs.slide_height
    result["slide_size"] = {"w": int(sw), "h": int(sh)}

    slides = list(prs.slides)
    if not slides:
        return result
    slides_els = [_slide_elements(s, sw, sh) for s in slides]
    _mark_fixed(slides_els)

    background = None
    try:
        mbg = prs.slide_masters[0].background.fill
        if mbg.type is not None:
            background = str(mbg.fore_color.rgb)
    except Exception:
        pass

    seen, layouts, type_count = set(), [], {}
    total = len(slides)
    for idx, (slide, els) in enumerate(zip(slides, slides_els)):
        sig = _layout_signature([e for e in els if e.get("role") != "fixed"])
        if sig in seen:
            continue
        seen.add(sig)
        dtype = _classify_slide(els, idx, total)
        type_count[dtype] = type_count.get(dtype, 0) + 1
        base_name = LAYOUT_TYPE_LABELS.get(dtype, "内容页")
        name = base_name if type_count[dtype] == 1 else f"{base_name}{type_count[dtype]}"

        texts = [e for e in els if e["kind"] == "text" and e.get("role") != "fixed"]
        texts.sort(key=lambda t: (-t.get("font_size", 0), t["y"], t["x"]))
        text_regions = []
        for ti, t in enumerate(texts):
            text_regions.append({
                "role": "title" if ti == 0 else ("subtitle" if dtype == "cover" and ti == 1 else "body"),
                **{k: t[k] for k in ("x", "y", "w", "h")},
                "font_size": t.get("font_size", 18), "bold": t.get("bold", False),
                "color": t.get("color"), "align": t.get("align")})
        layouts.append({
            "id": f"L{idx}",
            "name": name,
            "detected_type": dtype,
            "source_slide_index": idx,
            "slide_size": {"w": int(sw), "h": int(sh)},
            "background": background,
            "element_schema": els,
            "placeholders": [{"idx": ph.placeholder_format.idx,
                              "type": str(ph.placeholder_format.type)}
                             for ph in slide.placeholders] if slide.placeholders else [],
            "text_regions": text_regions,
            "image_regions": [{k: e[k] for k in ("x", "y", "w", "h")}
                              for e in els if e["kind"] == "picture" and e.get("role") != "fixed"],
            "chart_regions": [{k: e[k] for k in ("x", "y", "w", "h")}
                              for e in els if e["kind"] in ("chart", "table") and e.get("role") != "fixed"],
            "shape_regions": [{k: e[k] for k in ("x", "y", "w", "h")}
                              for e in els if e["kind"] == "shape" and e.get("role") == "fixed"],
        })
    result["layouts"] = layouts
    return result


# ================= 模板学习渲染：按版式库克隆页面并填充内容 =================

def _pick_layout(layouts: list, slide_type: str, used: Dict,
                 preferred_layout_id: str = "") -> Dict:
    """按页型从版式库选最合适的版式。

    用户在模板编辑器里给页型显式绑定某个学习版式 id（如 L3）时优先采用；
    没有显式绑定时仍按 detected_type + fallback 自动匹配。
    """
    if not layouts:
        return None

    preferred = (preferred_layout_id or "").strip()
    if preferred:
        hit = next((l for l in layouts if str(l.get("id") or "") == preferred), None)
        if hit:
            return hit

    chain = LEARNED_FALLBACK.get(slide_type, ["content"]) + ["content"]
    for want in chain:
        cands = [l for l in layouts if l.get("detected_type") == want]
        if cands:
            i = used.get(want, 0) % len(cands)
            used[want] = used.get(want, 0) + 1
            return cands[i]
    return layouts[0]


def preferred_layout_id(slide: Dict, skeleton: Dict) -> str:
    """单页人工选择优先，其次采用模板为该页型配置的默认版式。"""
    return str(slide.get("layout") or skeleton.get(slide.get("type", "content"), "") or "")


def _clone_slide(prs, src_slide):
    """在同一演示文稿内克隆一页：深拷贝所有形状，并迁移图片关系。"""
    import copy
    from pptx.opc.constants import RELATIONSHIP_TYPE as RT
    new_slide = prs.slides.add_slide(src_slide.slide_layout)
    for shp in list(new_slide.shapes):
        shp._element.getparent().remove(shp._element)
    rid_map = {}
    for shp in src_slide.shapes:
        new_el = copy.deepcopy(shp._element)
        new_slide.shapes._spTree.append(new_el)
    from pptx.oxml.ns import qn as _qn
    for blip in new_slide.shapes._spTree.iter(_qn("a:blip")):
        old_rid = blip.get(_qn("r:embed"))
        if not old_rid:
            continue
        if old_rid not in rid_map:
            try:
                image_part = src_slide.part.rels[old_rid].target_part
                new_rid = new_slide.part.relate_to(image_part, RT.IMAGE)
                rid_map[old_rid] = new_rid
            except Exception:
                continue
        blip.set(_qn("r:embed"), rid_map[old_rid])
    return new_slide


def _fill_text_region(shape, lines, keep_para_format=True):
    """向文本框填充内容：用首个段落的格式作为模板逐条写入，清除多余示例段落。"""
    import copy
    tf = shape.text_frame
    paras = list(tf.paragraphs)
    if not paras:
        return
    proto = paras[0]._p
    for p in list(tf.paragraphs[1:]):
        p._p.getparent().remove(p._p)
    first = tf.paragraphs[0]
    for r in list(first.runs):
        r._r.getparent().remove(r._r)
    if not lines:
        first.text = ""
        return
    first.text = str(lines[0])
    for line in lines[1:]:
        new_p = copy.deepcopy(proto)
        for r in new_p.findall(
                "{http://schemas.openxmlformats.org/drawingml/2006/main}r"):
            new_p.remove(r)
        tf._txBody.append(new_p)
        tf.paragraphs[-1].text = str(line)


def _clear_text(shape):
    try:
        tf = shape.text_frame
        for p in list(tf.paragraphs[1:]):
            p._p.getparent().remove(p._p)
        if tf.paragraphs:
            tf.paragraphs[0].text = ""
    except Exception:
        pass


def _delete_shape(shape):
    shape._element.getparent().remove(shape._element)


def _add_native_chart(slide, chart_spec, region, colors, font, sw, sh):
    """在模板图表区域绘制原生可编辑图表（替换示例图表）。"""
    from pptx.util import Emu, Pt
    from pptx.dml.color import RGBColor
    from pptx.chart.data import CategoryChartData
    from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION
    C = lambda h: RGBColor.from_string(h)
    x, y = Emu(int(region["x"] * sw)), Emu(int(region["y"] * sh))
    w, h = Emu(int(region["w"] * sw)), Emu(int(region["h"] * sh))
    cd = CategoryChartData()
    cd.categories = chart_spec.get("categories", [])
    for serie in chart_spec.get("series", []):
        cd.add_series(serie.get("name", ""), serie.get("values", []))
    ct = {"bar": XL_CHART_TYPE.COLUMN_CLUSTERED,
          "line": XL_CHART_TYPE.LINE_MARKERS,
          "pie": XL_CHART_TYPE.PIE}.get(chart_spec.get("chart_type", "bar"),
                                        XL_CHART_TYPE.COLUMN_CLUSTERED)
    gf = slide.shapes.add_chart(ct, x, y, w, h, cd)
    chart = gf.chart
    chart.has_title = False
    try:
        chart.font.name = font
        chart.font.size = Pt(11)
    except Exception:
        pass
    if chart_spec.get("chart_type") != "pie" and len(chart_spec.get("series", [])) > 1:
        chart.has_legend = True
        chart.legend.position = XL_LEGEND_POSITION.BOTTOM
        chart.legend.include_in_layout = False
    palette = [C(colors["primary"]), C(colors["accent"]), C(colors["dark"]), C("8FAADC")]
    for si, serie in enumerate(chart.series):
        serie.format.fill.solid()
        serie.format.fill.fore_color.rgb = palette[si % len(palette)]
    return gf


def _fill_learned_slide(slide, layout, sdata, colors, font, sw, sh, prs):
    """把大纲一页的内容填进克隆出来的模板页：
    - 标题/副标题/正文 → 对应文本区域（示例文字全部替换）
    - 示例图片/图表/表格（非固定元素）→ 删除；有匹配素材图时在图片区插入
    - 固定元素（logo/装饰/页脚）→ 原样保留
    - 有图表块且有图表区域 → 绘制原生图表
    """
    schema = layout.get("element_schema", [])

    def role_of(e):
        for se in schema:
            if se["kind"] == e["kind"] and abs(se["x"] - e["x"]) < 0.01 \
                    and abs(se["y"] - e["y"]) < 0.01:
                return se.get("role", "content")
        return "content"

    texts, pics, chartframes = [], [], []
    for shp in list(slide.shapes):
        e = _element_of(shp, sw, sh)
        if not e:
            continue
        role = role_of(e)
        kind = e["kind"]
        if role == "fixed":
            continue
        if kind == "text":
            texts.append((shp, e))
        elif kind == "picture":
            pics.append((shp, e))
        elif kind in ("chart", "table"):
            chartframes.append((shp, e))

    texts.sort(key=lambda te: (-te[1].get("font_size", 0), te[1]["y"], te[1]["x"]))
    title = sdata.get("title", "")
    subtitle = sdata.get("subtitle", "")
    points = [str(p) for p in (sdata.get("points") or [])]
    blocks = sdata.get("blocks") or {}

    if blocks.get("cards") and not layout.get("chart_regions"):
        for c in blocks["cards"]:
            points.append(f"{c.get('label', '')}：{c.get('value', '')}")
    if blocks.get("timeline"):
        for t in blocks["timeline"]:
            points.append(f"{t.get('time', '')}　{t.get('event', '')}")
    if blocks.get("process"):
        for i, p in enumerate(blocks["process"], 1):
            points.append(f"第{i}步：{p if isinstance(p, str) else p.get('name', '')}")

    is_cover = layout.get("detected_type") == "cover"
    body_filled = False
    for ti, (shp, e) in enumerate(texts):
        if ti == 0:
            _fill_text_region(shp, [title] if title else [])
        elif is_cover and ti == 1:
            _fill_text_region(shp, [subtitle] if subtitle else [])
        elif not body_filled and points:
            _fill_text_region(shp, points)
            body_filled = True
        else:
            _clear_text(shp)

    img_path = (sdata.get("_image") or {}).get("file_path")
    for pi, (shp, e) in enumerate(pics):
        if pi == 0 and img_path and os.path.exists(img_path):
            try:
                slide.shapes.add_picture(img_path, shp.left, shp.top, shp.width, shp.height)
            except Exception:
                pass
        _delete_shape(shp)

    chart_spec = blocks.get("chart")
    chart_drawn = False
    for shp, e in chartframes:
        if chart_spec and not chart_drawn:
            region = {k: e[k] for k in ("x", "y", "w", "h")}
            _delete_shape(shp)
            try:
                _add_native_chart(slide, chart_spec, region, colors, font, sw, sh)
                chart_drawn = True
            except Exception as ex:
                logger.warning("图表绘制失败: %s", ex)
        else:
            _delete_shape(shp)
    if chart_spec and not chart_drawn:
        names = "、".join(sr.get("name", "") for sr in chart_spec.get("series", []))
        if texts and len(texts) > 1:
            shp, e = texts[1]
            _fill_text_region(shp, points + [f"（图表数据：{names}）"] if points else [f"（图表数据：{names}）"])


def build_pptx_learned(outline: Dict, template: Dict, base_pptx: bytes,
                       layout_library: list, warnings: Optional[List[str]] = None) -> bytes:
    """模板学习渲染：克隆模板页 → 清除示例内容 → 填充新内容。
    模板没有的页型自动降级到已有版式，不套用 DEFAULT_LAYOUTS。"""
    from pptx import Presentation
    warnings = warnings if warnings is not None else []
    colors = template["colors"]
    font = template.get("font") or DEFAULT_CJK_FONT
    prs = Presentation(io.BytesIO(base_pptx))
    src_slides = list(prs.slides)
    used = {}
    plan = []
    skeleton = template.get("layouts") or {}
    for s in outline.get("slides", []):
        slide_type = s.get("type", "content")
        preferred = preferred_layout_id(s, skeleton)
        # 内置模板 layouts 值是 band_bottom / bar_title 等渲染样式名；
        # 只有值确实命中学习版式 id 时才视为“骨架绑定”，完全向后兼容。
        lay = _pick_layout(layout_library, slide_type, used, preferred)
        if not lay:
            break
        idx = lay.get("source_slide_index", 0)
        if idx >= len(src_slides):
            idx = 0
        plan.append((s, lay, src_slides[idx]))
    new_slides = []
    for s, lay, src in plan:
        try:
            ns = _clone_slide(prs, src)
            new_slides.append((ns, lay, s))
        except Exception as e:
            logger.warning("克隆页面失败: %s", e)
    from pptx.oxml.ns import qn as _qn2
    sldIdLst = prs.slides._sldIdLst
    for sld in list(sldIdLst)[:len(src_slides)]:
        rid = sld.get(_qn2('r:id'))
        sldIdLst.remove(sld)
        try:
            prs.part.drop_rel(rid)
        except Exception:
            pass
    sw, sh = prs.slide_width, prs.slide_height
    for ns, lay, s in new_slides:
        try:
            diagram_xml = (s.get("blocks") or {}).get("drawio_xml")
            template_shapes = []
            if diagram_xml:
                from copy import deepcopy
                template_shapes = [deepcopy(shape._element) for shape in ns.shapes]
            payload = {**s, "points": [], "blocks": {}} if diagram_xml else s
            _fill_learned_slide(ns, lay, payload, colors, font, sw, sh, prs)
            if diagram_xml:
                if not _try_drawio_render(ns, s, (int(sw * .06), int(sh * .23),
                                                int(sw * .88), int(sh * .64)), font, warnings, colors):
                    # Blank text regions stop being classified as text. Restore the
                    # original layout before filling it with the fallback content.
                    for shape in list(ns.shapes):
                        _delete_shape(shape)
                    for element in template_shapes:
                        ns.shapes._spTree.insert_element_before(element, "p:extLst")
                    # The learned layout consumes the original structured process/text blocks;
                    # only the unusable XML is excluded. Other pages retain their own layouts.
                    is_process = (s["blocks"].get("drawio_kind") or "process") == "process"
                    fallback = {**s, "blocks": {key: value for key, value in s["blocks"].items()
                                              if key != "drawio_xml" and (is_process or key != "process")}}
                    if not is_process:
                        fallback["points"] = (s["blocks"].get("diagram_labels") or
                                              s["blocks"].get("process") or s.get("points") or [])
                    _fill_learned_slide(ns, lay, fallback, colors, font, sw, sh, prs)
        except Exception as e:
            if (s.get("blocks") or {}).get("drawio_xml"):
                raise
            logger.warning("页面填充失败: %s", e)
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


def render_pptx(outline: Dict, template: Dict, base_pptx: bytes = None,
                warnings: Optional[List[str]] = None) -> bytes:
    """渲染总入口：有版式库+底版 → 模板学习渲染；否则 → 精修渲染（fallback）。"""
    library = template.get("layout_library") or []
    if base_pptx and library:
        try:
            return build_pptx_learned(outline, template, base_pptx, library, warnings=warnings)
        except Exception as e:
            logger.warning("模板学习渲染失败，回退默认渲染: %s", e)
    return build_pptx(outline, template, base_pptx=base_pptx, warnings=warnings)
