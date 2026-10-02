"""Automatic writing evaluation sample capture.

When a user manually saves edits immediately after an AI-produced document version, persist the
pair ``latest AI version -> user-saved version`` into ``training_samples`` as a candidate. The
immutable document version chain is the source of truth; ``WritingTask.ai_draft`` intentionally
remains the first-draft field and is not repurposed as a moving baseline.

No sample is created for unchanged content, manual-after-manual saves, or deterministic structural
sync versions. Samples remain candidates and therefore still require the existing human review
flow before they can enter a training dataset.
"""
from __future__ import annotations

import difflib
import logging
import re
from typing import Any, Dict, Optional

from sqlalchemy import desc, select

from app.application.writing.quality_retry_service import QualityRetryWritingTaskService
from app.infrastructure.database.models.document import MyDocumentVersionModel
from app.infrastructure.database.models.training import TrainingSampleModel

logger = logging.getLogger(__name__)

_AI_CONTINUE_NOTE_RE = re.compile(r"^V\d+\s+继续生成")
_AI_NOTE_PREFIXES = (
    "V1 AI 初稿",
    "AI 修改：",
    "AI 局部修改：",
)


class EvalCaptureWritingTaskService(QualityRetryWritingTaskService):
    """Production writing service with automatic AI→human evaluation-pair capture."""

    @staticmethod
    def _is_ai_version_note(note: Optional[str]) -> bool:
        value = (note or "").strip()
        if not value:
            return False
        return value.startswith(_AI_NOTE_PREFIXES) or bool(_AI_CONTINUE_NOTE_RE.match(value))

    def _latest_version(self, task) -> Optional[MyDocumentVersionModel]:
        if not task.document_id:
            return None
        return self.db.scalar(
            select(MyDocumentVersionModel)
            .where(MyDocumentVersionModel.document_id == task.document_id)
            .order_by(desc(MyDocumentVersionModel.version_no))
            .limit(1)
        )

    def _latest_ai_version(self, task) -> Optional[MyDocumentVersionModel]:
        """Return the newest AI-authored immutable version, even if a manual version follows it."""
        if not task.document_id:
            return None
        rows = self.db.scalars(
            select(MyDocumentVersionModel)
            .where(MyDocumentVersionModel.document_id == task.document_id)
            .order_by(desc(MyDocumentVersionModel.version_no))
        ).all()
        return next((row for row in rows if self._is_ai_version_note(row.note)), None)

    @staticmethod
    def _sample_instruction(ctx: Dict[str, Any]) -> str:
        instruction = "起草" + (str(ctx.get("document_type") or "公文"))
        if ctx.get("title"):
            instruction += f"：{ctx['title']}"
        if ctx.get("requirements"):
            instruction += f"（{ctx['requirements']}）"
        return instruction

    @staticmethod
    def _diff_stats(before: str, after: str) -> Dict[str, Any]:
        """Return compact observability stats; the full pair remains reconstructable in DB."""
        matcher = difflib.SequenceMatcher(None, before or "", after or "", autojunk=False)
        added = 0
        removed = 0
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag in ("insert", "replace"):
                added += j2 - j1
            if tag in ("delete", "replace"):
                removed += i2 - i1
        return {
            "similarity": round(matcher.ratio(), 4),
            "added_chars": added,
            "removed_chars": removed,
            "ai_chars": len(before or ""),
            "final_chars": len(after or ""),
        }

    def _persist_eval_sample(self, task, user_id: str, ai_content: str,
                             final_content: str) -> TrainingSampleModel:
        ctx = dict(task.context or {})
        sample = TrainingSampleModel(
            instruction=self._sample_instruction(ctx),
            input="",
            draft=ai_content,
            output=final_content,
            source="writing_eval",
            session_id=task.session_id,
            biz_type=ctx.get("document_type") or "writing",
            status="candidate",
            created_by=user_id,
        )
        self.db.add(sample)
        self.db.commit()
        self.db.refresh(sample)
        return sample

    def save_version(self, task_id: str, user_id: str, content: str,
                     note: Optional[str] = None) -> Dict[str, Any]:
        """Save the manual version and capture one eval pair when its immediate parent is AI."""
        task = self._get_owned(task_id, user_id)
        previous = self._latest_version(task)
        should_capture = bool(
            previous
            and self._is_ai_version_note(previous.note)
            and (previous.content or "").strip() != (content or "").strip()
        )
        ai_content = previous.content if should_capture and previous else ""
        ai_version_no = previous.version_no if should_capture and previous else None

        # Persist the user's version first. Eval capture is a secondary data-asset concern and must
        # never make a successful manual document save disappear if sample persistence later fails.
        result = super().save_version(task_id, user_id, content, note)
        result["eval_captured"] = False

        if not should_capture:
            return result

        try:
            sample = self._persist_eval_sample(task, user_id, ai_content, content)
        except Exception as exc:
            self.db.rollback()
            logger.exception("[写作评测集] 自动样本保存失败，人工版本已保留: %s", exc)
            result["eval_capture_error"] = "sample_persist_failed"
            return result

        result["eval_captured"] = True
        result["eval_sample_id"] = sample.id
        result["eval_source_version"] = ai_version_no
        result["eval_final_version"] = result.get("version_no")
        result["eval_diff"] = self._diff_stats(ai_content, content)
        logger.info(
            "[写作评测集] captured task=%s ai_v=%s final_v=%s sample=%s",
            task_id, ai_version_no, result.get("version_no"), sample.id,
        )
        return result

    def add_to_training(self, task_id: str, user_id: str,
                        final_content: str) -> Dict[str, Any]:
        """Keep the manual endpoint, but pair final text with the latest AI version, not V1 only."""
        task = self._get_owned(task_id, user_id)
        ai_version = self._latest_ai_version(task)
        ai_content = ai_version.content if ai_version else (task.ai_draft or "")
        if not ai_content.strip():
            from fastapi import HTTPException
            raise HTTPException(status_code=400, detail="该任务没有AI版本，无法形成训练样本")
        if ai_content.strip() == (final_content or "").strip():
            return {"sample_id": None, "message": "人工稿与最近AI版本一致，未重复加入训练集"}

        sample = self._persist_eval_sample(task, user_id, ai_content, final_content)
        return {
            "sample_id": sample.id,
            "message": "已加入候选训练样本",
            "source_version": ai_version.version_no if ai_version else None,
            "diff": self._diff_stats(ai_content, final_content),
        }
