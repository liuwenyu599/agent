"""对话用例编排（移植旧 api/chat.py /chat/send 的完整流程）。

流程：会话获取/创建 → 附件绑定与上下文 → 参考模板/参考材料上下文 →
写作意图澄清判断 → RAG 检索 + 范文检索 → WritingAssistant 生成 → 消息入库
→ 每 20 条消息触发会话总结。
"""
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.application.chat.attachment_service import AttachmentService
from app.application.chat.intent_service import IntentService
from app.application.chat.memory_service import MemoryService
from app.application.knowledge.rag_service import RagService
from app.application.shared.writing_assistant import WritingAssistant
from app.core.logging import get_logger
from app.domain.chat.entities import ChatMessage, ChatSession
from app.domain.identity.entities import User
from app.infrastructure.database.models.templates import WritingTemplateModel
from app.infrastructure.repositories.chat import (
    SqlAlchemyChatMessageRepository,
    SqlAlchemyChatSessionRepository,
)

logger = get_logger(__name__)


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
        }
