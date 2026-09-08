"""写作任务服务：Writing Task 全生命周期。

核心原则：
- 任务上下文结构化，识别不出的字段为 None，绝不虚构；
- 文号/成文日期默认关闭，只有用户明确要求才启用（用户指定值原样使用）；
- revise 是"对当前文档的修改"，明确告知模型不得重新起草、不得改变事实；
- 每次 AI 修改自动形成版本（复用 documents 版本快照）；
- 所有查询按 user_id 隔离。
"""
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.application.writing import task_parser
from app.core.config import settings

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

REVISION_RULES = (
    "这是一个【已有文档修改】任务，不是新的起草请求。必须遵守：\n"
    "1. 只修改用户要求的部分，其余内容原样保留，不得重新生成全文；\n"
    "2. 不得改变或删除用户未要求修改的事实；\n"
    "3. 不得虚构数据、成效或日期，材料中没有的具体数据用「⚠️ 缺少事实依据」标注；\n"
    "4. 直接输出修改后的完整公文，不要解释、不要加前后缀。"
)

DRAFT_RULES = (
    "这是公文起草任务。要求：\n"
    "1. 不要编造文号，不要写文号行；\n"
    "2. 不要编造具体数据和成效，材料中没有的用「⚠️ 缺少事实依据」标注；\n"
    "3. 结构完整：标题、主送（如适用）、正文、落款（如适用）。"
)


class WritingTaskService:
    def __init__(self, db: Session, assistant=None, rag=None, attachments=None):
        self.db = db
        self.assistant = assistant
        self.rag = rag
        self.attachments = attachments

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
            "current_content": t.current_content or "",
            "version_no": t.version_no or 0,
            "status": t.status,
            "char_count": len(t.current_content or ""),
            "created_at": t.created_at.isoformat() if t.created_at else None,
            "updated_at": t.updated_at.isoformat() if t.updated_at else None,
        }

    def create_task(self, user_id: str, message: str,
                    session_id: Optional[str] = None) -> Dict[str, Any]:
        """从自然语言初始化任务：解析要素 -> 建任务 -> 返回上下文与追问。"""
        from app.infrastructure.database.models.writing_task import WritingTaskModel

        ctx = task_parser.empty_context()
        changes = task_parser.merge_context(ctx, task_parser.parse_message(message))
        missing = task_parser.compute_missing(ctx)
        title = task_parser.build_title(ctx)
        if title:
            ctx["title"] = title

        t = WritingTaskModel(user_id=user_id, session_id=session_id,
                             context=ctx, status="collecting")
        self.db.add(t)
        self.db.commit()
        self.db.refresh(t)

        reply = self._collecting_reply(ctx, changes, missing, message)
        return {**self._to_dict(t), "reply": reply, "content_changed": False}

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
        task_parser.compute_missing(ctx)
        t.context = ctx
        t.updated_at = datetime.utcnow()
        self.db.commit()
        return self._to_dict(t)

    # ---------------- 对话（任务内持续对话） ----------------

    def chat(self, task_id: str, user_id: str, message: str) -> Dict[str, Any]:
        """任务内对话：更新上下文，或触发起草/修改，或追问缺失信息。"""
        t = self._get_owned(task_id, user_id)
        ctx = dict(t.context or {})

        # 1. 解析并合并要素
        changes = task_parser.merge_context(ctx, task_parser.parse_message(message))
        missing = task_parser.compute_missing(ctx)
        title = task_parser.build_title(ctx)
        if title and not ctx.get("title"):
            ctx["title"] = title
            changes.append(f"标题：{title}")

        # 2. 决策：修改当前稿 > 起草 > 继续追问
        if (t.current_content or "").strip() and task_parser.looks_like_revise(message):
            result = self.revise(task_id, user_id, instruction=message, mode="revise")
            result["context_changes"] = changes
            return result

        if task_parser.looks_like_draft(message) and not (t.current_content or "").strip():
            result = self.draft(task_id, user_id)
            result["context_changes"] = changes
            return result

        # 3. 信息收集对话
        t.context = ctx
        t.updated_at = datetime.utcnow()
        self.db.commit()
        reply = self._collecting_reply(ctx, changes, missing, message)
        return {**self._to_dict(t), "reply": reply, "content_changed": False,
                "context_changes": changes}

    def _collecting_reply(self, ctx, changes, missing, message) -> str:
        parts: List[str] = []
        if changes:
            parts.append("已更新任务信息：" + "；".join(changes) + "。")
        known = []
        if ctx.get("document_type"):
            known.append(f"文种是{ctx['document_type']}")
        if ctx.get("topic"):
            known.append(f"主题是{ctx['topic']}")
        if ctx.get("time_range"):
            known.append(f"时间范围是{ctx['time_range']}")
        if not parts:
            if known:
                parts.append("好的，目前我知道：" + "，".join(known) + "。")
            else:
                parts.append("好的，我先记下您的写作需求。")
        if missing:
            parts.append("为了让初稿更准确，还需要补充：" + "、".join(missing) +
                         "。如果暂时没有材料，回复「先写一版」我可以先搭建框架。")
        else:
            parts.append("关键信息已齐，回复「起草」即可生成第一版草稿。")
        return "".join(parts)

    # ---------------- 起草 ----------------

    def draft(self, task_id: str, user_id: str,
              outline_only: bool = False) -> Dict[str, Any]:
        t = self._get_owned(task_id, user_id)
        ctx = dict(t.context or {})
        instruction = self._build_draft_instruction(ctx, outline_only)
        sources = self._retrieve(ctx, user_id)
        attachment_ctx = self._attachment_context(t, ctx)

        text = self._llm_draft(instruction, sources, attachment_ctx, user_id)
        if not text.strip():
            raise HTTPException(status_code=502, detail="模型未返回内容，请重试")

        # 后处理：文号/日期按任务开关决定，默认不注入
        text, events, doc_number, doc_date = self._postprocess(text, ctx)
        from app.application.writing.quality_gate import QualityGate
        quality = QualityGate().evaluate(text, topic=ctx.get("title") or ctx.get("topic") or "")

        if doc_number:
            ctx["document_number"] = doc_number
        if doc_date:
            ctx["document_date"] = doc_date
        t.context = ctx
        t.current_content = text
        if not t.ai_draft:
            t.ai_draft = text
        t.status = "editing"
        self.db.flush()
        doc_id, ver = self._snapshot(t, user_id, note="V1 AI 初稿" if t.version_no == 0 else "重新生成")
        t.document_id = doc_id
        t.version_no = ver
        t.updated_at = datetime.utcnow()
        self.db.commit()

        reply = "已生成 V1 初稿（待完善）。"
        if sources:
            reply += f"本次检索到 {len(sources)} 份内部资料作为写作依据。"
        if ctx.get("missing_fields"):
            reply += "以下内容因缺少事实依据已标注：" + "、".join(ctx["missing_fields"]) + "。"
        reply += "您可以继续对话修改，或直接编辑正文后保存版本。"
        return {**self._to_dict(t), "reply": reply, "content_changed": True,
                "quality": quality, "postprocess_events": events,
                "references": [s.get("source", "") for s in sources if s.get("source")]}

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

        revised, events, doc_number, doc_date = self._postprocess(revised, ctx)
        from app.application.writing.quality_gate import QualityGate
        quality = QualityGate().evaluate(revised, topic=ctx.get("title") or "")

        # 上下文同步（例如"不要文号"这类指令）
        changes = task_parser.merge_context(ctx, task_parser.parse_message(instruction))
        task_parser.compute_missing(ctx)
        if doc_number:
            ctx["document_number"] = doc_number
        if doc_date:
            ctx["document_date"] = doc_date
        t.context = ctx

        t.current_content = revised
        self.db.flush()
        _, ver = self._snapshot(t, user_id, note=f"AI 修改：{instruction[:30]}")
        t.version_no = ver
        t.updated_at = datetime.utcnow()
        self.db.commit()

        reply = f"已按您的要求修改当前文档（{mode_desc.split('：')[0]}），保存为 v{ver}。"
        if changes:
            reply += "任务信息同步更新：" + "；".join(changes) + "。"
        return {**self._to_dict(t), "reply": reply, "content_changed": True,
                "quality": quality, "postprocess_events": events, "context_changes": changes}

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
        t.updated_at = datetime.utcnow()
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

    def export_docx(self, task_id: str, user_id: str, red_header: bool = True):
        """导出当前内容。文号区域仅在 document_number_enabled 且有值时输出。"""
        from io import BytesIO
        from urllib.parse import quote
        from app.application.chat.docx_export import generate_official_document, markdown_to_docx

        t = self._get_owned(task_id, user_id)
        ctx = t.context or {}
        if not (t.current_content or "").strip():
            raise HTTPException(status_code=409, detail="暂无内容可导出")
        doc_number = ""
        if ctx.get("document_number_enabled") and ctx.get("document_number"):
            doc_number = ctx["document_number"]
        title = ctx.get("title") or "公文"
        if red_header:
            buf = generate_official_document(
                content=t.current_content, title=title, doc_number=doc_number,
                recipient=ctx.get("recipient") or "",
                signature=ctx.get("authority") or "",
                date_text=ctx.get("document_date") or "",
            )
        else:
            buf = markdown_to_docx(
                text=t.current_content, title=title, doc_number=doc_number,
                recipient=ctx.get("recipient") or "",
                signature=ctx.get("authority") or "",
                date_text=ctx.get("document_date") or "",
            )
        return buf, quote(f"{title}.docx")

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

    def _build_draft_instruction(self, ctx: Dict[str, Any], outline_only: bool) -> str:
        parts = ["请起草一份公文提纲。" if outline_only else "请起草一份公文。"]
        if ctx.get("document_type"):
            parts.append(f"文种：{ctx['document_type']}。")
        if ctx.get("title"):
            parts.append(f"标题：{ctx['title']}。")
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
        if ctx.get("tone"):
            parts.append(f"语气风格：{ctx['tone']}。")
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
            inject_date=bool(user_date),
        )

    def _retrieve(self, ctx: Dict[str, Any], user_id: str,
                  extra_query: str = "") -> List[Dict]:
        if not self.rag:
            return []
        query = " ".join(filter(None, [
            ctx.get("title"), ctx.get("topic"),
            ctx.get("time_range"), extra_query,
        ])) or (ctx.get("requirements") or "")
        if not query.strip():
            return []
        try:
            return self.rag.search(query=query, user_id=user_id) or []
        except Exception as e:
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

    def _llm_draft(self, instruction: str, sources, attachment_ctx, user_id) -> str:
        if not self.assistant:
            raise HTTPException(status_code=503, detail="模型服务不可用")
        system = DRAFT_RULES
        return self.assistant.chat(
            message=instruction, history=[], sources=sources, user_role="user",
            system_prompt=system, attachment_context=attachment_ctx,
        ) or ""

    def _llm_revise(self, prompt: str, sources, attachment_ctx, user_id) -> str:
        if not self.assistant:
            raise HTTPException(status_code=503, detail="模型服务不可用")
        return self.assistant.chat(
            message=prompt, history=[], sources=sources, user_role="user",
            system_prompt=REVISION_RULES, attachment_context=attachment_ctx,
        ) or ""

    def _snapshot(self, t, user_id: str, note: str):
        """把当前内容写入 documents 版本链，返回 (document_id, version_no)。"""
        from app.application.documents.dto import DocumentCreateRequest, DocumentSaveRequest
        from app.application.documents.service import DocumentService
        svc = DocumentService(self.db)
        ctx = t.context or {}
        if t.document_id:
            doc = svc.save_version(t.document_id, user_id, DocumentSaveRequest(
                content=t.current_content, title=ctx.get("title"), note=note))
            return doc["id"], doc["current_version"]
        doc = svc.create_document(user_id, DocumentCreateRequest(
            title=ctx.get("title") or "未命名文档",
            content=t.current_content,
            doc_type=ctx.get("document_type"),
            document_number=ctx.get("document_number"),
            document_date=ctx.get("document_date"),
            session_id=t.session_id,
            note=note,
        ))
        return doc["id"], doc["current_version"]
