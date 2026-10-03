"""Async clarification path for chat writing requests."""
from __future__ import annotations

from typing import Dict, List, Optional

from app.application.chat.intent_service import IntentService
from app.core.llm_json import loads_llm_object
from app.core.logging import get_logger

logger = get_logger(__name__)


class AsyncIntentService(IntentService):
    async def check_writing_clarification_async(
        self,
        message: str,
        history: List[Dict],
        has_materials: bool,
        reference_template: Optional[Dict] = None,
    ) -> Optional[str]:
        try:
            if not self.is_writing_request(message):
                return None
            if has_materials or self._last_assistant_was_asking(history):
                return None
            tmpl_name = reference_template.get("name") if reference_template else None
            prompt = self._render_clarify_prompt(message, tmpl_name)
            raw = await self.assistant.acomplete([
                {"role": "system", "content": "你是需求分析模块，只输出 JSON。"},
                {"role": "user", "content": prompt},
            ], temperature=0.1, max_tokens=300)
            if not raw or raw.startswith("【系统错误】") or raw.startswith("调用模型失败"):
                return None
            result = loads_llm_object(raw)
            if result is None or result.get("ready"):
                return None
            questions = [q.strip() for q in (result.get("questions") or [])
                         if q and q.strip()][:3]
            if not questions:
                return None
            doc_hint = f"这篇{tmpl_name}" if tmpl_name else "这篇材料"
            lines = [f"可以，我可以先帮您起草{doc_hint}。为了让内容准确完整，还需要确认几个关键信息："]
            lines += [f"{i + 1}. {q}" for i, q in enumerate(questions)]
            lines.append("如果有相关通知、方案、记录或现场照片等材料，也可以直接上传，我会根据材料起草。")
            return "\n".join(lines)
        except Exception as exc:
            logger.warning("[Intent] 异步信息完整度判断失败，回退为直接生成: %s", exc)
            return None
