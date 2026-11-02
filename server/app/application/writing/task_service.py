"""写作任务服务：Writing Task 全生命周期。

本类是**基类**，保留成熟的版本/RAG/导出/结构字段链路。内容生成（起草、整篇改写、局部修改、
任务内对话）只有异步实现，位于 ``async_task_service``；这里不再保留同步副本。

核心原则：
- 任务上下文结构化，识别不出的字段为 None，绝不虚构；
- 文号默认关闭；成文日期由用户确认后交给程序排版，起草时不猜测签发日期；
- revise 是"对当前文档的修改"，明确告知模型不得重新起草、不得改变事实；
- 每次 AI 修改自动形成版本（复用 documents 版本快照）；
- 所有查询按 user_id 隔离；
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
from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.application.writing import task_parser
from app.application.writing.section_policy import brief_length_range, is_speech_type
from app.application.writing.finalize_pipeline import finalize_text, persist_revision
from app.application.documents.formatting import effective_formatting
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
    "5. 标题由系统结构化排版；主送机关行属于正文的一部分，原样保留（除非用户要求修改）；"
    "输出修改后的正文主体，不要在正文开头重复标题，不要解释、不要加前后缀。"
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
    "5. 标题由系统统一管理，正文不要重复标题；主送机关行是否书写由你按文种规范判断"
    "（通知、函、请示、报告等通常需要主送机关，宣传材料、讲话稿等不需要），"
    "需要时写在正文最前面，格式为单独一行「××：」；"
    "任何情况下都不要输出「报送对象：」「主送机关：」这类字段标签或空标签行；"
    "落款和成文日期仍由系统字段管理，正文不要写。其他文种按自身体例行文，不添加无关的公文套式；\n"
    "6. 不编造文号或成文日期；成文日期只有用户确认后才由系统排版，正文不要另写；"
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

# 模型残留的字段标签行（「报送对象：」「主送机关：××」）：不是正文，确定性剥掉。
# 「各有关单位：」这类规范主送行不带字段标签，属于正文，不在此列。
_RECIPIENT_LABEL_LINE_RE = re.compile(
    r"^(?:报送对象|主送机关|主送|发文对象|收文单位)(?:\s*[：:]|$)"
)


def _sse(event: Dict[str, Any]) -> str:
    """一条 SSE 事件行。"""
    return "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"


class WritingTaskService:
    def __init__(self, db: Session, assistant=None, rag=None, attachments=None):
        self.db = db
        self.assistant = assistant
        self.rag = rag
        self.attachments = attachments

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
            "reference_items": list((t.context or {}).get("reference_items") or []),
            "formatting": effective_formatting(
                t.current_content or "", (t.context or {}).get("formatting")),
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

    @classmethod
    def _reference_items(cls, sources: List[Dict]) -> List[Dict[str, str]]:
        """保留检索命中的真实文档 ID，客户端可经鉴权接口查看原文。"""
        labels = cls._reference_labels(sources)
        grouped: Dict[str, str] = {}
        for source in sources or []:
            title = cls._CHUNK_SUFFIX_RE.sub("", str(source.get("source") or "")).strip()
            doc_id = str(source.get("doc_id") or "")
            if title and doc_id and title not in grouped:
                grouped[title] = doc_id
        return [{"title": label, "doc_id": grouped.get(
            re.sub(r"（命中 \d+ 段）$", "", label), "")} for label in labels]

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
        allowed = set(task_parser.empty_context().keys()) - {"word_count_source"}
        for k, v in patch.items():
            if k in allowed:
                ctx[k] = v
        if "word_count_target" in patch:
            ctx["word_count_source"] = "user" if patch["word_count_target"] else None
            if "word_count_max" not in patch:
                ctx.pop("word_count_max", None)
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
        if not ctx.get("authority") and (doc_type in task_parser.FORMAL_DOC_TYPES or "通知" in doc_type):
            ctx["authority"] = self._default_authority() or None

    def _finalize_draft(self, t, ctx: Dict[str, Any], text: str,
                        sources: List[Dict], user_id: str) -> Dict[str, Any]:
        """起草收尾（draft 与 draft_stream 共用）：收尾 → 落库 → 版本快照。"""
        finalized = finalize_text(self, text, ctx, sources)
        version, _ = persist_revision(
            self, t, ctx, finalized.text, user_id,
            note="V1 AI 初稿" if t.version_no == 0 else f"V{t.version_no + 1} 继续生成",
            mark_editing=True,
        )

        quality = finalized.quality
        if version <= 1:
            reply = "已生成 V1 初稿（待完善）。"
        else:
            reply = (f"已按当前任务参数继续生成一版（v{version}），上一版仍在「历史版本」中可随时查看/回退；"
                     "不满意可先修改左侧参数再点「继续生成」。")
        if finalized.references:
            reply += f"本次检索到 {len(finalized.references)} 份内部资料作为写作依据。"
        if finalized.citation_warnings:
            reply += (
                f"系统发现 {len(finalized.citation_warnings)} 处无法从本次资料或用户输入核实的文号，"
                "已移除具体号码并改为“相关文件”，请在确认来源后再补回。"
            )
        if ctx.get("missing_fields"):
            reply += "以下内容因缺少事实依据已标注：" + "、".join(ctx["missing_fields"]) + "。"
        seed = t.current_content or ""
        reply += self._draft_followup(quality, ctx.get("missing_fields"), seed)
        return {**self._to_dict(t), "reply": reply, "content_changed": True,
                "quality": quality, "content_check": finalized.content_check,
                "postprocess_events": finalized.events, "references": finalized.references}

    # ---------------- 版本 / 导出 ----------------

    def save_version(self, task_id: str, user_id: str, content: str,
                     note: Optional[str] = None, formatting: Optional[Dict] = None) -> Dict[str, Any]:
        """用户手动保存当前编辑内容为新版本。"""
        t = self._get_owned(task_id, user_id)
        t.current_content = content
        if formatting is not None:
            from app.application.documents.formatting import normalize_formatting
            ctx = dict(t.context or {})
            ctx["formatting"] = normalize_formatting(content, formatting)
            t.context = ctx
        self.db.flush()
        doc_id, ver = self._snapshot(t, user_id, note=note or "人工编辑")
        t.document_id = doc_id
        t.version_no = ver
        t.updated_at = now_local()
        self.db.commit()
        from app.application.documents.formatting import format_warnings
        return {**self._to_dict(t), "format_warnings": format_warnings(
            content, (t.context or {}).get("formatting"),
            str((t.context or {}).get("document_type") or ""))}

    def list_versions(self, task_id: str, user_id: str) -> List[Dict[str, Any]]:
        t = self._get_owned(task_id, user_id)
        if not t.document_id:
            return []
        from app.application.documents.service import DocumentService
        doc = DocumentService(self.db).get_document(t.document_id, user_id)
        return doc["versions"]

    def check_current_format(self, task_id: str, user_id: str) -> Dict[str, Any]:
        """按该用户当前启用的 Word 格式规则检查已保存稿，不调用模型、不创建记录。"""
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from app.application.format_check.service import FormatCheckService, _rule_to_dict
        from app.application.documents.formatting import OFFICIAL_TYPES

        task = self._get_owned(task_id, user_id)
        if str((task.context or {}).get("document_type") or "") not in OFFICIAL_TYPES:
            return {"issues": [], "issue_count": 0, "skipped": "非标准公文材料"}
        service = FormatCheckService(self.db, assistant=None, rag=None)
        service.rules.ensure_user_defaults(user_id)
        rules = [_rule_to_dict(rule) for rule in service.rules.list_for_check(user_id, None)
                 if rule.target != "ppt"]
        if not rules:
            return {"issues": [], "issue_count": 0, "skipped": "未启用校验规则"}
        buffer, _ = self._render_docx(task.current_content or "", task.context or {}, False)
        with TemporaryDirectory(prefix="writing-format-") as temp_dir:
            path = Path(temp_dir) / "draft.docx"
            path.write_bytes(buffer.getvalue())
            result = service.engine.check_file(path, "draft.docx", rules, use_ai=False)
        issues = result.get("issues") or []
        return {"issues": issues, "issue_count": len(issues)}

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
        ctx = dict(t.context or {})
        ctx["formatting"] = ver.get("formatting")
        t.context = ctx
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
        from app.application.documents.formatting import remap_formatting
        original_content = content
        formatting = effective_formatting(content, ctx.get("formatting"))
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
        formatting = remap_formatting(original_content, content, formatting)

        renderer = generate_official_document if red_header else markdown_to_docx
        # 主送机关行已回归正文（由模型按文种判断书写），导出不再用字段另渲染一次，
        # 否则正文主送 + chrome 主送会出现双主送。
        buf = renderer(
            content=content, title=title, doc_number=doc_number,
            signature=signature,
            date_text=date_text,
            formatting=formatting,
        ) if red_header else renderer(
            text=content, title=title, doc_number=doc_number,
            signature=signature,
            date_text=date_text,
            formatting=formatting,
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
        buf, title = self._render_docx(content, {**(t.context or {}),
            "formatting": ver.get("formatting")}, red_header)
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

        if lines and title and lines[0].strip().rstrip("。") == title.rstrip("。"):
            lines.pop(0)
            while lines and not lines[0].strip():
                lines.pop(0)

        # 主送机关行回归正文（由模型按文种判断书写），这里只剥掉字段标签垃圾行；
        # 「各有关单位：」这类规范主送行属于正文，不再剥掉。
        while lines and lines[0].strip() and _RECIPIENT_LABEL_LINE_RE.match(lines[0].strip()):
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

    def _effective_draft_context(self, ctx: Dict[str, Any],
                                 template: Optional[Dict[str, Any]],
                                 user_id: str = "") -> Dict[str, Any]:
        """Use the selected template's length for every generation path.

        Keep the task's saved context untouched; a later explicit user target
        must always take precedence over the template default.
        """
        effective = dict(ctx)
        model_target = None
        if effective.get("word_count_source") == "model":
            model_target = effective.pop("word_count_target", None)
        if (user_id and not effective.get("word_count_target")
                and getattr(self, "rag", None) and ctx.get("document_type")):
            try:
                rng = self.rag.exemplar_length_range(
                    user_id,
                    str(ctx["document_type"]), ctx.get("kb_ids") or None)
                if rng:
                    effective["reference_length_range"] = list(rng)
                    effective["word_count_target"] = (rng[0] + rng[1]) // 2
                    effective["word_count_source"] = "knowledge"
            except Exception as exc:
                logger.warning("同类范文篇幅查询失败，使用模板/常规篇幅: %s", type(exc).__name__)
        if not effective.get("word_count_target") and template:
            try:
                target = int(template.get("word_count") or 0)
            except (TypeError, ValueError):
                target = 0
            if target > 0:
                effective["word_count_target"] = target
                effective["word_count_source"] = "template"
        if (not effective.get("word_count_target") and model_target
                and not brief_length_range(str(effective.get("document_type") or ""))):
            effective["word_count_target"] = model_target
        return effective

    def _build_draft_instruction(self, ctx: Dict[str, Any], outline_only: bool,
                                 template: Optional[Dict[str, Any]] = None) -> str:
        parts = ["请起草一份提纲。" if outline_only else "请起草一份完整材料。"]
        original_request = next((str(item.get("content") or "").strip()
                                 for item in ctx.get("history") or []
                                 if item.get("role") == "user" and item.get("content")), "")
        if original_request:
            parts.append(f"用户原始需求：{original_request}。")
        parts.append(f"当前日期：{_today_doc_date()}。只用于理解本次写作的时间背景，"
                     "不得据此编造会议召开时间或成文日期，不得把历史范文中的旧时间移植到本稿。")
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
            # 主送不再写死渲染：交给模型按文种判断（宣传材料/讲话稿等不需要称呼）。
            parts.append(
                f"报送对象（供参考，是否写入由你按文种规范判断）：{ctx['recipient']}。"
                "本文种需要主送机关的，在正文最前面输出一行规范主送（如「各有关单位：」）；"
                "不需要的就不要输出主送行；"
                "绝不要输出「报送对象：」「主送机关：」这类字段标签或空标签行。"
            )
        if ctx.get("authority"):
            parts.append(f"落款单位：{ctx['authority']}。")
        if ctx.get("key_facts"):
            parts.append("主要工作内容：" + "、".join(ctx["key_facts"]) + "。")
        if ctx.get("requirements"):
            parts.append(f"写作要求：{ctx['requirements']}。")
        doc_type = str(ctx.get("document_type") or "")
        explicit_target = ctx.get("word_count_target")
        target = explicit_target or (template or {}).get("word_count")
        if target and not outline_only:
            try:
                target = max(50, min(100000, int(target)))
            except (TypeError, ValueError):
                target = None
        if target:
            if outline_only:
                parts.append(f"后续成稿的目标篇幅约 {target} 字；本次只输出提纲。")
            else:
                origin = ("知识库同类文" if ctx.get("reference_length_range") else "本次要求/模板")
                parts.append(
                    f"正文目标约 {target} 字（依据：{origin}；不计标题、主送、落款和日期）。"
                    "按事项的重要程度分配各部分篇幅，写足必要事实、措施与执行要求；"
                    "短文不硬拆章节，长文不靠套话和重复段落凑字数。"
                    "用户另有明确篇幅或压缩要求时以本次要求为准。"
                )
                if ctx.get("reference_length_range"):
                    low, high = ctx["reference_length_range"]
                    parts.append(f"同文种知识库材料的参考篇幅为 {low}-{high} 字，"
                                 "仅作篇幅和体例参考，不复制其中的事实、姓名和日期。")
                if ctx.get("word_count_max"):
                    parts.append(f"用户要求的硬上限：正文不得超过 {ctx['word_count_max']} 字。")
        elif not outline_only:
            # 用户没给字数、也没有模板可参照时，给一个文种惯例区间作锚点。
            # 缺了这段，35B 对「通知」没有篇幅概念，会写成上千字的年度方案。
            rng = brief_length_range(doc_type)
            if rng:
                parts.append(
                    f"正文篇幅按{doc_type}的常规体例控制，通常 {rng[0]}-{rng[1]} 字"
                    "（不计标题、主送、落款和日期）。"
                    "写清发文缘由、具体事项和执行要求（含时限、责任单位）即收束；"
                    "不铺陈工作背景，不展开年度任务部署，不增设无实质内容的章节。"
                    "用户另有明确篇幅要求时以本次要求为准。"
                )
        if template:
            parts.append(
                "按所选文种写作：法定公文遵循党政机关公文格式及该文种的行文规则，"
                "不把模板示例中的机关、数字、日期或政策名称当作本次事实；"
                "标题、主送、落款和成文日期按文种及用户提供的信息判断，"
                "不输出空字段标签，也不为讲话稿等非公文材料强加公文落款。"
            )
        if ctx.get("tone"):
            parts.append(f"语气风格：{ctx['tone']}。")
        if not outline_only:
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
            elif is_speech_type(doc_type) and not wants_sections:
                length_rule = (
                    "3) 这是现场宣读的致辞或讲话，按自然段推进：向听众开场，紧扣活动主题，"
                    "表达认识与期待，最后自然致谢或祝愿；不要写成工作方案、实施步骤、"
                    "责任分工或报告式成效清单；\n"
                )
                ending_rule = ""
            else:
                brief_rng = brief_length_range(doc_type)
                if brief_rng and explicit_target:
                    length_rule = (
                        f"3) {doc_type}是一事一文的文种：按用户指定字数写足，"
                        "字数要通过把每件事写实写细来达标，不得靠增加章节条目凑字数；\n"
                    )
                elif brief_rng:
                    length_rule = (
                        f"3) {doc_type}是一事一文的文种：发文缘由一两句交代清楚，"
                        "具体事项逐条写实（时间、地点、对象、办理方式、报送时限），"
                        "按上文篇幅执行；不铺陈工作背景，不罗列全年任务，"
                        "不设“加强领导”“督导考核”式空泛章节；\n"
                    )
                else:
                    length_rule = "3) 按文种组织必要结构，避免机械凑章节；除用户另有字数要求外，以完整、精炼为准；\n"
                ending_rule = ""
            if is_speech_type(doc_type) and not wants_sections:
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
                "8) 文号由系统管理；成文日期仅在用户明确提供后由系统排版。"
                "正文不要输出文号、成文日期或日期占位符；会议时间属于正文事实，未知时不得编造；\n"
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
            if ctx.get("word_count_max"):
                parts.append(f"全文不得超过 {ctx['word_count_max']} 字，不计标题、主送、落款和日期。")
            else:
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
            inject_date=False,
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

    def _snapshot(self, t, user_id: str, note: str, *, commit: bool = True):
        """把当前内容写入 documents 版本链，返回 (document_id, version_no)。"""
        from app.application.documents.dto import DocumentCreateRequest, DocumentSaveRequest
        from app.application.documents.service import DocumentService
        svc = DocumentService(self.db)
        ctx = t.context or {}
        stored = ctx.get("formatting")
        formatting = effective_formatting(t.current_content or "", stored)
        formatting = formatting if formatting != {
            "title": {}, "paragraphs": {}} else None
        if t.document_id:
            doc = svc.save_version(t.document_id, user_id, DocumentSaveRequest(
                content=t.current_content, title=ctx.get("title"), note=note,
                formatting=formatting),
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
            formatting=formatting,
        ), commit=commit)
        return doc["id"], doc["current_version"]
