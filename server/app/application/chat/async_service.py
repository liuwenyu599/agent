"""Async ChatService for ASGI request paths.

Database/RAG work remains synchronous and short-lived; every potentially long model request is
awaited through AsyncWritingAssistant, including clarification, quality retries, title generation
and periodic conversation summaries.
"""
from __future__ import annotations

from typing import Callable, List, Optional

from app.application.chat.async_intent_service import AsyncIntentService
from app.application.chat.service import ChatService
from app.core.config import settings
from app.core.logging import get_logger
from app.domain.chat.entities import ChatMessage, ChatSession
from app.domain.identity.entities import User
from app.infrastructure.database.models.chat import SessionSummaryModel

logger = get_logger(__name__)


class AsyncChatService(ChatService):
    def __init__(self, db, assistant, rag) -> None:
        super().__init__(db, assistant, rag)
        self.intent = AsyncIntentService(assistant)

    async def _ai_session_title_async(self, first_message: str, first_reply: str) -> str:
        prompt = (
            "请把下面这段对话概括成一个不超过 15 个字的中文会话标题，"
            "体现用户要办的事。只输出标题本身：不要引号、不要标点结尾、不要解释、不要换行。\n\n"
            f"用户：{first_message[:200]}\n助手：{first_reply[:200]}"
        )
        raw = await self.assistant.acomplete(
            [{"role": "user", "content": prompt}], temperature=0.1, max_tokens=40) or ""
        title = raw.strip().splitlines()[0].strip() if raw.strip() else ""
        return title.strip("\"'「」『』【】《》<>。！？!?，,、；;：:… .—-")[:30]

    async def _summarize_session_async(self, session_id: str) -> Optional[str]:
        messages = self.memory.get_full_session_history(session_id, self.db)
        if len(messages) < 10:
            return None
        dialog_text = "\n".join(f"{m['role']}: {m['content'][:200]}" for m in messages)
        summary = await self.assistant.acomplete([
            {"role": "system", "content": "你是一个对话摘要助手。"},
            {"role": "user", "content": (
                "请总结以下对话的关键信息：\n\n" + dialog_text
                + "\n\n请用2-3句话总结用户的主要意图和关键信息。只输出总结内容。")},
        ], max_tokens=200)
        self.db.add(SessionSummaryModel(
            session_id=session_id,
            summary=summary,
            key_points=self.memory._extract_key_points(summary),
            message_count=len(messages),
        ))
        self.db.commit()
        return summary

    async def _writing_pipeline_async(self, reply: str, message: str,
                                      sources: list, history: list, examples: list,
                                      system_prompt, template_category,
                                      attachment_context, reference_template,
                                      task_reference_context,
                                      template_reference_context, user: User,
                                      user_preference: Optional[str] = None,
                                      image_paths: Optional[List[str]] = None) -> tuple:
        from app.application.writing.content_check import ContentChecker
        from app.application.writing.postprocessor import PostProcessor
        from app.application.writing.quality_gate import QualityGate, merge_level

        def run_pipeline(text: str) -> tuple:
            processed, events, doc_num, doc_dt = PostProcessor(self.db).process(text)
            quality = QualityGate().evaluate(processed, topic=message)
            content = ContentChecker().check(processed, sources=sources, header_docnum=doc_num)
            quality["issues"].extend(content["issues"])
            quality["level"] = merge_level(
                quality["level"], "B" if content["issues"] else "A")
            quality["passed"] = quality["level"] != "D"
            return processed, events, doc_num, doc_dt, quality, content

        processed, events, doc_number, doc_date, quality, content = run_pipeline(reply)
        retries = 0
        while quality["level"] == "D" and retries < settings.WRITING_RETRY_MAX:
            retries += 1
            current_issues = list(quality.get("issues") or [])
            retry_message = self._quality_retry_message(
                original_message=message, failed_text=processed,
                issues=current_issues, attempt=retries)
            events.append(
                f"质量门 D 级，携带 {len(current_issues)} 项问题自动重试第 {retries} 次")
            try:
                retry_reply = await self.assistant.achat(
                    message=retry_message, history=history, sources=sources,
                    user_role=user.role, memories=None, examples=examples,
                    system_prompt=system_prompt, template_category=template_category,
                    attachment_context=attachment_context,
                    reference_template=reference_template,
                    task_reference_context=task_reference_context,
                    template_reference_context=template_reference_context,
                    user_preference=user_preference, image_paths=image_paths,
                )
            except Exception as exc:
                logger.warning("[写作流水线] 异步重试生成失败: %s", exc)
                events.append(f"重试第 {retries} 次生成失败")
                break
            p2, ev2, dn2, dd2, q2, c2 = run_pipeline(retry_reply)
            events.append(
                f"重试第 {retries} 次评级 {q2['level']}，问题 {len(q2.get('issues') or [])} 项")
            if self._quality_candidate_score(q2) > self._quality_candidate_score(quality):
                events.append(f"采用第 {retries} 次重试结果")
                processed, doc_number, doc_date = p2, dn2, dd2
                quality, content = q2, c2
                events.extend(f"重试后{event}" for event in ev2)
            else:
                events.append(f"第 {retries} 次重试结果未更优，保留当前最佳稿")
        if quality["level"] == "D":
            events.append("重试后仍为 D 级，已标记问题，请人工处理")
        return processed, doc_number, doc_date, quality, content, events

    async def send_message_async(self, user: User, message: str,
                                 session_id: Optional[str] = None,
                                 use_rag: bool = True,
                                 system_prompt: Optional[str] = None,
                                 template_category: Optional[str] = None,
                                 source: str = "chat",
                                 attachment_ids: Optional[List[str]] = None,
                                 reference_template_id: Optional[str] = None,
                                 task_reference_ids: Optional[List[str]] = None,
                                 on_delta: Optional[Callable[[str], None]] = None) -> dict:
        session = self.sessions.get_for_user(session_id, user.id) if session_id else None
        if not session:
            session = self.sessions.add(ChatSession(user_id=user.id, title=message[:30]))

        new_attachments = []
        if attachment_ids:
            new_attachments = self.attachments.get_attachments(
                attachment_ids, user.id, self.db)
            self.attachments.bind_to_session(
                attachment_ids, session.id, user.id, self.db)
        image_paths = self._image_paths_of(new_attachments) or None
        session_attachments = self.attachments.get_session_attachments(session.id, self.db)
        attachment_context = self.attachments.build_attachment_context(
            session_attachments, query=message)
        reference_template = self._load_reference_template(reference_template_id)

        from app.application.references.context import (
            build_task_reference_context, build_template_reference_context)
        task_reference_context = build_task_reference_context(
            task_reference_ids or [], user.id, self.db) or None
        template_reference_context = (
            build_template_reference_context(reference_template_id, self.db)
            if reference_template_id else None)
        history_messages = self.memory.get_session_context(session.id, self.db)
        memories = self.memory.get_user_memory(user.id, self.db, query=message)
        user_preference = self._user_preference_block(user.id)
        knowledge_qa = source == "knowledge_qa"
        writing_request = False if knowledge_qa else self.intent.is_writing_request(message)
        if writing_request or template_category or reference_template_id:
            from app.application.writing.scoped_memory import ScopedWritingMemory
            from app.application.writing.task_parser import explicit_document_type
            user_preference = (user_preference or "") + ScopedWritingMemory(
                self.db).prompt_block(user.id, explicit_document_type(message) or "")

        clarify_reply = None
        if not system_prompt and writing_request:
            clarify_reply = await self.intent.check_writing_clarification_async(
                message=message, history=history_messages,
                has_materials=bool(attachment_context),
                reference_template=reference_template)

        if clarify_reply:
            reply, sources, examples = clarify_reply, [], []
        else:
            sources = []
            if use_rag:
                sources = self.rag.search(
                    query=message, user_id=user.id, kb_types=["public", "personal"])
                if not sources:
                    prev_user = [m["content"] for m in history_messages
                                 if m.get("role") == "user"][-2:]
                    if prev_user:
                        sources = self.rag.search(
                            query=" ".join(prev_user + [message]), user_id=user.id,
                            kb_types=["public", "personal"])
            examples = self.rag.search_examples(message, user.id, top_k=2) \
                if writing_request else []
            if on_delta:
                chunks = []
                async for chunk in self.assistant.achat_stream(
                    message=message, history=history_messages, sources=sources,
                    user_role=user.role, memories=memories, examples=examples,
                    system_prompt=system_prompt, template_category=template_category,
                    attachment_context=attachment_context or None,
                    reference_template=reference_template,
                    task_reference_context=task_reference_context,
                    template_reference_context=template_reference_context,
                    user_preference=user_preference, image_paths=image_paths,
                ):
                    chunks.append(chunk)
                    on_delta(chunk)
                reply = "".join(chunks)
            else:
                reply = await self.assistant.achat(
                    message=message, history=history_messages, sources=sources,
                    user_role=user.role, memories=memories, examples=examples,
                    system_prompt=system_prompt, template_category=template_category,
                    attachment_context=attachment_context or None,
                    reference_template=reference_template,
                    task_reference_context=task_reference_context,
                    template_reference_context=template_reference_context,
                    user_preference=user_preference, image_paths=image_paths,
                )

        doc_number = doc_date = None
        quality_info = content_check_info = None
        document_id = None
        postprocess_events: List[str] = []
        is_writing = bool(reference_template or template_category or writing_request)
        if settings.WRITING_AUTO_QA and is_writing and not clarify_reply and reply:
            (reply, doc_number, doc_date, quality_info,
             content_check_info, postprocess_events) = await self._writing_pipeline_async(
                reply=reply, message=message, sources=sources,
                history=history_messages, examples=examples,
                system_prompt=system_prompt, template_category=template_category,
                attachment_context=attachment_context or None,
                reference_template=reference_template,
                task_reference_context=task_reference_context,
                template_reference_context=template_reference_context,
                user=user, user_preference=user_preference,
                image_paths=image_paths)
            document_id = self._auto_save_draft(
                user_id=user.id, session_id=session.id, topic=message,
                content=reply, doc_number=doc_number, doc_date=doc_date,
                quality=quality_info, content_check=content_check_info)

        self.messages.add(ChatMessage(
            session_id=session.id, role="user", content=message, source=source,
            sources=[],
            attachments=self.attachments.summarize_for_message(new_attachments)
            if new_attachments else []))
        self.messages.add(ChatMessage(
            session_id=session.id, role="assistant", content=reply,
            source=source, sources=sources if sources else [], tokens_used=len(reply)))
        self.db.commit()
        msg_count = self.messages.count_by_session(session.id)

        if msg_count <= 2 and (session.title or "") == message[:30]:
            try:
                ai_title = await self._ai_session_title_async(message, reply)
                if ai_title:
                    session_row = self.sessions.get_model(session.id)
                    if session_row is not None:
                        session_row.title = ai_title
                        self.db.commit()
            except Exception as exc:
                logger.warning("[对话] AI 会话命名失败: %s", exc)
        if msg_count > 0 and msg_count % 12 == 0:
            try:
                await self._summarize_session_async(session.id)
            except Exception as exc:
                logger.warning("[Memory] 异步总结会话失败: %s", exc)

        return {
            "reply": reply, "sources": sources,
            "attachments": self.attachments.summarize_for_message(new_attachments),
            "session_id": session.id, "document_id": document_id,
            "document_number": doc_number, "document_date": doc_date,
            "quality": quality_info, "content_check": content_check_info,
            "postprocess_events": postprocess_events,
        }
