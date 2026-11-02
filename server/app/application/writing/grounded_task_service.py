"""Grounded writing service: exemplar imitation + deterministic calculation checks.

- RAG facts remain evidence sources.
- Style exemplars are permission-scoped cards and bounded excerpts, never full articles.
- Exemplar retrieval explicitly prefixes the detected document type so same-type examples rank first.
- Arithmetic is verified by Python after generation/revision.
- Explicit literal values are protected deterministically after semantic routing.
"""
from __future__ import annotations

import os
import re
from typing import Any, Dict, List

from app.application.writing import task_parser
from app.application.writing.calculation_guard import verify_and_fix_calculations
from app.application.writing.semantic_task_service import SemanticWritingTaskService
from app.application.shared.prompt_budget import compact_style_examples

_STYLE_ADAPTER_ENV = "WRITING_STYLE_ADAPTER"


def style_adapter_active() -> bool:
    """风格是否已经蒸馏到模型权重里。

    这是一道**运行期开关**，目的很直白：训练是可以选择不做的事。
    配了这个变量说明模型本身已经会这套写法，推理时就不再灌抽象风格卡，
    但仍检索当前知识库的同文种范文摘录；不配则保留风格卡，
    一字不变。所以「训了」和「没训」共用同一套代码，只差一个环境变量，
    不会出现训到一半、adapter 撤了之后质量突然塌掉的中间态。
    """
    return bool((os.getenv(_STYLE_ADAPTER_ENV) or "").strip())


class GroundedWritingTaskService(SemanticWritingTaskService):
    """Production writing service with grounded style cards and arithmetic guardrails."""

    @staticmethod
    def _literal_overrides(message: str) -> Dict[str, Any]:
        parsed = task_parser.parse_message(message or "")
        allowed = (
            "document_date",
            "document_number_enabled",
            "document_number",
            "word_count_target",
            "word_count_max",
        )
        return {k: parsed[k] for k in allowed if k in parsed}

    @staticmethod
    def _exemplar_query(message: str) -> str:
        """Make the requested document type an explicit ranking signal.

        Historical examples share many generic official-writing words. Without a strong type
        signal a semantically similar report can outrank a notice/request. Prefixing the
        server-parsed type keeps retrieval compatible with the existing RAG API while making
        same-type matching deterministic at the query-contract level.
        """
        raw = (message or "").strip()
        doc_type = GroundedWritingTaskService._requested_type(raw)
        if not doc_type:
            return raw
        return f"文种：{doc_type}\n同文种范文优先：{doc_type}\n{raw}"

    @staticmethod
    def _requested_type(message: str) -> str:
        explicit = re.search(r"(?m)^(?:全文)?文种[：:]\s*([^\n。；]+)", message or "")
        if explicit:
            return explicit.group(1).strip()
        return str(task_parser.explicit_document_type(message) or "").strip()

    # 范文注入的两块内容与各自预算（上下文有限，按重要性分配）：
    #   风格卡 —— 结构/套语/开头结尾的抽象，好处是短
    #   原文摘录 —— 真实段落，好处是模型能看到本单位怎么说话
    # 两者都要：只有风格卡时模型学得到「怎么写」但拿不到「写什么」，
    # 表现为格式对、内容空洞且容易编造（实测曾生成已过期的年份）。
    _STYLE_CARD_CHARS = 900
    _EXCERPT_CHARS = 1800
    _EXCERPT_TOP_K = 3

    def _example_style_block(self, query: str, user_id: str) -> str:
        """检索同文种范文，向模型注入「风格卡 + 原文摘录」。

        防照抄的边界仍然保留：只迁移写法与本单位行文习惯，不搬具体数据、
        人名、日期与文号。但必须让模型看到原文——只给抽象的写法摘要时，
        模型无从获得本单位的实际表述，产出会退化成通用套话。
        """
        if not self.rag:
            return ""
        requested_type = self._requested_type(query)
        try:
            examples = self.rag.search_examples(
                query=self._exemplar_query(query),
                user_id=user_id,
                top_k=max(8, self._EXCERPT_TOP_K),
                max_chars=2500,
                document_type=requested_type,
            ) or []
        except Exception:
            self._rag_failed = True
            examples = []
        # Nearby topics in a different genre are poor format examples.
        if requested_type:
            examples = [ex for ex in examples if (
                str(ex.get("doc_type") or "") == requested_type
                or requested_type in str(ex.get("title") or "")
            )]
        examples = examples[:self._EXCERPT_TOP_K]
        if not examples:
            return ""

        # The adapter can replace the abstract style card, but live KB excerpts still
        # anchor the draft to this task's document type and current local practice.
        cards = ("" if style_adapter_active() else
                 compact_style_examples(examples, max_chars=self._STYLE_CARD_CHARS))
        excerpts = self._excerpt_block(examples, self._EXCERPT_CHARS)
        parts = []
        if cards:
            parts.append(
                "【结构与行文风格参考】\n" + cards
            )
        if excerpts:
            parts.append(
                "【同文种范文原文摘录】\n" + excerpts
            )
        if not parts:
            return ""
        return (
            "\n\n【知识库范文参考】\n"
            + "\n\n".join(parts)
            + "\n\n使用方式：学习同文种范文的章节组织、主送、落款和联系人等要素"
            "是否出现及其位置，并根据本次任务决定是否需要；学习句式、过渡与本单位行文习惯，"
            "可复用其中属于本单位的专有表述；"
            "但严禁把范文里具体的数据、日期、人名、文号与个案事实当作本次事实"
            "照搬——本次事实只能来自用户输入、附件与本轮检索到的资料。"
        )

    @staticmethod
    def _excerpt_block(examples: List[Dict], max_chars: int) -> str:
        """拼接范文原文摘录，按 total 预算均分，保留段落原貌。"""
        items = []
        total = max_chars
        for ex in examples:
            if not ex:
                continue
            title = str(ex.get("title") or "").strip()
            content = str(ex.get("content") or "").strip()
            if not content:
                continue
            share = max(400, total // max(1, len(examples)))
            excerpt = content[:share].rstrip()
            if not excerpt:
                continue
            items.append(f"—《{title or '范文'}》—\n{excerpt}")
            total -= len(excerpt) + 40
            if total <= 0:
                break
        return "\n\n".join(items)

    def _postprocess(self, text: str, ctx: Dict[str, Any]):
        processed, events, doc_number, doc_date = super()._postprocess(text, ctx)
        processed, calc_events = verify_and_fix_calculations(processed)
        events = list(events or []) + calc_events
        return processed, events, doc_number, doc_date
