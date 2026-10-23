"""写作任务服务：Writing Task 全生命周期。

核心原则：
- 任务上下文结构化，识别不出的字段为 None，绝不虚构；
- 文号默认关闭；成文日期由程序接管，用户指定日期优先，否则使用系统当天；
- revise 是"对当前文档的修改"，明确告知模型不得重新起草、不得改变事实；
- 每次 AI 修改自动形成版本（复用 documents 版本快照）；
- 所有查询按 user_id 隔离；
- 起草支持流式（draft_stream）：模型边生成边推给前端，完成后落库与非流式一致。
- 未产生实际改动时如实告知，不声称"已修改"、不生成新版本。
- 提纲式退化兜底：起草落库前检测，只给骨架的自动重写一次，不把「此处略去」
  式占位稿交给用户（提示词是软约束，检测+重写是结构性防线）。
"""
from app.core.timeutil import now_local
import json
import logging
import re
import zlib
from datetime import datetime
from typing import Any, Dict, Iterator, List, Optional

from fastapi import HTTPException
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.application.writing import task_parser
from app.core.config import settings
from app.infrastructure.database.models.knowledge import DocumentModel

logger = logging.getLogger(__name__)

# 快捷操作 -> 修改模式说明（与"当前文档 revision"逻辑绑定）
REVISE_MODES = {
    "expand": "扩写：增加事实性展开、工作过程、成效、问题与措施，不改变已有事实",
    "polish": "润色：保持信息和结构基本不变，只优化语言",
    "condense": "精简：保留核心事实和结论，减少冗余",
    "normalize": "规范化：调整为司法行政机关正式材料语言",
    "complete": "补充结构：判断当前文档缺少哪些必要部分并补充",
    "rewrite": "改写：按用户要求重写",
    "revise": "修改：按用户指令修改",
}

# ---- 兜底回复措辞变体（供 _collecting_reply 轮换）----
# 单句模板反复出现是「回复死板」的直接观感来源。这里每种情形备几种说法，
# 由 _collecting_reply 按 message 确定性取模挑选，不再每次同一副骨架。
_REPLY_OPENERS_WITH_CHANGES = (
    "记下了，{changes}。",
    "已经同步好了：{changes}。",
    "{changes}，这部分我改过了。",
)
_REPLY_OPENERS_KNOWN = (
    "现在手头有：{known}。",
    "我这边记着的是：{known}。",
    "目前定下来的：{known}。",
)
_REPLY_OPENERS_BLANK = (
    "需求我记下了，我们先理一下还差什么。",
    "我先按你说的建个写作任务。",
)
_REPLY_MISSING = (
    "还有一处没定：{m}。你给个准话，写出来的准确度会高不少；暂时没有的话我也能先按常规写法搭一版。",
    "就差 {m} 了——告诉我具体口径我就动手，或者我先写个框架你再往里补。",
    "要动笔还缺 {m}。不确定的地方直接说「先写一版」，我按惯例先架起来。",
)
# 「信息够了」的三个变体必须都带「起草」这个触发词：这是用户对上就需要按下的指令，
# 只说「可以开始写了」而不给动作，用户会卡在「那我该点哪儿」上。
_REPLY_READY = (
    "信息够动笔了，说「起草」我就开工。",
    "条件齐了，随时能起第一版——你说起草就行。",
    "这些足够了，要动笔说一声「起草」。",
)

def _today_doc_date() -> str:
    """默认成文日期（今天），形如「2026年10月6日」，与 PostProcessor 日期格式一致。"""
    t = now_local()
    return f"{t.year}年{t.month}月{t.day}日"

REVISION_RULES = (
    "这是一个【已有文档修改】任务，不是新的起草请求。必须遵守：\n"
    "1. 只修改用户要求的部分，其余内容原样保留，不得重新生成全文；\n"
    "2. 不得改变或删除用户未要求修改的事实；\n"
    "3. 不得虚构数据、成效或日期；区分两类内容——外部事实（他人姓名、统计数字、"
    "具体日期、已有成效）材料中没有出处的，不得自行填充或编造；"
    "而工作计划、方案、举措等用户自主规划的内容应充分展开，不得整段标注占位；\n"
    "4. 如果用户的要求在当前文档中已经满足、或不构成实质改动，"
    "原样输出全文，不得为了显得有改动而做无谓变动；\n"
    "5. 标题、主送机关由系统结构化排版；输出修改后的正文主体，不要在正文开头重复标题或主送机关，不要解释、不要加前后缀。"
)

DRAFT_RULES = (
    "这是写作任务。以用户指定的文种、对象和用途为准；可写各种文种，"
    "不要把未知文种强行改成通知、报告或方案。要求：\n"
    "1. 正式公文不要编造文号；其他文种不添加无关的公文要素；\n"
    "2. 区分两类内容，区别对待，不可一刀切：\n"
    "   （1）外部事实——政策文号、他人姓名、统计数字、具体日期、已有成效——"
    "必须有出处，材料里没有的不得自行填充或编造；\n"
    "   （2）工作计划、方案、举措、下一步打算等属于用户自主规划的内容，"
    "按用户意图充分展开，写清工作思路、具体举措、责任分工与预期目标；"
    "这类内容本就没有现成出处，不得因缺少数据而退化为占位说明；\n"
    "3. 必须生成完整成文：每个部分都展开为连贯、完整的正式段落，"
    "禁止只列提纲或要点清单，也禁止用「此处略去」「仅保留思路」「待补充」"
    "一类说明文字代替正文段落——缺少的只是具体数字，不是整段内容；\n"
    "4. 文种与边界以用户表达为准：用户说明了文种、用途、报送对象、时间范围的，"
    "严格照此撰写，不得擅自改文种、不得扩写范围；用户没有明说的，由你根据内容特征"
    "选择最贴切的文种与结构，不要因为信息缺失就退回成提纲或空话；\n"
    "5. 标题由系统统一管理；正式公文的主送、落款和成文日期由系统字段管理，"
    "正文不要重复这些字段。其他文种按自身体例行文，不添加无关的公文套式；\n"
    "6. 不编造文号；正式公文成文日期由系统确定，不要在正文中另写日期；"
    "联系人、电话、邮箱等材料未提供时直接省略，不得伪造；\n"
    "7. 输出前自检：逐节回看，凡是章节标题下面没有完整段落、只有「略」"
    "「待补充」「仅保留思路」式说明的，一律重写该节为具体内容后再输出——"
    "宁可写得概括，也不得只留骨架。"
)

# 正文末尾的落款行（机关署名）：导出时据此判断正文是否已自带落款，避免重复追加
SIGNOFF_TAIL_RE = re.compile(
    r"^[\u4e00-\u9fa5（）()]{2,25}"
    r"(政府|办公厅|办公室|委员会|局|厅|部|署|所|处|院|中心)$"
)

DATE_TAIL_RE = re.compile(r"20\d{2}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日")


def _sse(event: Dict[str, Any]) -> str:
    """一条 SSE 事件行。"""
    return "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"


class WritingTaskService:
    def __init__(self, db: Session, assistant=None, rag=None, attachments=None):
        self.db = db
        self.assistant = assistant
        self.rag = rag
        self.attachments = attachments
        from app.application.writing.intent_interpreter import WritingIntentInterpreter
        self.interpreter = WritingIntentInterpreter(assistant) if assistant else None

    # ---------------- 上下文合并 ----------------

    @staticmethod
    def _apply_interpretation(ctx: Dict[str, Any], it: Dict[str, Any],
                              message: str) -> List[str]:
        """合并 LLM 语义理解结果；确定性字段（文号/日期/字数）由 parser 裁定覆盖。

        - LLM 只填它确信的语义字段，None 不覆盖已有值；
        - parser 对文号/日期/字数拥有最终裁定权（用户明确说的不能被 LLM 改）；
        - key_facts 做并集合并，不丢用户已补充的事实。
        """
        from app.application.writing.intent_interpreter import SEMANTIC_FIELDS
        upd: Dict[str, Any] = {}
        for f in SEMANTIC_FIELDS:
            v = it.get(f)
            if v is None:
                continue
            if f == "key_facts":
                merged = list(dict.fromkeys((ctx.get("key_facts") or []) + (v or [])))
                if merged != (ctx.get("key_facts") or []):
                    upd["key_facts"] = merged
            elif not ctx.get(f) or ctx.get(f) != v:
                # 用户本轮重新指定的允许覆盖；否则仅填空
                if not ctx.get(f):
                    upd[f] = v
                elif f in ("title", "topic", "document_type", "time_range",
                           "recipient", "authority", "requirements", "tone", "purpose"):
                    upd[f] = v
        # 确定性字段：parser 裁定
        det = task_parser.parse_message(message)
        for f in ("document_number_enabled", "document_number",
                  "document_date", "word_count_target"):
            if f in det:
                upd[f] = det[f]
        return task_parser.merge_context(ctx, upd)

    def _interpret(self, message: str, ctx: Dict[str, Any],
                   has_draft: bool) -> Optional[Dict[str, Any]]:
        if not self.interpreter:
            return None
        history = (ctx.get("history") or [])[-6:]
        return self.interpreter.interpret(
            message, context=ctx, has_draft=has_draft, history=history)

    @staticmethod
    def _push_history(ctx: Dict[str, Any], role: str, content: str) -> None:
        h = list(ctx.get("history") or [])
        h.append({"role": role, "content": content[:1000]})
        ctx["history"] = h[-12:]

    # ---------------- 基础 CRUD ----------------

    def _get_owned(self, task_id: str, user_id: str):
        from app.infrastructure.database.models.writing_task import WritingTaskModel
        t = self.db.get(WritingTaskModel, task_id)
        if not t or t.user_id != user_id:
            raise HTTPException(status_code=404, detail="写作任务不存在")
        return t

    @staticmethod
    def _to_dict(t) -> Dict[str, Any]:
        return {
            "task_id": t.id,
            "session_id": t.session_id,
            "document_id": t.document_id,
            "task_context": t.context or {},
            "current_content": WritingTaskService._strip_leading_structural_fields(
                t.current_content or "", t.context or {}),
            "version_no": t.version_no or 0,
            "status": t.status,
            "char_count": len(t.current_content or ""),
            # 引用资料随任务落库：GET /writing/tasks/{id} 恢复任务时也要能带回来，
            # 否则切走再切回页面后「依据」栏永远是空的
            "references": list((t.context or {}).get("references") or []),
            "created_at": t.created_at.isoformat() if t.created_at else None,
            "updated_at": t.updated_at.isoformat() if t.updated_at else None,
        }

    # RAG 返回的 source 形如「文档标题（第N段）」，这里只用来剥掉段号取回文档标题
    _CHUNK_SUFFIX_RE = re.compile(r"（第\d+段）\s*$")
    # 正文里引用外部文件时常见的规范文号；只允许保留可从用户输入/RAG 证据中找到的文号。
    _EXTERNAL_DOCNUM_RE = re.compile(
        r"[\u4e00-\u9fffA-Za-z]{1,16}〔20\d{2}〕\d{1,8}号"
    )
    _DOCNUM_CUE_WORDS = ("根据", "依据", "按照", "依照", "遵照")

    @classmethod
    def _canonical_external_docnum(cls, raw: str) -> str:
        """剥掉正文连接词，避免把“根据穗司发〔…〕号”整体当作文号。"""
        value = raw
        for cue in cls._DOCNUM_CUE_WORDS:
            pos = value.rfind(cue)
            if pos >= 0 and pos + len(cue) < len(value):
                value = value[pos + len(cue):]
        return value

    @classmethod
    def _guard_external_document_numbers(
            cls, text: str, sources: List[Dict], ctx: Dict[str, Any]):
        """阻断无来源的外部文号引用。

        模型偶发会“记忆”出看似真实的历史文号。正文中的文号只有在本轮 RAG
        命中片段或用户已确认上下文里能逐字找到时才保留；否则替换为“相关文件”，
        并把原文号记录到 citation_warnings，避免把无法核实的号码交付给用户。
        """
        if not text:
            return "", []

        evidence_parts: List[str] = []
        for src in sources or []:
            if not isinstance(src, dict):
                continue
            evidence_parts.extend([
                str(src.get("content") or ""),
                str(src.get("source") or ""),
                str(src.get("source_name") or ""),
            ])
        for key in (
                "title", "topic", "requirements", "document_number",
                "recipient", "authority"):
            value = ctx.get(key)
            if value:
                evidence_parts.append(str(value))
        evidence_parts.extend(str(x) for x in (ctx.get("key_facts") or []))
        evidence = "\n".join(evidence_parts)

        cited = list(dict.fromkeys(
            cls._canonical_external_docnum(raw)
            for raw in cls._EXTERNAL_DOCNUM_RE.findall(text)
        ))
        unsupported = [num for num in cited if num not in evidence]
        if not unsupported:
            return text, []

        cleaned = text
        for num in unsupported:
            cleaned = cleaned.replace(num, "相关文件")
        logger.warning(
            "[写作任务] 移除无来源外部文号：%s",
            "、".join(unsupported),
        )
        return cleaned, unsupported

    @classmethod
    def _reference_labels(cls, sources: List[Dict]) -> List[str]:
        """把逐段命中的检索结果合并成「一份资料一条」的引用清单。

        同一篇文档命中多段时，RAG 会返回多条只有段号不同的记录；
        直接透传会让「依据」栏变成一屏重复、看不出差别的长串。
        这里按文档去重，命中多段时用「（命中 N 段）」表达，保留真实信息不虚构。
        """
        order: List[str] = []
        counts: Dict[str, int] = {}
        for s in sources or []:
            raw = (s or {}).get("source") or ""
            if not raw:
                continue
            title = cls._CHUNK_SUFFIX_RE.sub("", raw).strip() or raw.strip()
            if title not in counts:
                counts[title] = 0
                order.append(title)
            counts[title] += 1
        return [t if counts[t] <= 1 else f"{t}（命中 {counts[t]} 段）" for t in order]

    def create_task(self, user_id: str, message: str,
                    session_id: Optional[str] = None,
                    template_id: Optional[str] = None,
                    kb_ids: Optional[List[str]] = None,
                    planned_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """从自然语言初始化任务：解析要素 -> 建任务 -> 返回上下文与追问。"""
        from app.infrastructure.database.models.writing_task import WritingTaskModel

        ctx = task_parser.empty_context()
        it = None
        changes: List[str] = []

        # /plan 已经完成语义理解时，复用这份服务端产生的上下文，避免同一句话
        # 再跑一次 LLM。只接收 empty_context 已知字段，拒绝客户端夹带任意键。
        if planned_context:
            for key in tuple(ctx.keys()):
                if key in planned_context and key not in ("history", "missing_fields"):
                    ctx[key] = planned_context[key]
            # A planning snapshot may suggest a template, but binding requires explicit choice.
            ctx["template_id"] = None
            ctx["template_name"] = None
            # planned_context 已经完成过语义理解，文种/主题/主送/发文机关等语义字段
            # 必须以它为准。规则 parser 这里只刷新“可从原文字面确定”的严格字段，
            # 避免诸如“关于报送材料的通知”被误抽成 recipient="材料的通知"。
            parsed = task_parser.parse_message(message)
            literal_keys = {
                "time_range", "word_count_target",
                "document_number_enabled", "document_number", "document_date",
            }
            literal_updates = {k: v for k, v in parsed.items() if k in literal_keys}
            changes = task_parser.merge_context(ctx, literal_updates)
        else:
            # 未经过 /plan 的兼容路径仍保留原有 LLM 语义理解能力。
            it = self._interpret(message, ctx, has_draft=False)
            if it:
                changes = self._apply_interpretation(ctx, it, message)
            else:
                changes = task_parser.merge_context(ctx, task_parser.parse_message(message))

        # 标题是排版结构字段：用户未显式填写时按已确认的主题+文种确定性生成，
        # 不再让模型在正文里自行重复一个标题。
        if not ctx.get("title"):
            derived_title = task_parser.build_title(ctx)
            if derived_title:
                ctx["title"] = derived_title

        # 创建时显式选择的模板 / 知识库优先于规划快照。
        if template_id:
            tmpl = self._load_template(template_id)
            if tmpl:
                ctx["template_id"] = tmpl["id"]
                ctx["template_name"] = tmpl["name"]
                # 模板声明 need_signature / need_date 但用户未显式填落款单位 / 日期时，
                # 由系统兜底：落款取组织机构名 org.name，日期取今天。
                # 这样“排版三件套”（标题 / 主送 / 落款 / 日期）不会漏渲染。
                if tmpl.get("need_signature") and not ctx.get("authority"):
                    authority = self._default_authority()
                    if authority:
                        ctx["authority"] = authority
                if tmpl.get("need_date") and not ctx.get("document_date"):
                    ctx["document_date"] = _today_doc_date()
        if kb_ids:
            ctx["kb_ids"] = [k for k in kb_ids if k]
        self._complete_default_authority(ctx)
        missing = task_parser.compute_missing(ctx)
        self._push_history(ctx, "user", message)

        t = WritingTaskModel(user_id=user_id, session_id=session_id,
                             context=ctx, status="collecting")
        self.db.add(t)
        self.db.commit()
        self.db.refresh(t)

        if it and it.get("reply"):
            reply = it["reply"]
        else:
            reply = self._collecting_reply(ctx, changes, missing, message)
        self._push_history(ctx, "assistant", reply)
        t.context = ctx
        self.db.commit()
        return {**self._to_dict(t), "reply": reply, "content_changed": False}

    # ---------------- 任务规划：AI 构造本次写作的工作环境 ----------------

    def plan_task(self, user_id: str, message: str) -> Dict[str, Any]:
        """一句话指令 → WorkspaceSpec（左栏分区 / 材料 / 知识 / 模板 / AI 动作）。

        与 create_task 的区别：只做规划，不落库、不生成正文。
        LLM 不可用或解析失败时降级为规则规划，并在 source 中标注 rule，绝不假装规划过。
        """
        ctx = task_parser.empty_context()
        # 常见明确任务走规则快速路径，避免“进入写作台”先等一次完整 LLM。
        # 只有规则无法同时确定文种和主题/标题时，才调用语义解释模型。
        rule_upd = task_parser.parse_message(message)
        task_parser.merge_context(ctx, rule_upd)
        has_clear_core = bool(
            ctx.get("document_type") and
            (ctx.get("topic") or ctx.get("title") or task_parser.build_title(ctx))
        )
        if has_clear_core:
            source = "rule_fast"
        else:
            it = self._interpret(message, ctx, has_draft=False)
            if it:
                self._apply_interpretation(ctx, it, message)
                source = "llm"
            else:
                source = "rule"

        # 科室 Agent 与知识边界（后端强隔离，前端不参与推导）
        try:
            from app.application.organization.service import OrganizationService
            org = OrganizationService(self.db)
            org_ctx = org.user_context(user_id)
        except Exception as e:
            logger.warning("[写作规划] 科室上下文加载失败: %s", e)
            org_ctx = {"dept_code": "", "dept_name": "", "short_name": "",
                       "agent": None, "scopes": ["GLOBAL"]}

        doc_type = ctx.get("document_type") or ""
        fields: List[Dict[str, str]] = []
        for key, label in (("document_type", "文种"), ("recipient", "报送对象"),
                           ("authority", "发文机关"), ("time_range", "时间范围"),
                           ("purpose", "用途"), ("topic", "主题")):
            val = ctx.get(key)
            if val:
                fields.append({"label": label, "value": str(val)})

        # 进入工作台不应被“推荐材料检索”拖住。只有用户明确表达要参考/结合材料时，
        # 才在规划阶段做向量检索；真正起草时仍会按知识权限正常 RAG，不影响内容依据。
        material_cues = ("参考", "结合", "根据", "依据", "材料", "范文", "案例", "政策", "文件")
        materials = self._plan_materials(ctx, user_id, org_ctx) \
            if any(cue in message for cue in material_cues) else []
        knowledge = self._plan_knowledge(user_id, org_ctx)

        return {
            "doc_type": doc_type,
            "target": ctx.get("purpose") or ctx.get("topic") or message[:40],
            "audience": ctx.get("recipient") or "",
            "department": org_ctx.get("dept_name") or org_ctx.get("short_name") or "",
            "agent": (org_ctx.get("agent") or {}).get("name") or "",
            "title": ctx.get("title") or task_parser.build_title(ctx) or "",
            "source": source,
            "planned_context": {
                k: v for k, v in ctx.items()
                if k not in ("history", "missing_fields")
            },
            "fields": fields,
            "materials": materials,
            "knowledge": knowledge,
            "template_id": "",
            "template_name": "",
            "scopes": org_ctx.get("scopes") or ["GLOBAL"],
            "kb_ids": [k["id"] for k in knowledge],
            "ai_actions": self._plan_actions(doc_type),
        }

    def _plan_materials(self, ctx: Dict[str, Any], user_id: str,
                        org_ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
        """按主题检索可参考的范文 / 材料（走同一套科室作用域约束的 RAG）。"""
        if not self.rag:
            return []
        query = " ".join(filter(None, [
            ctx.get("title"), ctx.get("topic"), ctx.get("time_range"),
            ctx.get("document_type"),
        ])).strip()
        if not query:
            return []
        kb_ids: List[str] = []
        try:
            dept_code = org_ctx.get("dept_code") or ""
            scopes = org_ctx.get("scopes")
            kb_ids = self.rag._get_accessible_kb_ids(
                user_id, dept_code, bool(org_ctx.get("is_admin")))
            if not kb_ids:
                return []
            if getattr(self.rag, "fast_mode", False):
                return self._plan_materials_fallback(query, user_id, kb_ids)
            query_vec = self.rag.embedder.encode_queries([query])[0]
            hits = self.rag.vector_store.search(query_vec, kb_ids, top_k=8, scopes=scopes)
            out, seen = [], set()
            for h in hits:
                if h["doc_id"] in seen:
                    continue
                seen.add(h["doc_id"])
                # 展示名优先用文档标题（向量元数据里是块标题，用户看不懂）
                _doc = self.db.get(DocumentModel, h["doc_id"])
                _doc_title = (_doc.title if _doc else "") or h.get("title") or "未命名材料"
                out.append({
                    "id": h["doc_id"],
                    "label": _doc_title,
                    "selected": len(out) < 3,
                    "note": "",
                })
            return out
        except Exception as e:
            logger.warning("[写作规划] 材料向量检索失败: %s", e)
        # 向量库不可用（未建索引 / 依赖缺失）时回退混合检索：
        # 写作时真正用的就是这条链路，规划阶段不能因为它不可用就把材料清单给空掉
        return self._plan_materials_fallback(query, user_id, kb_ids)

    def _plan_materials_fallback(self, query: str, user_id: str,
                                 kb_ids: List[str]) -> List[Dict[str, Any]]:
        """用 RagService.search（向量 + 关键词双路召回）兜底出材料清单。"""
        try:
            hits = self.rag.search(query=query, user_id=user_id,
                                   kb_ids=kb_ids or None, top_k=8)
        except Exception as e:
            logger.warning("[写作规划] 材料检索回退失败: %s", e)
            return []
        out, seen = [], set()
        for h in hits or []:
            doc_id = h.get("doc_id")
            if not doc_id or doc_id in seen:
                continue
            seen.add(doc_id)
            # source 形如「标题（第N段）」，剥掉段号取标题
            raw = h.get("source") or ""
            title = self._CHUNK_SUFFIX_RE.sub("", raw).strip()
            if not title:
                _doc = self.db.get(DocumentModel, doc_id)
                title = (_doc.title if _doc else "") or "未命名材料"
            out.append({"id": doc_id, "label": title,
                        "selected": len(out) < 3, "note": ""})
        return out

    def _plan_knowledge(self, user_id: str,
                        org_ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
        """用户可见知识库：全局公共 + 本人个人 + 本科室（系统管理员全部）。

        走统一访问策略，杜绝把他人个人库或他科室库规划给用户。
        """
        from app.infrastructure.database.models.knowledge import KnowledgeBaseModel
        try:
            from sqlalchemy import select
            dept_code = org_ctx.get("dept_code") or ""
            kb_ids = self.rag._get_accessible_kb_ids(
                user_id, dept_code, bool(org_ctx.get("is_admin")))
            if not kb_ids:
                return []
            kbs = self.db.scalars(
                select(KnowledgeBaseModel).where(KnowledgeBaseModel.id.in_(kb_ids))).all()
            return [{
                "id": kb.id,
                "label": kb.name,
                "selected": bool(dept_code and kb.department_code == dept_code),
                "note": ("本科室知识库" if kb.department_code
                         else ("我的个人知识库" if kb.kb_type == "personal" else "全局公共知识库")),
            } for kb in kbs]
        except Exception as e:
            logger.warning("[写作规划] 知识库加载失败: %s", e)
            return []

    @staticmethod
    def _plan_actions(doc_type: str) -> List[str]:
        base = ["完善结构", "补充依据", "压缩篇幅", "润色表达"]
        if doc_type in ("会议纪要", "纪要"):
            return ["补全参会信息", "整理议定事项", "压缩篇幅", "公文润色"]
        if doc_type in ("工作总结", "报告", "工作情况报告"):
            return ["完善结构", "补充数据依据", "提炼成效", "公文润色"]
        if doc_type in ("请示", "函"):
            return ["明确请示事项", "补充依据", "压缩篇幅", "公文润色"]
        return base

    def _plan_template(self, doc_type: str, org_ctx: Dict[str, Any]) -> Dict[str, Any]:
        """按文种 + 科室推荐模板：本科室模板优先，其次公共模板。"""
        from app.infrastructure.database.models.templates import WritingTemplateModel
        if not doc_type:
            return {}
        try:
            from sqlalchemy import select
            dept_code = org_ctx.get("dept_code") or ""
            rows = self.db.scalars(
                select(WritingTemplateModel).where(
                    WritingTemplateModel.is_active.is_(True),
                    WritingTemplateModel.category == doc_type,
                )).all()
            if not rows:
                return {}
            owned = [r for r in rows if (r.department_code or "") == dept_code]
            picked = (owned or rows)[0]
            return {"id": picked.id, "name": picked.name}
        except Exception as e:
            logger.warning("[写作规划] 模板匹配失败: %s", e)
            return {}

    def get_task(self, task_id: str, user_id: str) -> Dict[str, Any]:
        return self._to_dict(self._get_owned(task_id, user_id))

    def list_tasks(self, user_id: str) -> List[Dict[str, Any]]:
        from app.infrastructure.database.models.writing_task import WritingTaskModel
        rows = self.db.scalars(
            select(WritingTaskModel)
            .where(WritingTaskModel.user_id == user_id)
            .order_by(desc(WritingTaskModel.updated_at))
        ).all()
        return [self._to_dict(t) for t in rows]

    def update_context(self, task_id: str, user_id: str,
                       patch: Dict[str, Any]) -> Dict[str, Any]:
        """用户直接编辑左侧结构化字段，同步进 task context。"""
        t = self._get_owned(task_id, user_id)
        ctx = dict(t.context or {})
        allowed = set(task_parser.empty_context().keys())
        for k, v in patch.items():
            if k in allowed:
                ctx[k] = v
        # 模板绑定：由 template_id 解析名称，前端无需关心
        if "template_id" in patch:
            tmpl = self._load_template(ctx.get("template_id")) if ctx.get("template_id") else None
            ctx["template_name"] = tmpl["name"] if tmpl else None
            ctx["template_id"] = tmpl["id"] if tmpl else None
        if "kb_ids" in patch and not isinstance(ctx.get("kb_ids"), list):
            ctx["kb_ids"] = []
        task_parser.compute_missing(ctx)
        t.context = ctx
        t.updated_at = now_local()
        self.db.commit()
        return self._to_dict(t)

    # ---------------- 对话（任务内持续对话） ----------------

    def chat(self, task_id: str, user_id: str, message: str) -> Dict[str, Any]:
        """任务内对话：LLM 意图理解 → 动作编排（追问/更新/起草/修改/回答）。

        规则关键词仅作 LLM 不可用时的确定性回退。
        """
        t = self._get_owned(task_id, user_id)
        ctx = dict(t.context or {})
        has_draft = bool((t.current_content or "").strip())
        self._push_history(ctx, "user", message)

        before_ctx = dict(ctx)
        # 1. LLM 意图理解（含当前上下文/草稿状态/对话历史）
        it = self._interpret(message, ctx, has_draft=has_draft)
        if it:
            changes = self._apply_interpretation(ctx, it, message)
            intent = it["intent"]
        else:
            changes = task_parser.merge_context(ctx, task_parser.parse_message(message))
            # 确定性回退路径
            if has_draft and task_parser.looks_like_revise(message):
                intent = "revise_content"
            elif not has_draft and task_parser.looks_like_draft(message):
                intent = "draft"
            else:
                intent = "update_context"

        # 本轮实际变动的结构化字段（落款日期/文号）——后面要把它们落到正文上
        structured_changes = {
            k for k in ("document_date", "document_number",
                        "document_number_enabled")
            if before_ctx.get(k) != ctx.get(k)
        }

        missing = task_parser.compute_missing(ctx)
        t.context = ctx
        t.updated_at = now_local()
        self.db.commit()

        # 2. 动作编排
        if intent == "revise_content" and has_draft:
            instruction = (it or {}).get("revision_instruction") or message
            mode = (it or {}).get("revision_mode") or "revise"
            result = self.revise(task_id, user_id, instruction=instruction, mode=mode)
            result["context_changes"] = changes
            new_ctx = dict(t.context or {})
            self._push_history(new_ctx, "assistant", result["reply"])
            t.context = new_ctx
            self.db.commit()
            return result

        if intent in ("draft", "outline") and not has_draft:
            result = self.draft(task_id, user_id, outline_only=(intent == "outline"))
            result["context_changes"] = changes
            new_ctx = dict(t.context or {})
            self._push_history(new_ctx, "assistant", result["reply"])
            t.context = new_ctx
            self.db.commit()
            return result

        # 3. 追问 / 要素更新 / 普通回答
        #    结构化字段改了但没走 AI 改写时，必须同步落进正文：
        #    否则就是「助手说已更新落款日期，正文里的日期纹丝不动」
        if has_draft and structured_changes:
            sync_note = self._sync_structured_fields(t, user_id)
            if sync_note:
                changes = list(changes) + [sync_note]

        if it and it.get("reply"):
            reply = it["reply"]
        else:
            reply = self._collecting_reply(ctx, changes, missing, message)
        self._push_history(ctx, "assistant", reply)
        t.context = ctx
        self.db.commit()
        return {**self._to_dict(t), "reply": reply, "content_changed": False,
                "context_changes": changes}

    def _sync_structured_fields(self, t, user_id: str) -> str:
        """把 ctx 里已变更的结构化字段（落款日期 / 文号）同步到正文。

        只在这两个字段上做：它们由后处理器程序化注入，不会篡改正文语义。
        发文机关（落款单位）不在此列——正文里的署名行属于正文内容，
        改它需要重写正文，不能悄悄替换。
        没有任何实际变化时返回空串，避免制造噪音版本。
        """
        content = (t.current_content or "").strip()
        if not content:
            return ""
        new_text, events, _doc_number, _doc_date = self._postprocess(
            content, dict(t.context or {}))
        if not new_text.strip() or new_text.strip() == content:
            return ""
        t.current_content = new_text
        self.db.flush()
        _, ver = self._snapshot(t, user_id, note="结构化字段同步")
        t.version_no = ver
        t.updated_at = now_local()
        self.db.commit()
        return ("；".join(events) if events else "正文已同步") + f"（v{ver}）"

    _DRAFT_FOLLOWUP_VARIANTS = (
        "哪儿要改跟我说，或者直接改正文再存一版。",
        "接着聊就行，哪块不对我改哪块。",
        "要微调直接讲，也可以在正文里改完自己保存。",
    )

    def _draft_followup(self, quality: Optional[Dict[str, Any]],
                        missing_fields: Optional[List[str]], seed: str) -> str:
        """草稿生成后的下一步引导：先看这一稿实际怎么样，再决定说什么。

        原先这里无条件拼「您可以继续对话修改，或直接编辑正文后保存版本。」——
        每一轮、每一篇、无论写得好不好、缺不缺依据，都跟同一句，
        是用户眼里最典型的橡皮图章。改成：有该处理的事先说那件事，
        实在没得说才给一句通用引导（且措辞轮换）。
        """
        if missing_fields:
            return (f"这几处建议你给个准确说法（尤其「{missing_fields[0]}」），"
                    "我再改一版会实很多。")
        review = list((quality or {}).get("review") or [])
        if review:
            return f"另外有一条待复核：{review[0]}，定稿前最好过一眼。"
        return self._DRAFT_FOLLOWUP_VARIANTS[
            zlib.crc32((seed or "").encode("utf-8")) % len(self._DRAFT_FOLLOWUP_VARIANTS)
        ]

    def _collecting_reply(self, ctx, changes, missing, message) -> str:
        """LLM 不可用时的兜底回复。

        这是用户抱怨「回复很死板」的直接来源之一：原先每段都是写死的单句模板，
        无论说什么都回同一副骨架。这里改成**措辞变体确定性轮换**——按 message
        取模而不是随机，保证同一句话重放时回复稳定（也让测试可以断言）。
        这个路径拿不到模型能力，所以只能轮换措辞 + 把 missing 转成会说人话的追问，
        做不到真正理解语义；有 LLM 时一律走 ``_interpret`` 的 reply。
        """
        # 各段落用不同 salt 独立取模：否则同一 seed 会让开头、追问总落在同一个
        # 索引上，四种情形撞成同一种组合，轮换等于没做。
        seed = message or ""

        def pick(options, salt: int) -> str:
            h = zlib.crc32(f"{seed}|{salt}".encode("utf-8"))
            return options[h % len(options)]

        parts: List[str] = []
        if changes:
            parts.append(pick(_REPLY_OPENERS_WITH_CHANGES, 1).format(
                changes="；".join(changes)))
        known = []
        if ctx.get("document_type"):
            known.append(f"文种是{ctx['document_type']}")
        if ctx.get("topic"):
            known.append(f"主题是{ctx['topic']}")
        if ctx.get("time_range"):
            known.append(f"时间范围是{ctx['time_range']}")

        if not parts:
            if known:
                parts.append(pick(_REPLY_OPENERS_KNOWN, 2).format(
                    known="，".join(known)))
            else:
                parts.append(pick(_REPLY_OPENERS_BLANK, 3))

        if missing:
            # 把「缺什么」说成人话的追问，并留出「先写一版」的逃生口：
            # 用户手头常常没有材料，不能因为没有就把人拦在这里。
            parts.append(pick(_REPLY_MISSING, 4).format(m="、".join(missing)))
        else:
            parts.append(pick(_REPLY_READY, 5))
        return "".join(parts)

    # ---------------- 模板 ----------------

    def _load_template(self, template_id: Optional[str]) -> Optional[Dict[str, Any]]:
        """读取任务关联的写作模板；不存在/不可见不阻塞写作，仅视为未绑定。"""
        if not template_id:
            return None
        try:
            from app.application.templates.service import TemplateService
            tmpl = TemplateService(self.db).get_template(template_id)
            return tmpl if tmpl.get("is_active", True) else None
        except Exception as e:
            logger.warning("[写作任务] 模板 %s 读取失败: %s", template_id, e)
            return None

    def _default_authority(self) -> str:
        """从系统配置 org.name 读取本单位名称，作为落款单位的默认值。

        模板声明 need_signature 且用户未显式指定落款单位时调用，兑现“落款由系统补齐”。
        org.name 不存在时返回空串（不强行编一个落款）。
        """
        try:
            from app.infrastructure.database.models.system import SystemConfigModel
            from sqlalchemy import select
            row = self.db.scalars(
                select(SystemConfigModel).where(SystemConfigModel.key == "org.name")
            ).first()
            if row and row.value:
                value = str(row.value).strip()
                return "广州市白云区司法局" if value == "白云区司法局" else value
        except Exception as e:  # noqa: BLE001
            logger.warning("[写作任务] 读取 org.name 失败: %s", e)
        return ""

    def _complete_default_authority(self, ctx: Dict[str, Any]) -> None:
        """Use the configured issuing organization for official documents when omitted."""
        doc_type = str(ctx.get("document_type") or "")
        if not ctx.get("authority") and doc_type in task_parser.FORMAL_DOC_TYPES:
            ctx["authority"] = self._default_authority() or None

    # ---------------- 起草 / 继续生成 ----------------

    def draft(self, task_id: str, user_id: str,
              outline_only: bool = False) -> Dict[str, Any]:
        """起草初稿；已有正文时调用即「继续生成」——按当前任务参数重新起草，
        旧版本不覆盖，每次生成自动沉淀为新版本（v1/v2/v3…）。"""
        t = self._get_owned(task_id, user_id)
        ctx = dict(t.context or {})
        template = self._load_template(ctx.get("template_id"))
        instruction = self._build_draft_instruction(ctx, outline_only, template)
        sources = self._retrieve(ctx, user_id)
        attachment_ctx = self._attachment_context(t, ctx)

        text = self._llm_draft(instruction, sources, attachment_ctx, user_id,
                               template=template)
        text = self._clean_markdown(text)
        if not text.strip():
            raise HTTPException(status_code=502, detail="模型未返回内容，请重试")
        # 提纲式退化兜底：只给骨架的自动重写一次，不把「此处略去」式占位稿落库
        text, retry_reason = self._regenerate_if_needed(
            instruction, sources, attachment_ctx, user_id, template, text, ctx)
        payload = self._finalize_draft(t, ctx, text, sources, user_id)
        if retry_reason:
            payload["reply"] = retry_reason + payload["reply"]
        return payload

    def draft_stream(self, task_id: str, user_id: str,
                     outline_only: bool = False) -> Iterator[str]:
        """流式起草（SSE）：先逐段推 {"type":"delta"} 供前端渐进展示，
        完成后推 {"type":"done","data":...}，data 与非流式 draft 返回结构一致（最终权威内容）；
        失败推 {"type":"error","message":...}。

        delta 是模型原始输出（未经后处理/清洗），仅用于展示；落库内容以 done 为准。
        若 delta 呈现的内容检出提纲式退化，服务端会重写一次，done 携带重写后的成文。
        """
        try:
            t = self._get_owned(task_id, user_id)
            ctx = dict(t.context or {})
            template = self._load_template(ctx.get("template_id"))
            instruction = self._build_draft_instruction(ctx, outline_only, template)
            sources = self._retrieve(ctx, user_id)
            attachment_ctx = self._attachment_context(t, ctx)

            parts: List[str] = []
            for delta in self._llm_draft_stream(instruction, sources, attachment_ctx,
                                                user_id, template=template):
                if not delta:
                    continue
                parts.append(delta)
                yield _sse({"type": "delta", "text": delta})

            text = self._clean_markdown("".join(parts))
            if not text.strip():
                yield _sse({"type": "error", "message": "模型未返回内容，请重试"})
                return
            # 提纲式退化兜底：只给骨架的自动重写一次（done 携带重写后的成文）
            text, retry_reason = self._regenerate_if_needed(
                instruction, sources, attachment_ctx, user_id, template, text, ctx)
            payload = self._finalize_draft(t, ctx, text, sources, user_id)
            if retry_reason:
                payload["reply"] = retry_reason + payload["reply"]
            yield _sse({"type": "done", "data": payload})
        except HTTPException as e:
            yield _sse({"type": "error", "message": str(e.detail)})
        except Exception as e:  # 模型中断 / 网络异常 / 其他未预期错误
            logger.exception("[写作任务] 流式起草失败")
            yield _sse({"type": "error", "message": f"生成中断：{e}"})

    def _regenerate_if_needed(self, instruction: str, sources,
                              attachment_ctx, user_id,
                              template: Optional[Dict[str, Any]],
                              text: str, ctx: Dict[str, Any]) -> tuple:
        """质量兜底：提纲式退化或函件明显过长时，最多自动重写一次。

        - 提纲退化：要求逐节展开；
        - 函件过长：在用户未指定长篇字数时，压缩到 3-5 个部分/自然段，
          合并重复事项并保留事实、金额、时限和办理要求。
        """
        from app.application.writing.postprocessor import detect_outline_degeneration

        degenerate = bool(detect_outline_degeneration(text))
        doc_type = str(ctx.get("document_type") or "")
        # 函件体例问题不只是“太长”，更是“被写成了报告”：章节一多就是结构错，
        # 所以字数未超 1500 但一级条目超过 5 条时同样要精简。
        heading_count = len(
            re.findall(r"(?m)^\s*(一|二|三|四|五|六|七|八|九|十)+、", text)
        )
        # 用户指定了字数时也不能靠加章节凑字数：条目一旦超过 6 条，
        # 即便字数达标照样精简（只合并条目，不砍字数）。
        word_target = ctx.get("word_count_target")
        compact_letter = (
            "函" in doc_type
            and (
                heading_count > 6
                or (not word_target
                    and (len(re.sub(r"\s+", "", text)) > 1500
                         or heading_count > 5))
            )
        )
        if not degenerate and not compact_letter:
            return text, None

        if degenerate:
            logger.warning("[写作任务] 检测到提纲式退化，自动重写一次")
            retry_instruction = (
                instruction +
                "\n\n【重写要求】上一次输出只有章节标题和占位说明，是提纲不是公文，不合格。"
                "请逐节展开为完整段落：每节写清工作思路、具体举措、责任分工与预期目标；"
                "工作举措属于作者自主规划，必须写实写具体，"
                "不得出现任何「略」「待补充」「仅保留思路」式占位文字。")
            reason = "检测到初稿只有提纲，已自动重写为完整成文。"
        else:
            logger.warning("[写作任务] 检测到函件体例偏报告（%d 字 / %d 个条目），"
                           "自动精简一次", len(re.sub(r"\s+", "", text)), heading_count)
            if word_target:
                compact_requirement = (
                    f"上一版为了凑字数拆成了 {heading_count} 个条目，不符合函件体例。"
                    f"请在仍然不少于 {word_target} 字的前提下，把一级条目合并到 3-5 个，"
                    "达标的办法是把每段的依据、标准、流程、时限、要求写实写足，"
                    "而不是继续增加章节条目。"
                )
            else:
                compact_requirement = (
                    "上一版函件过长，不符合函件简明直接的体例。"
                    "请在不丢失事实、金额、时限、办理要求和责任主体的前提下，"
                    "合并重复事项，将正文压缩为 3-5 个自然段或部分，通常控制在 800-1200 字；"
                    "不得写成 7、8 个条目的长篇报告。"
                )
            retry_instruction = (
                instruction + "\n\n【精简重写要求】" + compact_requirement
                + "不得新增材料中没有的事实。")
            reason = "检测到函件被写成了长篇报告体例，已自动精简为更符合函件体例的版本。"

        try:
            retry = self._llm_draft(retry_instruction, sources, attachment_ctx,
                                    user_id, template=template)
            retry = self._clean_markdown(retry)
        except Exception as e:
            logger.warning("[写作任务] 自动重写失败: %s", e)
            return text, None

        if not retry.strip() or detect_outline_degeneration(retry):
            return text, None
        if degenerate and len(retry) <= len(text):
            return text, None
        if compact_letter:
            retry_len = len(re.sub(r"\s+", "", retry))
            original_len = len(re.sub(r"\s+", "", text))
            retry_headings = len(
                re.findall(r"(?m)^\s*(一|二|三|四|五|六|七|八|九|十)+、", retry)
            )
            if word_target:
                # 有字数目标：看条目有没有并下来，同时字数不能塌到目标的 80% 以下
                if retry_headings > 5 or retry_len < word_target * 0.8:
                    logger.warning(
                        "[写作任务] 函件精简未达标（条目 %d / 字数 %d），保留原文",
                        retry_headings, retry_len)
                    return text, None
            elif retry_len >= original_len or retry_len > 1500:
                logger.warning("[写作任务] 函件精简结果仍过长，保留原文供质量门提示：%d 字", retry_len)
                return text, None
        return retry, reason

    def _finalize_draft(self, t, ctx: Dict[str, Any], text: str,
                        sources: List[Dict], user_id: str) -> Dict[str, Any]:
        """起草收尾（draft 与 draft_stream 共用）：后处理 → 质量评估 → 落库 → 版本快照。"""
        # 后处理：文号/日期按任务开关决定，默认不注入
        text, events, doc_number, doc_date = self._postprocess(text, ctx)
        text = self._strip_leading_structural_fields(text, ctx)
        text, citation_warnings = self._guard_external_document_numbers(
            text, sources, ctx)
        if citation_warnings:
            ctx["citation_warnings"] = citation_warnings
        else:
            ctx.pop("citation_warnings", None)
        from app.application.writing.quality_gate import QualityGate
        quality = QualityGate().evaluate(
            text, body_only=True, document_type=ctx.get("document_type") or "",
            word_count_target=ctx.get("word_count_target"))
        from app.application.writing.content_check import ContentChecker
        content_check = ContentChecker().check(
            text, sources=sources, header_docnum=doc_number)
        if content_check["issues"]:
            quality["issues"] = list(quality.get("issues") or []) + content_check["issues"]
            if quality.get("level") == "A":
                quality["level"] = "B"

        if doc_number:
            ctx["document_number"] = doc_number
        if doc_date:
            ctx["document_date"] = doc_date
        # 引用清单按文档去重后随任务落库，供后续 GET 任务时回放
        references = self._reference_labels(sources)
        ctx["references"] = references
        t.context = ctx
        t.current_content = text
        if not t.ai_draft:
            t.ai_draft = text
        t.status = "editing"
        self.db.flush()
        doc_id, ver = self._snapshot(
            t, user_id,
            note="V1 AI 初稿" if t.version_no == 0 else f"V{t.version_no + 1} 继续生成",
            commit=False)
        t.document_id = doc_id
        t.version_no = ver
        t.updated_at = now_local()
        self.db.commit()

        if ver <= 1:
            reply = "已生成 V1 初稿（待完善）。"
        else:
            reply = (f"已按当前任务参数继续生成一版（v{ver}），上一版仍在「历史版本」中可随时查看/回退；"
                     "不满意可先修改左侧参数再点「继续生成」。")
        if references:
            reply += f"本次检索到 {len(references)} 份内部资料作为写作依据。"
        if citation_warnings:
            reply += (
                f"系统发现 {len(citation_warnings)} 处无法从本次资料或用户输入核实的文号，"
                "已移除具体号码并改为“相关文件”，请在确认来源后再补回。"
            )
        if ctx.get("missing_fields"):
            reply += "以下内容因缺少事实依据已标注：" + "、".join(ctx["missing_fields"]) + "。"
        seed = t.current_content or ""
        reply += self._draft_followup(quality, ctx.get("missing_fields"), seed)
        return {**self._to_dict(t), "reply": reply, "content_changed": True,
                "quality": quality, "content_check": content_check,
                "postprocess_events": events, "references": references}

    # ---------------- 修改（核心：作用于当前文档） ----------------

    def revise(self, task_id: str, user_id: str, instruction: str,
               mode: str = "revise", selection: Optional[str] = None) -> Dict[str, Any]:
        t = self._get_owned(task_id, user_id)
        current = (t.current_content or "").strip()
        if not current:
            raise HTTPException(status_code=409, detail="当前还没有草稿，请先起草")

        ctx = dict(t.context or {})
        mode_desc = REVISE_MODES.get(mode, REVISE_MODES["revise"])
        prompt = self._build_revise_prompt(current, instruction, mode_desc, selection, ctx)
        sources = self._retrieve(ctx, user_id, extra_query=instruction)
        attachment_ctx = self._attachment_context(t, ctx)

        revised = self._llm_revise(prompt, sources, attachment_ctx, user_id)
        if not revised.strip():
            raise HTTPException(status_code=502, detail="模型未返回内容，请重试")

        # 诚实校验：新旧正文逐字比对，没有实际改动就不得声称"已修改"，
        # 也不生成新版本（版本链只记录真实变化）
        if revised.strip() == current:
            reply = ("对照您的要求检查了当前文档，没有需要实际改动的地方，"
                     "正文保持原样，也未生成新版本。"
                     "如果想调整得更准确，请指出具体要改的部分和方向。")
            return {**self._to_dict(t), "reply": reply, "content_changed": False,
                    "context_changes": []}

        # ⚠ 顺序很重要：必须**先**把用户这句话里的上下文变更合进 ctx
        # （"落款改成 X" / "日期填 X" / "不要文号" 这类指令），**再**走后处理。
        # 从前是先 _postprocess 再 merge_context，结果后处理拿到的还是旧日期：
        # 助手回复里报告"任务信息已同步更新：落款日期 X"，正文里的日期却纹丝不动，
        # 而且紧随其后的 `ctx["document_date"] = doc_date` 还会把用户刚给的新值覆盖回去。
        changes = task_parser.merge_context(ctx, task_parser.parse_message(instruction))
        task_parser.compute_missing(ctx)

        revised, events, doc_number, doc_date = self._postprocess(revised, ctx)
        revised = self._strip_leading_structural_fields(revised, ctx)
        revised, citation_warnings = self._guard_external_document_numbers(
            revised, sources, ctx)
        if citation_warnings:
            ctx["citation_warnings"] = citation_warnings
        else:
            ctx.pop("citation_warnings", None)
        from app.application.writing.quality_gate import QualityGate
        quality = QualityGate().evaluate(
            revised, body_only=True, document_type=ctx.get("document_type") or "",
            word_count_target=ctx.get("word_count_target"))
        from app.application.writing.content_check import ContentChecker
        content_check = ContentChecker().check(
            revised, sources=sources, header_docnum=doc_number)
        if content_check["issues"]:
            quality["issues"] = list(quality.get("issues") or []) + content_check["issues"]
            if quality.get("level") == "A":
                quality["level"] = "B"

        # 后处理**实际采用**的文号/成文日期回写 ctx，保证任务信息与正文一致
        if doc_number:
            ctx["document_number"] = doc_number
        if doc_date:
            ctx["document_date"] = doc_date
        # 改写同样带检索：有命中就更新引用清单，没命中保留上一版（不把已有依据清空）
        references = self._reference_labels(sources) or list(ctx.get("references") or [])
        ctx["references"] = references
        t.context = ctx

        t.current_content = revised
        self.db.flush()
        _, ver = self._snapshot(t, user_id, note=f"AI 修改：{instruction[:30]}")
        t.version_no = ver
        t.updated_at = now_local()
        self.db.commit()

        reply = f"已按您的要求修改当前文档（{mode_desc.split('：')[0]}），保存为 v{ver}。"
        if citation_warnings:
            reply += (
                f"系统同时移除了 {len(citation_warnings)} 处无法核实的具体文号，"
                "请确认资料来源后再补回。"
            )
        if changes:
            reply += "任务信息同步更新：" + "；".join(changes) + "。"
        return {**self._to_dict(t), "reply": reply, "content_changed": True,
                "quality": quality, "content_check": content_check,
                "postprocess_events": events, "context_changes": changes,
                "references": references}

    # ---------------- 版本 / 导出 ----------------

    def save_version(self, task_id: str, user_id: str, content: str,
                     note: Optional[str] = None) -> Dict[str, Any]:
        """用户手动保存当前编辑内容为新版本。"""
        t = self._get_owned(task_id, user_id)
        t.current_content = content
        self.db.flush()
        doc_id, ver = self._snapshot(t, user_id, note=note or "人工编辑")
        t.document_id = doc_id
        t.version_no = ver
        t.updated_at = now_local()
        self.db.commit()
        return self._to_dict(t)

    def list_versions(self, task_id: str, user_id: str) -> List[Dict[str, Any]]:
        t = self._get_owned(task_id, user_id)
        if not t.document_id:
            return []
        from app.application.documents.service import DocumentService
        doc = DocumentService(self.db).get_document(t.document_id, user_id)
        return doc["versions"]

    def get_version(self, task_id: str, user_id: str, version_no: int) -> Dict[str, Any]:
        t = self._get_owned(task_id, user_id)
        if not t.document_id:
            raise HTTPException(status_code=404, detail="暂无版本")
        from app.application.documents.service import DocumentService
        return DocumentService(self.db).get_version(t.document_id, version_no, user_id)

    def restore_version(self, task_id: str, user_id: str,
                        version_no: int) -> Dict[str, Any]:
        """回退到指定历史版本。

        安全语义：回退前先把当前内容自动保存为一个新版本（不丢用户手改），
        再把目标版本内容恢复为当前内容并同样形成一个新版本。
        版本链只增不改，任何一步都可再次回退。
        """
        t = self._get_owned(task_id, user_id)
        if not t.document_id:
            raise HTTPException(status_code=404, detail="暂无版本")
        from app.application.documents.service import DocumentService
        ver = DocumentService(self.db).get_version(t.document_id, version_no, user_id)
        content = (ver.get("content") or "").strip()
        if not content:
            raise HTTPException(status_code=409, detail="该版本内容为空，无法回退")

        current = (t.current_content or "").strip()
        if current and current != content:
            # 回退前自动保存当前内容，防止手改内容丢失
            self.db.flush()
            self._snapshot(t, user_id, note=f"回退到 v{version_no} 前自动保存")

        t.current_content = content
        self.db.flush()
        _, new_ver = self._snapshot(t, user_id, note=f"回退到 v{version_no}")
        t.version_no = new_ver
        t.updated_at = now_local()
        self.db.commit()

        return {**self._to_dict(t),
                "reply": f"已回退到 v{version_no} 的内容；回退前的内容已自动保存为新版本 v{new_ver}，可随时再次回退。",
                "content_changed": True}

    @staticmethod
    def _tail_lines(content: str, n: int = 6) -> List[str]:
        """正文末尾的非空行（用于判断是否已自带落款/成文日期）。"""
        return [l.strip() for l in (content or "").split("\n") if l.strip()][-n:]

    def _render_docx(self, content: str, ctx: Dict[str, Any], red_header: bool):
        """把文本内容渲染为可编辑的带格式 docx（红头或普通排版）。

        落款去重：模型起草的正文按规范自带署名与成文日期，导出时若正文末尾
        已含落款行/日期，则不再用 ctx 中的发文机关/成文日期追加，避免出现两个落款。
        """
        from app.application.chat.docx_export import generate_official_document, markdown_to_docx
        # 兼容旧任务：历史正文可能把标题/主送也写进 current_content；
        # 导出前再次确定性去重，避免 Word 出现双标题/双主送。
        content = self._strip_leading_structural_fields(content, ctx)
        doc_number = ""
        if ctx.get("document_number_enabled") and ctx.get("document_number"):
            doc_number = ctx["document_number"]
        title = ctx.get("title") or "公文"

        # 只抽取连续尾部的独立署名/日期行，正文提及机关或日期不算落款。
        lines = content.rstrip().split("\n")
        signature = ctx.get("authority") or ""
        date_text = ctx.get("document_date") or ""
        while lines and not lines[-1].strip():
            lines.pop()
        if lines and DATE_TAIL_RE.fullmatch(lines[-1].strip()):
            date_text = lines.pop().strip()
        while lines and not lines[-1].strip():
            lines.pop()
        if lines and ((signature and lines[-1].strip() == signature)
                      or SIGNOFF_TAIL_RE.fullmatch(lines[-1].strip())):
            signature = lines.pop().strip()
        content = "\n".join(lines).rstrip()

        renderer = generate_official_document if red_header else markdown_to_docx
        buf = renderer(
            content=content, title=title, doc_number=doc_number,
            recipient=ctx.get("recipient") or "",
            signature=signature,
            date_text=date_text,
        ) if red_header else renderer(
            text=content, title=title, doc_number=doc_number,
            recipient=ctx.get("recipient") or "",
            signature=signature,
            date_text=date_text,
        )
        return buf, title

    def export_docx(self, task_id: str, user_id: str, red_header: bool = True):
        """导出当前内容。文号区域仅在 document_number_enabled 且有值时输出。"""
        from urllib.parse import quote
        t = self._get_owned(task_id, user_id)
        if not (t.current_content or "").strip():
            raise HTTPException(status_code=409, detail="暂无内容可导出")
        buf, title = self._render_docx(t.current_content, t.context or {}, red_header)
        return buf, quote(f"{title}.docx")

    def export_version_docx(self, task_id: str, user_id: str, version_no: int,
                            red_header: bool = True):
        """把某个历史版本导出为可编辑 docx（版本不再是纯文本）。"""
        from urllib.parse import quote
        t = self._get_owned(task_id, user_id)
        if not t.document_id:
            raise HTTPException(status_code=404, detail="暂无版本")
        from app.application.documents.service import DocumentService
        ver = DocumentService(self.db).get_version(t.document_id, version_no, user_id)
        content = (ver.get("content") or "").strip()
        if not content:
            raise HTTPException(status_code=409, detail="该版本内容为空")
        buf, title = self._render_docx(content, t.context or {}, red_header)
        return buf, quote(f"{title}_v{version_no}.docx")

    def add_to_training(self, task_id: str, user_id: str, final_content: str) -> Dict[str, Any]:
        """instruction + AI 初稿 + 人工最终稿 → 候选样本（pending_review）。"""
        from app.infrastructure.database.models.training import TrainingSampleModel
        t = self._get_owned(task_id, user_id)
        ctx = t.context or {}
        instruction = "起草" + (ctx.get("document_type") or "公文")
        if ctx.get("title"):
            instruction += f"：{ctx['title']}"
        if ctx.get("requirements"):
            instruction += f"（{ctx['requirements']}）"
        sample = TrainingSampleModel(
            instruction=instruction,
            input="",
            output=final_content,
            draft=t.ai_draft or "",
            source="writing_task",
            session_id=t.session_id,
            biz_type=ctx.get("document_type") or "writing",
            status="pending_review",
            created_by=user_id,
        )
        self.db.add(sample)
        self.db.commit()
        self.db.refresh(sample)
        return {"sample_id": sample.id, "status": sample.status}

    # ---------------- 内部 ----------------

    @staticmethod
    def _strip_leading_structural_fields(text: str, ctx: Dict[str, Any]) -> str:
        """正文只保存正文段落；标题/主送由结构化字段单独渲染。

        模型即使按旧提示重复输出标题、主送机关，也在这里确定性去重，
        避免桌面排版视图和 Word 导出出现“双标题/双主送”。
        只处理开头完全匹配的结构行，不碰正文中的同名引用。
        """
        if not text:
            return ""
        lines = text.splitlines()
        while lines and not lines[0].strip():
            lines.pop(0)

        title = (ctx.get("title") or task_parser.build_title(ctx) or "").strip()
        recipient = (ctx.get("recipient") or "").strip()

        if lines and title and lines[0].strip().rstrip("。") == title.rstrip("。"):
            lines.pop(0)
            while lines and not lines[0].strip():
                lines.pop(0)

        if lines and recipient:
            first = lines[0].strip()
            normalized = first.rstrip("：:").strip()
            if normalized == recipient.rstrip("：:").strip():
                lines.pop(0)
                while lines and not lines[0].strip():
                    lines.pop(0)

        return "\n".join(lines).strip()

    @staticmethod
    def _clean_markdown(text: str) -> str:
        """剥离模型可能输出的 Markdown 标记（公文应为纯文本排版）。"""
        if not text:
            return ""
        t = re.sub(r"(?m)^#{1,6}\s*", "", text)                 # 标题井号
        t = re.sub(r"\*\*(.+?)\*\*", r"\1", t)                  # 加粗
        t = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"\1", t)  # 斜体
        t = re.sub(r"(?m)^\s*---+\s*$", "", t)                   # 分隔线
        t = re.sub(r"(?m)^\s*[-*+]\s+", "", t)                   # 列表符
        t = re.sub(r"\n{3,}", "\n\n", t)                         # 多余空行
        return t.strip()

    def _build_draft_instruction(self, ctx: Dict[str, Any], outline_only: bool,
                                 template: Optional[Dict[str, Any]] = None) -> str:
        parts = ["请起草一份提纲。" if outline_only else "请起草一份完整材料。"]
        original_request = next((str(item.get("content") or "").strip()
                                 for item in ctx.get("history") or []
                                 if item.get("role") == "user" and item.get("content")), "")
        if original_request:
            parts.append(f"用户原始需求：{original_request}。")
        parts.append(f"当前日期：{_today_doc_date()}。只用于理解本次写作的时间背景，"
                     "不得把历史范文中的旧时间移植到本稿。")
        # 关联模板：把模板的结构/写作指导/篇幅作为起草依据（模板内容由管理员/用户预先配置，非模型编造）
        if template:
            parts.append(
                f"本任务显式选择了写作模板「{template.get('name', '')}」。"
                "模板用于约束文种边界、必要组成和文风，不是逐项填空表。"
                "应结合用户原话和本次材料重新组织内容；可按实际事项合并、拆分或改写"
                "参考小标题，但不得遗漏模板明确要求的必要部分。"
            )
            if template.get("writing_style"):
                parts.append(f"模板文风：{template['writing_style']}。")
            if template.get("writing_guide"):
                parts.append("模板写作指导：" + str(template["writing_guide"])[:1200])
            skeleton = template.get("body_skeleton") or template.get("structure") or []
            if isinstance(skeleton, list):
                sections = []
                for item in skeleton[:12]:
                    if isinstance(item, dict):
                        sections.append(str(item.get("name") or "") + "：" + str(item.get("guide") or ""))
                    elif isinstance(item, str):
                        sections.append(item)
                if sections:
                    parts.append("模板章节要点：\n" + "\n".join(sections)[:1600])
            if template.get("content_template"):
                parts.append(
                    "模板结构参考（只保留适合本任务的结构与规范句式，禁止照抄示例、"
                    "占位内容或虚构缺失事实）：\n"
                    + str(template["content_template"])[:1500]
                )
        if ctx.get("document_type"):
            parts.append(f"文种：{ctx['document_type']}。")
        derived_title = ctx.get("title") or task_parser.build_title(ctx)
        if derived_title:
            parts.append(f"标题：{derived_title}。")
        elif ctx.get("topic"):
            parts.append(f"主题：{ctx['topic']}。")
        if ctx.get("time_range"):
            parts.append(f"时间范围：{ctx['time_range']}。")
        if ctx.get("recipient"):
            parts.append(f"主送机关：{ctx['recipient']}。")
        if ctx.get("authority"):
            parts.append(f"落款单位：{ctx['authority']}。")
        if ctx.get("key_facts"):
            parts.append("主要工作内容：" + "、".join(ctx["key_facts"]) + "。")
        if ctx.get("requirements"):
            parts.append(f"写作要求：{ctx['requirements']}。")
        if ctx.get("word_count_target"):
            parts.append(f"全文约 {ctx['word_count_target']} 字。")
        elif template and template.get("word_count"):
            parts.append(f"全文约 {template['word_count']} 字。")
        if ctx.get("tone"):
            parts.append(f"语气风格：{ctx['tone']}。")
        if not outline_only:
            doc_type = str(ctx.get("document_type") or "")
            original_request = original_request or str(ctx.get("requirements") or "")
            wants_sections = any(cue in original_request for cue in ("小标题", "分章节", "分节", "分条", "一二三"))
            if doc_type == "函":
                length_rule = (
                    "3) 函件务必简明，"
                    + ("全文按用户指定字数执行，字数必须通过把每段写实写足来达标，"
                       "严禁靠增加章节条目凑字数；" if ctx.get("word_count_target")
                       else "一般控制为 3-5 个自然段或部分，通常控制在 800-1200 字，"
                            "能合并的事项不要拆成多条；")
                    + "无论字数要求多少，一级条目不得超过 5 个；"
                    "不得套用总结、报告的长篇结构；\n"
                )
                ending_rule = (
                    "10) 函件不得使用书信式“此致、敬礼”，结尾用规范公文函结语："
                    "告知类用“特此函告。”，商请/请批类用“特此函请，请予支持。”"
                    "或“请予拨付为盼。”；\n"
                    "11) 函是平级或不相隶属机关之间的商洽文种，正文不得用下行文口气"
                    "（不得用“我局决定……现将……函告如下”来表达请求事项）；"
                    "凡涉及请对方拨款、审批、配合的事项，必须明确写出"
                    "“请予……”“望予……”“……为盼”等商请表述；\n"
                )
            elif any(kind in doc_type for kind in ("致辞", "讲话", "发言", "主持词")) and not wants_sections:
                length_rule = (
                    "3) 这是现场宣读的致辞或讲话，按自然段推进：向听众开场，紧扣活动主题，"
                    "表达认识与期待，最后自然致谢或祝愿；不要写成工作方案、实施步骤、"
                    "责任分工或报告式成效清单；\n"
                )
                ending_rule = ""
            else:
                length_rule = "3) 按文种组织必要结构，避免机械凑章节；除用户另有字数要求外，以完整、精炼为准；\n"
                ending_rule = ""
            if any(kind in doc_type for kind in ("致辞", "讲话", "发言", "主持词")) and not wants_sections:
                structure_rule = "按现场讲话体例写连贯自然段，不硬设公文章节标题；\n"
            elif doc_type in task_parser.FORMAL_DOC_TYPES:
                structure_rule = (
                    "正文按事项分条时，层级依次采用“一、”“（一）”“1．”“（1）”，"
                    "按实际需要使用，不必凑齐四级；事项超过 3 条时不得写成连续叙述段落，"
                    "也不要给短材料机械增加章节；\n"
                )
            else:
                structure_rule = "按用户要求和该文种的自然体例组织段落；有明确结构要求时照办，不套公文层级；\n"
            boundary_rule = (
                "通知围绕具体事项和工作要求行文，不得把通知写成工作要点，"
                "不得把报送事项扩写成全年工作部署；\n"
                if doc_type == "通知" else ""
            )
            metadata_rule = (
                "8) 当前文件的文号与成文日期由系统程序处理，正文不要输出文号或日期占位符；\n"
                if doc_type in task_parser.FORMAL_DOC_TYPES else
                "8) 不添加与本次文种无关的文号、落款或日期占位符；\n"
            )
            parts.append(
                "\n严格要求：\n"
                "1) 必须输出完整正文，禁止只输出提纲或片段；\n"
                "2) 标题由系统单独排版；正文从第一段开始，不重复系统已有的结构字段；\n"
                + length_rule +
                "4) 禁止使用任何 Markdown 标记：不要 ###、####、**、---、-、* 等；\n"
                "5) 直接以纯文本输出，段落之间用一个空行分隔；\n"
                + structure_rule +
                boundary_rule +
                "6) 语气、措辞和结构符合本次文种与使用场景；知识库同类范文仅供参考写法，不照抄事实和段落；\n"
                "7) 严禁编造具体信息：不得虚构联系人姓名、联系电话、邮箱地址、网址；"
                "材料未提供这类可选字段时直接省略，不得输出 XX/xx/XXXX 等占位符；\n"
                + metadata_rule +
                "9) 严格遵守用户确认的文种与内容边界，不得把一种文种写成另一种；\n"
                + ending_rule +
                "12) 外部事实（姓名、电话、文号、统计数字、具体日期）必须有来源；"
                "工作思路、具体举措、责任分工、预期目标属于作者自主规划，应写实写具体。"
            )
        return "".join(parts)

    def _build_revise_prompt(self, current: str, instruction: str,
                             mode_desc: str, selection: Optional[str],
                             ctx: Dict[str, Any]) -> str:
        parts = [f"修改方式：{mode_desc}。", f"用户修改要求：{instruction}。"]
        if ctx.get("word_count_target"):
            parts.append(f"全文控制在 {ctx['word_count_target']} 字左右。")
        if selection:
            parts.append(f"只修改以下选中段落：\n「{selection}」\n其余内容原样保留。")
        parts.append(f"当前文档全文：\n{current}")
        return "\n".join(parts)

    def _postprocess(self, text: str, ctx: Dict[str, Any]):
        """文号/日期：用户指定 > 程序生成(仅当用户明确要文号且未给值) > 不注入。"""
        from app.application.writing.postprocessor import PostProcessor
        enabled = bool(ctx.get("document_number_enabled"))
        user_number = ctx.get("document_number") if enabled else None
        user_date = ctx.get("document_date")
        return PostProcessor(self.db).process(
            text,
            signoff_hint=ctx.get("authority"),
            doc_number=user_number,
            doc_date=user_date,
            inject_docnum=enabled and not user_number,
            inject_date=True,
            document_type=ctx.get("document_type"),
        )

    def _retrieve(self, ctx: Dict[str, Any], user_id: str,
                  extra_query: str = "") -> List[Dict]:
        if not self.rag:
            return []
        original_request = next((str(item.get("content") or "").strip()
                                 for item in ctx.get("history") or []
                                 if item.get("role") == "user" and item.get("content")), "")
        query = " ".join(filter(None, [
            ctx.get("document_type"), ctx.get("title"), ctx.get("topic"),
            ctx.get("purpose"), ctx.get("time_range"), original_request,
            extra_query,
        ])) or (ctx.get("requirements") or "")
        if not query.strip():
            return []
        try:
            kb_ids = ctx.get("kb_ids") or None  # 关联知识库时限定检索范围
            sources = self.rag.search(query=query, user_id=user_id, kb_ids=kb_ids) or []
            doc_type = str(ctx.get("document_type") or "").strip()
            if doc_type:
                try:
                    norm_query = (f"{doc_type} 写作规范 公文格式" if
                                  doc_type in task_parser.FORMAL_DOC_TYPES else
                                  f"{doc_type} 写作规范 体例风格")
                    norms = self.rag.search(
                        query=norm_query, user_id=user_id,
                        kb_ids=kb_ids, top_k=3,
                    ) or []
                    seen = {item.get("chunk_id") or (item.get("doc_id"), item.get("source"))
                            for item in sources}
                    for item in norms:
                        key = item.get("chunk_id") or (item.get("doc_id"), item.get("source"))
                        if key not in seen:
                            sources.append(item)
                            seen.add(key)
                except Exception as e:
                    logger.warning("[写作任务] 规范检索失败: %s", e)
            return sources
        except Exception as e:
            self._rag_failed = True
            logger.warning("[写作任务] RAG 检索失败: %s", e)
            return []

    def _attachment_context(self, t, ctx) -> Optional[str]:
        if not self.attachments or not t.session_id:
            return None
        try:
            atts = self.attachments.get_session_attachments(t.session_id, self.db)
            return self.attachments.build_attachment_context(
                atts, query=ctx.get("title") or ctx.get("topic")
            ) or None
        except Exception as e:
            logger.warning("[写作任务] 附件上下文失败: %s", e)
            return None

    def _agent_prompt(self, user_id: str) -> str:
        """科室 Agent 上下文：让同一底层模型带上本科室的业务口径与知识边界。"""
        try:
            from app.application.organization.service import OrganizationService
            return OrganizationService(self.db).agent_system_prompt(user_id) or ""
        except Exception as e:
            logger.warning("[写作任务] 科室 Agent 上下文加载失败: %s", e)
            return ""

    # 模板系统提示的注入上限。此前写死800 字会把专业模板的尾部约束
    # （禁忌与事实纪律）整段砍掉——那恰恰是最该被执行的部分。
    # 模板始终是**可选增强**：不绑模板时这里什么都不加，模型按通用规则自由生成。
    TEMPLATE_PROMPT_MAX_CHARS = 4000

    def _draft_system(self, user_id: str,
                      template: Optional[Dict[str, Any]] = None) -> str:
        """起草系统提示（draft 与 draft_stream 共用）。

        模板是可选的：不传 template 时只返回通用起草规则，模型按其自身判断
        组织文种与结构；绑了模板才在其后追加该文种的专门要求。
        """
        agent = self._agent_prompt(user_id)
        system = (agent + "\n" if agent else "") + DRAFT_RULES
        if template and template.get("system_prompt"):
            prompt = str(template["system_prompt"]).strip()
            if len(prompt) > self.TEMPLATE_PROMPT_MAX_CHARS:
                prompt = prompt[:self.TEMPLATE_PROMPT_MAX_CHARS] + "\n（模板要求已截断）"
            system = system + "\n\n模板附加要求（用户已主动选择该文种模板）：\n" + prompt
        return system

    def _llm_draft(self, instruction: str, sources, attachment_ctx, user_id,
                   template: Optional[Dict[str, Any]] = None) -> str:
        if not self.assistant:
            raise HTTPException(status_code=503, detail="模型服务不可用")
        return self.assistant.chat(
            message=instruction, history=[], sources=sources, user_role="user",
            system_prompt=self._draft_system(user_id, template),
            attachment_context=attachment_ctx,
        ) or ""

    def _llm_draft_stream(self, instruction: str, sources, attachment_ctx, user_id,
                          template: Optional[Dict[str, Any]] = None) -> Iterator[str]:
        """流式起草：网关不支持流式时由 assistant 降级为一次性输出。"""
        if not self.assistant:
            raise HTTPException(status_code=503, detail="模型服务不可用")
        return self.assistant.chat_stream(
            message=instruction, history=[], sources=sources, user_role="user",
            system_prompt=self._draft_system(user_id, template),
            attachment_context=attachment_ctx,
        )

    def _llm_revise(self, prompt: str, sources, attachment_ctx, user_id) -> str:
        if not self.assistant:
            raise HTTPException(status_code=503, detail="模型服务不可用")
        agent = self._agent_prompt(user_id)
        system = (agent + "\n" if agent else "") + REVISION_RULES
        return self.assistant.chat(
            message=prompt, history=[], sources=sources, user_role="user",
            system_prompt=system, attachment_context=attachment_ctx,
        ) or ""

    def _snapshot(self, t, user_id: str, note: str, *, commit: bool = True):
        """把当前内容写入 documents 版本链，返回 (document_id, version_no)。"""
        from app.application.documents.dto import DocumentCreateRequest, DocumentSaveRequest
        from app.application.documents.service import DocumentService
        svc = DocumentService(self.db)
        ctx = t.context or {}
        if t.document_id:
            doc = svc.save_version(t.document_id, user_id, DocumentSaveRequest(
                content=t.current_content, title=ctx.get("title"), note=note),
                commit=commit)
            return doc["id"], doc["current_version"]
        doc = svc.create_document(user_id, DocumentCreateRequest(
            title=ctx.get("title") or "未命名文档",
            content=t.current_content,
            doc_type=ctx.get("document_type"),
            document_number=ctx.get("document_number"),
            document_date=ctx.get("document_date"),
            session_id=t.session_id,
            note=note,
        ), commit=commit)
        return doc["id"], doc["current_version"]
