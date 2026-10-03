"""Async facade for WritingAssistant.

Prompt assembly remains shared with the mature synchronous assistant. Only model transport is
changed: ASGI request paths await the gateway directly and never park a worker thread for a long
model timeout.
"""
from __future__ import annotations

from typing import Any, AsyncIterator, Dict, List, Optional

from app.application.shared.writing_assistant import WritingAssistant


class AsyncWritingAssistant(WritingAssistant):
    @staticmethod
    async def _acomplete_gateway(gateway, messages, temperature=None, max_tokens=None) -> str:
        fn = getattr(gateway, "acomplete", None)
        if callable(fn):
            return await fn(messages, temperature=temperature, max_tokens=max_tokens)
        # Mock/legacy gateways are deterministic and local. Production QwenGateway implements
        # acomplete, so no network request is sent through this compatibility branch.
        return gateway.complete(messages, temperature=temperature, max_tokens=max_tokens)

    async def acomplete(self, messages: List[Dict[str, Any]],
                        temperature: Optional[float] = None,
                        max_tokens: Optional[int] = None) -> str:
        return await self._acomplete_gateway(
            self.gateway, messages, temperature=temperature, max_tokens=max_tokens)

    async def acomplete_with_tools(self, messages: List[Dict[str, Any]],
                                   tools: List[Dict[str, Any]], tool_choice=None,
                                   temperature: Optional[float] = 0.0,
                                   max_tokens: Optional[int] = None) -> Dict[str, Any]:
        fn = getattr(self.gateway, "acomplete_with_tools", None)
        if callable(fn):
            return await fn(
                messages, tools=tools, tool_choice=tool_choice,
                temperature=temperature, max_tokens=max_tokens,
            )
        sync_fn = getattr(self.gateway, "complete_with_tools", None)
        if callable(sync_fn):
            return sync_fn(
                messages, tools=tools, tool_choice=tool_choice,
                temperature=temperature, max_tokens=max_tokens,
            )
        raise NotImplementedError("gateway does not support tool calling")

    async def achat(self, message: str, history: List[Dict], sources: List[Dict], user_role: str,
                    memories: List[Dict] = None, examples: list = None,
                    system_prompt: str = None, template_category: str = None,
                    attachment_context: str = None, reference_template: Dict = None,
                    task_reference_context: str = None,
                    template_reference_context: str = None,
                    user_preference: str = None,
                    image_paths: List[str] = None) -> str:
        system_prompt = self._build_system_prompt(
            message, sources, examples=examples, system_prompt=system_prompt,
            reference_template=reference_template,
            task_reference_context=task_reference_context,
            template_reference_context=template_reference_context,
            user_preference=user_preference,
            attachment_context=attachment_context,
        )
        messages, gateway = self._assemble_messages(
            message, history, system_prompt, image_paths=image_paths)
        return await self._acomplete_gateway(gateway, messages)

    async def achat_stream(self, message: str, history: List[Dict], sources: List[Dict],
                           user_role: str, system_prompt: str = None,
                           attachment_context: str = None) -> AsyncIterator[str]:
        system_prompt = self._build_system_prompt(
            message, sources, system_prompt=system_prompt,
            attachment_context=attachment_context,
        )
        messages, gateway = self._assemble_messages(message, history, system_prompt)
        stream = getattr(gateway, "acomplete_stream", None)
        if callable(stream):
            async for chunk in stream(messages):
                if chunk:
                    yield chunk
            return
        text = await self._acomplete_gateway(gateway, messages)
        if text:
            yield text

    async def agenerate_document(self, doc_type: str, topic: str, references: str = "",
                                 style: str = "严谨", word_count: int = 1000) -> str:
        prompt = self._render_prompt(
            f"writing/{doc_type}", topic=topic, references=references,
            style=style, word_count=word_count,
        )
        return await self.acomplete([
            {"role": "system", "content": "你是司法局公文写作专家。"},
            {"role": "user", "content": prompt},
        ], max_tokens=8192)
