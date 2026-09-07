"""对话用例编排（移植旧 api/chat.py /chat/send 的完整流程）。

流程：会话获取/创建 → 附件绑定与上下文 → 参考模板/参考材料上下文 →
写作意图澄清判断 → RAG 检索 + 范文检索 → WritingAssistant 生成 →
写作类请求追加智能写作流水线（后处理 → 质量门 → 内容校验 → D 级重试）→
消息入库 → 每 20 条消息触发会话总结。
"""
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.application.chat.attachment_service import AttachmentService
from app.application.chat.intent_service import IntentService
from app.application.chat.memory_service import MemoryService
from app.application.knowledge.rag_service import RagService
from app.application.shared.writing_assistant import WritingAssistant
from app.core.config import settings
from app.core.logging import get_logger
from app.domain.chat.entities import ChatMessage, ChatSession
from app.domain.identity.entities import User
from app.infrastructure.database.models.templates import WritingTemplateModel
from app.infrastructure.repositories.chat import (
    SqlAlchemyChatMessageRepository,
    SqlAlchemyChatSessionRepository,
)

logger = get_logger(__name__)

WRITING_KEYWORDS = ("写", "起草", "生成", "撰写", "拟")


class ChatService:
    def __init__(self, db: Session, assistant: WritingAssistant,
                 rag: RagService) -> None:
        self.db = db
        self.assistant = assistant
        self.rag = rag
        self.sessions = SqlAlchemyChatSessionRepository(db)
        self.messages = SqlAlchemyChatMessageRepository(db)
        self.attachments = AttachmentService(db)
        self.memory = MemoryService(assistant)
        self.intent = IntentService(assistant)

    def _load_reference_template(self, template_id: Optional[str]) -> Optional[dict]:
        """加载对话中选择的参考模板。找不到/已停用则返回 None。"""
        if not template_id:
            return None
        tmpl = self.db.get(WritingTemplateModel, template_id)
        if not tmpl or not tmpl.is_active:
            return None
        return {
            "id": tmpl.id,
            "name": tmpl.name,
            "content_template": tmpl.content_template,
            "system_prompt": tmpl.system_prompt,
            "writing_style": tmpl.writing_style,
            "word_count": tmpl.word_count,
            "need_red_header": tmpl.need_red_header,
            "need_signature": tmpl.need_signature,
            "need_date": tmpl.need_date,
            "need_doc_number": tmpl.need_doc_number,
            "keywords": tmpl.keywords,
        }

    def send_message(self, user: User, message: str, session_id: Optional[str] = None,
                     use_rag: bool = True, system_prompt: Optional[str] = None,
                     template_category: Optional[str] = None, source: str = "chat",
                     attachment_ids: Optional[List[str]] = None,
                     reference_template_id: Optional[str] = None,
                     task_reference_ids: Optional[List[str]] = None) -> dict:
        # 获取或创建会话
        session = None
        if session_id:
            session = self.sessions.get_for_user(session_id, user.id)
        if not session:
            session = self.sessions.add(ChatSession(user_id=user.id, title=message[:30]))

        # 附件：绑定到会话并构建上下文（多轮对话持续注入）
        new_attachments = []
        if attachment_ids:
            new_attachments = self.attachments.get_attachments(attachment_ids, user.id, self.db)
            self.attachments.bind_to_session(attachment_ids, session.id, user.id, self.db)

        session_attachments = self.attachments.get_session_attachments(session.id, self.db)
        attachment_context = self.attachments.build_attachment_context(
            session_attachments, query=message
        )

        reference_template = self._load_reference_template(reference_template_id)

        # 参考材料上下文（事实材料 / 风格范式，职责分离）
        from app.application.references.context import (
            build_task_reference_context,
            build_template_reference_context,
        )
        task_reference_context = build_task_reference_context(
            task_reference_ids or [], user.id, self.db
        ) or None
        template_reference_context = None
        if reference_template_id:
            template_reference_context = build_template_reference_context(
                reference_template_id, self.db
            ) or None

        history_messages = self.memory.get_session_context(session.id, self.db)

        # 写作类请求的信息完整度判断（模板表单模式跳过）
        clarify_reply = None
        if not system_prompt:
            clarify_reply = self.intent.check_writing_clarification(
                message=message,
                history=history_messages,
                has_materials=bool(attachment_context),
                reference_template=reference_template,
            )

        if clarify_reply:
            reply = clarify_reply
            sources = []
        else:
            sources = []
            if use_rag:
                sources = self.rag.search(query=message, user_id=user.id,
                                          kb_types=["public", "personal"])

            examples = []
            if any(k in message for k in ["写", "起草", "生成", "撰写", "拟"]):
                examples = self.rag.search_examples(message, user.id, top_k=2)

            reply = self.assistant.chat(
                message=message,
                history=history_messages,
                sources=sources,
                user_role=user.role,
                memories=None,  # 关闭长期记忆注入（与旧系统一致）
                examples=examples,
                system_prompt=system_prompt,
                template_category=template_category,
                attachment_context=attachment_context or None,
                reference_template=reference_template,
                task_reference_context=task_reference_context,
                template_reference_context=template_reference_context,
            )

        # ---- 智能写作流水线（仅写作类请求，自动质检，不影响普通问答）----
        doc_number = doc_date = None
        quality_info = content_check_info = None
        document_id = None
        postprocess_events: List[str] = []
        is_writing = bool(
            reference_template or template_category
            or any(k in message for k in WRITING_KEYWORDS)
        )
        if (
            settings.WRITING_AUTO_QA and is_writing
            and not clarify_reply and reply
        ):
            reply, doc_number, doc_date, quality_info, \
                content_check_info, postprocess_events = \
                self._writing_pipeline(
                    reply=reply, message=message, sources=sources,
                    history=history_messages, examples=examples,
                    system_prompt=system_prompt,
                    template_category=template_category,
                    attachment_context=attachment_context or None,
                    reference_template=reference_template,
                    task_reference_context=task_reference_context,
                    template_reference_context=template_reference_context,
                    user=user,
                )
            # 自动落草稿：生成结果即成为"我的文档"中的版本 1，可在线编辑/存版本/导出
            document_id = self._auto_save_draft(
                user_id=user.id, session_id=session.id, topic=message,
                content=reply, doc_number=doc_number, doc_date=doc_date,
                quality=quality_info, content_check=content_check_info,
            )

        # 消息入库
        self.messages.add(ChatMessage(
            session_id=session.id, role="user", content=message, source=source,
            sources=[s["source"] for s in sources] if sources else [],
            attachments=self.attachments.summarize_for_message(new_attachments) if new_attachments else [],
        ))
        self.messages.add(ChatMessage(
            session_id=session.id, role="assistant", content=reply,
            source=source, tokens_used=len(reply),
        ))
        self.db.commit()

        # 每 20 条消息总结一次会话
        msg_count = self.messages.count_by_session(session.id)
        if msg_count > 0 and msg_count % 20 == 0:
            try:
                self.memory.summarize_session(session.id, self.db)
            except Exception as e:
                logger.warning("[Memory] 总结会话失败: %s", e)

        return {
            "reply": reply,
            "sources": sources,
            "attachments": self.attachments.summarize_for_message(new_attachments),
            "session_id": session.id,
            "document_id": document_id,
            "document_number": doc_number,
            "document_date": doc_date,
            "quality": quality_info,
            "content_check": content_check_info,
            "postprocess_events": postprocess_events,
        }

    # ========== 智能写作流水线 ==========
    def _writing_pipeline(self, reply: str, message: str,
                          sources: list, history: list, examples: list,
                          system_prompt, template_category,
                          attachment_context, reference_template,
                          task_reference_context,
                          template_reference_context, user: User) -> tuple:
        """后处理 → 质量门 → 内容校验 → D 级自动重试一次。

        返回 (最终文本, 文号, 成文日期, quality, content_check, events)。
        任何环节失败都降级为返回原文，不阻塞对话。
        """
        from app.application.writing.content_check import ContentChecker
        from app.application.writing.postprocessor import PostProcessor
        from app.application.writing.quality_gate import QualityGate, merge_level

        def run_pipeline(text: str) -> tuple:
            processed, events, doc_num, doc_dt = PostProcessor(
                self.db
            ).process(text)
            quality = QualityGate().evaluate(processed, topic=message)
            content = ContentChecker().check(
                processed, sources=sources, header_docnum=doc_num
            )
            quality["issues"].extend(content["issues"])
            quality["level"] = merge_level(
                quality["level"],
                "B" if content["issues"] else "A",
            )
            quality["passed"] = quality["level"] != "D"
            return processed, events, doc_num, doc_dt, quality, content

        processed, events, doc_number, doc_date, quality, content = \
            run_pipeline(reply)

        # D 级（退化/截断/占位符等硬伤）自动重试，取评级更优者
        retries = 0
        while quality["level"] == "D" and retries < settings.WRITING_RETRY_MAX:
            retries += 1
            events.append(f"质量门 D 级，自动重试第 {retries} 次")
            logger.info("[写作流水线] D 级重试: %s",
                        [i["message"] for i in quality["issues"]
                         if i["severity"] == "critical"])
            try:
                retry_reply = self.assistant.chat(
                    message=message, history=history, sources=sources,
                    user_role=user.role, memories=None, examples=examples,
                    system_prompt=system_prompt,
                    template_category=template_category,
                    attachment_context=attachment_context,
                    reference_template=reference_template,
                    task_reference_context=task_reference_context,
                    template_reference_context=template_reference_context,
                )
            except Exception as e:  # noqa: BLE001
                logger.warning("[写作流水线] 重试生成失败: %s", e)
                break
            p2, ev2, dn2, dd2, q2, c2 = run_pipeline(retry_reply)
            rank = {"A": 2, "B": 1, "D": 0}
            if (rank[q2["level"]], q2["char_count"]) > \
                    (rank[quality["level"]], quality["char_count"]):
                events.append("采用重试结果")
                processed, doc_number, doc_date = p2, dn2, dd2
                quality, content = q2, c2
                events.extend(f"重试后{e}" for e in ev2)
            else:
                events.append("重试结果未更优，保留首次")

        if quality["level"] == "D":
            events.append("重试后仍为 D 级，已标记问题，请人工处理")

        logger.info(
            "[写作流水线] level=%s 文号=%s 事件=%d 内容问题=%d",
            quality["level"], doc_number, len(events),
            len(content["issues"]),
        )
        return processed, doc_number, doc_date, quality, content, events

    def _auto_save_draft(self, user_id: str, session_id: str, topic: str,
                         content: str, doc_number, doc_date,
                         quality, content_check) -> Optional[str]:
        """写作生成结果自动保存为文档草稿（版本 1）。

        草稿创建失败不影响对话响应，仅记录日志。
        """
        if not settings.WRITING_AUTO_SAVE_DRAFT:
            return None
        try:
            from app.application.documents.dto import DocumentCreateRequest
            from app.application.documents.service import DocumentService

            # 标题取正文首个非空行（公文标题），退化为主题前 30 字
            title = next(
                (ln.strip() for ln in (content or "").splitlines() if ln.strip()),
                (topic or "未命名文档")[:30],
            )[:100]
            doc = DocumentService(self.db).create_document(
                user_id,
                DocumentCreateRequest(
                    title=title, content=content,
                    document_number=doc_number, document_date=doc_date,
                    session_id=session_id,
                    quality=quality, content_check=content_check,
                    note="对话生成自动草稿",
                ),
            )
            return doc["id"]
        except Exception as e:
            logger.warning("[写作流水线] 自动保存草稿失败: %s", e)
            self.db.rollback()
            return None
