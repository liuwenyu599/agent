"""正文收尾与落库的唯一管线。

起草、整篇改写、局部修改三条支路此前各抄了一遍同样的七步：
``_postprocess → 剥结构行 → 外部文号核对 → QualityGate → ContentChecker →
回写 ctx → 版本快照``。四份拷贝的细微差别（谁保留旧引用、谁清引用、谁补 ai_draft）
并非设计，而是抄写漂移。这里收成两件事：

- :func:`finalize_text` —— 只做「模型正文 → 可落库正文」的确定性加工与体检，
  不碰数据库，便于单测与复用；
- :func:`persist_revision` —— 并发校验 + 写正文 + 版本快照 + 提交，
  由调用方决定 note 与是否切换到 editing 状态。

最终候选的 fail-closed 判断也在这里完成：后处理后的正文只评估一次，再结合
``ContentChecker`` 的问题决定是否允许落库。生成中途的候选修复属于另一阶段。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from app.application.writing.content_check import ContentChecker
from app.application.writing.quality_policy import assert_acceptable, quality_result
from app.core.timeutil import now_local


@dataclass
class Finalized:
    """一次正文收尾的完整结果。"""

    text: str
    events: List[Any] = field(default_factory=list)
    doc_number: Optional[str] = None
    doc_date: Optional[str] = None
    quality: Dict[str, Any] = field(default_factory=dict)
    content_check: Dict[str, Any] = field(default_factory=dict)
    citation_warnings: List[str] = field(default_factory=list)
    references: List[str] = field(default_factory=list)


def finalize_text(service, text: str, ctx: Dict[str, Any], sources: List[Dict],
                  *, keep_previous_references: bool = False) -> Finalized:
    """确定性收尾：结构化字段、外部文号、质检、引用清单。

    ``keep_previous_references``：改写/局部修改时，若本轮检索没有命中，保留上一版
    引用清单（不把已有依据清空）；起草则总是以本轮结果为准。
    """
    text, events, doc_number, doc_date = service._postprocess(text, ctx)
    text = service._strip_leading_structural_fields(text, ctx)
    text, citation_warnings = service._guard_external_document_numbers(text, sources, ctx)
    if citation_warnings:
        ctx["citation_warnings"] = citation_warnings
    else:
        ctx.pop("citation_warnings", None)

    quality = quality_result(
        text,
        topic=str(ctx.get("title") or ctx.get("topic") or ""),
        document_type=str(ctx.get("document_type") or ""),
        word_count_target=ctx.get("word_count_target"),
    )
    content_check = ContentChecker().check(
        text, sources=sources, header_docnum=doc_number)
    if content_check["issues"]:
        quality["issues"] = list(quality.get("issues") or []) + content_check["issues"]
        if quality.get("level") == "A":
            quality["level"] = "B"
    assert_acceptable(quality, "收尾后的结果仍存在硬伤，未保存该版本。")

    # 后处理**实际采用**的文号/成文日期回写 ctx，保证任务信息与正文一致。
    if doc_number:
        ctx["document_number"] = doc_number
    if doc_date:
        ctx["document_date"] = doc_date

    references = service._reference_labels(sources)
    reference_items = service._reference_items(sources)
    if keep_previous_references:
        references = references or list(ctx.get("references") or [])
        reference_items = reference_items or list(ctx.get("reference_items") or [])
    ctx["references"] = references
    ctx["reference_items"] = reference_items

    return Finalized(
        text=text, events=list(events or []), doc_number=doc_number,
        doc_date=doc_date, quality=quality, content_check=content_check,
        citation_warnings=citation_warnings, references=references,
    )


def persist_revision(service, task, ctx: Dict[str, Any], text: str, user_id: str,
                     *, note: str, expected_state: Optional[Tuple[Any, Any]] = None,
                     mark_editing: bool = False,
                     supersede_suggestions: bool = False) -> Tuple[int, bool]:
    """把已收尾的正文写成新版本；返回 (version_no, 逐段建议是否失效)。

    ``expected_state``：调用方读到的 (正文, 版本号)。给了就先做条件更新拿行锁，
    正文在生成期间被人改过则 409，绝不覆盖。起草路径由外层语义守卫处理，传 None。
    """
    if expected_state is not None:
        service._claim_revision_state(task, user_id, expected_state)

    task.context = ctx
    task.current_content = text
    if mark_editing:
        if not task.ai_draft:
            task.ai_draft = text
        task.status = "editing"
    service.db.flush()
    document_id, version = service._snapshot(task, user_id, note=note, commit=False)
    task.document_id = document_id
    task.version_no = version
    task.updated_at = now_local()
    suggestions_reset = (
        service._supersede_pending_suggestions(task.id, user_id)
        if supersede_suggestions and getattr(task, "id", None) else False
    )
    service.db.commit()
    return version, suggestions_reset
