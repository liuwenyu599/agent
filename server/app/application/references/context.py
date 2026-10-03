"""参考材料 → 写作上下文构建（chat 模块跨模块调用，签名固定不可改）。

- build_template_reference_context：模板固定参考材料 → 风格学习上下文（严禁照搬事实）
- build_task_reference_context：当前任务佐证材料 → 事实依据上下文（优先级最高）
"""
from typing import List

from sqlalchemy.orm import Session

from app.application.shared.prompt_budget import compact_style_examples
from app.infrastructure.repositories.references import (
    SqlAlchemyTaskReferenceRepository,
    SqlAlchemyTemplateReferenceRepository,
)


def _style_scan_window(text: str, limit: int) -> str:
    """Bound local scanning cost while retaining both opening and real closing patterns."""
    text = text or ""
    if len(text) <= limit:
        return text
    head = max(1, int(limit * 0.75))
    return text[:head] + "\n" + text[-(limit - head):]


def build_template_reference_context(template_id: str, db: Session,
                                     max_refs: int = 3, per_ref_chars: int = 1500) -> str:
    """固定范文只注入结构化风格卡，不再把多篇历史正文直接塞进上下文。

    ``per_ref_chars`` 保留既有签名兼容调用方；它限制本地结构抽取的扫描窗口，
    且窗口同时保留文章开头与真实结尾。最终注入统一受约 1.5K token 控制。
    """
    refs = SqlAlchemyTemplateReferenceRepository(db).list_active_by_template(
        template_id, limit=max_refs
    )
    refs = [r for r in refs if (r.text_content or "").strip()]
    if not refs:
        return ""
    examples = [
        {"title": r.name, "content": _style_scan_window(r.text_content or "", per_ref_chars)}
        for r in refs
    ]
    cards = compact_style_examples(examples, max_chars=1100)
    if not cards:
        return ""
    return (
        "以下是本模板历史优秀稿件提炼出的结构化风格范式。"
        "只学习一级结构、固定用语、开头/结尾句式和正式程度；"
        "不得迁移其中任何具体事实，新文章事实只能来自本次任务材料和知识库：\n\n"
        + cards
    )


def build_task_reference_context(ref_ids: List[str], user_id: str, db: Session,
                                 per_ref_chars: int = 2000) -> str:
    if not ref_ids:
        return ""
    refs = SqlAlchemyTaskReferenceRepository(db).list_by_ids_for_user(ref_ids, user_id)
    refs = [r for r in refs if (r.text_content or "").strip()]
    if not refs:
        return ""
    blocks = []
    for i, r in enumerate(refs):
        label = {"file": "上传文件", "text": "粘贴文本", "url": "参考网页"}.get(r.ref_type, "材料")
        src = f"（{r.source_url}）" if r.source_url else ""
        blocks.append(f"【本次写作材料{i + 1}（{label}）：{r.name}】{src}\n{r.text_content[:per_ref_chars]}")
    return (
        "以下是用户为本次写作提供的事实材料。文章中的事实、数据、时间、地点、"
        "人物和事件经过以这些材料为准，材料中没有的信息不要虚构：\n\n"
        + "\n\n".join(blocks)
    )
