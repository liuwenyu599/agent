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

from app.application.writing import prompt_snapshot
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

    def _materials_for(self, task) -> str:
        """把起草那一刻的检索资料回填到样本 ``input``。

        这一步不能省。样本原本只有一句 instruction（"起草通知：xxx"）配一整篇
        正文，拿去训练就是在教模型「给我个标题就能凭空写出这一篇」——事实部分
        不再有出处，等于把虚构能力连同格式一起训进去。
        """
        snap = prompt_snapshot.latest(getattr(task, "id", "") or "")
        if not snap:
            return ""
        return prompt_snapshot.build_material_text(snap)

    def _persist_eval_sample(self, task, user_id: str, ai_content: str,
                             final_content: str, *,
                             status: str = "candidate") -> TrainingSampleModel:
        """Persist one AI→human pair with an explicit review state.

        Automatic captures use ``candidate`` so they never enter training without review. The
        legacy manual ``/training-sample`` endpoint passes ``pending_review`` to preserve its
        existing API and database contract.
        """
        ctx = dict(task.context or {})
        materials = self._materials_for(task)
        sample = TrainingSampleModel(
            instruction=self._sample_instruction(ctx),
            input=materials,
            draft=ai_content,
            output=final_content,
            source="writing_eval",
            session_id=task.session_id,
            biz_type=ctx.get("document_type") or "writing",
            status=status,
            created_by=user_id,
        )
        self.db.add(sample)
        self.db.commit()
        self.db.refresh(sample)
        return sample

    # ------------------------------------------------------------ 原样采纳抓取

    def export_docx(self, task_id: str, user_id: str, red_header: bool = True):
        """导出当前内容，顺带补抓「AI 稿用户原样采纳」的样本。

        只由 ``save_version`` 触发抓样本时，采集到的是**被改动过**的那些
        ——用户对 AI 稿不满意才会去改。真正满意、一字不改直接导出走人的，
        一条也抓不到。结果是训练数据整体偏向负例：模型学到的是「照我写的
        那样会被改掉」，偏偏漏掉最有价值的正例。这里把导出当作采纳信号补上。
        """
        result = super().export_docx(task_id, user_id, red_header)
        self._try_capture_accepted(task_id, user_id)
        return result

    def export_version_docx(self, task_id: str, user_id: str, version_no: int,
                            red_header: bool = True):
        buf, fname = super().export_version_docx(task_id, user_id, version_no, red_header)
        self._try_capture_accepted(task_id, user_id, version_no)
        return buf, fname

    def _try_capture_accepted(self, task_id: str, user_id: str,
                              version_no: Optional[int] = None) -> None:
        """把「最近一个 AI 版本 → 用户实际导出的内容」记成候选样本。

        采集是旁路行为：任何异常都只记日志，绝不能让一次导出失败。
        """
        try:
            task = self._get_owned(task_id, user_id)
            ai_version = self._latest_ai_version(task)
            if ai_version is None:
                return
            ai_content = (ai_version.content or "").strip()
            final_content = (task.current_content or "").strip()
            if not ai_content or not final_content:
                return
            if version_no and ai_version.version_no != version_no:
                # 导出的不是那个 AI 版本本身，配对关系会含糊，宁可不抓
                return
            if self._already_captured(task.session_id, ai_content, final_content):
                return
            self._persist_eval_sample(task, user_id, ai_content, final_content)
            logger.info("[写作评测集] accept-capture task=%s ai_v=%s changed=%s",
                        task_id, ai_version.version_no, final_content != ai_content)
        except Exception as exc:
            self.db.rollback()
            logger.warning("[写作评测集] 采纳样本抓取失败，导出已正常返回: %s", exc)

    def _already_captured(self, session_id: Optional[str], ai_content: str,
                          final_content: str) -> bool:
        """同一任务同一对 (AI稿, 终稿) 只留一条，避免反复导出刷样本。

        不去加去重列——那要迁移表。按内容比对即可命中：用户没改时两者相同，
        改了的话终稿也稳定，重复导出结果完全一致。
        """
        row = self.db.scalar(
            select(TrainingSampleModel.id)
            .where(TrainingSampleModel.session_id == session_id,
                   TrainingSampleModel.draft == ai_content,
                   TrainingSampleModel.output == final_content)
            .limit(1)
        )
        return row is not None

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
        """Keep the manual endpoint and its pending_review contract, using the latest AI version."""
        task = self._get_owned(task_id, user_id)
        ai_version = self._latest_ai_version(task)
        ai_content = ai_version.content if ai_version else (task.ai_draft or "")
        if not ai_content.strip():
            from fastapi import HTTPException
            raise HTTPException(status_code=400, detail="该任务没有AI版本，无法形成训练样本")
        if ai_content.strip() == (final_content or "").strip():
            return {
                "sample_id": None,
                "status": "not_created",
                "message": "人工稿与最近AI版本一致，未重复加入训练集",
            }

        sample = self._persist_eval_sample(
            task, user_id, ai_content, final_content, status="pending_review"
        )
        return {
            "sample_id": sample.id,
            "status": sample.status,
            "message": "已加入候选训练样本",
            "source_version": ai_version.version_no if ai_version else None,
            "diff": self._diff_stats(ai_content, final_content),
        }
