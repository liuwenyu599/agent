"""格式校验应用服务：编排校验流程、记录与规则管理、审校工作台状态机。

审校工作台数据模型（迁移 009 起）：
- ``issues``        —— append-only 问题清单，每条带稳定整数 ``id``（= 生成时的下标）。
                       复检只追加新问题，永不删除/重排老条目。
- ``applied_ids``   —— 用户已「应用」的 issue id；每次复检后重置为 []。
- ``resolved_ids``  —— 经复检确认已修正的 issue id；累计保留。
- ``open_issue_count`` 为派生值：``len(issues) - len(resolved_ids)``，不落库。

原始上传文件 ``{id}.docx`` 只被两类操作改写：
1. 自动修正重放到 ``*_preview.docx`` / ``*_current.docx`` / ``*_fixed.docx``；
2. 工作台中栏的人工正文修改经 ``update_record_content`` 显式保存后直接写回
   ``{id}.docx``（人工修改成为新基线），同时重置 applied/resolved 状态。
"""
import asyncio
import re
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from docx import Document as DocxDocument
from sqlalchemy.orm import Session

from app.application.format_check.check_engine import (
    FormatCheckEngine,
    extract_page_properties,
    extract_paragraph_properties,
)
from app.application.shared.writing_assistant import WritingAssistant
from app.application.knowledge.rag_service import RagService
from app.core.config import settings
from app.core.exceptions import AppError, NotFoundError, PermissionDeniedError
from app.core.llm_json import LLMJsonError, loads_lenient
from app.core.logging import get_logger
from app.domain.format_check.entities import (
    VALID_RULE_TARGETS,
    FormatCheckRecord,
    FormatRule,
)
from app.domain.identity.entities import ADMIN_OR_ABOVE, User
from app.infrastructure.repositories.format_check import (
    SqlAlchemyFormatCheckRecordRepository,
    SqlAlchemyFormatRuleRepository,
    load_id_list,
)

logger = get_logger(__name__)

SUPPORTED_SUFFIXES = ("docx", "txt", "md", "pdf")

# 记录关联的文件后缀（删除记录时一并清理）
_RECORD_FILE_SUFFIXES = ("", "_preview", "_current", "_fixed")

# ---- 规则校验项目录（与 check_engine 实际消费的键一一对应，供 AI 编译与二次校验） ----
_PAGE_KEYS = {
    "top_margin_cm", "bottom_margin_cm", "left_margin_cm", "right_margin_cm",
    "page_width_cm", "page_height_cm",
}
_PARA_KEYS = {
    "font_name", "font_size_pt", "bold", "alignment", "line_spacing_pt",
    "first_line_indent_chars", "right_indent_chars", "space_before_pt", "space_after_pt",
}
_GENERAL_KEYS = {"no_extra_blank_lines", "no_trailing_spaces"}
_CONTENT_KEYS = {"forbidden_words", "sensitive_words", "preferred_terms",
                 "normalize_numeric_dates", "relative_time_notice"}
_PPT_KEYS = {"check_page_count", "check_cover_overflow", "forbidden_fonts", "max_chars_per_slide"}
_NUMERIC_KEYS = _PAGE_KEYS | {
    "font_size_pt", "line_spacing_pt", "first_line_indent_chars", "right_indent_chars",
    "space_before_pt", "space_after_pt",
}
_BOOL_KEYS = {"bold", "no_extra_blank_lines", "no_trailing_spaces"}
_BOOL_KEYS |= {"check_page_count", "check_cover_overflow"}
_BOOL_KEYS |= {"normalize_numeric_dates", "relative_time_notice"}
_ALIGN_VALUES = ("left", "center", "right", "justify")

_TARGET_LABELS = {
    "page": "页面设置", "title": "标题", "body": "正文",
    "heading1": "一级标题", "heading2": "二级标题",
    "signature": "落款", "date": "成文日期", "general": "全文通用", "content": "内容规范",
    "ppt": "PPT 成品",
}
_KEY_LABELS = {
    "top_margin_cm": "上边距", "bottom_margin_cm": "下边距",
    "left_margin_cm": "左边距", "right_margin_cm": "右边距",
    "page_width_cm": "页面宽度", "page_height_cm": "页面高度",
    "font_name": "字体", "font_size_pt": "字号", "bold": "加粗",
    "alignment": "对齐方式", "line_spacing_pt": "行距",
    "first_line_indent_chars": "首行缩进",
    "right_indent_chars": "右侧缩进",
    "space_before_pt": "段前间距", "space_after_pt": "段后间距",
    "no_extra_blank_lines": "不允许多余空行", "no_trailing_spaces": "不允许行尾空格",
    "forbidden_words": "禁用词", "sensitive_words": "敏感词", "preferred_terms": "规范替换词",
    "normalize_numeric_dates": "数字日期规范", "relative_time_notice": "相对时间提示",
    "check_page_count": "检查页数", "check_cover_overflow": "检查封面越界",
    "forbidden_fonts": "禁用字体", "max_chars_per_slide": "每页最多字数",
}
_ALIGN_CN = {"left": "左对齐", "center": "居中", "right": "右对齐", "justify": "两端对齐"}

_CN_FONT_SIZES = {
    # 长名称在前，避免“小二号”先命中“二号”。
    "小初": 36, "小一": 24, "小二": 18, "小三": 15, "小四": 12,
    "小五": 9, "初号": 42, "一号": 26, "二号": 22, "三号": 16,
    "四号": 14, "五号": 10.5,
}


def _checks_from_description(target: str, description: str) -> Dict:
    """从白话里确定性提取常见规则，补齐 35B 偶发漏项。

    AI 仍负责理解整句和复杂表达；这里仅复核用户明确写出的字体、字号、距离、
    对齐等硬数值，作用与写作规划中的字数复核一致。
    """
    text = (description or "").strip()
    checks: Dict = {}
    if not text:
        return checks
    # 否定、范围和更正语句交给 AI 理解，避免把“不要仿宋”“不小于三号”
    # 当成肯定的精确值。程序只补齐无歧义的字面格式。
    if target not in {"content", "ppt", "general"} and any(
        cue in text for cue in ("不要", "不用", "不得", "不使用", "不是", "改为",
                                "不少于", "不小于", "不大于", "不超过", "至少", "最多")
    ):
        return checks

    if target not in {"page", "general", "content", "ppt"}:
        fonts = (
            "方正小标宋简体", "方正小标宋", "小标宋", "仿宋_GB2312",
            "楷体_GB2312", "思源黑体", "微软雅黑", "仿宋", "黑体", "楷体", "宋体",
        )
        font = next((name for name in fonts if name.lower() in text.lower()), None)
        if font:
            checks["font_name"] = font
        size = next((pt for name, pt in _CN_FONT_SIZES.items() if name in text), None)
        if size is None:
            match = re.search(r"(?:字号|字大小|字体大小)[^\d]{0,5}(\d+(?:\.\d+)?)\s*磅", text)
            size = float(match.group(1)) if match else None
        if size is not None:
            checks["font_size_pt"] = size
        if "不加粗" in text or "不粗体" in text:
            checks["bold"] = False
        elif "加粗" in text or "粗体" in text:
            checks["bold"] = True
        for phrase, value in (("两端对齐", "justify"), ("分散对齐", "justify"),
                              ("居中", "center"), ("右对齐", "right"),
                              ("左对齐", "left")):
            if phrase in text:
                checks["alignment"] = value
                break
        numeric_patterns = {
            "line_spacing_pt": r"(?:固定行距|行距(?:固定值)?)[^\d]{0,5}(\d+(?:\.\d+)?)\s*磅",
            "first_line_indent_chars": r"首行缩进[^\d]{0,5}(\d+(?:\.\d+)?)\s*(?:个)?字符",
            "right_indent_chars": r"右(?:侧)?缩进[^\d]{0,5}(\d+(?:\.\d+)?)\s*(?:个)?字符",
            "space_before_pt": r"段前[^\d]{0,5}(\d+(?:\.\d+)?)\s*磅",
            "space_after_pt": r"段后[^\d]{0,5}(\d+(?:\.\d+)?)\s*磅",
        }
        for key, pattern in numeric_patterns.items():
            match = re.search(pattern, text)
            if match:
                checks[key] = float(match.group(1))
    elif target == "page":
        patterns = {
            "top_margin_cm": r"上(?:边距)?[^\d]{0,4}(\d+(?:\.\d+)?)\s*(?:厘米|cm)",
            "bottom_margin_cm": r"下(?:边距)?[^\d]{0,4}(\d+(?:\.\d+)?)\s*(?:厘米|cm)",
            "left_margin_cm": r"左(?:边距)?[^\d]{0,4}(\d+(?:\.\d+)?)\s*(?:厘米|cm)",
            "right_margin_cm": r"右(?:边距)?[^\d]{0,4}(\d+(?:\.\d+)?)\s*(?:厘米|cm)",
            "page_width_cm": r"页(?:面)?宽[^\d]{0,4}(\d+(?:\.\d+)?)\s*(?:厘米|cm)",
            "page_height_cm": r"页(?:面)?高[^\d]{0,4}(\d+(?:\.\d+)?)\s*(?:厘米|cm)",
        }
        for key, pattern in patterns.items():
            match = re.search(pattern, text, re.I)
            if match:
                checks[key] = float(match.group(1))
    elif target == "general":
        if any(cue in text for cue in ("不得有多余空行", "不允许多余空行", "删除多余空行")):
            checks["no_extra_blank_lines"] = True
        if any(cue in text for cue in ("不得有行尾空格", "不允许行尾空格", "删除行尾空格")):
            checks["no_trailing_spaces"] = True
    elif target == "ppt":
        match = re.search(r"每页(?:最多|不超过)[^\d]{0,4}(\d+)\s*字", text)
        if match:
            checks["max_chars_per_slide"] = int(match.group(1))
        if "页数" in text:
            checks["check_page_count"] = True
        if "越界" in text or "超出页面" in text:
            checks["check_cover_overflow"] = True
        match = re.search(r"禁用字体\s*[：:]\s*([^。；;\n]+)", text)
        if match:
            checks["forbidden_fonts"] = [x.strip() for x in re.split(r"[、,，]", match.group(1)) if x.strip()]
    return _sanitize_checks(target, checks)


def _allowed_keys(target: str) -> set:
    if target == "page":
        return set(_PAGE_KEYS)
    if target == "general":
        return set(_GENERAL_KEYS)
    if target == "content":
        return set(_CONTENT_KEYS)
    if target == "ppt":
        return set(_PPT_KEYS)
    return set(_PARA_KEYS)


def _sanitize_checks(target: str, raw) -> Dict:
    """白名单过滤 + 类型收敛：AI 输出的 checks 只保留引擎认识的键。"""
    if not isinstance(raw, dict):
        return {}
    allowed = _allowed_keys(target)
    out: Dict = {}
    for key, value in raw.items():
        if key not in allowed:
            continue
        try:
            if key in _NUMERIC_KEYS:
                out[key] = float(value)
            elif key in _BOOL_KEYS:
                if isinstance(value, str):
                    out[key] = value.strip().lower() in ("1", "true", "yes", "是")
                else:
                    out[key] = bool(value)
            elif key == "alignment":
                v = str(value).strip().lower()
                cn = {"左对齐": "left", "居中": "center", "右对齐": "right",
                      "两端对齐": "justify", "分散对齐": "justify"}
                v = cn.get(str(value).strip(), v)
                if v in _ALIGN_VALUES:
                    out[key] = v
            elif key in ("forbidden_words", "sensitive_words"):
                if isinstance(value, list):
                    out[key] = [str(x).strip() for x in value if str(x).strip()]
                elif isinstance(value, str):
                    out[key] = [x.strip() for x in re.split(r"[,，;；\n]", value) if x.strip()]
            elif key == "forbidden_fonts":
                out[key] = [str(x).strip() for x in value if str(x).strip()] if isinstance(value, list) else []
            elif key == "max_chars_per_slide":
                count = int(value)
                if 20 <= count <= 2000:
                    out[key] = count
            elif key == "preferred_terms":
                if isinstance(value, dict):
                    out[key] = {str(k).strip(): str(v).strip()
                                for k, v in value.items() if str(k).strip() and str(v).strip()}
            else:
                out[key] = str(value).strip()
        except (TypeError, ValueError):
            continue
    return out


def _summarize_checks(checks: Dict) -> List[str]:
    """把 checks 转成给用户看的白话预览行。"""
    lines: List[str] = []
    for key, value in checks.items():
        label = _KEY_LABELS.get(key, key)
        try:
            if key == "alignment":
                text = _ALIGN_CN.get(str(value), str(value))
            elif key == "bold":
                text = "加粗" if value else "不加粗"
            elif key in ("no_extra_blank_lines", "no_trailing_spaces"):
                text = "是" if value else "否"
            elif key.endswith("_pt"):
                text = f"{float(value):g} 磅"
            elif key.endswith("_cm"):
                text = f"{float(value):g} 厘米"
            elif key in ("first_line_indent_chars", "right_indent_chars"):
                text = f"{float(value):g} 字符"
            else:
                text = str(value)
        except (TypeError, ValueError):
            text = str(value)
        lines.append(f"{label}：{text}")
    return lines


def _rule_to_dict(r: FormatRule) -> dict:
    return {
        "id": r.id, "name": r.name, "target": r.target, "checks": r.checks,
        "severity": r.severity, "is_default": r.is_default, "is_active": r.is_active,
        "remark": r.remark,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


def _open_issue_count(record: FormatCheckRecord) -> int:
    """未解决问题数 = 总问题数 - 已解决问题数（接口层派生，不落库）。"""
    issues = record.issues or []
    return max(len(issues) - len(set(load_id_list(record.resolved_ids))), 0)


def _record_brief(r: FormatCheckRecord) -> dict:
    return {
        "id": r.id, "filename": r.filename, "file_type": r.file_type,
        # issue_count 语义保持不变：累计总问题数（列表页与桌面端已消费）
        "issue_count": r.issue_count,
        "rule_issue_count": r.rule_issue_count,
        "ai_issue_count": r.ai_issue_count,
        "open_issue_count": _open_issue_count(r),
        "applied_ids": load_id_list(r.applied_ids),
        "resolved_ids": load_id_list(r.resolved_ids),
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


class FormatCheckService:
    def __init__(self, db: Session, assistant: Optional[WritingAssistant] = None,
                 rag: Optional[RagService] = None) -> None:
        self.db = db
        self.rules = SqlAlchemyFormatRuleRepository(db)
        self.records = SqlAlchemyFormatCheckRecordRepository(db)
        self.engine = FormatCheckEngine(assistant)
        self.rag = rag

    # ---- 校验文件存放（审阅/修正用，docx 保留，其他类型校验后即删） ----
    @property
    def check_dir(self) -> Path:
        d = settings.DATA_DIR / "format-check"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def record_file(self, record_id: str) -> Path:
        return self.check_dir / f"{record_id}.docx"

    # ================= issue id 稳定性（T3） =================
    def _ensure_issue_ids(self, record: FormatCheckRecord) -> bool:
        """存量老记录惰性补 id 并写回。

        - id 规则与新增记录完全一致：``enumerate(issues)`` 的下标（整数）。
        - 同时把 applied_ids / resolved_ids 初始化为 ``[]``（不能留 NULL，
          否则 open_issue_count 计算会 TypeError）。

        :return: 是否发生了写回。
        """
        issues = record.issues or []
        missing_id = any(
            not isinstance(it, dict) or it.get("id") is None for it in issues
        )
        missing_lists = record.applied_ids is None or record.resolved_ids is None
        if not missing_id and not missing_lists:
            return False

        for idx, it in enumerate(issues):
            if isinstance(it, dict):
                it["id"] = idx
        record.issues = issues
        if record.applied_ids is None:
            record.applied_ids = []
        if record.resolved_ids is None:
            record.resolved_ids = []

        logger.info(
            "格式校验记录 %s 缺少 issue id/工作台状态，已惰性补写（issues=%d）",
            record.id, len(issues),
        )
        self.records.update(record)
        return True

    def _load_record(self, record_id: str, user: User) -> FormatCheckRecord:
        """取记录并确保 issue id / 工作台状态可用。"""
        record = self.get_record_checked(record_id, user)
        self._ensure_issue_ids(record)
        return record

    # ================= 校验 =================
    async def check_upload(self, file, user: User, use_ai: bool = True,
                           rule_ids: Optional[str] = None) -> dict:
        filename = file.filename or "unnamed"
        suffix = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
        if suffix not in SUPPORTED_SUFFIXES:
            raise AppError(400, f"暂不支持 .{suffix} 文件的格式校验，请上传 Word(.docx) 文件")

        data = await file.read()
        if len(data) > settings.FORMAT_CHECK_MAX_SIZE:
            raise AppError(400, "文件超过大小限制")
        if not data:
            raise AppError(400, "文件为空")

        ids = [i for i in rule_ids.split(",") if i] if rule_ids else None
        self.rules.ensure_user_defaults(user.id)
        rules = [r for r in self.rules.list_for_check(user.id, ids) if r.target != "ppt"]
        if ids and len({r.id for r in rules}) != len(set(ids)):
            raise PermissionDeniedError("所选规则不存在、已停用或不属于当前用户")
        # 用户可停用全部可配置规则；基础内容检查仍可独立执行。
        ai_only = not rules and use_ai and self.engine.assistant is not None
        rule_dicts = [_rule_to_dict(r) for r in rules]

        tmp_path = self.check_dir / f"{uuid.uuid4().hex}_{filename}"
        await asyncio.to_thread(tmp_path.write_bytes, data)
        try:
            result = await asyncio.to_thread(
                self.engine.check_file, tmp_path, filename, rule_dicts, use_ai)
        except ValueError as e:
            tmp_path.unlink(missing_ok=True)
            raise AppError(400, str(e))
        except Exception as e:
            tmp_path.unlink(missing_ok=True)
            raise AppError(500, f"校验过程出错: {e}")

        issues = result["issues"]

        # ---- 与知识库冲突检查：必须有真实检索证据，AI 不得凭空判冲突 ----
        if result["file_type"] == "docx" and self.rag is not None and self.engine.assistant is not None:
            try:
                def read_text():
                    doc = DocxDocument(str(tmp_path))
                    return "\n".join(p.text.strip() for p in doc.paragraphs if p.text.strip())

                full_text = await asyncio.to_thread(read_text)
            except Exception as e:
                logger.warning("内容读取失败，已跳过证据核验: %s", e)
                full_text = ""
            if full_text:
                for check, label in ((self._knowledge_conflict_issues, "知识库冲突"),
                                     (self._law_citation_issues, "法条引文")):
                    try:
                        issues.extend(await asyncio.to_thread(check, full_text, user))
                    except Exception as e:
                        logger.warning("%s校验失败，已跳过: %s", label, e)

        # 注入稳定整数 id（= 下标）。不用 uuid：复检后必须能与老条目对齐。
        for idx, issue in enumerate(issues):
            if isinstance(issue, dict):
                issue["id"] = idx

        record = self.records.add(FormatCheckRecord(
            user_id=user.id, filename=filename, file_type=result["file_type"],
            # B5'：快照必须带 severity，否则复检新增的问题会一律降级/升级为 error
            rule_snapshot=[{"id": r["id"], "name": r["name"], "target": r["target"],
                            "checks": r["checks"],
                            "severity": r.get("severity") or "error"}
                           for r in rule_dicts],
            issues=issues, issue_count=len(issues),
            rule_issue_count=len([i for i in issues if i["source"] == "rule"]),
            ai_issue_count=len([i for i in issues if i["source"] == "ai"]),
            applied_ids=[], resolved_ids=[],
        ))

        # docx 保留源文件（以记录ID命名），供审阅模式与自动修正使用；其他类型删除
        if result["file_type"] == "docx":
            tmp_path.replace(self.record_file(record.id))
        else:
            tmp_path.unlink(missing_ok=True)

        return {
            # 同一资源的 id 字段名统一：`id` 与 `record_id` 同值（为兼容两种客户端），
            # 与 GET /format-check/records 列表项的 `id` 对齐。
            "id": record.id,
            "record_id": record.id,
            "filename": filename,
            "file_type": result["file_type"],
            "ai_used": result["ai_used"],
            "check_mode": "ai_only" if ai_only else ("hybrid" if result.get("ai_used") else "rule"),
            # issue_count 语义保持不变：累计总问题数
            "issue_count": len(issues),
            "open_issue_count": len(issues),
            "applied_ids": [],
            "resolved_ids": [],
            "issues": issues,
            "rules_used": [{"id": r["id"], "name": r["name"], "target": r["target"]}
                           for r in rule_dicts],
        }

    def _knowledge_conflict_issues(self, text: str, user: User) -> List[dict]:
        """用当前用户可访问知识库核对正文事实/口径。

        只允许基于 RagService 的真实命中判定；每条冲突都绑定知识库、文档、chunk，
        没有证据索引或证据无法映射时直接丢弃。
        """
        if not text.strip() or self.rag is None or self.engine.assistant is None:
            return []

        query = text[:1800]
        hits = self.rag.search(query=query, user_id=user.id, top_k=8)
        if not hits:
            return []

        evidence_lines = []
        for idx, h in enumerate(hits, start=1):
            evidence_lines.append(
                f"[{idx}] 知识库={h.get('kb_name') or ''}；"
                f"文档={h.get('doc_title') or h.get('source') or ''}；"
                f"段落={h.get('chunk_index')}; 原文={h.get('chunk_content') or h.get('content') or ''}"
            )
        evidence = "\n".join(evidence_lines)

        prompt = f"""你是司法行政公文内容一致性审校助手。
请把【待审正文】与【知识库证据】逐项比较，只报告有明确原文证据支持的冲突或口径不一致。

规则：
1. 不要用你的常识判断，只能依据给出的知识库证据。
2. 若正文只是知识库没有提到，不算冲突。
3. 若知识库证据之间互相矛盾，不要替用户裁决，提示“知识库内部口径不一致”。
4. 每条必须给 evidence_index，对应下面 [1]...[N] 中的一条；没有证据索引的不要输出。
5. current 必须摘录正文中可定位的短语或句子，不要编造。
6. expected 写知识库证据表达的口径；suggestion 给出保守修改建议。
7. 没有明确冲突返回 []。

【待审正文】
{text[:settings.FORMAT_CHECK_AI_BUDGET]}

【知识库证据】
{evidence}

只输出 JSON 数组：
[{{"current":"正文原句","expected":"知识库口径","suggestion":"建议","evidence_index":1}}]"""
        try:
            reply = self.engine.assistant.complete(
                [
                    {"role": "system", "content": "你只做有证据的知识库一致性核对，只输出 JSON。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.0,
                max_tokens=1200,
            )
            if not reply:
                return []
            items = loads_lenient(reply)
            if not isinstance(items, list):
                return []
        except Exception as e:
            logger.warning("知识库冲突 AI 判定失败: %s", e)
            return []

        result: List[dict] = []
        for it in items[:12]:
            if not isinstance(it, dict):
                continue
            try:
                evidence_index = int(it.get("evidence_index"))
            except (TypeError, ValueError):
                continue
            if evidence_index < 1 or evidence_index > len(hits):
                continue
            hit = hits[evidence_index - 1]
            current = str(it.get("current") or "").strip()
            if not current or current not in text:
                continue

            paragraph_index = None
            for idx, line in enumerate(text.splitlines()):
                if current in line:
                    paragraph_index = idx
                    break

            doc_title = hit.get("doc_title") or hit.get("source") or "知识库文档"
            kb_name = hit.get("kb_name") or "知识库"
            chunk_index = hit.get("chunk_index")
            result.append({
                "location": f"第{paragraph_index + 1}段" if paragraph_index is not None else "全文",
                "element": "知识库口径冲突",
                "current": current,
                "expected": str(it.get("expected") or "").strip(),
                "suggestion": str(it.get("suggestion") or "").strip(),
                "source": "knowledge",
                "severity": "warning",
                "paragraph_index": paragraph_index,
                "fix_hint": None,
                "evidence": {
                    "kb_id": hit.get("kb_id"),
                    "kb_name": kb_name,
                    "kb_type": hit.get("kb_type"),
                    "doc_id": hit.get("doc_id"),
                    "doc_title": doc_title,
                    "chunk_id": hit.get("chunk_id"),
                    "chunk_index": chunk_index,
                    "excerpt": hit.get("chunk_content") or hit.get("content") or "",
                },
            })
        return result

    def _law_citation_issues(self, text: str, user: User) -> List[dict]:
        """Check explicit article citations against curated authoritative law chunks.

        No retrieved authoritative article means no legal conclusion. The model
        may only identify a conflict between the supplied draft sentence and a
        verbatim span of the matched article.
        """
        if not text.strip() or self.rag is None or self.engine.assistant is None:
            return []
        pattern = re.compile(
            r"《(?P<title>[^》\n]{2,50})》\s*第(?P<article>[一二三四五六七八九十百千零〇\d]+)条")
        evidence = []
        for match in list(pattern.finditer(text))[:6]:
            title, article = match.group("title"), match.group("article")
            try:
                hits = self.rag.search(query=f"{title} 第{article}条", user_id=user.id, top_k=8)
            except Exception as exc:
                logger.warning("法条检索失败: %s", exc)
                continue
            hit = next((h for h in hits
                        if h.get("authoritative") and h.get("doc_type") == "法规"
                        and title in str(h.get("doc_title") or "")
                        and f"第{article}条" in str(h.get("chunk_content") or "")), None)
            if hit is None:
                continue
            line = text.rfind("\n", 0, match.start()) + 1
            end = text.find("\n", match.end())
            sentence = text[line:end if end >= 0 else len(text)].strip()[:300]
            evidence.append((sentence, hit, text[:line].count("\n")))
        if not evidence:
            return []
        brief = "\n".join(
            f"[{i}] 待审={sentence}\n权威法条={hit.get('chunk_content') or ''}"
            for i, (sentence, hit, _) in enumerate(evidence, 1))
        prompt = (
            "逐项核对待审句子引用的法条编号与内容。只能依据给出的权威法条，"
            "不要凭记忆补充法规；无法确定则不报。只输出 JSON 数组。"
            "每项包含 evidence_index、current（待审句中原文）、"
            "expected（权威法条中连续的原文片段）、reason。无问题输出 []。\n" + brief)
        try:
            raw = self.engine.assistant.complete(
                [{"role": "system", "content": "你是严谨的法条引文核对员，只输出 JSON。"},
                 {"role": "user", "content": prompt}],
                temperature=0.0, max_tokens=1000)
            items = loads_lenient(raw or "[]")
        except Exception as exc:
            logger.warning("法条一致性判定失败: %s", exc)
            return []
        if not isinstance(items, list):
            return []
        issues = []
        for item in items[:8]:
            if not isinstance(item, dict):
                continue
            try:
                index = int(item.get("evidence_index")) - 1
            except (TypeError, ValueError):
                continue
            if index < 0 or index >= len(evidence):
                continue
            sentence, hit, paragraph_index = evidence[index]
            current = str(item.get("current") or "").strip()
            expected = str(item.get("expected") or "").strip()
            original = str(hit.get("chunk_content") or "")
            if not current or current not in sentence or not expected or expected not in original:
                continue
            issues.append({
                "location": f"第{paragraph_index + 1}段", "element": "法条引文不一致",
                "current": current, "expected": expected,
                "suggestion": str(item.get("reason") or "请依据权威法条核对并修改。"),
                "source": "law", "severity": "error", "paragraph_index": paragraph_index,
                "fix_hint": None,
                "evidence": {"kb_id": hit.get("kb_id"), "doc_id": hit.get("doc_id"),
                             "doc_title": hit.get("doc_title"), "chunk_id": hit.get("chunk_id"),
                             "chunk_index": hit.get("chunk_index"), "excerpt": original},
            })
        return issues

    # ================= 记录 =================
    def list_records(self, user: User, page: int, page_size: int) -> dict:
        records, total = self.records.list_by_user(user.id, page, page_size)
        return {
            "total": total, "page": page, "page_size": page_size,
            "data": [_record_brief(r) for r in records],
        }

    def get_record_checked(self, record_id: str, user: User) -> FormatCheckRecord:
        record = self.records.get(record_id)
        if not record:
            raise NotFoundError("Record not found")
        if record.user_id != user.id and user.role not in ADMIN_OR_ABOVE:
            raise PermissionDeniedError("No permission")
        return record

    def get_record(self, record_id: str, user: User) -> dict:
        record = self._load_record(record_id, user)
        return {
            "id": record.id, "filename": record.filename, "file_type": record.file_type,
            "issues": record.issues, "issue_count": record.issue_count,
            "open_issue_count": _open_issue_count(record),
            "applied_ids": load_id_list(record.applied_ids),
            "resolved_ids": load_id_list(record.resolved_ids),
            "rule_snapshot": record.rule_snapshot,
            "created_at": record.created_at.isoformat() if record.created_at else None,
        }

    def delete_record(self, record_id: str, user: User) -> dict:
        """删除记录及其关联的全部文件（原始稿/预览稿/当前稿/修正稿）。

        单个文件删除失败（Windows 上被 Word / 杀毒软件占用很常见）只记 warning，
        不阻断记录删除——否则用户永远删不掉一条「文件被占用」的记录。
        """
        record = self.get_record_checked(record_id, user)
        removed: List[str] = []
        failed: List[str] = []
        for suffix in _RECORD_FILE_SUFFIXES:
            path = self.check_dir / f"{record.id}{suffix}.docx"
            if not path.exists():
                continue
            try:
                path.unlink()
                removed.append(path.name)
            except Exception as e:  # noqa: BLE001 - 文件清理失败绝不能阻断记录删除
                logger.warning("删除记录 %s 的关联文件 %s 失败（已忽略）: %s: %s",
                               record.id, path.name, type(e).__name__, e)
                failed.append(path.name)
        self.records.delete(record)
        logger.info("删除格式校验记录 %s，清理文件: %s", record.id, removed or "无")
        return {"id": record_id, "message": "记录已删除",
                "removed_files": removed, "failed_files": failed}

    # ================= 审阅模式 =================
    def _get_record_docx(self, record: FormatCheckRecord) -> Path:
        if record.file_type != "docx":
            raise AppError(400, "仅 Word(.docx) 文件支持审阅与自动修正")
        path = self.record_file(record.id)
        if not path.exists():
            raise AppError(410, "源文件已过期，请重新上传校验")
        return path

    @staticmethod
    def _read_doc_properties(path: Path) -> dict:
        """读取文档的段落排版属性 + 页面属性。"""
        doc = DocxDocument(str(path))
        return {
            "paragraphs": extract_paragraph_properties(doc),
            "page": extract_page_properties(doc),
        }

    def _build_current_doc(self, record: FormatCheckRecord,
                           applied: Optional[List[int]] = None) -> Path:
        """按已应用的 issue 从**原始文件**重放出「当前」文档。

        原始文件只读（人工修改经 update_record_content 显式写回后即为新基线），
        结果写到 ``{id}_current.docx``。
        """
        src = self._get_record_docx(record)
        applied = load_id_list(applied if applied is not None else record.applied_ids)
        if not applied:
            return src
        out_path = self.check_dir / f"{record.id}_current.docx"
        self.engine.apply_fixes(src, record.issues or [], applied, out_path)
        return out_path

    def get_record_paragraphs(self, record_id: str, user: User,
                              version: str = "current") -> dict:
        """段落排版属性快照。

        :param version: ``original`` 读原始文件；``current`` 读已应用修正后的重放稿
                        （无已应用项时与 original 完全一致）。
        """
        record = self._load_record(record_id, user)
        if version == "original":
            path = self._get_record_docx(record)
        else:
            path = self._build_current_doc(record)
        data = self._read_doc_properties(path)
        data["version"] = version
        return data

    def update_record_content(self, record_id: str, paragraphs: List[str],
                              user: User, formatting: Optional[dict] = None) -> dict:
        """保存工作台中栏的人工正文修改。

        语义：人工修改直接写回 ``{id}.docx``，成为后续校验 / 应用修正 / 导出的
        新基线（修改前视图也随之指向新内容——审校工作台以「当前可交付稿」为中心，
        历史原文以用户本地文件为准）。保存后 applied_ids / resolved_ids 全部重置，
        因为旧标记相对新文本已不再有意义；客户端随后应触发重新校验。
        段落级排版格式尽量保留：逐段替换首个 run 文本，多余段删除、不足段追加。
        """
        record = self._load_record(record_id, user)
        path = self._get_record_docx(record)
        texts = [str(t) for t in (paragraphs or [])]
        if not any(t.strip() for t in texts):
            raise AppError(400, "正文不能为空")

        doc = DocxDocument(str(path))
        from app.application.documents.formatting import normalize_formatting
        from app.application.chat.docx_export import _apply_user_format
        validated = normalize_formatting("\n".join(texts), {"paragraphs": formatting or {}})
        paragraph_styles = validated["paragraphs"]
        paras = list(doc.paragraphs)
        for i, text in enumerate(texts):
            if i < len(paras):
                p = paras[i]
                if p.text != text:
                    font_name = p.runs[0].font.name if p.runs else None
                    font_size = p.runs[0].font.size if p.runs else None
                    p.clear()
                    for part in re.split(r"(\*\*.+?\*\*)", text):
                        if not part:
                            continue
                        bold = part.startswith("**") and part.endswith("**")
                        run = p.add_run(part[2:-2] if bold else part)
                        run.bold = bold
                        if font_name:
                            run.font.name = font_name
                        if font_size:
                            run.font.size = font_size
            else:
                p = doc.add_paragraph(text)
            _apply_user_format(p, paragraph_styles.get(str(i)))
        for p in paras[len(texts):]:
            try:
                p._p.getparent().remove(p._p)
            except Exception as e:  # noqa: BLE001 - 个别段删除失败不阻断整体保存
                logger.warning("记录 %s 删除多余段落失败（已跳过）: %s", record.id, e)
        doc.save(str(path))

        record.applied_ids = []
        record.resolved_ids = []
        self.records.update(record)
        props = self._read_doc_properties(path)
        logger.info("记录 %s 正文被手工修改（%d 段），应用/解决状态已重置",
                    record.id, len(texts))
        return {
            "id": record.id, "record_id": record.id,
            "applied_ids": [], "resolved_ids": [],
            "issue_count": record.issue_count,
            "open_issue_count": _open_issue_count(record),
            "paragraphs": props["paragraphs"],
            "page": props["page"],
            "message": "正文修改已保存，建议重新校验",
        }

    def preview_fix(self, record_id: str, accepted_indices: Optional[List[int]],
                    user: User) -> dict:
        record = self._load_record(record_id, user)
        if accepted_indices is None:
            accepted_indices = load_id_list(record.applied_ids)
        path = self._get_record_docx(record)
        out_path = self.check_dir / f"{record.id}_preview.docx"
        self.engine.apply_fixes(path, record.issues or [], accepted_indices, out_path)
        data = self._read_doc_properties(out_path)
        data["version"] = "preview"
        return data

    def fix_document(self, record_id: str, accepted_indices: Optional[List[int]],
                     user: User) -> Tuple[Path, str]:
        """生成修正稿。返回 (文件路径, 下载文件名)。

        accepted_indices 为 None 时使用持久化的 applied_ids，
        否则桌面端点「导出修正稿」会导出一份空修正。
        """
        record = self._load_record(record_id, user)
        if accepted_indices is None:
            accepted_indices = load_id_list(record.applied_ids)
        path = self._get_record_docx(record)
        out_path = self.check_dir / f"{record.id}_fixed.docx"
        self.engine.apply_fixes(path, record.issues or [], accepted_indices, out_path)
        return out_path, f"修正稿_{record.filename}"

    # ================= 工作台状态机（T6） =================
    @staticmethod
    def _issue_ids(issues: List[Dict]) -> List[int]:
        return [i.get("id") for i in issues
                if isinstance(i, dict) and i.get("id") is not None]

    def _workbench_payload(self, record: FormatCheckRecord) -> dict:
        """apply / undo 的统一响应体（不含 issues：这两个接口不改变 issues）。"""
        applied = load_id_list(record.applied_ids)
        resolved = load_id_list(record.resolved_ids)
        current = self._build_current_doc(record, applied)
        props = self._read_doc_properties(current)
        return {
            "id": record.id,
            "record_id": record.id,
            "applied_ids": applied,
            "resolved_ids": resolved,
            "issue_count": record.issue_count,
            "open_issue_count": _open_issue_count(record),
            "paragraphs": props["paragraphs"],
            "page": props["page"],
        }

    def apply_issue(self, record_id: str, issue_id: int, user: User) -> dict:
        """应用单条修正。未知 issue_id → 400 且不写库。"""
        try:
            issue_id = int(issue_id)
        except (TypeError, ValueError):
            raise AppError(400, "issue_id 必须是整数")
        record = self._load_record(record_id, user)
        known = set(self._issue_ids(record.issues or []))
        if issue_id not in known:
            # 必须拦截：否则垃圾 id 会被持久化，之后每次重放都带着它
            # detail 会原文展示给终端用户，因此用中文业务话术（id 仅供参考/排障）
            raise AppError(400, f"问题项不存在或已被处理（issue_id={issue_id}）")

        applied = sorted(set(load_id_list(record.applied_ids)) | {issue_id})
        record.applied_ids = applied
        self.records.update(record)
        return self._workbench_payload(record)

    def undo_issue(self, record_id: str, issue_id: int, user: User) -> dict:
        """撤销单条修正。未知 issue_id → 200 空操作（移除不存在元素本就是 no-op）。

        撤销 = 回到「未处理」：同时从 resolved_ids 里摘掉，否则会出现
        「界面显示已修正 ✓，但文档里修正已被撤掉」的自相矛盾状态。
        """
        try:
            issue_id = int(issue_id)
        except (TypeError, ValueError):
            issue_id = -1
        record = self._load_record(record_id, user)
        applied = [i for i in load_id_list(record.applied_ids) if i != issue_id]
        resolved = [i for i in load_id_list(record.resolved_ids) if i != issue_id]
        record.applied_ids = applied
        record.resolved_ids = resolved
        self.records.update(record)
        return self._workbench_payload(record)

    def recheck(self, record_id: str, user: User) -> dict:
        """对「当前（已应用修正后）」的文档重跑规则检查，结果收敛回同一条记录。

        要点：
        - 规则、确定性内容检查、AI 内容审校、知识库一致性检查全部重跑；
        - issues 是 append-only：老条目 id/下标永不变，只追加新问题；
          「已修正」由 resolved_ids 表达。
        - 段落位移补偿：应用过 ``delete_paragraph`` 后后续段落下标会前移，
          匹配键用 ``paragraph_index - offset(p)``。
        - 复检后 applied_ids **保留**已写入当前稿的修正（含本次确认已解决的），
          resolved_ids 累计保留。

        applied_ids 不能重置为 []：当前稿是由「原始文件 + applied_ids」实时重放
        出来的，一旦清空，已应用的修正会全部消失——表现为「点了重新校验，刚才改的
        全没了，导出修正稿也是原文」。因此语义固定为：
        ``applied_ids`` = 已写入当前稿的修正；``resolved_ids`` = 复检确认已生效的修正。
        """
        record = self._load_record(record_id, user)
        issues: List[Dict] = list(record.issues or [])
        applied = load_id_list(record.applied_ids)
        resolved = set(load_id_list(record.resolved_ids))

        applied_issues = [issues[i] for i in applied
                          if isinstance(i, int) and 0 <= i < len(issues)
                          and isinstance(issues[i], dict)]
        # 被删除的段落（原始下标），用于位移补偿
        deleted_idx = sorted({
            it["paragraph_index"] for it in applied_issues
            if (it.get("fix_hint") or {}).get("type") == "delete_paragraph"
            and it.get("paragraph_index") is not None
        })

        def offset(p: int) -> int:
            """原始下标 p 之前被删除的段落数。"""
            return sum(1 for d in deleted_idx if d < p)

        def match_key(it: Dict, mapped_index: Optional[int]) -> Tuple:
            hint = it.get("fix_hint") or {}
            if hint:
                value = hint.get("value")
                return ("fix", mapped_index, it.get("element"), hint.get("type"),
                        hint.get("field"), str(value) if value is not None else None,
                        str(hint.get("old") or ""), str(hint.get("new") or ""))
            # AI / 知识库 / 仅提示类问题没有 fix_hint，用来源 + 问题项 + 当前原文定位。
            current = str(it.get("current") or "").strip()[:120]
            return ("review", mapped_index, it.get("source"), it.get("element"), current)

        # 老问题：把原始下标换算到当前文档坐标系；AI/知识库问题也参与解决判定。
        old_keys: Dict[Tuple, int] = {}
        for it in issues:
            if not isinstance(it, dict):
                continue
            p = it.get("paragraph_index")
            mapped = (p - offset(p)) if p is not None else None
            old_keys.setdefault(match_key(it, mapped), it.get("id"))

        # 复检使用当前个人规则：新增、编辑、停用立即生效。快照仅用于保留
        # 本次实际执行的规则，不能让旧快照屏蔽后来新增或修改的检查项。
        self.rules.ensure_user_defaults(user.id)
        rules = [_rule_to_dict(r) for r in self.rules.list_for_check(user.id, None)
                 if r.target != "ppt"]
        record.rule_snapshot = rules

        doc_path = self._build_current_doc(record, applied)
        result = self.engine.check_file(doc_path, record.filename, rules, use_ai=True)
        new_issues: List[Dict] = result.get("issues", [])
        if self.rag is not None and self.engine.assistant is not None:
            try:
                doc = DocxDocument(str(doc_path))
                full_text = "\n".join(p.text.strip() for p in doc.paragraphs if p.text.strip())
                new_issues.extend(self._knowledge_conflict_issues(full_text, user))
            except Exception as e:
                logger.warning("复检时知识库冲突检查失败，已跳过: %s", e)
        new_keys = {match_key(it, it.get("paragraph_index"))
                    for it in new_issues if isinstance(it, dict)}

        # 老问题若在复检结果中消失 → 标记已解决
        for key, issue_id in old_keys.items():
            if key not in new_keys and issue_id is not None:
                resolved.add(int(issue_id))

        # 新问题才追加，id 从 len(issues) 继续；老条目 id 永不变
        next_id = len(issues)
        added: List[Dict] = []
        for it in new_issues:
            if not isinstance(it, dict):
                continue
            if match_key(it, it.get("paragraph_index")) in old_keys:
                continue
            item = dict(it)
            item["id"] = next_id
            next_id += 1
            added.append(item)
        if added:
            issues = issues + added

        record.issues = issues
        record.issue_count = len(issues)
        record.rule_issue_count = len(
            [i for i in issues if isinstance(i, dict) and i.get("source") == "rule"])
        record.ai_issue_count = len(
            [i for i in issues if isinstance(i, dict) and i.get("source") == "ai"])
        # 已应用的修正必须留在 applied_ids 里：当前稿靠它从原始文件重放，
        # 清空会让「复检确认过的修改」连同「导出修正稿」一起退回原文。
        record.applied_ids = sorted(set(applied) | resolved)
        record.resolved_ids = sorted(resolved)
        self.records.update(record)

        logger.info(
            "记录 %s 复检完成：新增 %d 条，累计已解决 %d 条，保留已应用修正 %d 条",
            record.id, len(added), len(record.resolved_ids), len(record.applied_ids),
        )
        return {
            "id": record.id, "record_id": record.id,
            "filename": record.filename, "file_type": record.file_type,
            "check_mode": ("ai_only" if not rules
                           else ("hybrid" if result.get("ai_used") else "rule")),
            "ai_used": result.get("ai_used", False),
            "issue_count": len(issues),
            "open_issue_count": _open_issue_count(record),
            "applied_ids": record.applied_ids,
            "resolved_ids": record.resolved_ids,
            "added_count": len(added),
            "issues": issues,
            "rules_used": [{"id": r.get("id"), "name": r.get("name"),
                            "target": r.get("target")} for r in rules],
        }

    # ================= 规则管理 =================
    def list_rules(self, user: User) -> List[dict]:
        self.rules.ensure_user_defaults(user.id)
        return [_rule_to_dict(r) for r in self.rules.list_by_user(user.id)]

    def compile_rule(self, req, user: User) -> dict:
        """白话描述 → AI 生成校验项（不落库）。

        管理员和普通用户都只写自然语言；AI 输出先经白名单过滤
        （只保留 check_engine 认识的键、类型收敛），再交给前端预览确认。
        保存时只操作当前用户自己的规则。
        """
        target = (req.target or "").strip()
        if target not in VALID_RULE_TARGETS:
            raise AppError(400, f"target 必须是: {', '.join(VALID_RULE_TARGETS)}")
        description = (req.description or "").strip()
        if not description:
            raise AppError(400, "请先填写校验要求描述")

        label = _TARGET_LABELS.get(target, target)
        if target == "page":
            catalog = (
                "- top_margin_cm / bottom_margin_cm / left_margin_cm / right_margin_cm："
                "页边距，单位厘米（数值）\n"
                "- page_width_cm / page_height_cm：页面尺寸，单位厘米（数值）"
            )
        elif target == "general":
            catalog = (
                "- no_extra_blank_lines：不允许出现连续多余空行（true/false）\n"
                "- no_trailing_spaces：不允许段落末尾有多余空格（true/false）"
            )
        elif target == "content":
            catalog = (
                "- forbidden_words：禁用词数组，如 [\"严禁出现词\"]\n"
                "- sensitive_words：敏感词数组，如 [\"需核实词\"]\n"
                "- preferred_terms：不规范表达到规范表达的对象，如 {\"截止目前\": \"截至目前\"}"
                "\n- normalize_numeric_dates：提示数字日期写法（true/false）"
                "\n- relative_time_notice：提示相对时间（true/false）"
            )
        elif target == "ppt":
            catalog = (
                "- check_page_count：页数与已确认大纲一致（true/false）\n"
                "- check_cover_overflow：封面元素不越界（true/false）\n"
                "- forbidden_fonts：中文禁用字体数组，如 [\"DejaVu\"]\n"
                "- max_chars_per_slide：每页最大文字数（20-2000 的整数）"
            )
        else:
            catalog = (
                "- font_name：中文字体名（字符串，如 仿宋_GB2312、黑体、方正小标宋简体）\n"
                "- font_size_pt：字号，单位磅（数值；一号=26，小一=24，二号=22，小二=18，"
                "三号=16，小三=15，四号=14，小四=12）\n"
                "- bold：是否加粗（true/false）\n"
                "- alignment：对齐方式（left/center/right/justify，两端对齐用 justify）\n"
                "- line_spacing_pt：固定行距，单位磅（数值，如 28）\n"
                "- first_line_indent_chars：首行缩进字符数（数值，如 2）\n"
                "- right_indent_chars：右侧缩进字符数（数值，如 4）\n"
                "- space_before_pt / space_after_pt：段前/段后间距，单位磅（数值）"
            )

        prompt = f"""你是公文格式规则配置助手。用户用自然语言描述了对「{label}」的格式要求，
请转换成系统支持的校验项。

系统对「{label}」支持的校验项（只允许使用这些键，不要发明其他键）：
{catalog}

用户描述：{description}

要求：
1. 只输出一个 JSON 对象，格式为 {{"name": "简短规则名称", "checks": {{...}}, "unsupported": ["当前对象无法执行的具体要求"]}}，不要输出任何解释。
2. checks 的键只能来自上面列出的校验项；值类型按说明（数值不带单位）。
3. 逐项覆盖用户描述，无法映射的要求必须列入 unsupported，不能静默忽略。
4. 若描述同时涉及其他对象（例如选了正文，却描述页边距），把这些要求列入 unsupported，并说明应选择的校验对象。"""
        deterministic = _checks_from_description(target, description)
        parsed: Dict = {}
        if self.engine.assistant is not None:
            try:
                reply = self.engine.assistant.complete(
                    [{"role": "system", "content": "你是严谨的公文格式规则配置助手，只输出 JSON。"},
                     {"role": "user", "content": prompt}],
                    temperature=0.1, max_tokens=1024,
                )
                parsed_value = loads_lenient(reply) if reply else {}
                if isinstance(parsed_value, dict):
                    parsed = parsed_value
            except Exception as e:
                # 明确的硬格式仍可由程序识别；只有两条路径都失败才向用户报错。
                logger.warning("规则校验项 AI 生成失败，尝试使用明确格式项: %s", e)
        checks = _sanitize_checks(target, parsed.get("checks"))
        for key, value in deterministic.items():
            # AI 可能把用户说的“仿宋”规范成“仿宋_GB2312”；两者同族时保留
            # 更具体的名称。数值和布尔硬约束仍以用户原话为准。
            if (key == "font_name" and checks.get(key)
                    and str(value) in str(checks[key])):
                continue
            checks[key] = value
        if not checks:
            raise AppError(
                400,
                "未能从描述中识别出可执行的校验项。请描述具体的排版要求，"
                "例如「正文用仿宋三号字，首行缩进2字符，行距固定28磅，两端对齐」。",
            )
        name = (req.name or "").strip() or str(parsed.get("name") or "").strip()
        if not name:
            name = f"{label}格式规则"
        unsupported = parsed.get("unsupported") or []
        if not isinstance(unsupported, list):
            unsupported = []
        warnings = [str(item).strip()[:200] for item in unsupported[:10]
                    if isinstance(item, str) and item.strip()]
        raw_checks = parsed.get("checks") or {}
        if isinstance(raw_checks, dict) and set(raw_checks) - _allowed_keys(target):
            warnings.append("部分要求超出当前校验对象支持的范围，请拆分到对应对象后设置。")
        return {
            "name": name,
            "target": target,
            "checks": checks,
            "severity": "error",
            "summary": _summarize_checks(checks),
            "warnings": warnings,
            "recognition": "ai+literal" if parsed and deterministic else
                           ("ai" if parsed else "literal"),
        }

    def create_rule(self, req, user: User) -> dict:
        if req.target not in VALID_RULE_TARGETS:
            raise AppError(400, f"target 必须是: {', '.join(VALID_RULE_TARGETS)}")
        checks = _sanitize_checks(req.target, req.checks)
        if not checks:
            # 与 AI 编译路径同一道闸：存进去一条空规则，界面上会显示「规则已保存」
            # 但校验永远查不出问题，用户无从判断是规则没生效还是文档本来就合规。
            raise AppError(400, "没有可执行的校验项，请填写校验项 JSON 或用 AI 生成")
        rule = self.rules.add(FormatRule(
            name=req.name, target=req.target, checks=checks,
            severity="error" if req.target == "ppt" else req.severity, is_default=False,
            is_active=req.is_active, remark=req.remark, created_by=user.id,
        ))
        return {"id": rule.id, "message": "规则已创建"}

    def update_rule(self, rule_id: str, req, user: User) -> dict:
        if req.target not in VALID_RULE_TARGETS:
            raise AppError(400, f"target 必须是: {', '.join(VALID_RULE_TARGETS)}")
        rule = self.rules.get_owned(rule_id, user.id)
        if not rule:
            raise NotFoundError("Rule not found")
        if rule.is_default:
            raise AppError(400, "系统预置规则只能启用或停用；如需修改，请先复制为个人规则")
        checks = _sanitize_checks(req.target, req.checks)
        if not checks:
            raise AppError(400, "没有可执行的校验项，请填写校验项 JSON 或用 AI 生成")
        rule.name = req.name
        rule.target = req.target
        rule.checks = checks
        rule.severity = "error" if req.target == "ppt" else req.severity
        rule.is_default = False
        rule.is_active = req.is_active
        rule.remark = req.remark
        self.rules.update(rule)
        return {"message": "规则已更新"}

    def set_rule_active(self, rule_id: str, is_active: bool, user: User) -> dict:
        rule = self.rules.get_owned(rule_id, user.id)
        if not rule:
            raise NotFoundError("Rule not found")
        rule.is_active = is_active
        self.rules.update(rule)
        return _rule_to_dict(rule)

    def delete_rule(self, rule_id: str, user: User) -> dict:
        rule = self.rules.get_owned(rule_id, user.id)
        if not rule:
            raise NotFoundError("Rule not found")
        if rule.is_default:
            raise AppError(400, "系统预置规则不可删除，请停用")
        self.rules.hard_delete(rule)
        return {"message": "规则已删除"}
