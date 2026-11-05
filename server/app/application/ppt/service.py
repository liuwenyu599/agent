"""PPT 助手应用服务：模板/素材/文档/生成/导出/云端生成的编排。"""
import asyncio
import copy
import hashlib
from app.core.fonts import DEFAULT_CJK_FONT
import io
import json as _json
import os
import re
import shutil
import uuid
import zipfile
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.application.ppt import ppt_engine, template_prepare
from app.application.ppt.ppt_engine import BUILTIN_TEMPLATES, DEFAULT_COLORS, DEFAULT_LAYOUTS
from app.application.shared.writing_assistant import WritingAssistant
from app.core.config import settings
from app.core.exceptions import AppError, AIServiceError, NotFoundError, PermissionDeniedError
from app.core.llm_json import LLMJsonError, loads_lenient, loads_llm_object
from app.core.logging import get_logger
from app.domain.identity.entities import User
from app.domain.ppt.entities import PPTDocument, PPTMaterial, PPTTemplate, PPTTemplateFavorite
from app.infrastructure.database.models.knowledge import DocumentModel, KnowledgeBaseModel
from app.infrastructure.database.models.ppt import PPTLibraryImageModel
from app.infrastructure.repositories.ppt import (
    SqlAlchemyPPTDocumentRepository,
    SqlAlchemyPPTMaterialRepository,
    SqlAlchemyPPTTemplateFavoriteRepository,
    SqlAlchemyPPTTemplateRepository,
)
from app.infrastructure.repositories.format_check import SqlAlchemyFormatRuleRepository
from app.domain.presentation_quality import PPT_DEFAULT_RULES

logger = get_logger(__name__)

# 大纲流式接口的兜底错误文案（不得回传原始异常文本）
_OUTLINE_UNEXPECTED_ERROR_MSG = (
    "大纲生成中断：AI 服务本次返回异常（已记录日志）。"
    "本次没有生成任何文档，可以放心重试；若多次失败，可尝试缩短材料正文或减少页数要求。"
)

_PPTX_MIME = ("application/vnd.openxmlformats-officedocument."
              "presentationml.presentation")

# 逐页预览链路依赖的外部命令（顺序即执行顺序）与各自超时秒数。
# 任一命令在 PATH 上找不到时，预览直接降级为空页数列表，绝不冒泡成 500。
_PREVIEW_TOOLS: Tuple[str, ...] = ("soffice", "pdftoppm")
_PREVIEW_TIMEOUTS: Dict[str, int] = {"soffice": 180, "pdftoppm": 120}

# 用户不再承担“怎么设计”的提示工程。服务端按场景自动附加视觉约束。
DEFAULT_DESIGN_PROMPT: Dict[str, str] = {
    "gov": (
        "庄重政务风格，沿用整稿配色，少装饰；每页不超过 4 个要点；"
        "封面只放标题、副标题、汇报单位和日期，不放图表、流程图和数据框；"
        "数据统一优先用清晰的数据卡片页呈现；正文突出结论，避免大段文字；"
        "图表必须足够大且可直接阅读，不得用角落小图凑版面；结束页保持简洁。"
    ),
    "policy": (
        "沉稳政策解读风格，沿用整稿配色，层级清楚、少装饰；"
        "每页不超过 4 个要点；政策条款用结构卡片或对照结构表达；"
        "封面不放图表，正文避免密集小字，结论和执行要求优先突出。"
    ),
    "training": (
        "清晰培训课件风格，沿用整稿配色，结构直观；每页不超过 4 个要点；"
        "知识点优先使用步骤、对比、案例卡片表达；图片和图表必须足够大；"
        "封面保持干净，不叠加数据框，结束页简洁。"
    ),
}
DEFAULT_GOV_TEMPLATE_ID = "gov_report_blue"
_TOC_TITLE_RE = re.compile(r"^(目录|汇报提纲|内容提要|主要内容|汇报目录)$")


def _official_preview_id(spec: dict) -> str:
    fingerprint = _json.dumps({key: spec.get(key) for key in
                               ("name", "colors", "layouts")},
                              ensure_ascii=False, sort_keys=True)
    return "official-" + hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:10]


class _PreviewRenderError(Exception):
    """预览渲染流程内部可控失败（如命令执行成功但未产出文件）。"""

_CLOUD_DEFAULT = {
    "enabled": False,
    "api_key": "",
    "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "mode": "general",               # general=模板模式 / creative=创意模式
    "template_id": "summary_01",
}


def _parse_json_object(raw: str) -> Optional[Dict[str, Any]]:
    """从模型输出里宽松提取一个 JSON 对象。

    模型常常带 ```json 代码围栏或前后废话（"好的，结果如下："），这里统一剥掉
    再解析；解析不出来返回 None，由调用方降级处理，**不抛异常**。

    Args:
        raw: 模型返回的原始文本。

    Returns:
        解析出的 dict；解析失败或不是对象时返回 None。
    """
    if not raw:
        return None
    try:
        obj = loads_lenient(raw)
    except LLMJsonError as e:
        # 非法 JSON 是预期内的情况，交给调用方降级处理，不抛异常
        logger.warning("[PPT] 模型输出解析失败（已尝试宽容解析）：%s", e.message)
        return None
    return obj if isinstance(obj, dict) else None


class PPTService:
    def __init__(self, db: Session, assistant: WritingAssistant) -> None:
        self.db = db
        self.assistant = assistant
        self.templates = SqlAlchemyPPTTemplateRepository(db)
        self.favorites = SqlAlchemyPPTTemplateFavoriteRepository(db)
        self.materials = SqlAlchemyPPTMaterialRepository(db)
        self.documents = SqlAlchemyPPTDocumentRepository(db)
        # PPT 专用助手（DeepPresenter-9B），惰性初始化；未配置时回退主模型
        self._ppt_asst: Optional[WritingAssistant] = None

    def _ppt_assistant(self) -> WritingAssistant:
        """PPT 专用模型助手（DeepPresenter-9B）。
        未配置 PPT_MODEL_URL 时回退主文本模型，功能保持可用。"""
        if self._ppt_asst is None:
            from app.infrastructure.ai import get_ppt_gateway
            gw = get_ppt_gateway()
            self._ppt_asst = WritingAssistant(gw) if gw is not None else self.assistant
        return self._ppt_asst

    @staticmethod
    def _auto_slide_count(content: str) -> int:
        """用户未指定页数时按材料长度确定服务端权威页数。"""
        chars = len(re.sub(r"\s+", "", content or ""))
        if chars < 1000:
            return 6
        if chars <= 3000:
            return 10
        return 15

    @classmethod
    def _effective_slide_count(cls, requested: int, explicit: bool, content: str) -> int:
        raw = requested if explicit else cls._auto_slide_count(content)
        value = max(2, min(int(raw or 6), 18))
        logger.info("[PPT] 页数决策：explicit=%s material_chars=%d target=%d",
                    explicit, len(re.sub(r"\s+", "", content or "")), value)
        return value

    @staticmethod
    def sanitize_outline(outline: Dict[str, Any], target_count: Optional[int] = None,
                         ensure_toc: bool = True,
                         enforce_bookends: bool = True) -> Dict[str, Any]:
        """清理页面字段；自由生成保留模型选定的页面角色。"""
        normalized = ppt_engine.normalize_outline(
            dict(outline or {}), target_count=target_count,
            require_bookends=enforce_bookends)
        slides = [dict(s) for s in (normalized.get("slides") or [])]
        if not slides:
            return normalized

        def cover_clean(src: Dict[str, Any]) -> Dict[str, Any]:
            out: Dict[str, Any] = {
                "type": "cover",
                "title": str(src.get("title") or normalized.get("title") or "演示文稿"),
                "subtitle": str(src.get("subtitle") or normalized.get("subtitle") or ""),
            }
            if src.get("id"):
                out["id"] = src["id"]
            if src.get("layout"):
                out["layout"] = src["layout"]
            for key in ("unit", "organization", "location", "date", "report_date",
                        "presenter", "汇报单位", "日期"):
                if src.get(key):
                    out[key] = src[key]
            # 兼容旧大纲把单位/日期塞进 points 的情况：提取元数据后丢弃 points/blocks。
            for point in src.get("points") or []:
                text = str(point).strip()
                if re.match(r"^(汇报单位|单位|地点)[：:]", text) and "unit" not in out:
                    out["unit"] = re.split(r"[：:]", text, maxsplit=1)[-1].strip()
                elif re.match(r"^(汇报时间|日期|落款日期)[：:]", text) and "date" not in out:
                    out["date"] = re.split(r"[：:]", text, maxsplit=1)[-1].strip()
            return out

        def closing_clean(src: Dict[str, Any]) -> Dict[str, Any]:
            out = {"type": "closing",
                   "title": str(src.get("title") or "谢谢聆听，请批评指正")}
            if src.get("id"):
                out["id"] = src["id"]
            if src.get("layout"):
                out["layout"] = src["layout"]
            return out

        if slides[0].get("type") == "cover":
            slides[0] = cover_clean(slides[0])
        if len(slides) > 1 and slides[-1].get("type") == "closing":
            slides[-1] = closing_clean(slides[-1])

        toc_index: Optional[int] = None
        for i in range(1, max(1, len(slides) - 1)):
            s = slides[i]
            title = str(s.get("title") or "").strip()
            if s.get("type") == "toc" or (ensure_toc and _TOC_TITLE_RE.match(title)):
                s["type"] = "toc"
                s.pop("blocks", None)
                s.pop("image", None)
                s.pop("chart", None)
                toc_index = i if toc_index is None else toc_index

        # 6 页以上的政务汇报默认应有目录；模型漏掉时由系统确定性补齐。
        if ensure_toc and len(slides) >= 6 and toc_index is None:
            titles = [
                str(s.get("title") or "").strip()
                for s in slides[1:-1]
                if str(s.get("title") or "").strip()
                and str(s.get("title") or "").strip() != "补充内容"
            ][:6]
            slides.insert(1, {
                "type": "toc",
                "title": "目录",
                "points": titles or ["工作概况", "重点工作", "下一步安排"],
                "sources": [],
            })
            # 插目录后仍必须满足权威页数：优先删除 normalize_outline 自动补的空白页，
            # 不直接牺牲原本的第 2 页正文。
            if target_count and len(slides) > target_count:
                drop = next(
                    (i for i in range(len(slides) - 2, 1, -1)
                     if str(slides[i].get("title") or "") == "补充内容"),
                    len(slides) - 2,
                )
                slides.pop(drop)
            logger.info("[PPT] 大纲净化：自动插入目录页并保持总页数")

        normalized["slides"] = slides
        normalized["title"] = (slides[0].get("title") if enforce_bookends else
                               normalized.get("title")) or "演示文稿"
        normalized["subtitle"] = (slides[0].get("subtitle") if enforce_bookends else
                                  normalized.get("subtitle")) or ""
        return normalized

    def _audit_and_repair_outline(self, outline: Dict[str, Any], target_count: Optional[int],
                                  content: str) -> Dict[str, Any]:
        """检查模型规划，保留其选择的封面、目录及结束页。"""
        clean = self.sanitize_outline(outline, target_count=None,
                                      ensure_toc=False, enforce_bookends=False)
        planned_style = clean.get("style")
        prompt = (
            "你是司法行政机关 PPT 大纲质量检查员。检查并在必要时直接修正大纲。\n"
            "重点检查：页面注水或重复、章节顺序不合理、一页要点过多。"
            "封面、目录和结束页由任务需要决定，不要为套格式强行添加。"
            "不得新增材料中不存在的事实或数据。\n"
            + (f"用户明确要求 {target_count} 页，最终页数必须一致。\n"
               if target_count is not None else
               "用户未指定页数，请按内容完整性决定页数，不要凑页。\n")
            + "如需修正，请保留原大纲的 style 风格类别，除非它明显与主题矛盾。只输出 JSON："
            '{"needs_fix":true或false,"issues":["问题"],"outline":{"title":"","subtitle":"","style":"","slides":[]}}。'
            "\n若无需修正，outline 原样返回。\n"
            f"【材料节选】\n{(content or '')[:1800]}\n"
            f"【当前大纲】\n{_json.dumps(clean, ensure_ascii=False)[:10000]}"
        )
        try:
            raw = self._ppt_assistant().complete(
                [{"role": "user", "content": prompt}], temperature=0.1, max_tokens=5000)
            data = _parse_json_object(raw or "")
        except Exception as e:  # noqa: BLE001
            logger.warning("[PPT] 大纲自动审查失败，保留规则净化结果：%s", e)
            data = {}
        if not data:
            logger.warning("[PPT] 大纲自动审查返回不可解析内容，保留规则净化结果")
            data = {}
        issues = [str(x)[:160] for x in (data.get("issues") or []) if str(x).strip()]
        repaired = data.get("outline")
        if data.get("needs_fix") and isinstance(repaired, dict) and repaired.get("slides"):
            logger.info("[PPT] 大纲自动审查触发修正：%s", "；".join(issues) or "结构质量")
            clean = self.sanitize_outline(
                repaired, target_count=None, ensure_toc=False,
                enforce_bookends=False)
            if not clean.get("style") and planned_style:
                clean["style"] = planned_style
        if target_count is not None and len(clean.get("slides") or []) != target_count:
            raise RuntimeError(
                f"AI 页面规划未达到指定的 {target_count} 页，请重试或调整页数要求")
        logger.info("[PPT] 大纲自动审查通过%s",
                    f"（提示：{'；'.join(issues)}）" if issues else "")
        return clean

    def design_prompt_for_document(self, doc: PPTDocument) -> str:
        """根据已选模板/场景生成服务端内置设计约束；未选模板默认政务模板。"""
        category = "工作汇报"
        name = "政务工作汇报"
        font = DEFAULT_CJK_FONT
        colors: Dict[str, Any] = {}
        if doc.template_id:
            t = self.templates.get(doc.template_id)
            if t:
                category, name, font, colors = t.category, t.name, t.font, dict(t.colors or {})
        else:
            spec = next((s for s in BUILTIN_TEMPLATES
                         if s["id"] == (doc.theme_id or DEFAULT_GOV_TEMPLATE_ID)),
                        BUILTIN_TEMPLATES[0])
            category, name = spec["category"], spec["name"]
            colors = dict(spec.get("colors") or {})
        scene = "training" if "培训" in category else ("policy" if "政策" in category else "gov")
        base = DEFAULT_DESIGN_PROMPT[scene]
        palette = "、".join(str(v) for v in list(colors.values())[:6] if v)
        return (
            f"{base}\n已选模板：{name}（{category}）；字体：{font or DEFAULT_CJK_FONT}；"
            + (f"主色参考：{palette}。" if palette else "")
        )

    def active_quality_rules(self, user_id: str) -> List[Dict]:
        repo = SqlAlchemyFormatRuleRepository(self.db)
        repo.ensure_user_defaults(user_id)
        return [dict(target=r.target, checks=r.checks, name=r.name)
                for r in repo.list_for_check(user_id, None) if r.target == "ppt"]

    @staticmethod
    def assess_generated_pptx(data: bytes, expected_pages: int,
                              rules: Optional[List[Dict]] = None) -> List[str]:
        """静态质量闸：页数、封面越界、明显不适合中文的显式字体。"""
        issues: List[str] = []
        if rules is None:
            rules = PPT_DEFAULT_RULES
        checks = [r.get("checks") or {} for r in rules if r.get("target") == "ppt"]
        try:
            from pptx import Presentation
            prs = Presentation(io.BytesIO(data))
        except Exception as e:
            return [f"文件解析失败：{type(e).__name__}"]
        if expected_pages and len(prs.slides) != expected_pages and any(
                c.get("check_page_count") for c in checks):
            issues.append(f"页数不符：期望{expected_pages}页，实际{len(prs.slides)}页")
        if prs.slides and any(c.get("check_cover_overflow") for c in checks):
            sw, sh = int(prs.slide_width), int(prs.slide_height)
            tol = max(sw, sh) // 1000
            for shape in prs.slides[0].shapes:
                left = int(getattr(shape, "left", 0) or 0)
                top = int(getattr(shape, "top", 0) or 0)
                width = int(getattr(shape, "width", 0) or 0)
                height = int(getattr(shape, "height", 0) or 0)
                if left < -tol or top < -tol or left + width > sw + tol or top + height > sh + tol:
                    issues.append("封面存在越界元素")
                    break
        risky_fonts = [str(font).lower() for c in checks
                       for font in (c.get("forbidden_fonts") or []) if str(font).strip()]
        max_chars = min((int(c["max_chars_per_slide"]) for c in checks
                         if c.get("max_chars_per_slide")), default=0)
        for slide_no, slide in enumerate(prs.slides, 1):
            slide_chars = 0
            for shape in slide.shapes:
                if not getattr(shape, "has_text_frame", False):
                    continue
                slide_chars += len(re.sub(r"\s+", "", shape.text or ""))
                for para in shape.text_frame.paragraphs:
                    for run in para.runs:
                        if re.search(r"[\u4e00-\u9fff]", run.text or ""):
                            name = (run.font.name or "").lower()
                            if any(bad in name for bad in risky_fonts):
                                issues.append(f"中文字体异常：{run.font.name}")
            if max_chars and slide_chars > max_chars:
                issues.append(f"第{slide_no}页文字过多：{slide_chars}字，超过{max_chars}字")
        return list(dict.fromkeys(issues))

    @staticmethod
    def review_pptx_visuals(data: bytes) -> Dict[str, Any]:
        """逐页检查可见排版风险，供工作台在导出前复检。"""
        from math import ceil
        try:
            from pptx import Presentation
            prs = Presentation(io.BytesIO(data))
        except Exception as exc:
            return {"status": "review", "pages_checked": 0, "issues": [{
                "page": 0, "code": "invalid_file", "severity": "error",
                "message": f"演示文稿无法解析：{type(exc).__name__}",
            }]}

        issues: List[Dict[str, Any]] = []
        issue_keys = set()
        sw, sh = int(prs.slide_width), int(prs.slide_height)
        tolerance = max(sw, sh) // 1000

        def add(page: int, code: str, message: str, severity: str = "warning") -> None:
            key = (page, code, message)
            if key not in issue_keys:
                issue_keys.add(key)
                issues.append({"page": page, "code": code,
                               "severity": severity, "message": message})

        for page, slide in enumerate(prs.slides, 1):
            text_shapes = []
            char_count = 0
            for shape in slide.shapes:
                left = int(getattr(shape, "left", 0) or 0)
                top = int(getattr(shape, "top", 0) or 0)
                width = int(getattr(shape, "width", 0) or 0)
                height = int(getattr(shape, "height", 0) or 0)
                has_text_frame = bool(getattr(shape, "has_text_frame", False))
                raw_text = (shape.text or "") if has_text_frame else ""
                compact = re.sub(r"\s+", "", raw_text)
                shape_type = str(getattr(shape, "shape_type", ""))
                carries_content = bool(compact) or any(
                    kind in shape_type.upper() for kind in ("PICTURE", "CHART", "TABLE"))
                # Purchased templates commonly let background artwork bleed a
                # few millimetres over the slide edge. That is clipped by the
                # slide canvas and is not an exported content overflow.
                picture_bleed = ("PICTURE" in shape_type.upper() and
                    (left <= tolerance or top <= tolerance or
                     left + width >= sw - tolerance or top + height >= sh - tolerance))
                modest_bleed = (max(0, -left, left + width - sw) <= sw * .12 and
                                max(0, -top, top + height - sh) <= sh * .12)
                if carries_content and (left < -tolerance or top < -tolerance
                        or left + width > sw + tolerance or top + height > sh + tolerance) \
                        and not (picture_bleed and modest_bleed):
                    if compact:
                        add(page, "out_of_bounds", "存在超出页面边界的内容元素", "error")
                    else:
                        # 无文字的图形/图片是贴边出血装饰，画布会裁掉，不阻止保存
                        add(page, "out_of_bounds", "装饰图形超出页面边界（将裁切）", "warning")
                if not has_text_frame:
                    continue
                if not compact:
                    continue
                char_count += len(compact)
                sizes = [run.font.size.pt for para in shape.text_frame.paragraphs
                         for run in para.runs if run.font.size]
                min_size = min(sizes, default=18.0)
                # 用估算的文字实际占地区域判重叠：模板标题框常把副标题框包在
                # 框范围内，按整框判会把正常设计误判成压字、阻止保存。
                glyph = ppt_engine._glyph_rect(shape, left, top, width, height,
                                               raw_text, min_size, sw, sh)
                text_shapes.append((*glyph, shape))
                if min_size < 9:
                    add(page, "small_font", f"存在小于 9pt 的文字（{min_size:g}pt）")
                width_in = max(width / 914400, 0.5)
                height_in = max(height / 914400, 0.2)
                chars_per_line = max(6, int(width_in * 2.4 * 18 / max(min_size, 8)))
                estimated_lines = sum(max(1, ceil(len(line) / chars_per_line))
                                      for line in raw_text.splitlines() or [raw_text])
                line_capacity = max(1, int(height_in * 72 / (max(min_size, 8) * 1.2)))
                if estimated_lines > line_capacity + 1:
                    add(page, "text_overflow_risk", "文字可能超出文本框，请检查预览")
            if char_count > 450:
                add(page, "text_density", f"本页约 {char_count} 字，阅读密度偏高")

            for index, first in enumerate(text_shapes):
                ax, ay, aw, ah = first[:4]
                for bx, by, bw, bh in (other[:4] for other in
                                       text_shapes[index + 1:]):
                    overlap_w = max(0, min(ax + aw, bx + bw) - max(ax, bx))
                    overlap_h = max(0, min(ay + ah, by + bh) - max(ay, by))
                    overlap = overlap_w * overlap_h
                    smaller = min(max(aw * ah, 1), max(bw * bh, 1))
                    if overlap / smaller > 0.25:
                        add(page, "text_overlap", "两个文字区域明显重叠", "error")
                        break

        return {"status": "review" if issues else "passed",
                "pages_checked": len(prs.slides), "issues": issues}

    @staticmethod
    def review_rendered_pages(data: bytes, gateway=None) -> Dict[str, Any]:
        """让配置的本地视觉模型审看实际渲染截图，不信任其页码或问题代码。"""
        from app.application.ppt.visual_review import review_rendered_pages
        if gateway is None:
            from app.infrastructure.ai import get_vision_gateway
            gateway = get_vision_gateway()
        return review_rendered_pages(data, gateway)

    # ---- 存储路径 ----
    @property
    def ppt_dir(self) -> Path:
        d = settings.ppt_dir
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _tpl_source_path(self, template_id: str) -> Path:
        return self.ppt_dir / "tpl_src" / f"{template_id}.pptx"

    def _save_tpl_source(self, template_id: str, data: bytes) -> None:
        d = self.ppt_dir / "tpl_src"
        d.mkdir(parents=True, exist_ok=True)
        self._tpl_source_path(template_id).write_bytes(data)

    def _tpl_base_bytes(self, trow: Optional[PPTTemplate]) -> Optional[bytes]:
        """读取上传模板的原始 pptx 作为渲染底版；官方内置模板没有底版。"""
        if not trow:
            return None
        p = self._tpl_source_path(trow.id)
        if p.exists():
            try:
                return p.read_bytes()
            except Exception:
                return None
        return None

    def _layout_preview_path(self, template_id: str, layout_id: str) -> Path:
        return self.ppt_dir / "tpl_prev" / template_id / f"{layout_id}.png"

    # ================= 模板 =================
    def template_dto(self, t: PPTTemplate, user_id: str) -> dict:
        fav = self.favorites.get(user_id, t.id) is not None
        library = t.layout_library or []
        official_spec = next((spec for spec in BUILTIN_TEMPLATES
                              if t.is_official and spec["id"] == t.builtin_id), None)
        preview_url = ""
        for lay in library:
            if lay.get("preview"):
                preview_url = f"/api/v1/ppt/templates/{t.id}/layout-preview/{lay['id']}"
                break
        if official_spec and not preview_url:
            preview_url = (f"/api/v1/ppt/templates/{t.id}/layout-preview/"
                           f"{_official_preview_id(official_spec)}")
        return {
            "id": t.id,
            "name": official_spec["name"] if official_spec else t.name,
            "category": official_spec["category"] if official_spec else t.category,
            "description": official_spec.get("description") if official_spec else t.description,
            "is_official": bool(t.is_official), "is_mine": t.created_by == user_id,
            "colors": official_spec["colors"] if official_spec else t.colors,
            "font": t.font,
            "layouts": (ppt_engine.normalize_template_layouts(official_spec["layouts"])
                        if official_spec else t.layouts),
            "use_count": t.use_count, "is_favorite": fav,
            "is_learned": bool(library and self._tpl_base_bytes(t)),
            "is_shared": bool(t.is_official and not t.builtin_id),
            "license_note": t.license_note if t.created_by == user_id else "",
            "layout_count": (len(library) if library else
                             len(official_spec["layouts"] if official_spec else (t.layouts or {}))),
            "preview_url": preview_url,
            "created_at": t.created_at.strftime("%Y-%m-%d %H:%M") if t.created_at else "",
        }

    def list_templates(self, user: User, scope: str = "all",
                       category: Optional[str] = None,
                       keyword: Optional[str] = None) -> dict:
        rows = self.templates.list_for_user(user.id, scope, category, keyword)
        return {"items": [self.template_dto(t, user.id) for t in rows]}

    def list_categories(self) -> dict:
        return {"items": self.templates.list_categories()}

    def seed_builtin_templates(self) -> dict:
        """初始化内置官方模板（upsert 模式，可重复调用刷新）。"""
        created = 0
        for spec in BUILTIN_TEMPLATES:
            existing = self.templates.get_by_builtin_id(spec["id"])
            if existing:
                existing.name = spec["name"]
                existing.category = spec["category"]
                existing.description = spec.get("description")
                existing.colors = spec["colors"]
                existing.layouts = spec["layouts"]
                self.templates.update(existing)
            else:
                self.templates.add(PPTTemplate(
                    builtin_id=spec["id"], name=spec["name"], category=spec["category"],
                    description=spec.get("description"), is_official=True,
                    colors=spec["colors"], layouts=spec["layouts"]))
                created += 1
        return {"message": f"官方模板已同步（新增 {created} 个）"}

    def create_template(self, body, user: User) -> dict:
        try:
            colors = ppt_engine.normalize_template_colors(body.colors)
            layouts = ppt_engine.normalize_template_layouts(body.layouts)
            if any(re.fullmatch(r"L\d+", value) for value in layouts.values()):
                raise ValueError("学习版式只能绑定到已上传的模板")
        except ValueError as exc:
            raise AppError(400, str(exc)) from exc
        t = self.templates.add(PPTTemplate(
            name=body.name, category=body.category, description=body.description,
            is_official=False, created_by=user.id,
            colors=colors,
            font=body.font, layouts=layouts))
        return {"id": t.id, "message": "模板已创建"}

    def _get_editable_template(self, template_id: str, user: User) -> PPTTemplate:
        t = self.templates.get(template_id)
        if not t:
            raise NotFoundError("模板不存在")
        if t.is_official:
            if t.builtin_id or user.role not in {"developer", "knowledge_admin", "admin"}:
                raise PermissionDeniedError("内置模板不能修改；共享模板仅管理员可维护")
            return t
        if t.created_by != user.id:
            raise PermissionDeniedError("只能修改自己创建的模板")
        return t

    def _get_visible_template(self, template_id: str, user: User) -> PPTTemplate:
        """Only official templates and the current user's private templates are usable."""
        t = self.templates.get(template_id)
        if not t:
            raise NotFoundError("模板不存在")
        if not t.is_official and t.created_by != user.id:
            raise NotFoundError("模板不存在")
        return t

    def update_template(self, template_id: str, body, user: User) -> dict:
        t = self._get_editable_template(template_id, user)
        try:
            colors = ppt_engine.normalize_template_colors({**(t.colors or {}), **(body.colors or {})})
            layouts = ppt_engine.normalize_template_layouts({**(t.layouts or {}), **(body.layouts or {})})
            learned_ids = {item.get("id") for item in (t.layout_library or [])}
            if any(re.fullmatch(r"L\d+", value) and value not in learned_ids
                   for value in layouts.values()):
                raise ValueError("模板绑定了不存在的学习版式")
        except ValueError as exc:
            raise AppError(400, str(exc)) from exc
        t.name, t.category, t.description = body.name, body.category, body.description
        t.colors = colors
        t.font = body.font or t.font
        t.layouts = layouts
        self.templates.update(t)
        return {"message": "模板已更新"}

    def delete_template(self, template_id: str, user: User) -> dict:
        t = self._get_editable_template(template_id, user)
        self.favorites.delete_by_template(t.id)
        self.templates.hard_delete(t)
        p = self._tpl_source_path(template_id)
        if p.exists():
            try:
                p.unlink()
            except Exception:
                pass
        preview_dir = (self.ppt_dir / "tpl_prev" / template_id).resolve()
        preview_root = (self.ppt_dir / "tpl_prev").resolve()
        if preview_dir.parent == preview_root and preview_dir.is_dir():
            shutil.rmtree(preview_dir)
        return {"message": "模板已删除"}

    def toggle_favorite(self, template_id: str, user: User) -> dict:
        self._get_visible_template(template_id, user)
        fav = self.favorites.get(user.id, template_id)
        if fav:
            self.favorites.delete(fav)
            return {"is_favorite": False}
        self.favorites.add(PPTTemplateFavorite(user_id=user.id, template_id=template_id))
        return {"is_favorite": True}

    async def upload_template(self, file, name: str, category: str, user: User,
                              shared: bool = False, license_note: str = "") -> dict:
        """上传 .pptx 作为个人模板：提取主题色与字体，沿用默认版式体系。"""
        if not (file.filename or "").lower().endswith(".pptx"):
            raise AppError(400, "仅支持 .pptx 文件")
        data = await file.read(50 * 1024 * 1024 + 1)
        if not data:
            raise AppError(400, "文件内容为空")
        if len(data) > 50 * 1024 * 1024:
            raise AppError(400, "文件过大（限 50MB）")
        if not zipfile.is_zipfile(io.BytesIO(data)):
            raise AppError(400, "文件损坏或不是有效的 .pptx 文件")
        if shared and user.role not in {"developer", "knowledge_admin", "admin"}:
            raise PermissionDeniedError("只有管理员可以发布共享模板")
        if shared and not license_note.strip():
            raise AppError(400, "共享模板须填写允许系统内重复使用和改编的授权说明")
        # 上传即预处理：打 token/去品牌/清示例字/统一字体/自动去空页（与
        # deploy/prepare_ppt_template.py 同一套流水线）。比例不符或个别处理
        # 失败时回退原始文件，由 analyze 兜底，不让预处理阻塞上传。
        prep_notes: list = []
        try:
            data, prep_notes = await asyncio.to_thread(
                template_prepare.prepare_template_bytes, data)
        except template_prepare.RatioNotSupported as e:
            logger.warning("模板%s 比例不是 16:9，跳过自动预处理：%s", name, e)
        except Exception as e:
            logger.warning("模板%s 自动预处理失败，按原始文件继续: %s", name, e)
        try:
            learned = await asyncio.to_thread(ppt_engine.analyze_template, data)
            ppt_engine.validate_learned_template(learned)
        except Exception as e:
            raise AppError(400, f"模板解析失败：{e}")
        try:
            t = self.templates.add(PPTTemplate(
                name=name or os.path.splitext(file.filename)[0], category=category,
                description="管理员上传的共享模板" if shared else "用户上传的模板",
                is_official=shared, created_by=user.id,
                license_note=license_note.strip()[:500],
                colors=learned["colors"], font=learned["font"],
                layouts=DEFAULT_LAYOUTS.copy(),
                source_file=file.filename))
            self._save_tpl_source(t.id, data)
            library = learned.get("layouts") or []
            await asyncio.to_thread(self._gen_tpl_previews, t.id, data, library)
            t.layout_library = library
            self.templates.update(t)
        except (AppError, PermissionDeniedError):
            raise
        except Exception as e:
            self.db.rollback()
            raise AppError(500, f"模板保存失败：{e}")
        n = len(t.layout_library or [])
        message = f"模板「{t.name}」已创建，自动识别出 {n} 种版式"
        if prep_notes:
            message += f"，并已完成自动预处理（{len(prep_notes)} 项：去品牌/打锚点等）"
        return {"id": t.id,
                "message": message,
                "layout_count": n,
                "prepare_notes": prep_notes[:30]}

    def _gen_tpl_previews(self, template_id: str, data: bytes, layouts: list) -> None:
        """用 LibreOffice 把上传的 pptx 渲染成图片，截取各版式源页作为预览图。
        失败不影响上传（前端回退到结构示意图）。"""
        try:
            import glob
            import subprocess
            import tempfile
            d = self.ppt_dir / "tpl_prev" / template_id
            d.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory() as td:
                src = os.path.join(td, "tpl.pptx")
                with open(src, "wb") as f:
                    f.write(data)
                profile = (Path(td) / "lo-profile").as_uri()
                subprocess.run(["soffice", f"-env:UserInstallation={profile}",
                                "--headless", "--convert-to", "pdf",
                                "--outdir", td, src], timeout=180, capture_output=True)
                pdf = os.path.join(td, "tpl.pdf")
                if not os.path.exists(pdf):
                    return
                subprocess.run(["pdftoppm", "-png", "-r", "60", pdf,
                                os.path.join(td, "pg")], timeout=120, capture_output=True)
                pages = sorted(glob.glob(os.path.join(td, "pg-*.png")))
                for lay in layouts:
                    i = lay.get("source_slide_index", 0)
                    if i < len(pages):
                        shutil.copy(pages[i], str(d / f"{lay['id']}.png"))
                        lay["preview"] = f"{lay['id']}.png"
        except Exception as e:
            logger.warning("模板预览图生成失败（不影响使用）: %s", e)

    def get_layout_preview(self, template_id: str, layout_id: str, user: User) -> Path:
        template = self._get_visible_template(template_id, user)
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", layout_id):
            raise NotFoundError("预览图不存在")
        p = self._layout_preview_path(template_id, layout_id)
        official_spec = next((spec for spec in BUILTIN_TEMPLATES
                              if template.is_official and spec["id"] == template.builtin_id), None)
        if official_spec and layout_id == _official_preview_id(official_spec) and not p.exists():
            design = ppt_engine.template_to_dict(template)
            sample = {"slides": [{"type": "cover", "title": design["name"],
                                    "subtitle": template.description or "演示文稿模板"}]}
            data = ppt_engine.render_pptx(sample, design)
            self._gen_tpl_previews(template.id, data, [{"id": layout_id, "source_slide_index": 0}])
        if not p.exists():
            raise NotFoundError("预览图不存在")
        return p

    def template_detail(self, template_id: str, user: User) -> dict:
        t = self._get_visible_template(template_id, user)
        d = self.template_dto(t, user.id)
        library = []
        for lay in (t.layout_library or []):
            item = dict(lay)
            item.pop("element_schema", None)  # 结构 schema 不给前端，太大
            item["applicable_types"] = ppt_engine.layout_applicable_slide_types(
                str(item.get("detected_type") or "content"))
            if item.get("preview"):
                item["preview_url"] = f"/api/v1/ppt/templates/{t.id}/layout-preview/{item['id']}"
            library.append(item)
        d["layout_library"] = library
        return d

    def copy_template(self, template_id: str, user: User) -> dict:
        """复制模板（官方模板复制为个人模板，可在我的模板中编辑）。"""
        t = self._get_visible_template(template_id, user)
        nt = self.templates.add(PPTTemplate(
            name=t.name + "（副本）", category=t.category, description=t.description,
            is_official=False, created_by=user.id, colors=dict(t.colors or {}),
            font=t.font, layouts=dict(t.layouts or {}),
            layout_library=copy.deepcopy(t.layout_library or [])))
        src = self._tpl_base_bytes(t)
        if src:
            self._save_tpl_source(nt.id, src)
            source_previews = (self.ppt_dir / "tpl_prev" / t.id).resolve()
            target_previews = (self.ppt_dir / "tpl_prev" / nt.id).resolve()
            preview_root = (self.ppt_dir / "tpl_prev").resolve()
            if (source_previews.parent == preview_root and target_previews.parent == preview_root
                    and source_previews.is_dir()):
                shutil.copytree(source_previews, target_previews, dirs_exist_ok=True)
        return {"id": nt.id, "message": "已复制到「我的模板」"}

    def import_template_url(self, body, user: User) -> dict:
        """从在线链接导入 pptx 模板（仅提取版式风格，不保存原始内容）。"""
        try:
            from app.application.knowledge.web_fetcher import fetch_public_bytes
            data = fetch_public_bytes(body.url, max_bytes=50 * 1024 * 1024, timeout=30)
        except Exception as e:
            raise AppError(400, f"下载失败：{e}")
        if len(data) > 50 * 1024 * 1024:
            raise AppError(400, "文件超过 50MB")
        prep_notes: list = []
        try:
            data, prep_notes = template_prepare.prepare_template_bytes(data)
        except template_prepare.RatioNotSupported as e:
            logger.warning("在线模板比例不是 16:9，跳过自动预处理：%s", e)
        except Exception as e:
            logger.warning("在线模板自动预处理失败，按原始文件继续: %s", e)
        try:
            learned = ppt_engine.analyze_template(data)
            ppt_engine.validate_learned_template(learned)
        except Exception as e:
            raise AppError(400, f"模板解析失败：{e}") from e
        name = body.name or os.path.splitext(
            os.path.basename(body.url.split("?")[0]))[0] or "在线导入模板"
        t = self.templates.add(PPTTemplate(
            name=name, category=body.category, description="从在线链接导入的模板",
            is_official=False, created_by=user.id,
            colors=learned["colors"], font=learned["font"],
            layouts=DEFAULT_LAYOUTS.copy(),
            source_file=body.url[:500]))
        self._save_tpl_source(t.id, data)
        library = learned.get("layouts") or []
        self._gen_tpl_previews(t.id, data, library)
        t.layout_library = library
        self.templates.update(t)
        message = f"模板「{t.name}」已导入，自动识别出 {len(library)} 种版式"
        if prep_notes:
            message += f"，并已完成自动预处理（{len(prep_notes)} 项：去品牌/打锚点等）"
        return {"id": t.id, "message": message, "layout_count": len(library),
                "prepare_notes": prep_notes[:30]}

    def list_themes(self) -> dict:
        """旧首页兼容：主题 = 内置官方模板。"""
        return {"items": [{"id": s["id"], "name": s["name"], "category": s["category"],
                           "description": s.get("description", ""), "colors": s["colors"]}
                          for s in BUILTIN_TEMPLATES]}

    # ================= 素材库 =================
    def list_materials(self, user: User) -> dict:
        rows = self.materials.list_by_user(user.id)
        personal = [{"id": m.id, "name": m.name, "caption": m.caption,
                     "source": "personal", "category": "我的图片",
                     "url": f"/api/v1/ppt/materials/{m.id}/file"} for m in rows]
        return {"items": personal + self.list_library_images()["items"]}

    def list_library_images(self, category: str = "", keyword: str = "") -> dict:
        query = select(PPTLibraryImageModel).where(PPTLibraryImageModel.enabled.is_(True))
        if category:
            query = query.where(PPTLibraryImageModel.category == category)
        if keyword:
            term = f"%{keyword.strip()[:80]}%"
            query = query.where(PPTLibraryImageModel.name.ilike(term) |
                                PPTLibraryImageModel.caption.ilike(term))
        rows = self.db.scalars(query.order_by(PPTLibraryImageModel.category,
                                              PPTLibraryImageModel.created_at.desc()).limit(200)).all()
        return {"items": [{"id": row.id, "name": row.name, "caption": row.caption,
                           "category": row.category, "tags": row.tags or [],
                           "source": "library", "credit": row.source,
                           "license_note": row.license_note,
                           "url": f"/api/v1/ppt/library/images/{row.id}/file",
                           "thumb_url": f"/api/v1/ppt/library/images/{row.id}/thumb"}
                          for row in rows]}

    async def upload_library_image(self, file, name: str, caption: str, category: str,
                                   tags: str, source: str, license_note: str) -> dict:
        if not source.strip() or not license_note.strip():
            raise AppError(400, "公共图片必须登记来源和允许在本系统使用的授权说明")
        if not category.strip() or len(category) > 50 or len(name) > 200:
            raise AppError(400, "图片名称或分类无效")
        data = await file.read(10 * 1024 * 1024 + 1)
        if not data or len(data) > 10 * 1024 * 1024:
            raise AppError(400, "图片为空或超过 10MB")
        from PIL import Image, UnidentifiedImageError
        try:
            with Image.open(io.BytesIO(data)) as image:
                if image.format not in {"JPEG", "PNG", "WEBP"}:
                    raise ValueError("unsupported image format")
                width, height = image.size
                if width < 128 or height < 128 or width * height > 40_000_000:
                    raise ValueError("unsupported image dimensions")
                image.load()
                thumb = image.convert("RGB")
                thumb.thumbnail((480, 480))
                output = io.BytesIO()
                thumb.save(output, format="JPEG", quality=82)
                extension = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}[image.format]
                mime = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}[image.format]
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            raise AppError(400, "文件不是支持的有效图片") from exc
        if not caption.strip():
            from app.application.ppt.image_analysis import describe_image
            caption = await describe_image(data)
        folder = self.ppt_dir / "library"
        folder.mkdir(parents=True, exist_ok=True)
        image_id = uuid.uuid4().hex
        path = folder / f"{image_id}{extension}"
        thumbnail = folder / f"{image_id}-thumb.jpg"
        path.write_bytes(data)
        thumbnail.write_bytes(output.getvalue())
        row = PPTLibraryImageModel(id=image_id, name=name.strip() or Path(file.filename or "图片").stem[:200],
            caption=caption.strip()[:500], category=category.strip(),
            tags=[part.strip() for part in tags.split(",") if part.strip()][:12],
            file_path=str(path), thumb_path=str(thumbnail), file_size=len(data),
            width=width, height=height, mime_type=mime,
            source=source.strip()[:200], license_note=license_note.strip()[:500], enabled=True)
        try:
            self.db.add(row)
            self.db.commit()
        except Exception:
            self.db.rollback()
            path.unlink(missing_ok=True)
            thumbnail.unlink(missing_ok=True)
            raise
        return {"id": row.id, "caption": row.caption,
                "analysis_status": "ready" if row.caption else "unavailable",
                "message": ("图片已加入公共图库" if row.caption else
                            "图片已上架；视觉识别不可用，请补写图片说明后再用于自动配图")}

    def library_image_file(self, image_id: str, thumbnail: bool = False) -> tuple[Path, str]:
        row = self.db.get(PPTLibraryImageModel, image_id)
        if not row or not row.enabled:
            raise NotFoundError("图片不存在")
        path = Path(row.thumb_path if thumbnail else row.file_path)
        if not path.is_file():
            raise NotFoundError("图片文件不存在")
        return path, "image/jpeg" if thumbnail else row.mime_type

    def disable_library_image(self, image_id: str) -> dict:
        row = self.db.get(PPTLibraryImageModel, image_id)
        if not row:
            raise NotFoundError("图片不存在")
        row.enabled = False
        self.db.commit()
        return {"message": "图片已下架"}

    def update_library_image_caption(self, image_id: str, caption: str) -> dict:
        row = self.db.get(PPTLibraryImageModel, image_id)
        if not row or not row.enabled:
            raise NotFoundError("图片不存在")
        row.caption = caption.strip()[:500]
        self.db.commit()
        return {"id": row.id, "caption": row.caption, "message": "图片说明已更新"}

    async def upload_material(self, name: str, caption: str, file, user: User) -> dict:
        ext = os.path.splitext(file.filename or "")[1].lower()
        if ext not in [".jpg", ".jpeg", ".png", ".webp", ".gif"]:
            raise AppError(400, "仅支持图片文件")
        data = await file.read(20 * 1024 * 1024 + 1)
        if not data or len(data) > 20 * 1024 * 1024:
            raise AppError(400, "图片为空或超过 20MB")
        try:
            from PIL import Image
            with Image.open(io.BytesIO(data)) as image:
                image.verify()
            with Image.open(io.BytesIO(data)) as image:
                width, height = image.size
            if width < 32 or height < 32 or width > 12000 or height > 12000 \
                    or width * height > 40_000_000:
                raise ValueError("图片尺寸不适合演示文稿")
        except Exception as exc:
            logger.info("PPT 素材图片校验未通过：%s", type(exc).__name__)
            raise AppError(400, "文件不是有效图片，或图片尺寸不适合演示文稿")
        if not caption.strip():
            from app.application.ppt.image_analysis import describe_image
            caption = await describe_image(data)
        fname = f"{uuid.uuid4().hex}{ext}"
        path = self.ppt_dir / "materials" / fname
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        m = self.materials.add(PPTMaterial(
            user_id=user.id, name=name, caption=caption,
            file_path=str(path), file_size=len(data),
            width=width, height=height,
            mime_type=file.content_type or ""))
        return {"id": m.id, "width": width, "height": height,
                "caption": m.caption,
                "analysis_status": "ready" if m.caption else "unavailable",
                "message": ("图片已识别并加入素材库" if m.caption else
                            "图片已上传；视觉识别不可用，请补写图片说明后再用于自动配图")}

    def update_material(self, mid: str, name: str, caption: str, user: User) -> dict:
        m = self.materials.get_for_user(mid, user.id)
        if not m:
            raise NotFoundError("素材不存在")
        m.name, m.caption = name, caption
        self.materials.update(m)
        return {"message": "素材已更新"}

    def update_material_caption(self, mid: str, caption: str, user: User) -> dict:
        m = self.materials.get_for_user(mid, user.id)
        if not m:
            raise NotFoundError("素材不存在")
        m.caption = caption.strip()[:500]
        self.materials.update(m)
        return {"id": m.id, "caption": m.caption, "message": "图片说明已更新"}

    def delete_material(self, mid: str, user: User) -> dict:
        m = self.materials.get_for_user(mid, user.id)
        if not m:
            raise NotFoundError("素材不存在")
        if os.path.exists(m.file_path):
            os.remove(m.file_path)
        self.materials.delete(m)
        return {"message": "素材已删除"}

    def material_file(self, mid: str, user: User) -> Tuple[Path, str]:
        m = self.materials.get_for_user(mid, user.id)
        if not m or not os.path.exists(m.file_path):
            raise NotFoundError("文件不存在")
        return Path(m.file_path), m.mime_type or "image/jpeg"

    def _user_images(self, user_id: str,
                     material_ids: Optional[List[str]] = None,
                     strict: bool = True) -> List[Dict]:
        personal = self.materials.list_by_user(user_id)
        library_ids = list(dict.fromkeys(material_ids or []))
        library = (self.db.scalars(select(PPTLibraryImageModel).where(
            PPTLibraryImageModel.enabled.is_(True),
            PPTLibraryImageModel.id.in_(library_ids))).all() if library_ids else [])
        available = {row.id: {"id": row.id, "name": row.name,
            "caption": row.caption, "file_path": row.file_path,
            "width": row.width, "height": row.height, "source": "personal"}
            for row in personal}
        available.update({row.id: {"id": row.id, "name": row.name,
            "caption": row.caption, "tags": row.tags or [], "category": row.category,
            "file_path": row.file_path, "width": row.width,
            "height": row.height, "source": "library"}
            for row in library})
        if material_ids is None:
            return [available[row.id] for row in personal]
        selected = []
        for material_id in dict.fromkeys(material_ids):
            image = available.get(material_id)
            if not image:
                if strict:
                    raise NotFoundError("图片素材不存在")
                logger.info("PPT 已选图片素材不可用，渲染时跳过：material_id=%s", material_id)
                continue
            selected.append(image)
        return selected

    def _outline_images(self, user_id: str, material_ids: Optional[List[str]],
                        auto_images: bool, topic: str, content: str) -> List[Dict]:
        """Manual selection wins; automatic candidates stay inside user/public scope."""
        if material_ids:
            return self._user_images(user_id, material_ids)
        if not auto_images:
            return []
        personal = [item for item in self._user_images(user_id) if item["caption"]]
        public_rows = self.db.scalars(select(PPTLibraryImageModel).where(
            PPTLibraryImageModel.enabled.is_(True),
            PPTLibraryImageModel.caption != "").order_by(
                PPTLibraryImageModel.created_at.desc()).limit(200)).all()
        public = [{"id": row.id, "name": row.name, "caption": row.caption,
                   "tags": row.tags or [], "category": row.category,
                   "file_path": row.file_path, "width": row.width,
                   "height": row.height, "source": "library"}
                  for row in public_rows if row.source and row.license_note]
        candidates = personal + public
        # Bound the model's image catalogue. The model does the final semantic
        # page choice from these captions; this score only limits prompt size.
        query = set(re.findall(r"[\u4e00-\u9fff]{2,4}|[A-Za-z]{3,}",
                               (topic + " " + content[:1200]).lower()))

        def rank(item: Dict) -> tuple[int, int]:
            description = (str(item.get("name") or "") + " " +
                           str(item.get("caption") or "") + " " +
                           str(item.get("category") or "") + " " +
                           " ".join(item.get("tags") or [])).lower()
            return (sum(1 for word in query if word in description),
                    1 if item["source"] == "personal" else 0)

        return sorted(candidates, key=rank, reverse=True)[:50]

    @staticmethod
    def _bind_outline_images(outline: dict, images: List[Dict], mode: str) -> None:
        ppt_engine.resolve_slide_images(outline, images)
        used = []
        for slide in outline.get("slides") or []:
            image = slide.pop("_image", None)
            if image and image["id"] not in used:
                used.append(image["id"])
        outline["material_ids"] = ([item["id"] for item in images]
                                   if mode == "manual" else used)
        outline["image_selection_mode"] = mode

    # ================= 文档（我的PPT） =================
    @staticmethod
    def _doc_dto(d: PPTDocument, template_name: str = "") -> dict:
        slides = (d.outline or {}).get("slides") or []
        return {
            "id": d.id, "title": d.title, "subtitle": d.subtitle,
            "status": d.status, "is_favorite": bool(d.is_favorite),
            "template_id": d.template_id, "template_name": template_name,
            "theme_id": d.theme_id, "slide_count": len(slides),
            "has_drawio": any((s.get("blocks") or {}).get("drawio_xml") for s in slides),
            "created_at": d.created_at.strftime("%Y-%m-%d %H:%M") if d.created_at else "",
            "updated_at": d.updated_at.strftime("%Y-%m-%d %H:%M") if d.updated_at else "",
        }

    def list_documents(self, user: User, tab: str = "all",
                       keyword: Optional[str] = None) -> dict:
        rows = self.documents.list_by_user(user.id, tab, keyword)
        tmap = {t.id: t.name for t in self.templates.list_for_user(user.id, "all")}
        return {"items": [self._doc_dto(d, tmap.get(d.template_id, "")) for d in rows]}

    def _get_doc_checked(self, doc_id: str, user: User) -> PPTDocument:
        d = self.documents.get_for_user(doc_id, user.id)
        if not d:
            raise NotFoundError("文档不存在")
        return d

    def get_document(self, doc_id: str, user: User) -> dict:
        d = self._get_doc_checked(doc_id, user)
        template = None
        if d.template_id:
            t = self.templates.get(d.template_id)
            if t:
                template = ppt_engine.template_to_dict(t)
        elif d.theme_id:  # 兼容旧文档（theme_id 即内置模板 id）
            spec = next((s for s in BUILTIN_TEMPLATES if s["id"] == d.theme_id), None)
            if spec:
                template = ppt_engine.template_to_dict(spec)
        if not template:
            template = ppt_engine.template_to_dict(BUILTIN_TEMPLATES[0])
        return {**self._doc_dto(d, template["name"]), "outline": d.outline, "template": template}

    def save_draft(self, doc_id: str, body, user: User) -> dict:
        """自动保存草稿。

        已生成文档若内容/模板真的发生变化，则标记回 draft，表示现有 pptx 已过期；
        仅重新打开并原样保存时保持 generated，这样可以继续复用上次真实生成产物预览。
        """
        d = self._get_doc_checked(doc_id, user)
        changed = False
        effective_template_id = (body.template_id if "template_id" in body.model_fields_set
                                 else d.template_id)
        if body.outline is not None:
            payload = dict(body.outline)
            previous = d.outline or {}
            # 图片授权范围与配图模式是文档级状态，不属于可编辑的页面内容。
            # 客户端只回传 slides 时若直接整体替换，会丢掉 material_ids，
            # 导出重新渲染时公共图库图片便无法解析，表现为「图没了」。
            for key in ("material_ids", "image_selection_mode"):
                if key not in payload and key in previous:
                    payload[key] = previous[key]
            normalized = ppt_engine.normalize_outline(
                payload, require_bookends=bool(effective_template_id))
            if normalized != (d.outline or {}):
                changed = True
            d.outline = normalized
            new_title = body.title or d.outline.get("title") or d.title
            if new_title != d.title:
                changed = True
            d.title = new_title
            d.subtitle = d.outline.get("subtitle") or d.subtitle
        elif body.title and body.title != d.title:
            d.title = body.title
            changed = True
        if "template_id" in body.model_fields_set:
            if body.template_id:
                t = self._get_visible_template(body.template_id, user)
                if t.id != d.template_id:
                    d.template_id = t.id
                    changed = True
            elif d.template_id is not None:
                # 显式选择“智能选择”时清除之前绑定的模板；省略字段仍表示保持原值。
                d.template_id = None
                changed = True
        if changed and d.status == "generated":
            d.status = "draft"
        d = self.documents.update(d)
        return {"message": "已保存",
                "updated_at": d.updated_at.strftime("%H:%M:%S") if d.updated_at else ""}

    def copy_document(self, doc_id: str, user: User) -> dict:
        d = self._get_doc_checked(doc_id, user)
        nd = self.documents.add(PPTDocument(
            user_id=user.id, title=d.title + "（副本）", subtitle=d.subtitle,
            source_type=d.source_type, source_content=d.source_content,
            outline=d.outline, theme_id=d.theme_id, template_id=d.template_id,
            status="draft"))
        return {"id": nd.id, "message": "已复制"}

    def toggle_doc_favorite(self, doc_id: str, user: User) -> dict:
        d = self._get_doc_checked(doc_id, user)
        d.is_favorite = not d.is_favorite
        d = self.documents.update(d)
        return {"is_favorite": bool(d.is_favorite)}

    def rename_document(self, doc_id: str, user: User, title: str) -> dict:
        """重命名 PPT 文档：只改标题，不动 outline / status / 版本。"""
        d = self._get_doc_checked(doc_id, user)
        name = (title or "").strip()
        if not name:
            raise AppError(422, "文档标题不能为空")
        if len(name) > 200:
            raise AppError(422, "文档标题不能超过 200 字")
        d.title = name
        d = self.documents.update(d)
        # 模板名取值方式与 list_documents 完全一致，保证与列表项同构
        tmap = {t.id: t.name for t in self.templates.list_for_user(user.id, "all")}
        return self._doc_dto(d, tmap.get(d.template_id, ""))

    def delete_document(self, doc_id: str, user: User) -> dict:
        d = self._get_doc_checked(doc_id, user)
        if d.file_path and os.path.exists(d.file_path):
            os.remove(d.file_path)
        prev_dir = self.ppt_dir / "preview" / d.id
        if prev_dir.exists():
            shutil.rmtree(prev_dir, ignore_errors=True)
        (self.ppt_dir / "preview" / (d.id + ".key")).unlink(missing_ok=True)
        self.documents.delete(d)
        return {"message": "已删除"}

    # ================= 逐页预览（工作台中栏真实版式） =================
    @staticmethod
    def _missing_preview_tools() -> List[str]:
        """逐页预览依赖的外部命令体检：返回缺失的命令名（空列表=全部可用）。

        容器镜像若未安装 LibreOffice / poppler，这里能提前发现，避免把
        ``FileNotFoundError: 'soffice'`` 之类的进程异常冒泡成 HTTP 500。

        Returns:
            缺失的命令名列表，取自 ``("soffice", "pdftoppm")`` 的子集。
        """
        return [name for name in _PREVIEW_TOOLS if shutil.which(name) is None]

    @staticmethod
    def _degraded_preview(reason: str) -> dict:
        """预览不可用时的正常响应结构：页数列表为空 + 可读原因。

        桌面端拿到空 ``pages`` 即回退到结构化示意卡，与"无预览"完全一致，
        不会弹错误也不会卡住 loading；服务端同时已在日志里留下原因。

        Args:
            reason: 面向运维/前端展示的中文原因说明。

        Returns:
            与成功响应同构的字典，额外带 ``degraded`` / ``reason`` 字段。
        """
        return {"pages": [], "count": 0, "degraded": True, "reason": reason}

    def preview_document(self, doc_id: str, user: User) -> dict:
        """把当前草稿渲染成 pptx 并逐页转 PNG，供工作台中栏显示真实版式。

        依赖容器内 LibreOffice（soffice）+ poppler（pdftoppm）。任何环节不可用
        （命令缺失 / 超时 / 未产出文件）都**降级为空页数列表 + 原因说明**，
        绝不返回 500；桌面端据此回退到结构化预览卡，不影响其它功能。
        """
        d = self._get_doc_checked(doc_id, user)
        if not d.outline:
            raise NotFoundError("文档不存在或内容为空")

        missing = self._missing_preview_tools()
        if missing:
            reason = ("服务端未安装 " + " / ".join(missing)
                      + "，无法渲染真实版式预览（需在镜像中安装 libreoffice 与 poppler-utils）")
            logger.warning("PPT 逐页预览降级：缺少外部命令 %s（doc_id=%s）",
                           ",".join(missing), doc_id)
            return self._degraded_preview(reason)

        preview_source = "generated" if (
            d.status == "generated" and d.file_path and os.path.exists(d.file_path)
        ) else "draft"
        # 结果缓存：大纲、模板、产物来源都没变时直接复用上次渲染的 PNG。
        # 预览刷新/切模板是高频操作，LibreOffice 全量渲染一次要数秒到数十秒，
        # key 命中即可秒回，显著改善工作台切换模板与重开文档的速度。
        prev_dir = self.ppt_dir / "preview" / d.id
        key_file = self.ppt_dir / "preview" / (d.id + ".key")
        try:
            cache_key = hashlib.md5(_json.dumps(
                {"outline": d.outline, "template": d.template_id or "",
                 "source": preview_source,
                 "mtime": os.path.getmtime(d.file_path) if preview_source == "generated" else 0},
                ensure_ascii=False, sort_keys=True, default=str,
            ).encode("utf-8")).hexdigest()
        except Exception:  # 序列化失败只影响缓存，不影响渲染主流程
            cache_key = None
        cached_names = sorted(p.name for p in prev_dir.glob("pg-*.png")) \
            if prev_dir.exists() else []
        if cache_key and cached_names and key_file.exists() \
                and key_file.read_text(encoding="utf-8").strip() == cache_key:
            return {"pages": [f"/api/v1/ppt/preview/{d.id}/{n}" for n in cached_names],
                    "count": len(cached_names), "degraded": False, "reason": "",
                    "source": preview_source}
        try:
            # 已生成且未再编辑：直接预览上次真实产出的 pptx。
            # 这保证“生成完成时看到什么，重新打开仍看到什么”，避免退回本地简化模板。
            if preview_source == "generated":
                data = Path(d.file_path).read_bytes()
            else:
                if d.template_id:
                    data = self.render_strict_template_pptx(d, d.outline, user.id)
                else:
                    data, _ = self.render_adaptive_pptx(
                        d, d.outline, user.id, vision_review=False)
        except Exception as e:
            logger.warning("PPT 逐页预览降级：渲染 pptx 失败（doc_id=%s）：%s: %s",
                           doc_id, type(e).__name__, e)
            return self._degraded_preview("版式渲染失败，暂无法显示真实预览")

        if prev_dir.exists():
            shutil.rmtree(prev_dir, ignore_errors=True)
        prev_dir.mkdir(parents=True, exist_ok=True)
        try:
            import subprocess
            import tempfile
            with tempfile.TemporaryDirectory() as td:
                src = os.path.join(td, "prev.pptx")
                with open(src, "wb") as f:
                    f.write(data)
                subprocess.run(["soffice", "--headless", "--convert-to", "pdf",
                                "--outdir", td, src],
                               timeout=_PREVIEW_TIMEOUTS["soffice"], capture_output=True)
                pdf = os.path.join(td, "prev.pdf")
                if not os.path.exists(pdf):
                    raise _PreviewRenderError("LibreOffice 未产出 PDF")
                subprocess.run(["pdftoppm", "-png", "-r", "90", pdf,
                                os.path.join(str(prev_dir), "pg")],
                               timeout=_PREVIEW_TIMEOUTS["pdftoppm"], capture_output=True)
        except _PreviewRenderError as e:
            shutil.rmtree(prev_dir, ignore_errors=True)
            logger.warning("PPT 逐页预览降级：%s（doc_id=%s）", e, doc_id)
            return self._degraded_preview(
                f"预览渲染未完成：{e}（可能是文档内容无法转换）")
        except subprocess.TimeoutExpired as e:
            shutil.rmtree(prev_dir, ignore_errors=True)
            cmd = (e.cmd or [""])[0] if isinstance(e.cmd, list) else (e.cmd or "")
            logger.warning("PPT 逐页预览降级：外部命令超时 %s 超过 %ss（doc_id=%s）",
                           cmd, e.timeout, doc_id)
            return self._degraded_preview("版式渲染超时，请稍后重试或减少页数")
        except Exception as e:
            shutil.rmtree(prev_dir, ignore_errors=True)
            logger.warning("PPT 逐页预览降级：外部命令执行失败（doc_id=%s）：%s: %s",
                           doc_id, type(e).__name__, e)
            return self._degraded_preview("版式渲染服务暂时不可用，已回退为结构示意")
        names = sorted(p.name for p in prev_dir.glob("pg-*.png"))
        if not names:
            shutil.rmtree(prev_dir, ignore_errors=True)
            logger.warning("PPT 逐页预览降级：未产出任何预览图（doc_id=%s）", doc_id)
            return self._degraded_preview(
                "渲染流程完成但未生成预览图（请检查 pdftoppm 与字体依赖）")
        if cache_key:
            try:
                key_file.write_text(cache_key, encoding="utf-8")
            except OSError as e:
                logger.warning("PPT 预览缓存键写入失败（doc_id=%s）：%s", doc_id, e)
        return {"pages": [f"/api/v1/ppt/preview/{d.id}/{n}" for n in names],
                "count": len(names), "degraded": False, "reason": "",
                "source": preview_source}

    def visual_review_document(self, doc_id: str, user: User) -> dict:
        """按当前草稿和模板真实渲染，再返回逐页视觉风险。"""
        document = self._get_doc_checked(doc_id, user)
        if not document.outline:
            raise NotFoundError("文档不存在或内容为空")
        outline = self.sanitize_outline(
            dict(document.outline),
            target_count=len((document.outline or {}).get("slides") or []) or None,
            ensure_toc=False,
            enforce_bookends=bool(document.template_id),
        )
        selected_ids = outline.get("material_ids")
        available = self._user_images(user.id, selected_ids, strict=False)
        resolved_ids = {str(item["id"]) for item in available}
        outline = ppt_engine.resolve_slide_images(outline, available)
        missing_pages = sorted(
            index for index, slide in enumerate(outline.get("slides") or [], 1)
            if slide.get("image_id") and str(slide["image_id"]) not in resolved_ids)
        warnings: List[str] = []
        if document.template_id:
            template, template_row = self._resolve_template(
                document.template_id, document.theme_id or "")
            data = ppt_engine.render_pptx(
                outline, template, base_pptx=self._tpl_base_bytes(template_row),
                warnings=warnings)
        else:
            data, _ = self.render_adaptive_pptx(
                document, outline, user.id, warnings=warnings,
                vision_review=False)
        result = self.review_pptx_visuals(data)
        rendered = self.review_rendered_pages(data)
        result["rendered_pages_checked"] = rendered["pages_checked"]
        result["review_method"] = ("geometry_and_vision" if rendered["pages_checked"]
                                   else "geometry_only")
        result["issues"].extend(rendered["issues"])
        for page in missing_pages:
            result["issues"].append({
                "page": page, "code": "missing_image", "severity": "error",
                "message": "本页所选图片已下架或删除，导出时不会插入；请重新选择图片",
            })
        if rendered["status"] in ("unavailable", "partial"):
            result["issues"].append({
                "page": 0, "code": "vision_unavailable", "severity": "warning",
                "message": "实际页面视觉复检未全部完成；请查看逐页预览",
            })
        for warning in warnings:
            result["issues"].append({
                "page": 0, "code": "render_fallback", "severity": "warning",
                "message": warning,
            })
        if result["issues"]:
            result["status"] = "review"
        result["summary"] = ("视觉复检通过" if result["status"] == "passed" else
                             f"发现 {len(result['issues'])} 项需要确认的排版问题")
        return result

    def preview_image(self, doc_id: str, name: str, user: User) -> Path:
        """预览图下载（仅本人文档的预览目录，防目录穿越）。"""
        d = self._get_doc_checked(doc_id, user)
        root = (self.ppt_dir / "preview" / d.id).resolve()
        p = (root / name).resolve()
        if root != p.parent or not p.exists():
            raise NotFoundError("预览图不存在")
        return p

    # ================= 生成流程 =================
    def list_kbs(self, user: User) -> dict:
        """PPT 可选知识库列表（含文档数）。

        按服务端解析的可见范围过滤（公共库 + 本科室库 + 本人个人库），
        前端拿不到无权库的入口；检索时 RagService 还会再做一次交集校验。
        """
        from app.application.knowledge.access import KnowledgeAccessPolicy
        allowed = set(KnowledgeAccessPolicy(self.db).accessible_kb_ids(user))
        if not allowed:
            return {"items": []}
        rows = self.db.scalars(select(KnowledgeBaseModel).where(
            KnowledgeBaseModel.is_active == True,  # noqa: E712
            KnowledgeBaseModel.id.in_(allowed))).all()
        # 一次聚合统计全部知识库文档数，避免“每个知识库再查一遍全部文档”的 N+1。
        count_rows = self.db.execute(
            select(DocumentModel.kb_id, func.count(DocumentModel.id))
            .where(
                DocumentModel.kb_id.in_(allowed),
                DocumentModel.status == "published",
            )
            .group_by(DocumentModel.kb_id)
        ).all()
        counts = {kb_id: int(cnt or 0) for kb_id, cnt in count_rows}
        items = [{
            "id": kb.id,
            "name": kb.name,
            "description": kb.description or "",
            "doc_count": counts.get(kb.id, 0),
        } for kb in rows]
        return {"items": items}

    def _kb_content(self, kb_ids: list, limit: int = 6000) -> Tuple[str, List[str]]:
        """汇总所选知识库已发布文档的内容（按文档截断拼接）。

        Returns:
            (拼接文本, 命中文档标题清单)
        """
        docs = self.db.scalars(select(DocumentModel).where(
            DocumentModel.kb_id.in_(kb_ids),
            DocumentModel.status == "published")
            .order_by(DocumentModel.created_at.desc()).limit(20)).all()
        parts = []
        titles = []
        total = 0
        for d in docs:
            text = (d.content or "")[:1200]
            if not text.strip():
                continue
            seg = f"《{d.title}》\n{text}"
            if total + len(seg) > limit:
                break
            parts.append(seg)
            titles.append(d.title)
            total += len(seg)
        return "\n\n".join(parts), titles

    def _rag_kb_material(self, query: str, user: User,
                         kb_ids: List[str], limit: int = 4000) -> Tuple[str, List[str]]:
        """RAG 语义检索：按主题从所选知识库检索相关片段（而非整库原文截断灌入）。

        权限范围由 RagService 在服务端解析（kb_ids 与可访问库取交集），
        客户端传值无法扩大检索范围。向量服务 / 嵌入模型不可用时降级为空，
        绝不阻塞大纲生成。

        Returns:
            (拼接好的知识库材料文本, 命中来源文档名清单)
        """
        if not kb_ids or not query.strip():
            return "", []
        try:
            from app.application.knowledge.rag_service import RagService
            from app.infrastructure.rag import get_embedder, get_vector_store
            rag = RagService(self.db, get_embedder(), get_vector_store())
            hits = rag.search(query[:200], user.id, kb_ids=kb_ids, top_k=8)
        except Exception as e:  # noqa: BLE001 - 检索失败不能拖垮大纲生成
            logger.warning("[PPT] 知识库检索失败，按无知识库材料继续：%s: %s",
                           type(e).__name__, str(e)[:200])
            return "", []
        parts: List[str] = []
        sources: List[str] = []
        total = 0
        for h in hits:
            text = (h.get("content") or "").strip()
            if not text:
                continue
            raw_source = h.get("source") or ""
            name = h.get("source_name")
            if not name:
                title = raw_source.split("（第")[0].strip() if raw_source else ""
                name = title or "知识库文档"
            seg = f"《{name}》（{h.get('source') or '相关片段'}）\n{text[:800]}"
            if total + len(seg) > limit:
                break
            parts.append(seg)
            total += len(seg)
            if name not in sources:
                sources.append(name)
        return "\n\n".join(parts), sources

    def _apply_kb_material(self, user: User, kb_ids: Optional[List[str]],
                           topic: str, content: str,
                           material_names: Optional[List[str]]) -> Tuple[str, List[str]]:
        """把所选知识库的检索材料并入大纲上下文。

        有检索词（主题 / 材料正文）→ RAG 语义检索；什么都没有（纯选库）
        → 回退整库按文档截断拼接。检索为空不在这里报错：主题与上传材料
        仍可驱动生成；source_type="kb" 的纯知识库入口由调用方判空。

        Returns:
            (合并后的 content, 追加知识库来源后的 material_names)
        """
        names = list(material_names or [])
        if not kb_ids:
            return content, names
        query = (topic or "").strip() or (content or "")[:200]
        if query.strip():
            kb_text, kb_sources = self._rag_kb_material(query, user, kb_ids)
        else:
            kb_text, kb_sources = self._kb_content(kb_ids)
        if kb_text:
            content = (content.rstrip() + "\n\n" if content else "") + \
                "【知识库检索材料】\n" + kb_text
            names += [f"知识库《{s}》" for s in kb_sources]
        return content, names

    def outline_from_kb(self, kb_ids: List[str], topic: str, audience: str,
                        scene: str, slide_count: int, user: User) -> dict:
        """知识库入口大纲：有主题 → RAG 语义检索相关片段；无主题 → 整库截断拼接
        （合并与判空逻辑统一在 _do_outline / _apply_kb_material）。"""
        return self._do_outline(user, "kb", topic, "", slide_count, audience, scene,
                                kb_ids=kb_ids)

    async def extract_text(self, file) -> dict:
        """提取单个文档文本（前端多文件时循环调用，自行拼接后走 /outline）。"""
        data = await file.read()
        text = self._extract_any(file.filename or "unnamed", data)
        return {"filename": file.filename, "text": text[:3000]}

    # ---- 材料文本提取（一等公民：doc/docx/pdf/txt/md/xlsx/xls/csv/pptx 内容） ----
    _EXCEL_EXTS = (".xlsx", ".xlsm", ".xls", ".csv")

    def _extract_any(self, filename: str, data: bytes) -> str:
        """材料文本提取：Excel/CSV 直接读表格，其余走附件解析通道。"""
        ext = "." + filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
        if ext in self._EXCEL_EXTS:
            return self._extract_excel(filename, data, ext)
        if ext == ".pptx":
            # 已有 PPT 作为材料：抽取各页文字供 AI 参考
            try:
                ol = ppt_engine.outline_from_pptx(data)
                parts = [f"《{ol.get('title', '')}》"]
                for i, s in enumerate(ol.get("slides") or [], 1):
                    seg = f"第{i}页 {s.get('title', '')}"
                    pts = "；".join(s.get("points") or [])
                    if pts:
                        seg += "：" + pts
                    parts.append(seg)
                text = "\n".join(parts)
                if text.strip():
                    return text[:20000]
            except Exception:
                pass
            raise AppError(400, f"未能从「{filename}」提取到文字内容")
        return self._extract_upload_text(filename, data)

    @staticmethod
    def _extract_excel(filename: str, data: bytes, ext: str) -> str:
        """Excel/CSV → 纯文本（工作表名 + 行，竖线分隔），供 AI 读取数据表。"""
        try:
            if ext == ".csv":
                for enc in ("utf-8", "gb18030"):
                    try:
                        return data.decode(enc)[:20000]
                    except UnicodeDecodeError:
                        continue
                return data.decode("utf-8", errors="ignore")[:20000]
            import openpyxl
            wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
            parts = []
            for ws in wb.worksheets[:5]:
                parts.append(f"【工作表】{ws.title}")
                for i, row in enumerate(ws.iter_rows(values_only=True)):
                    if i >= 60:
                        parts.append("……（后续行省略）")
                        break
                    vals = ["" if v is None else str(v) for v in row]
                    if any(v.strip() for v in vals):
                        parts.append(" | ".join(vals))
            wb.close()
            text = "\n".join(parts)
            if not text.strip():
                raise AppError(400, f"未能从「{filename}」提取到表格内容")
            return text[:20000]
        except AppError:
            raise
        except Exception as e:
            raise AppError(400, f"表格「{filename}」解析失败：{e}")

    def _extract_upload_text(self, filename: str, data: bytes) -> str:
        from app.application.chat.attachment_service import AttachmentService
        suffix = "." + filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
        tmp = self.ppt_dir / "tmp" / f"{uuid.uuid4().hex}{suffix}"
        tmp.parent.mkdir(parents=True, exist_ok=True)
        try:
            tmp.write_bytes(data)
            text, status, note = AttachmentService().extract(tmp, suffix, "doc")
        except Exception as e:
            raise AppError(400, f"文件「{filename}」解析失败：{e}")
        finally:
            tmp.unlink(missing_ok=True)
        if status != "ok" and not text.strip():
            raise AppError(400, f"未能从「{filename}」提取到文字内容")
        return text

    # ================= 材料分析（先看见分析结果，再生成大纲） =================
    async def analyze_materials(self, files, user: User) -> dict:
        """上传材料并逐份分析：提取文本 + AI 结构化摘要（摘要 / 重点 / 数据表数）。

        让「上传完黑盒等待」变成可见的分析结果；返回的 text 供后续大纲步骤
        拼接使用（前端不必再调 extract-text）。

        返回结构（桌面端 PptViewModel 按此消费）：
            items: [{filename, chars, summary, key_points, tables, text}, ...]
            totals: {materials: 份数, key_points: 重点总条数, tables: 数据表总数}
        """
        if not files:
            raise AppError(400, "请先选择材料文件")
        assistant = self._ppt_assistant()
        items = []
        for f in files[:8]:
            data = await f.read()
            if not data:
                continue
            text = self._extract_any(f.filename or "unnamed", data)
            analysis = self._summarize_material(assistant, f.filename or "材料", text)
            items.append({
                "filename": f.filename, "chars": len(text),
                "summary": analysis.get("summary", ""),
                "key_points": analysis.get("key_points") or [],
                "tables": analysis.get("tables") or 0,
                "text": text[:4000],
            })
        if not items:
            raise AppError(400, "没有可解析的材料")
        # 聚合统计：桌面端「材料聚合统计」直接读这三个数
        totals = {
            "materials": len(items),
            "key_points": sum(len(i["key_points"]) for i in items),
            "tables": sum(i["tables"] for i in items),
        }
        return {"items": items, "totals": totals,
                "message": f"已分析 {len(items)} 份材料"}

    @staticmethod
    def _summarize_material(assistant, filename: str, text: str) -> Dict[str, Any]:
        """单份材料的结构化分析：摘要 + 重点清单 + 数据表数量。

        桌面端（PptViewModel.kt materials 解析）按 ``{summary, key_points, tables}``
        三个字段消费，因此这里必须产出**同名同类型**的字段：
        ``summary``=字符串 / ``key_points``=字符串数组 / ``tables``=整数。

        模型返回非法 JSON、调用失败、字段缺失时一律降级为「摘要=原文截断、
        key_points=空数组、tables=0」，**绝不抛异常**打断整批材料分析。

        Args:
            assistant: 模型助手（PPT 专用模型或主模型）。
            filename: 材料文件名，作为模型上下文。
            text: 材料提取出的文本。

        Returns:
            ``{"summary": str, "key_points": List[str], "tables": int}``
        """
        prompt = (
            "请分析这份材料，只输出一个 JSON 对象，不要输出解释、标题或代码块标记。\n"
            "JSON 结构：\n"
            '{"summary": "材料性质与内容的一句话说明", '
            '"key_points": ["重点1", "重点2"], "tables": 0}\n'
            "字段要求：\n"
            "1. summary：字符串，2~4 句简短中文，说明材料性质与主要内容；\n"
            "2. key_points：字符串数组，3~6 条材料重点（关键数字、结论、事项），"
            "每条不带序号或列表符号；\n"
            "3. tables：整数，材料中数据表/统计表格的数量，没有则填 0。\n\n"
            f"【文件名】{filename}\n【内容节选】\n{text[:2500]}")
        try:
            raw = assistant.complete(
                [{"role": "user", "content": prompt}],
                temperature=0.3, max_tokens=500)
        except Exception as e:  # noqa: BLE001 - 模型不可用不能拖垮整批材料分析
            logger.warning("材料分析调用模型失败，降级为空摘要：%s", type(e).__name__)
            return {"summary": "", "key_points": [], "tables": 0}

        obj = _parse_json_object(raw or "")
        if obj is None:
            # 降级：模型没按 JSON 返回，就把原文当摘要用，重点与表数留空
            logger.warning("材料分析返回非 JSON，降级为原文摘要：%s", filename)
            return {"summary": (raw or "").strip()[:300], "key_points": [], "tables": 0}

        summary = str(obj.get("summary") or "").strip()[:300]
        key_points: List[str] = []
        raw_points = obj.get("key_points")
        if isinstance(raw_points, list):
            key_points = [str(p).strip() for p in raw_points if str(p).strip()]
        elif isinstance(raw_points, str):
            # 有些模型把清单写成换行分隔的一段文字
            key_points = [s.strip() for s in raw_points.splitlines() if s.strip()]
        try:
            tables = max(0, int(obj.get("tables") or 0))
        except (TypeError, ValueError):
            tables = 0
        return {"summary": summary, "key_points": key_points[:8], "tables": tables}

    # ================= 生成前预检（信息不足先确认，不瞎编） =================
    def precheck_outline(self, body, user: User) -> dict:
        """兼容旧接口的无打扰预检。

        新交互只保留“描述需求 → 确认大纲 → 拿文件”。缺少风格、页数、场景等信息
        一律由服务端默认策略补齐；缺少事实时要求模型使用概括表述而不是编造，不再追问用户。
        """
        topic = (body.topic or "").strip()
        content = (body.content or "").strip()
        kb_ids = getattr(body, "kb_ids", None) or []
        if not topic and not content and not kb_ids:
            raise AppError(400, "请填写 PPT 主题，或上传/选择一份材料")
        logger.info("[PPT] 无打扰预检通过：user=%s topic_chars=%d content_chars=%d",
                    user.id, len(topic), len(content))
        return {"sufficient": True, "questions": []}

    # ================= 大纲 =================
    def _do_outline(self, user: User, source_type: str, topic: str, content: str,
                    slide_count: int, audience: str = "", scene: str = "",
                    material_names: Optional[List[str]] = None,
                    material_ids: Optional[List[str]] = None,
                    auto_images: bool = True,
                    kb_ids: Optional[List[str]] = None,
                    enforce_exact_count: bool = True) -> dict:
        content, material_names = self._apply_kb_material(
            user, kb_ids, topic, content, material_names)
        kb_empty = bool(kb_ids) and "【知识库检索材料】" not in (content or "")
        if kb_empty and (source_type == "kb"
                         or not ((topic or "").strip() or (content or "").strip())):
            raise AppError(400, "所选知识库没有检索到与主题相关的内容，"
                                "请换个主题描述，或检查库内是否有已发布文档")
        target_count = self._effective_slide_count(
            slide_count, enforce_exact_count, content)
        images = self._outline_images(user.id, material_ids, auto_images, topic, content)
        try:
            outline = ppt_engine.generate_outline(
                self._ppt_assistant(), source_type, topic, content, images,
                target_count, audience, scene,
                material_names=material_names,
                # 未填页数时仅给建议，由模型按材料决定实际页数。
                enforce_exact_count=enforce_exact_count, free_structure=True)
            outline = self._audit_and_repair_outline(
                outline, target_count if enforce_exact_count else None, content)
            # 大纲阶段自动为适合图示的页面挂接 drawio 原生图示（固化进 blocks.drawio_xml，
            # 后续渲染链路自动取用；未配置/失败则静默回退原生步骤条）。
            outline = ppt_engine.enrich_outline_with_diagrams(self._ppt_assistant(), outline)
            self._bind_outline_images(outline, images,
                                      "manual" if material_ids else
                                      "auto" if auto_images else "off")
        except RuntimeError as e:
            raise AIServiceError(str(e))
        d = self.documents.add(PPTDocument(
            user_id=user.id, title=outline.get("title", "未命名PPT"),
            subtitle=outline.get("subtitle", ""), source_type=source_type,
            # 后续 PPTAgent 必须能看到真实材料；topic 不能覆盖 material content。
            source_content=(content or topic or "")[:8000],
            # 用户未选模板：按大纲 style 提示与主题关键词自动配色，摆脱"永远深蓝"
            theme_id=ppt_engine.pick_builtin_template(
                topic or outline.get("title"), outline.get("style")),
            outline=outline, status="draft", slide_count=len(outline.get("slides") or [])))
        logger.info("[PPT] 权威大纲已创建：doc_id=%s pages=%d source=%s",
                    d.id, len(outline.get("slides") or []), source_type)
        return {"doc_id": d.id, "outline": outline}

    def make_outline(self, body, user: User) -> dict:
        explicit_count = "slide_count" in getattr(body, "model_fields_set", set())
        return self._do_outline(user, body.source_type, body.topic, body.content,
                                body.slide_count, body.audience, body.scene,
                                material_names=body.material_names,
                                material_ids=body.material_ids,
                                auto_images=body.auto_images,
                                kb_ids=getattr(body, "kb_ids", None),
                                enforce_exact_count=explicit_count)

    def outline_stream(self, body, user: User) -> Iterator[str]:
        """流式大纲（SSE）：stage 事件展示进度，done 携带权威大纲。

        大纲是结构化 JSON，不逐 token 上屏；流式的价值在过程可见：
        正在理解材料 → 正在梳理大纲 → 校验与保存。事件：
          {"type":"stage","text":...} / {"type":"done","data":{"doc_id,outline"}}
          / {"type":"error","message":...}
        """
        def _sse(obj) -> str:
            return f"data: {_json.dumps(obj, ensure_ascii=False)}\n\n"

        yield _sse({"type": "stage", "text": "正在理解材料与任务要求…"})
        kb_ids = getattr(body, "kb_ids", None) or []
        if kb_ids:
            yield _sse({"type": "stage", "text": "正在知识库中检索相关材料…"})
        content, material_names = self._apply_kb_material(
            user, kb_ids, body.topic, body.content, body.material_names)
        kb_empty = bool(kb_ids) and "【知识库检索材料】" not in (content or "")
        if kb_empty and (body.source_type == "kb"
                         or not ((body.topic or "").strip() or (body.content or "").strip())):
            yield _sse({"type": "error",
                        "message": "所选知识库没有检索到与主题相关的内容，"
                                   "请换个主题描述，或检查库内是否有已发布文档"})
            return
        yield _sse({"type": "stage", "text": "正在梳理汇报结构…"})
        try:
            if body.auto_images and not body.material_ids:
                yield _sse({"type": "stage", "text": "正在从图库挑选相关图片…"})
            images = self._outline_images(user.id, body.material_ids,
                                          body.auto_images, body.topic, content)
            explicit_count = "slide_count" in getattr(body, "model_fields_set", set())
            target_count = self._effective_slide_count(
                body.slide_count, explicit_count, content)
            outline = ppt_engine.generate_outline(
                self._ppt_assistant(), body.source_type, body.topic, content,
                images, target_count, body.audience, body.scene,
                material_names=material_names,
                enforce_exact_count=explicit_count, free_structure=True)
            yield _sse({"type": "stage", "text": "正在自动检查页面结构与内容密度…"})
            outline = self._audit_and_repair_outline(
                outline, target_count if explicit_count else None, content)
            # 仅在 drawio 真正开启时提示图示生成进度，避免无配置环境多出 stage 事件
            from app.application.ppt.drawio_service import DrawioService
            diagram_pages = [page for page in outline.get("slides") or []
                             if page.get("type") == "process" and not
                             (page.get("blocks") or {}).get("drawio_xml")]
            if diagram_pages and DrawioService().native_available:
                yield _sse({"type": "stage", "text": "正在为图示页生成可编辑图形…"})
            outline = ppt_engine.enrich_outline_with_diagrams(self._ppt_assistant(), outline)
            for page in outline.get("slides") or []:
                if page.get("diagram_warning"):
                    yield _sse({"type": "stage", "text":
                                f"{page.get('title') or '图示页'}：{page['diagram_warning']}"})
            self._bind_outline_images(outline, images,
                                      "manual" if body.material_ids else
                                      "auto" if body.auto_images else "off")
        except RuntimeError as e:
            yield _sse({"type": "error", "message": str(e)})
            return
        except Exception as e:
            logger.exception("PPT 大纲生成失败：%s", e)
            yield _sse({"type": "error", "message": _OUTLINE_UNEXPECTED_ERROR_MSG})
            return
        yield _sse({"type": "stage", "text": "大纲已优化，正在保存…"})
        d = self.documents.add(PPTDocument(
            user_id=user.id, title=outline.get("title", "未命名PPT"),
            subtitle=outline.get("subtitle", ""), source_type=body.source_type,
            source_content=(content or body.topic or "")[:8000],
            theme_id=ppt_engine.pick_builtin_template(
                body.topic or outline.get("title"), outline.get("style")),
            outline=outline, status="draft", slide_count=len(outline.get("slides") or [])))
        logger.info("[PPT] 流式权威大纲已创建：doc_id=%s pages=%d",
                    d.id, len(outline.get("slides") or []))
        yield _sse({"type": "done", "data": {"doc_id": d.id, "outline": outline}})

    async def outline_from_doc(self, file, topic: str, audience: str, scene: str,
                               slide_count: int, user: User) -> dict:
        data = await file.read()
        text = self._extract_any(file.filename or "unnamed", data)
        return self._do_outline(user, "document", topic, text, slide_count, audience, scene,
                                material_names=[file.filename] if file.filename else None)

    # ================= 已有 PPT 导入续改 =================
    async def import_pptx(self, file, user: User) -> dict:
        """上传已有 .pptx 继续修改：解析为可编辑大纲并创建文档（状态 draft）。
        之后走与新建文档完全相同的编辑 / AI 逐页修改 / 导出链路。"""
        if not (file.filename or "").lower().endswith(".pptx"):
            raise AppError(400, "仅支持 .pptx 文件")
        data = await file.read()
        if not data:
            raise AppError(400, "文件内容为空")
        if len(data) > 50 * 1024 * 1024:
            raise AppError(400, "文件过大（限 50MB）")
        if not zipfile.is_zipfile(io.BytesIO(data)):
            raise AppError(400, "文件损坏或不是有效的 .pptx 文件")
        try:
            outline = ppt_engine.outline_from_pptx(data)
        except RuntimeError as e:
            raise AppError(400, str(e))
        d = self.documents.add(PPTDocument(
            user_id=user.id, title=outline.get("title", "导入的PPT"),
            subtitle=outline.get("subtitle", ""), source_type="import",
            source_content=(file.filename or "")[:200], outline=outline, status="draft"))
        return {"doc_id": d.id, "outline": outline,
                "message": f"已导入「{file.filename}」，共 {len(outline.get('slides') or [])} 页，"
                           "可逐页编辑或让 AI 修改"}

    def _resolve_template(self, template_id: Optional[str],
                          fallback_theme: str = "") -> Tuple[Dict, Optional[PPTTemplate]]:
        """解析模板；任何缺省/失效选择都显式回到默认政务模板。"""
        if template_id:
            t = self.templates.get(template_id)
            if t:
                return ppt_engine.template_to_dict(t), t
            logger.warning("[PPT] 指定模板不存在，回退默认政务模板：template_id=%s",
                           template_id)

        desired = fallback_theme or DEFAULT_GOV_TEMPLATE_ID
        spec = next((s for s in BUILTIN_TEMPLATES if s["id"] == desired), None)
        if spec is None:
            logger.warning("[PPT] 主题不存在，回退默认政务模板：theme_id=%s", desired)
            spec = next(
                (s for s in BUILTIN_TEMPLATES if s["id"] == DEFAULT_GOV_TEMPLATE_ID),
                BUILTIN_TEMPLATES[0],
            )
        t = self.templates.get_by_builtin_id(spec["id"])
        if t:
            return ppt_engine.template_to_dict(t), t
        return ppt_engine.template_to_dict(spec), None

    def _render_pptx_bytes(self, d: PPTDocument, outline: dict, template: Dict,
                           base_pptx: Optional[bytes],
                           warnings: Optional[List[str]] = None,
                           adaptive: bool = False) -> Tuple[bytes, str]:
        """渲染 pptx 字节：自由排版直走本地；旧模板路线保留兼容回退。

        开关语义：
        - 自由排版或 ``PPT_AGENT_URL`` 为空 → 直接走本地 ``render_pptx``；
        - 显式模板且旧服务已启用 → 先试旧渲染器，失败则回退本地渲染。
        回退目标始终是真实可用的本地渲染结果，绝不会返回空文件或占位文件。

        Args:
            d: 当前 PPT 文档（提供标题与素材上下文）。
            outline: 已解析（图片路径已就位）的大纲。
            template: 模板字典（本地渲染用；PPTAgent 只取风格提示）。
            base_pptx: 模板底稿字节（本地渲染用）。

        Returns:
            (pptx 字节, 渲染来源 ``"pptagent"`` / ``"local"``)
        """
        def local_render() -> bytes:
            """未选模板时按内容排版并复检；显式模板保持原样。"""
            if adaptive:
                data, adjusted = self._render_with_feedback(
                    outline, template, warnings=warnings)
                outline.clear()
                outline.update(adjusted)
                return data
            return ppt_engine.render_pptx(outline, template, base_pptx=base_pptx, warnings=warnings)

        if adaptive or not (settings.PPT_AGENT_URL or "").strip():
            logger.debug("PPT 自适应或未配置旧渲染器，走本地可编辑版式")
            return local_render(), "local"

        # PPTAgent 走的是「喂主题 + 材料，由它全权排版」的形态，故把结构化大纲
        # 序列化成 Markdown 正文，并补上原始素材作为上下文。
        try:
            from app.infrastructure.ppt.ppt_agent_client import (
                PPTAgentClient, PPTAgentError, build_outline_markdown, looks_like_pptx,
            )
            md = build_outline_markdown(outline)
            material = (d.source_content or "").strip()
            design = self.design_prompt_for_document(d)
            content_md = md
            if material:
                content_md += f"\n\n# 原始素材\n{material[:8000]}"
            content_md += (
                "\n\n# 系统设计约束（必须执行）\n" + design
                + "\n严格按已确认页数生成，不新增封面/结束页，不编造数据。"
            )
            client = PPTAgentClient.from_settings()
            expected = len(outline.get("slides") or [])
            data = client.render(
                topic=(outline.get("title") or d.title or "未命名演示文稿"),
                content_markdown=content_md,
                slide_count=expected,
                template_hint=(template or {}).get("name") or (template or {}).get("id") or "",
            )
            ok, why = looks_like_pptx(data)
            if not ok:
                raise PPTAgentError(f"结果非法：{why}")

            quality_rules = self.active_quality_rules(d.user_id)
            issues = self.assess_generated_pptx(data, expected, quality_rules)
            if issues:
                logger.warning("[PPT] 同步 AI 智能设计未通过质量闸：%s", "；".join(issues))
                retry_content = (
                    content_md + "\n\n# 系统自动修正要求\n"
                    + "请完整重做并修复：" + "；".join(issues)
                    + "。保持页数和已确认大纲不变。"
                )
                retry = client.render(
                    topic=(outline.get("title") or d.title or "未命名演示文稿"),
                    content_markdown=retry_content,
                    slide_count=expected,
                    template_hint=(template or {}).get("name") or (template or {}).get("id") or "",
                )
                ok2, why2 = looks_like_pptx(retry)
                retry_issues = self.assess_generated_pptx(retry, expected, quality_rules) if ok2 else [why2]
                if retry_issues:
                    raise PPTAgentError("质量检查未通过：" + "；".join(retry_issues))
                data = retry
                logger.info("[PPT] 同步 AI 智能设计自动重试通过：doc_id=%s", d.id)

            logger.info("PPTAgent 渲染成功：doc_id=%s，%d 字节", d.id, len(data))
            return data, "pptagent"
        except Exception as e:  # noqa: BLE001 - 任何异常都必须落到本地渲染
            # 注意：不打印凭据，只打印类型与原因
            logger.warning("PPTAgent 渲染失败，回退本地渲染：%s: %s",
                           type(e).__name__, str(e)[:300])
            return local_render(), "local"

    def render_strict_template_pptx(
            self, d: PPTDocument, outline: dict, user_id: str) -> bytes:
        """严格套模板路径：不调用 PPTAgent，不允许模型重新决定布局。"""
        template, trow = self._resolve_template(d.template_id, d.theme_id or "")
        clean = self.sanitize_outline(
            outline,
            target_count=len((outline or {}).get("slides") or []) or None,
            ensure_toc=False,
        )
        selected_ids = clean.get("material_ids")
        clean = ppt_engine.resolve_slide_images(
            clean, self._user_images(user_id, selected_ids, strict=False))
        base = self._tpl_base_bytes(trow)
        logger.info(
            "[PPT] 严格套模板渲染：doc_id=%s template=%s learned_base=%s pages=%d",
            d.id,
            template.get("name") or template.get("id") or DEFAULT_GOV_TEMPLATE_ID,
            bool(base),
            len(clean.get("slides") or []),
        )
        return ppt_engine.render_pptx(clean, template, base_pptx=base)

    def render_local_pptx(self, d: PPTDocument, outline: dict, user_id: str) -> bytes:
        """显式模板走固定版式；自由生成按内容选择并复检版式。"""
        if d.template_id:
            return self.render_strict_template_pptx(d, outline, user_id)
        data, adjusted = self.render_adaptive_pptx(d, outline, user_id)
        d.outline = adjusted
        return data

    @staticmethod
    def _render_with_feedback(outline: dict, template: Dict,
                              warnings: Optional[List[str]] = None,
                              vision_review: bool = True) -> Tuple[bytes, dict]:
        """针对检测出排版问题的页面试用其他可行版式，保留内容和页数。"""
        from copy import deepcopy

        current = deepcopy(outline)
        render_warnings: List[str] = []
        data = ppt_engine.render_pptx(current, template, warnings=render_warnings,
                                      adaptive=True)
        review = PPTService.review_pptx_visuals(data)

        def score(result: dict, page: Optional[int] = None) -> int:
            weights = {"out_of_bounds": 10, "text_overlap": 10,
                       "text_overflow_risk": 4, "small_font": 2, "text_density": 1}
            return sum(weights.get(issue["code"], 2)
                       for issue in result.get("issues") or []
                       if page is None or issue.get("page") == page)

        bad_pages = sorted({issue["page"] for issue in review.get("issues") or []
                            if issue.get("page", 0) > 0 and
                            issue.get("code") in ("out_of_bounds", "text_overlap",
                                                   "text_overflow_risk")})[:3]
        for page in bad_pages:
            slide = current["slides"][page - 1]
            if slide.get("layout_locked"):
                continue
            original = str(slide.get("layout") or "")
            best_score = score(review, page)
            if not best_score:
                continue
            for layout in ppt_engine.layout_ids(slide.get("type") or "content")[:6]:
                if layout == original or ppt_engine.choose_layout(
                        {**slide, "layout": layout}) != layout:
                    continue
                trial = deepcopy(current)
                trial["slides"][page - 1]["layout"] = layout
                trial_warnings: List[str] = []
                try:
                    trial_data = ppt_engine.render_pptx(
                        trial, template, warnings=trial_warnings, adaptive=True)
                except Exception as exc:  # noqa: BLE001 - 候选版式失败不影响已生成的基线版本
                    logger.warning("[PPT] 替代版式渲染失败：page=%d layout=%s error=%s",
                                   page, layout, type(exc).__name__)
                    continue
                trial_review = PPTService.review_pptx_visuals(trial_data)
                trial_score = score(trial_review, page)
                if (trial_score < best_score
                        and score(trial_review) - trial_score <= score(review) - best_score):
                    current, data, review, best_score = trial, trial_data, trial_review, trial_score
                    render_warnings = trial_warnings
                if best_score == 0:
                    break
        if warnings is not None:
            warnings.extend(render_warnings)
            warnings.extend(
                f"第{issue['page']}页：{issue['message']}" for issue in review.get("issues") or []
                if issue.get("page", 0) > 0)
        if vision_review and settings.VISION_MODEL_URL:
            rendered = PPTService.review_rendered_pages(data)
            findings = [f"第{issue['page']}页：{issue['message']}"
                        for issue in rendered["issues"]]
            if warnings is not None:
                warnings.extend(findings)
                if rendered["status"] in ("unavailable", "partial"):
                    warnings.append("实际页面视觉复检未全部完成，请查看逐页预览")
            for finding in findings:
                logger.warning("[PPT] 视觉复检发现问题：%s", finding)
        return data, current

    def render_adaptive_pptx(self, d: PPTDocument, outline: dict,
                             user_id: str,
                             warnings: Optional[List[str]] = None,
                             vision_review: bool = True) -> Tuple[bytes, dict]:
        """自由生成使用主题配色；只在用户显式选模板时加载模板底稿。"""
        template, _ = self._resolve_template(None, d.theme_id or "")
        clean = self.sanitize_outline(
            outline, target_count=len((outline or {}).get("slides") or []) or None,
            ensure_toc=False, enforce_bookends=False)
        selected_ids = clean.get("material_ids")
        clean = ppt_engine.resolve_slide_images(
            clean, self._user_images(user_id, selected_ids, strict=False))
        return self._render_with_feedback(clean, template, warnings,
                                          vision_review=vision_review)

    def _render_and_store(self, d: PPTDocument, outline: dict, user: User,
                          template_id: Optional[str],
                          warnings: Optional[List[str]] = None) -> str:
        """渲染 pptx 并落盘，更新文档状态。返回文件路径。

        无论走 AI 智能设计还是严格套模板，渲染前都执行同一套确定性净化；
        用户在确认页明确把目录改成正文时不重新强制补目录。
        """
        target = len((outline or {}).get("slides") or []) or None
        selected_template_id = template_id or d.template_id
        outline = self.sanitize_outline(
            outline, target_count=target, ensure_toc=False,
            enforce_bookends=bool(selected_template_id))
        logger.info("[PPT] 渲染前规则净化完成：doc_id=%s pages=%d",
                    d.id, len(outline.get("slides") or []))
        if selected_template_id:
            self._get_visible_template(selected_template_id, user)
        template, trow = self._resolve_template(selected_template_id, d.theme_id or "")
        selected_ids = outline.get("material_ids")
        available = self._user_images(user.id, selected_ids, strict=False)
        resolved_ids = {str(item["id"]) for item in available}
        outline = ppt_engine.resolve_slide_images(outline, available)
        # 图片被下架/删除后仍留在页面 image_id 上，渲染只能跳过。不能静默：
        # 生成链路把页码放进 warnings，导出链路至少留日志，便于定位「图没了」。
        missing_pages = sorted(
            index for index, slide in enumerate(outline.get("slides") or [], 1)
            if slide.get("image_id") and str(slide["image_id"]) not in resolved_ids)
        if missing_pages:
            message = (f"第{'、'.join(str(page) for page in missing_pages)}页所用图片"
                       "已下架或删除，本次未插入，请重新选择图片")
            logger.warning("[PPT] %s：doc_id=%s", message, d.id)
            if warnings is not None:
                warnings.append(message)
        data, renderer = self._render_pptx_bytes(
            d, outline, template,
            self._tpl_base_bytes(trow) if selected_template_id else None,
            warnings=warnings, adaptive=not selected_template_id)
        review = self.review_pptx_visuals(data)
        hard = [issue for issue in review.get("issues") or []
                if issue.get("severity") == "error"]
        if hard and selected_template_id:
            # A purchased layout can still fail on unusual real content after
            # its per-page checks. Keep the selected color system, render a
            # readable editable deck, and tell the user what happened.
            safe_template = {**template, "layout_library": []}
            safe_data = ppt_engine.render_pptx(
                outline, safe_template, adaptive=True)
            safe_review = self.review_pptx_visuals(safe_data)
            if not any(issue.get("severity") == "error"
                       for issue in safe_review.get("issues") or []):
                pages = "、".join(str(page) for page in sorted(
                    {issue["page"] for issue in hard}))
                if warnings is not None:
                    warnings.append(f"模板第{pages}页排版未通过检查，已用本模板配色重新排版")
                data, renderer = safe_data, "local_safe_fallback"
                hard = []
        if hard:
            pages = "、".join(str(page) for page in sorted(
                {issue["page"] for issue in hard}))
            raise AppError(422, f"第{pages}页仍有文字重叠或越界，请精简内容后再生成")
        fname = f"{uuid.uuid4().hex}.pptx"
        path = self.ppt_dir / "generated" / fname
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        if d.file_path and os.path.exists(d.file_path):
            os.remove(d.file_path)
        d.outline = {k: v for k, v in outline.items()}  # 保存解析后的大纲
        d.title = outline.get("title") or d.title
        d.subtitle = outline.get("subtitle") or d.subtitle
        d.file_path = str(path)
        d.status = "generated"
        d.slide_count = len(outline.get("slides") or [])
        if trow and selected_template_id:
            d.template_id = trow.id
            trow.use_count = (trow.use_count or 0) + 1
            self.templates.update(trow)
        self.documents.update(d)
        logger.info("PPT 渲染落盘：doc_id=%s，来源=%s，%d 字节，路径=%s",
                    d.id, renderer, len(data), path)
        return str(path)

    def generate(self, body, user: User) -> dict:
        """渲染并保存 pptx 文件（编辑器中的'生成/重新生成'动作）。"""
        d = self._get_doc_checked(body.doc_id, user)
        if "template_id" in getattr(body, "model_fields_set", set()) and body.template_id is None:
            d.template_id = None
        outline = (ppt_engine.normalize_outline(
            body.outline, require_bookends=bool(body.template_id or d.template_id))
            if body.outline else d.outline)
        if not outline:
            raise AppError(400, "大纲为空")
        warnings: List[str] = []
        self._render_and_store(d, outline, user, body.template_id, warnings=warnings)
        return {"message": "已生成", "warnings": warnings,
                "download_url": f"/api/v1/ppt/documents/{d.id}/download"}

    def export_document(self, doc_id: str, user: User) -> Tuple[Path, str]:
        """导出可编辑 .pptx：按当前草稿重新渲染（保证导出的是最新编辑内容）。"""
        d = self._get_doc_checked(doc_id, user)
        if not d.outline:
            raise NotFoundError("文档不存在或内容为空")
        path = self._render_and_store(d, d.outline, user, None)
        return Path(path), f"{d.title or 'PPT'}.pptx"

    def download_document(self, doc_id: str, user: User) -> Tuple[Path, str]:
        d = self._get_doc_checked(doc_id, user)
        if not d.file_path or not os.path.exists(d.file_path):
            raise NotFoundError("文件不存在，请先生成或导出")
        return Path(d.file_path), f"{d.title or 'PPT'}.pptx"

    def download_drawio_source(self, doc_id: str, user: User) -> Tuple[bytes, str]:
        """Return the editable diagram pages stored in this user's current outline."""
        from app.application.ppt.drawio_native import build_drawio_source

        d = self._get_doc_checked(doc_id, user)
        try:
            source = build_drawio_source(d.outline or {})
        except ValueError as exc:
            raise AppError(400, str(exc)) from exc
        return source, f"{d.title or 'PPT'}-图示.drawio"

    def create_blank(self, body, user: User) -> dict:
        if body.template_id:
            self._get_visible_template(body.template_id, user)
        outline = ppt_engine.normalize_outline({
            "title": body.title, "subtitle": body.subtitle,
            "slides": [
                {"type": "cover", "title": body.title, "subtitle": body.subtitle},
                {"type": "content", "title": "第一页", "points": ["点击右侧 AI 助手或双击文字开始编辑"]},
                {"type": "closing", "title": "谢谢聆听，请批评指正"},
            ]})
        d = self.documents.add(PPTDocument(
            user_id=user.id, title=body.title, subtitle=body.subtitle,
            source_type="blank", outline=outline, template_id=body.template_id,
            status="draft"))
        return {"doc_id": d.id, "message": "已创建空白PPT"}

    # ================= AI 编辑器操作 =================
    def ai_slide_action(self, body) -> dict:
        try:
            return {"slide": ppt_engine.ai_slide_action(
                self._ppt_assistant(), body.action, body.slide, body.instruction)}
        except RuntimeError as e:
            raise AIServiceError(str(e))

    def ai_visual(self, body, user: User) -> dict:
        if body.kind not in {"chart", "timeline", "process", "data",
                             "relationship", "organization", "architecture"}:
            raise AppError(400, "不支持的可视化类型")
        try:
            warnings = []
            diagram_kinds = {"process", "relationship", "organization", "architecture"}
            if body.kind in diagram_kinds:
                from app.application.ppt.drawio_service import DrawioService
                if body.template_id:
                    self._get_visible_template(body.template_id, user)
                style, _ = self._resolve_template(body.template_id)
                drawio = DrawioService()
                if drawio.native_available:
                    diagram = drawio.generate_native_diagram(
                        self._ppt_assistant(), body.slide, body.instruction,
                        kind=body.kind, style=style)
                    if diagram is not None:
                        return {"slide": diagram}
                    logger.warning("Draw.io MCP 暂不可用，回退本地流程图生成")
                    if body.kind == "process":
                        warnings.append("图示增强服务暂不可用，已自动使用本地流程图生成。")
                    else:
                        warnings.append(
                            "图示增强服务暂不可用，已用基础流程版式展示本页内容；"
                            "连线关系与层级可能未表达，请核对。")
            fallback_kind = (
                "process" if body.kind in {"relationship", "organization", "architecture"}
                else body.kind
            )
            result: Dict[str, Any] = {"slide": ppt_engine.ai_generate_visual(
                self._ppt_assistant(), fallback_kind, body.slide, body.instruction)}
            if warnings:
                result["warnings"] = warnings
            return result
        except RuntimeError as e:
            raise AIServiceError(str(e))

    def ai_structure(self, body) -> dict:
        try:
            slides = ppt_engine.ai_structure_action(
                self._ppt_assistant(), body.action, body.slides, body.index, body.instruction)
            return {"slides": slides}
        except (RuntimeError, IndexError) as e:
            raise AIServiceError(str(e))

    def ai_outline_adjust(self, body) -> dict:
        """自然语言整体调整大纲；用户明确调整后的页型优先，不强制重新补目录。"""
        logger.info("[PPT] AI 大纲调整：instruction=%s", body.instruction[:120])
        try:
            outline = ppt_engine.ai_outline_adjust(
                self._ppt_assistant(), body.outline, body.instruction)
            # 仍清理封面/结束页脏字段，但 respect 用户“把目录改成正文”等显式修改。
            outline = self.sanitize_outline(
                outline, target_count=None, ensure_toc=False,
                enforce_bookends=False)
            logger.info("[PPT] AI 大纲调整完成：pages=%d",
                        len(outline.get("slides") or []))
            return {"outline": outline}
        except RuntimeError as e:
            logger.warning("[PPT] AI 大纲调整失败：%s", e)
            raise AIServiceError(str(e))

    # ================= 云端生成（qwen-doc-turbo，可选开关，仅脱敏验证用） =================
    @property
    def _cloud_cfg_path(self) -> Path:
        return self.ppt_dir / "cloud_config.json"

    def _load_cloud(self) -> dict:
        cfg = dict(_CLOUD_DEFAULT)
        if self._cloud_cfg_path.exists():
            try:
                cfg.update(_json.loads(self._cloud_cfg_path.read_text(encoding="utf-8")))
            except Exception:
                pass
        return cfg

    def _save_cloud(self, cfg: dict) -> None:
        self._cloud_cfg_path.write_text(
            _json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")

    def get_cloud_config(self) -> dict:
        cfg = self._load_cloud()
        key = cfg.get("api_key") or ""
        return {"enabled": cfg["enabled"],
                "api_key_masked": ("****" + key[-4:]) if key else "",
                "has_key": bool(key),
                "base_url": cfg["base_url"], "mode": cfg["mode"],
                "template_id": cfg["template_id"]}

    def put_cloud_config(self, body) -> dict:
        cfg = self._load_cloud()
        cfg.update(body.dict())
        if not body.api_key:          # 留空表示不修改已有 Key
            cfg["api_key"] = self._load_cloud().get("api_key", "")
        self._save_cloud(cfg)
        return {"message": "云端生成配置已保存"}

    @staticmethod
    def _outline_to_text(outline: dict) -> str:
        parts = [f"《{outline.get('title', '演示文稿')}》"]
        if outline.get("subtitle"):
            parts.append(outline["subtitle"])
        for i, s in enumerate(outline.get("slides") or [], 1):
            seg = f"第{i}页（{s.get('type')}）：{s.get('title', '')}"
            pts = "；".join(s.get("points") or [])
            if pts:
                seg += "——" + pts
            parts.append(seg)
        return "\n".join(parts)[:8000]

    def generate_cloud(self, body, user: User) -> dict:
        """调用阿里云 qwen-doc-turbo PPT skill 生成 PPTX（内容会出网，仅限脱敏材料）。"""
        import requests as _req

        cfg = self._load_cloud()
        if not cfg["enabled"] or not cfg.get("api_key"):
            raise AppError(400, "云端生成未启用或未配置 API Key，请先在「云生成设置」中配置")
        d = self._get_doc_checked(body.doc_id, user)
        if not d.outline:
            raise NotFoundError("文档不存在或内容为空")

        mode = body.mode or cfg["mode"]
        skill = {"type": "ppt", "mode": mode}
        if mode == "general":
            skill["template_id"] = body.template_id or cfg["template_id"]
        n_pages = len(d.outline.get("slides") or [])

        payload = {
            "model": "qwen-doc-turbo",
            "messages": [
                {"role": "system", "content": "you are a helpful assistant."},
                {"role": "system", "content": self._outline_to_text(d.outline)},
                {"role": "user", "content": f"根据以上大纲生成一个{max(n_pages, 6)}到{n_pages + 4}页的ppt"},
            ],
            "skill": [skill],
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        try:
            resp = _req.post(cfg["base_url"].rstrip("/") + "/chat/completions",
                             headers={"Authorization": f"Bearer {cfg['api_key']}",
                                      "Content-Type": "application/json"},
                             json=payload, stream=True, timeout=(15, 300))
        except Exception as e:
            raise AIServiceError(f"云端接口连接失败：{e}")
        if resp.status_code != 200:
            raise AIServiceError(f"云端接口返回 {resp.status_code}：{resp.text[:300]}")

        # 同 qwen.py：响应头未声明 charset 时 requests 按 ISO-8859-1 解码会产出中文乱码。
        # OpenAI 兼容端点一律 UTF-8，显式声明；不用 apparent_encoding（会把流整体缓冲）。
        resp.encoding = "utf-8"

        content = ""
        try:
            for line in resp.iter_lines(decode_unicode=True):
                if not line or not line.startswith("data:"):
                    continue
                data_str = line[5:].strip()
                if data_str == "[DONE]":
                    break
                try:
                    chunk = _json.loads(data_str)
                    delta = (chunk.get("choices") or [{}])[0].get("delta") or {}
                    if delta.get("content"):
                        content += delta["content"]
                except Exception:
                    continue
        finally:
            resp.close()

        m = re.search(r"https?://[^\s\)\"'>]+\.pptx[^\s\"'>]*", content)
        if not m:
            raise AIServiceError("云端未返回 PPT 下载链接，返回内容：" + content[:200])
        try:
            file_resp = _req.get(m.group(0), timeout=120)
            file_resp.raise_for_status()
            data = file_resp.content
        except Exception as e:
            raise AIServiceError(f"PPT 文件下载失败：{e}")

        fname = f"{uuid.uuid4().hex}.pptx"
        path = self.ppt_dir / "generated" / fname
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        if d.file_path and os.path.exists(d.file_path):
            os.remove(d.file_path)
        d.file_path = str(path)
        d.status = "generated"
        self.documents.update(d)
        return {"message": "云端生成完成（注意：材料已发送至阿里云，请勿用于真实业务数据）",
                "download_url": f"/api/v1/ppt/documents/{d.id}/download"}
