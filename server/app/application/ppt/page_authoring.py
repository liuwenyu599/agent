"""Second-stage, model-authored page composition after content and images settle.

The model may move content and design text-free shapes, but cannot rewrite facts.
Validated designs become the source for editable PPTX export; failed pages keep the
existing deterministic composition. This keeps one bad model page from breaking a
whole deck.
"""
from __future__ import annotations

import copy
import base64
import hashlib
import io
import json
import math
from pathlib import Path
from typing import Any

from app.application.ppt import page_scene
from app.application.ppt import svg_layer
from app.application.ppt.template_style import summarize_template_style
from app.application.ppt.visual_primitives import model_visuals
from app.core.llm_json import loads_llm_object
from app.core.logging import get_logger

logger = get_logger(__name__)


def _canvas_size(template: dict) -> tuple[int, int]:
    size = template.get("slide_size") or next(
        (layout.get("slide_size") for layout in
         (template.get("layout_library") or []) if layout.get("slide_size")), None)
    size = size or {}
    return (int(size.get("w") or 12191695), int(size.get("h") or 6858000))


def _signature(slide: dict, template: dict) -> str:
    image = slide.get("_image") or {}
    payload = {
        "type": slide.get("type"), "title": slide.get("title"),
        "points": slide.get("points"), "blocks": slide.get("blocks") or {},
        "image_id": slide.get("image_id"),
        "image_path": image.get("file_path"),
        "colors": template.get("colors"), "font": template.get("font"),
        "template_id": template.get("id"),
        "visual_reference_hash": template.get("visual_reference_hash"),
        # 模板换了（版式数量/画幅不同）而页面文字没变时，旧构图不能直接复用：
        # 同一套坐标落到另一套模板的正文区里可能整页都放不下。
        "layouts": [(item.get("id"), item.get("source_slide_index"))
                    for item in (template.get("layout_library") or [])],
        "slide_size": _canvas_size(template),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False,
                                     default=str).encode()).hexdigest()[:20]


def _region_issue(slide: dict, regions: object) -> str:
    """具体到「哪个区域、越界多少、和谁重叠」的拒绝原因。

    以前这里只回一句「区域缺失、重叠、越界或容纳不下文字」，模型第二次
    只能瞎猜，往往原样再错一次。重试只有在反馈可执行时才有意义。
    """
    if not isinstance(regions, list) or not regions:
        return "缺少 regions"
    checked = copy.deepcopy(regions)
    return page_scene.explain_layered(checked, slide) or page_scene.intent_issue(checked, slide)


def _valid_regions(slide: dict, regions: object) -> bool:
    return not _region_issue(slide, regions)


def _same_composition(first: object, second: object) -> bool:
    """Recognize repeated page geometry despite small model coordinate jitter."""
    if not isinstance(first, list) or not isinstance(second, list):
        return False
    if len(first) != len(second):
        return False
    before = {item.get("ref"): item for item in first if isinstance(item, dict)}
    after = {item.get("ref"): item for item in second if isinstance(item, dict)}
    if len(before) != len(first) or before.keys() != after.keys():
        return False
    return all(
        all(type(before[ref].get(key)) in (int, float)
            and type(after[ref].get(key)) in (int, float)
            and abs(before[ref][key] - after[ref][key]) <= .035
            for key in ("x", "y", "w", "h"))
        for ref in before)


def _page_brief(index: int, slide: dict) -> dict:
    image = slide.get("_image") or {}
    brief = {
        "page": index, "type": slide.get("type"), "title": slide.get("title"),
        "points": slide.get("points") or [],
        "structured_content": {key: value for key, value in
                               (slide.get("blocks") or {}).items()
                               if key in {"chart", "table", "cards"}},
        "required_refs": list(page_scene.references(slide)),
        "job": (slide.get("design") or {}).get("job") or "",
        "relationship": (slide.get("design") or {}).get("relationship") or "none",
        "image": bool(image.get("file_path")),
    }
    if image.get("file_path"):
        brief["image_caption"] = str(image.get("caption") or image.get("name") or "")[:160]
        try:
            from PIL import Image
            with Image.open(Path(image["file_path"])) as source:
                brief["image_aspect"] = round(source.width / max(source.height, 1), 2)
        except (OSError, ValueError):
            pass
    return brief


def _prompt(outline: dict, template: dict, pages: list[dict],
            issue: str = "", has_template_image: bool = False) -> str:
    spec = outline.get("design_spec") or {}
    first_page = min((page["page"] for page in pages), default=1)
    recent = []
    for index in range(max(1, first_page - 3), first_page):
        slide = (outline.get("slides") or [])[index - 1]
        regions = (slide.get("design") or {}).get("regions")
        if not isinstance(regions, list):
            continue
        recent.append({
            "page": index, "type": slide.get("type"), "title": slide.get("title"),
            "regions": [{key: item.get(key) for key in ("ref", "x", "y", "w", "h")}
                        for item in regions if isinstance(item, dict)],
        })
    context = {
        "deck_title": outline.get("title"), "style": outline.get("style"),
        "density": spec.get("density", "balanced"),
        "audience": spec.get("audience") or "",
        "communication_intent": spec.get("communication_intent") or "",
        "core_message": spec.get("core_message") or "",
        "delivery_context": spec.get("delivery_context") or "",
        "colors": template.get("colors") or {}, "font": template.get("font") or "",
        "template_visual_grammar": summarize_template_style(template),
        "page_sequence": [{"page": i, "type": s.get("type"), "title": s.get("title")}
                          for i, s in enumerate(outline.get("slides") or [], 1)],
        "recent_compositions": recent,
        "pages_to_design": pages,
    }
    canvas_width, canvas_height = _canvas_size(template)
    svg_height = svg_layer.viewbox_height(canvas_width, canvas_height)
    return (
        "你是演示文稿的逐页构图师。内容和图片已经确认，只设计页面；"
        "禁止改写标题、要点、数字和图片。先判断每页的图文关系，再决定图片和文字各占多大版面。"
        "整稿保持同一配色、字体和节奏，但相邻正文页避免重复同一种构图。\n"
        "输出单个 JSON 对象：{\"pages\":[{\"page\":页码,\"regions\":["
        "{\"ref\":\"title\",\"x\":0.06,\"y\":0.05,\"w\":0.88,\"h\":0.12},"
        "{\"ref\":\"point:0\",\"x\":0.06,\"y\":0.28,\"w\":0.42,\"h\":0.5}],"
        "\"visuals\":[]}]}。\n"
        "坐标均为页面宽高的 0~1 比例。每页 required_refs 中的区域必须各出现一次；"
        "chart 是可编辑原生 PPT 图表，模型只决定其位置和面积，不得改图表数据；"
        "table 是原生表格，metric:i 是原有指标卡，均不得改写数值。"
        "image=true 时 image 区域也必须出现一次，image=false 时不得出现。"
        "所有区域 x≥0.035、y≥0.025、右侧≤0.965、底部≤0.89；"
        "除下述图文叠加外彼此不重叠；"
        "相邻区域之间至少留 0.02 页高的空隙，并排的卡片左右缝不小于 0.015，"
        "否则几张卡在投影上会读成一块被竖线切开的板。"
        "标题优先位于上部，正文和图片按内容关系自由构图，长文字需要更宽或更高的区域。"
        "comparison 且有两条要点时，必须左右并排便于对照；takeaway 须让主结论明显大于次要说明；"
        "image_role=evidence 且有图时，照片应足够大以辨认现场细节。"
        "visuals 最多 6 个，只允许无文字的 rect、oval、chevron、gradient、line、"
        "donut（环形）、trapezoid（梯形）、down_arrow（向下箭头）；"
        "颜色只能用 primary/accent/light/dark/white/line，禁止 #RRGGBB。"
        "字段名必须是 kind（不是 type）；rect 等用 x/y/w/h + fill，"
        "line 用 x1/y1/x2/y2 + stroke，不要输出 strokeWidth。"
        '示例：{"kind":"rect","x":0.06,"y":0.25,"w":0.42,"h":0.55,"fill":"light"}。'
        "用浅色卡片衬托正文时，卡片尺寸要贴近该区域文字的实际占用（按字数估行数），"
        "不要比文字高出一大截——卡片下半截空着比不铺卡更难看；深色大块不能盖住文字。"
        "不要输出模板槽位编号、PPTX 代码或额外说明。"
        f"需要自由曲线或异形图时可输出 svg 字段：一张 viewBox='0 0 960 {svg_height}' 的 SVG，"
        "仅画无文字的纯色路径和形状，fill/stroke 只用 #RRGGBB 或 none，"
        "最多 128 个图形；不得包含渐变、text、image、脚本或外部资源。"
        "有实景照且适合图文叠加时，可设 image_overlay='dark'，让 image 区覆盖正文区，"
        "至少一个 point 区完整位于图片内并留边；程序会加深色透明遮罩和白字，"
        "按照片像素检查正文对比度至少 4.5:1、大字至少 3:1。"
        "区域可标 layer：title/point/metric 为 text，image 为 image，chart/table 为 chart；"
        "文字层互不重叠，图文叠加必须有蒙版。"
        + ("附图是来源模板的页面，仅学习底色、层级、装饰和留白；"
           "其中的文字、照片和事实都不得带入本次演示。" if has_template_image else "")
        + ("\n上次方案需要修正：" + issue + "。请修正全部页面。" if issue else "")
        + "\n设计输入：" + json.dumps(context, ensure_ascii=False, default=str)
    )


def _reference_url(data: bytes | None) -> str | None:
    if not data:
        return None
    try:
        from PIL import Image
        with Image.open(io.BytesIO(data)) as source:
            frame = source.convert("RGB")
            frame.thumbnail((960, 540))
            output = io.BytesIO()
            frame.save(output, "JPEG", quality=72)
        return "data:image/jpeg;base64," + base64.b64encode(output.getvalue()).decode("ascii")
    except (OSError, ValueError):
        return None


def _messages(prompt: str, reference_url: str | None) -> list[dict]:
    if not reference_url:
        return [{"role": "user", "content": prompt}]
    return [{"role": "user", "content": [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": reference_url}},
    ]}]


def _proposals(raw: str) -> dict[int, dict]:
    parsed = loads_llm_object(raw, default={}) or {}
    pages = parsed.get("pages")
    if not isinstance(pages, list):
        return {}
    result = {}
    for item in pages:
        if not isinstance(item, dict):
            continue
        page = item.get("page")
        # 模型经常把页码写成 "3"/" 3 "，严格要求 int 等于把整页构图丢掉，
        # 而丢掉之后只会静默降级成可读版式，看起来像模型没出力。
        if isinstance(page, str) and page.strip().isdigit():
            page = int(page.strip())
        if type(page) is int:
            result[page] = item
    return result


def _hex_role(value: str) -> str:
    """把模型常用的 #RRGGBB 归到 SYSTEM 色板角色，避免整页构图被颜色写 rejected。"""
    try:
        red, green, blue = (int(value[index:index + 2], 16) for index in (1, 3, 5))
    except (ValueError, IndexError):
        return "light"
    luminance = (0.2126 * red + 0.7152 * green + 0.0722 * blue) / 255
    return "light" if luminance > .8 else ("dark" if luminance < .2 else "primary")


def _normalize_visuals(proposed: object) -> list[dict]:
    """真实模型自然输出 SVG 风格（type / #RRGGBB / strokeWidth），这里收敛到契约。

    35B 首次实测给出的是 ``{"type":"rect","fill":"#F0F5FA","strokeWidth":0.005}``
    与 ``{"type":"line","x1":...}``。不归一化时 line 没有 x/y/w/h，
    分层校验会判「装饰层坐标无效」，连累合法的 regions 整页退回可读版式。
    """
    if not isinstance(proposed, list):
        return []
    out: list[dict] = []
    for raw in proposed[:6]:
        if not isinstance(raw, dict):
            continue
        item = dict(raw)
        if "kind" not in item and isinstance(item.get("type"), str):
            item["kind"] = item.pop("type")
        for key in ("fill", "stroke", "from", "to"):
            value = item.get(key)
            if (isinstance(value, str) and value.startswith("#")
                    and len(value) == 7):
                item[key] = _hex_role(value)
        # strokeWidth 是 SVG 线宽（页比例），不是 pt；丢弃后走默认 width，
        # 否则 0.005 会因 <0.5 被拒。
        item.pop("strokeWidth", None)
        item.pop("stroke-width", None)
        # 坐标不是有限数值的装饰直接丢掉，别留给分层校验判「装饰层坐标无效」
        # 而把已经合法的 regions 一起赔进去。
        kind = item.get("kind")
        keys = ("x1", "y1", "x2", "y2") if kind == "line" else ("x", "y", "w", "h")
        coords = [item.get(key) for key in keys]
        if any(type(value) not in (int, float) or not math.isfinite(value)
               for value in coords):
            continue
        out.append(item)
    return out


def _accept(slide: dict, template: dict, proposal: dict) -> tuple[bool, str]:
    regions = proposal.get("regions")
    if not isinstance(regions, list):
        return False, "缺少 regions"
    regions = page_scene.clamp_regions(copy.deepcopy(regions))
    overlay = proposal.get("image_overlay", "none")
    if overlay not in ("none", "dark"):
        return False, "image_overlay 只允许 none 或 dark"
    visuals = _normalize_visuals(proposal.get("visuals"))
    candidate = {**slide, "design": {**(slide.get("design") or {}),
                                     "image_overlay": overlay,
                                     "visuals": visuals}}
    issue = _region_issue(candidate, regions)
    if issue:
        return False, issue
    svg = proposal.get("svg") or ""
    if svg:
        canvas_width, canvas_height = _canvas_size(template)
        issue = svg_layer.validate(svg, width=canvas_width, height=canvas_height)
        if issue:
            return False, issue
        try:
            svg_png = svg_layer.to_png(svg, scale=.5, width=canvas_width,
                                       height=canvas_height)
            issue = page_scene.svg_text_overlap(svg_png, regions, candidate)
            if issue:
                return False, issue
        except ValueError as exc:
            return False, str(exc)
        except Exception:
            return False, "SVG 无法渲染为页面视觉层"
    if model_visuals(visuals, regions) is None:
        # 装饰不合格不该连累整页构图：regions 已经通过几何与关系校验，
        # 丢掉装饰继续用模型排版，比整页退回可读版式更接近用户要的「真跑」。
        logger.warning("[PPT] 第 %s 页装饰图形不合规，已忽略装饰保留模型区域",
                       slide.get("title") or "")
        visuals = []
    design = dict(slide.get("design") or {})
    design.update(regions=regions, visuals=visuals, svg=svg,
                  image_overlay=overlay,
                  plan_signature=_signature(slide, template))
    slide["design"] = design
    slide.pop("scene", None)
    return True, ""


def author_pages(outline: dict, template: dict, assistant: Any,
                 warnings: list[str] | None = None,
                 reference_image: bytes | None = None) -> dict:
    """Plan text-led pages in small batches, then retry invalid pages once."""
    if reference_image:
        template = {**template, "visual_reference_hash":
                    hashlib.sha256(reference_image).hexdigest()[:20]}
    result = copy.deepcopy(outline)
    missing_evidence = [index for index, slide in
                        enumerate(result.get("slides") or [], 1)
                        if (slide.get("design") or {}).get("image_role") == "evidence"
                        and not (slide.get("_image") or {}).get("file_path")]
    if missing_evidence:
        logger.warning("[PPT] %d 页要求场景证据图片但无匹配素材", len(missing_evidence))
        if warnings is not None:
            warnings.append(f"第{'、'.join(str(page) for page in missing_evidence)}页"
                            "需要场景图片，但图库没有匹配素材；已保留无图版式")
    pending = []
    for index, slide in enumerate(result.get("slides") or [], 1):
        page_type = slide.get("type")
        if page_type not in {"content", "case", "summary", "data", "chart"}:
            continue
        if page_type in {"content", "case", "summary"} and (
                not slide.get("points") or slide.get("blocks")):
            continue
        refs = page_scene.references(slide)
        if page_type in {"data", "chart"} and not any(
                ref in {"chart", "table"} or ref.startswith("metric:")
                for ref in refs):
            continue
        design = slide.get("design") or {}
        valid = _valid_regions(slide, design.get("regions"))
        # Explicitly locked pages remain user-controlled. Other pages always
        # receive the separate design pass once, even if outline drafting also
        # happened to include geometry.
        if slide.get("layout_locked") and valid:
            continue
        previous = result["slides"][index - 2] if index > 1 else {}
        is_repeated = _same_composition(
            (previous.get("design") or {}).get("regions"), design.get("regions"))
        if (valid and design.get("plan_signature") == _signature(slide, template)
                and not is_repeated):
            continue
        pending.append(index)
    if not pending:
        return result
    if assistant is None:
        # 以前这里直接返回，designed 模式看着是开的，成稿却全是可读兜底，
        # 用户既不知道模型没接上，也查不到原因。
        if warnings is not None:
            warnings.append("页面构图模型未配置，正文页使用可读版式")
        logger.warning("[PPT] 页面构图模型未配置，%d 页退回可读版式", len(pending))
        return result
    failed: list[int] = []
    repeated: list[int] = []
    reference_url = _reference_url(reference_image)
    batches = [pending[start:start + 4]
               for start in range(0, len(pending), 4)]

    # --- 首轮构图请求（串行） ---
    # 实测：2 页 + 模板图 + 3200 token 要 59s，同样 2 页不带图 + 1600 token
    # 只要 26s。曾试过 3 批并发，两个重视觉请求互相抢推理资源，双双超时
    # (120s / 8 页全退回)，比串行更慢，因此保持串行。
    # 折中办法：模板图只随第一批发送，让模型先「看过模板」；后续批次沿用
    # prompt 里的配色、字号层级和形状语法摘要，不再重复做视觉编码。
    def request_batch(batch_index: int, batch: list[int], budget: int):
        pages = [_page_brief(index, result["slides"][index - 1]) for index in batch]
        with_image = bool(reference_url) and batch_index == 0
        image = reference_url if with_image else None
        try:
            raw = assistant.complete(
                _messages(_prompt(result, template, pages,
                                  has_template_image=with_image), image),
                temperature=0.35, max_tokens=budget)
            return _proposals(raw), False, False
        except Exception as exc:  # model outage only affects this batch
            if with_image and str(exc) == "模型调用失败":
                logger.warning("[PPT] 页面模型拒绝模板图，退回文字视觉摘要")
                try:
                    raw = assistant.complete(
                        _messages(_prompt(result, template, pages), None),
                        temperature=0.35, max_tokens=budget)
                    return _proposals(raw), False, True
                except Exception as retry_exc:
                    logger.warning("[PPT] 页面构图请求失败：%s", type(retry_exc).__name__)
                    return {}, True, True
            logger.warning("[PPT] 页面构图请求失败：%s", type(exc).__name__)
            return {}, True, False

    # 带图批给足预算，后续纯文字批按页数收紧，避免模型漫无边际地输出。
    budgets = [max(2400, 800 * len(batch)) if i == 0
               else max(1400, 700 * len(batch))
               for i, batch in enumerate(batches)]
    responses = []
    for i, batch in enumerate(batches):
        if responses and responses[-1][1]:
            # 网关整体不可用时不再为剩余批次各等一次超时，直接走可读版式。
            responses.append(({}, True, False))
            continue
        responses.append(request_batch(i, batch, budgets[i]))
    # --- 阶段 B：按页顺序串行验收 / 重试 / 跨页去重 ---
    # 重试与「和上一页构图相同」的判断依赖前页已写回的 design，必须串行。
    # 单页修复是点名几何错误，文字反馈足够，不再附带模板图（省一次视觉编码）。
    for batch_index, batch in enumerate(batches):
        proposed, request_failed = responses[batch_index][:2]
        for index in batch:
            slide = result["slides"][index - 1]
            accepted, reason = _accept(slide, template, proposed.get(index) or {})
            if not accepted and not request_failed:
                try:
                    raw = assistant.complete(
                        _messages(_prompt(result, template,
                                          [_page_brief(index, slide)], reason),
                                  None),
                        temperature=0.15, max_tokens=1400)
                    accepted, reason = _accept(
                        slide, template, _proposals(raw).get(index) or {})
                except Exception as exc:
                    logger.warning("[PPT] 第 %d 页构图修复失败：%s", index, type(exc).__name__)
            if accepted:
                previous = result["slides"][index - 2] if index > 1 else {}
                prior_regions = (previous.get("design") or {}).get("regions")
                current_regions = (slide.get("design") or {}).get("regions")
                if _same_composition(prior_regions, current_regions):
                    # A valid but repeated page is still better than an invalid
                    # repair. Keep it if the diversity retry fails.
                    original_design = copy.deepcopy(slide["design"])
                    try:
                        raw = assistant.complete(
                            _messages(_prompt(
                                result, template, [_page_brief(index, slide)],
                                "与上一页的图文区域几乎相同；保持内容，改换明显不同的构图"),
                                None),
                            temperature=0.45, max_tokens=1400)
                        alternative = _proposals(raw).get(index) or {}
                        if (_same_composition(prior_regions,
                                              alternative.get("regions"))
                                or not _accept(slide, template, alternative)[0]):
                            slide["design"] = original_design
                            repeated.append(index)
                    except Exception as exc:
                        slide["design"] = original_design
                        repeated.append(index)
                        logger.warning("[PPT] 第 %d 页重复构图修复失败：%s",
                                       index, type(exc).__name__)
                continue
            if not accepted:
                design = dict(slide.get("design") or {})
                design.pop("regions", None)
                design.pop("visuals", None)
                design.pop("svg", None)
                design.pop("image_overlay", None)
                design.pop("plan_signature", None)
                slide["design"] = design
                logger.warning("[PPT] 第 %d 页模型构图未采用：%s", index, reason)
                failed.append(index)
    if failed and warnings is not None:
        # 一次批量请求失败会拖累整批 4 页，逐页追加会把提示区刷成 4 条同样的话。
        warnings.append(f"第{'、'.join(str(page) for page in failed)}页"
                        "模型构图未通过检查，已采用可读版式")
    if repeated and warnings is not None:
        warnings.append(f"第{'、'.join(str(page) for page in repeated)}页"
                        "与前页构图相近，已保留可用方案")
    return result
