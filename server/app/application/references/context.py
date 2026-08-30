"""参考材料 → 写作上下文构建（chat 模块跨模块调用，签名固定不可改）。

- build_template_reference_context：模板固定参考材料 → 风格学习上下文（严禁照搬事实）
- build_task_reference_context：当前任务佐证材料 → 事实依据上下文（优先级最高）
"""
from typing import List

from sqlalchemy.orm import Session

from app.infrastructure.repositories.references import (
    SqlAlchemyTaskReferenceRepository,
    SqlAlchemyTemplateReferenceRepository,
)


def build_template_reference_context(template_id: str, db: Session,
                                     max_refs: int = 3, per_ref_chars: int = 1500) -> str:
    refs = SqlAlchemyTemplateReferenceRepository(db).list_active_by_template(
        template_id, limit=max_refs
    )
    refs = [r for r in refs if (r.text_content or "").strip()]
    if not refs:
        return ""
    blocks = []
    for i, r in enumerate(refs):
        blocks.append(f"【风格范例{i + 1}：{r.name}】\n{r.text_content[:per_ref_chars]}")
    return (
        "以下是本模板配置的固定参考材料（本单位历史优秀稿件）。"
        "它们只用于学习：标题风格、行文方式、常用表达、文章长度、叙事结构；"
        "严禁把范例中的具体事实（单位名、人名、时间、地点、数据、事件经过）写进新文章，"
        "新文章的事实只能来自用户本次提供的材料和知识库检索结果：\n\n"
        + "\n\n".join(blocks)
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
