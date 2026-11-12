"""风格自学习：用户终稿 → 35B 蒸馏风格画像 → 个人写作记忆（writing_memories source=auto）。

闭环设计（模仿 → 越用越像）：
- 触发：写作任务保存终稿版本（POST /writing-tasks/{id}/versions）成功后，
  fire-and-forget 后台线程，绝不阻塞保存响应。
- 门槛：该用户该文种累计终稿 ≥ ``WRITING_STYLE_LEARN_MIN_FINALS``（默认 3，
  样本太少画像噪声大）；距上次蒸馏 ≥ ``WRITING_STYLE_LEARN_COOLDOWN_HOURS``
  （默认 24h，用自动记忆条目的 updated_at 做冷却时钟，不引入新表）。
- 素材：最近 ``WRITING_STYLE_LEARN_SAMPLES`` 篇终稿摘录 + 最近 6 条该用户
  同文种「采纳的段落修改」对照（用户亲手改的地方才是最真实的风格信号）。
- 蒸馏：一次模型调用，输出 ≤400 字风格画像；Prompt 硬约束只迁移写法
  （结构/语气/句式/固定用语/开头结尾/句长/称谓），严禁迁移事实。
- 存储：writing_memories 的 personal 记忆 upsert（source=auto），同文种仅一条、
  每次蒸馏覆盖更新；用户可在记忆管理中编辑、禁用或删除——用户始终拥有否决权。
- 消费：ScopedWritingMemory.prompt_block 已有的注入逻辑原样生效，零新增注入代码。
- 安全：蒸馏任何异常只记日志，不影响保存；全局同一时刻至多一个蒸馏线程；
  模型调用走共享网关（受 MODEL_MAX_CONCURRENCY 信号量约束，写作高峰不会被挤爆）。
"""
from __future__ import annotations

import logging
import re
import threading
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.infrastructure.database.models.writing_memory import WritingMemoryModel
from app.infrastructure.database.models.writing_task import WritingTaskModel

logger = logging.getLogger(__name__)

# 同一时刻至多一个蒸馏线程在跑：蒸馏是低优先级后台作业，绝不排队堆积。
_DISTILL_LOCK = threading.Lock()

_ACCEPTED_PAIRS = 6
_PROFILE_CHARS = 500          # writing_memories.content 的列级上限
_FINAL_EXCERPT_CHARS = 1200
_PAIR_CHARS = 200

_SYSTEM_PROMPT = (
    "你是公文写作风格分析师。分析用户的终稿与其采纳的修改，"
    "提炼一份该用户的写作风格画像。只描述写法层面：篇章结构、段落节奏、"
    "句长偏好、语气与正式程度、固定用语和套话、开头结尾句式、称谓习惯、"
    "人称与数字表述习惯。"
    "严禁出现任何具体事实：不得包含真实的人名、单位名、地名、日期、数字、"
    "文号或事件；引用原文表述时只用抽象概括。"
    "输出纯文本，条目式（每行一条，以「·」开头），不超过 400 字，"
    "不要标题、不要解释、不要 Markdown。"
)


def schedule_style_distill(user_id: str, document_type: str) -> None:
    """终稿保存后调用：不阻塞、不抛错，满足条件才起后台蒸馏线程。"""
    document_type = (document_type or "").strip()
    if not user_id or not document_type:
        return
    if not getattr(settings, "WRITING_STYLE_LEARN", True):
        return
    try:
        threading.Thread(
            target=_distill_guarded, args=(user_id, document_type),
            name=f"style-distill-{document_type}", daemon=True,
        ).start()
    except Exception as exc:  # noqa: BLE001 - 调度失败绝不影响保存
        logger.warning("[风格自学习] 调度失败（忽略）：%s", exc)


def _distill_guarded(user_id: str, document_type: str) -> None:
    if not _DISTILL_LOCK.acquire(blocking=False):
        return  # 已有蒸馏在跑，本次跳过（下次保存再试）
    try:
        distill_style(user_id, document_type)
    except Exception as exc:  # noqa: BLE001 - 后台线程绝不能抛穿
        logger.exception("[风格自学习] 蒸馏异常（不影响保存）：%s", exc)
    finally:
        _DISTILL_LOCK.release()


def _get_gateway():
    from app.infrastructure.ai import get_llm_gateway
    return get_llm_gateway()


def _collect_material(db: Session, user_id: str, document_type: str
                      ) -> Optional[Dict[str, Any]]:
    """收集蒸馏素材，返回 None 表示门槛未过（终稿不足或冷却中）。"""
    limit = max(1, int(getattr(settings, "WRITING_STYLE_LEARN_MIN_FINALS", 3)))
    tasks = db.scalars(
        select(WritingTaskModel).where(
            WritingTaskModel.user_id == user_id,
        ).order_by(WritingTaskModel.updated_at.desc()).limit(60)
    ).all()
    finals = [t for t in tasks
              if str((t.context or {}).get("document_type") or "") == document_type
              and (t.current_content or "").strip()]
    if len(finals) < limit:
        return None

    samples = max(1, int(getattr(settings, "WRITING_STYLE_LEARN_SAMPLES", 6)))
    excerpts = [
        f"【终稿{i + 1}】{(t.current_content or '').strip()[:_FINAL_EXCERPT_CHARS]}"
        for i, t in enumerate(finals[:samples])
    ]

    from app.infrastructure.database.models.writing_suggestion import WritingSuggestionModel
    accepted = db.scalars(
        select(WritingSuggestionModel).where(
            WritingSuggestionModel.user_id == user_id,
            WritingSuggestionModel.document_type == document_type,
            WritingSuggestionModel.status == "accepted",
            WritingSuggestionModel.final_content.is_not(None),
        ).order_by(WritingSuggestionModel.updated_at.desc())
        .limit(_ACCEPTED_PAIRS)).all()
    pairs = [
        f"原：{(row.original_content or '')[:_PAIR_CHARS]}\n"
        f"改：{(row.final_content or '')[:_PAIR_CHARS]}"
        for row in accepted
        if (row.final_content or "") != (row.original_content or "")
    ]
    return {"excerpts": excerpts, "pairs": pairs}


def _auto_row(db: Session, user_id: str, document_type: str
              ) -> Optional[WritingMemoryModel]:
    return db.scalar(select(WritingMemoryModel).where(
        WritingMemoryModel.scope == "personal",
        WritingMemoryModel.owner_user_id == user_id,
        WritingMemoryModel.document_type == document_type,
        WritingMemoryModel.source == "auto",
    ))


def distill_style(user_id: str, document_type: str, gateway=None) -> Optional[str]:
    """同步蒸馏入口（测试直接调用；生产走 schedule 的后台线程）。

    Returns:
        蒸馏出的画像文本；未触发（门槛未过）或失败返回 None。
    """
    from app.infrastructure.database.session import SessionLocal
    db: Session = SessionLocal()
    try:
        material = _collect_material(db, user_id, document_type)
        if material is None:
            return None

        # 冷却：自动条目最近更新过就先不蒸馏（用它当冷却时钟）。
        cooldown_hours = max(
            1, int(getattr(settings, "WRITING_STYLE_LEARN_COOLDOWN_HOURS", 24)))
        existing = _auto_row(db, user_id, document_type)
        if existing is not None and existing.updated_at is not None:
            from datetime import timedelta

            from app.core.timeutil import now_local
            if now_local() - existing.updated_at < timedelta(hours=cooldown_hours):
                return None

        profile = _call_model(gateway or _get_gateway(), user_id,
                              document_type, material)
        if not profile:
            return None

        _upsert_auto_row(db, existing, user_id, document_type, profile)
        logger.info("[风格自学习] 已沉淀画像 user=%s 文种=%s 长度=%d",
                    user_id, document_type, len(profile))
        return profile
    finally:
        db.close()


def _call_model(gateway, user_id: str, document_type: str,
                material: Dict[str, Any]) -> str:
    parts = [f"文种：{document_type}", "", "一、用户近期终稿摘录："]
    parts.extend(material["excerpts"])
    if material["pairs"]:
        parts.append("")
        parts.append("二、用户亲手采纳的段落修改（原→改对照，风格信号最强）：")
        parts.extend(material["pairs"])
    parts.append("")
    parts.append(
        "请提炼该用户在此文种上的写作风格画像。记住：只描述写法与习惯，"
        "任何具体事实（人名/单位/日期/数字/文号/事件）都不得出现。")
    raw = gateway.complete(
        [{"role": "system", "content": _SYSTEM_PROMPT},
         {"role": "user", "content": "\n".join(parts)}],
        temperature=0.3, max_tokens=700,
    ) or ""
    return _sanitize_profile(raw)


def _sanitize_profile(raw: str) -> str:
    text = (raw or "").strip()
    # 去掉模型可能加的代码围栏 / 引号 / 标题前缀
    text = re.sub(r"^```[a-zA-Z]*\n?|```$", "", text).strip()
    text = text.strip('"').strip()
    text = re.sub(r"^(?:风格画像|画像)[：:]\s*", "", text)
    # 与既有 prompt 注入格式对齐：确保行首「·」条目
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if lines:
        text = "\n".join(
            ln if ln.startswith(("·", "-", "•")) else f"·{ln}"
            for ln in lines)
    return text[:_PROFILE_CHARS]


def _upsert_auto_row(db: Session, existing: Optional[WritingMemoryModel],
                     user_id: str, document_type: str, profile: str) -> None:
    try:
        if existing is not None:
            existing.content = profile
            existing.enabled = True
        else:
            db.add(WritingMemoryModel(
                scope="personal", owner_user_id=user_id, department_code="",
                created_by=user_id, document_type=document_type,
                content=profile, source="auto"))
        db.commit()
    except Exception:
        db.rollback()
        raise
