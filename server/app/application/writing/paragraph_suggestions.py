"""Version-safe, per-user suggestions for the line-sized paragraphs shown in the desktop editor."""
from __future__ import annotations

import difflib
import hashlib
import re
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select, update

from app.core.timeutil import now_local
from app.infrastructure.database.models.writing_suggestion import (
    WritingSuggestionEventModel, WritingSuggestionModel,
)
from app.infrastructure.database.models.writing_task import WritingTaskModel


def paragraph_id(task_id: str, index: int, content: str) -> str:
    # Index disambiguates repeated text. The content hash makes a manually edited line stale.
    return hashlib.sha256(f"{task_id}\0{index}\0{content}".encode("utf-8")).hexdigest()


def content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _lines(content: str) -> list[str]:
    # Must match the desktop editor's split('\n') contract exactly.
    return content.split("\n")


def _suggestion_dict(row: WritingSuggestionModel) -> dict[str, Any]:
    return {
        "id": row.id, "paragraph_id": row.paragraph_id,
        "original_content": row.original_content,
        "proposed_content": row.proposed_content,
        "final_content": row.final_content,
        "instruction": row.instruction, "status": row.status,
    }


class ParagraphSuggestionMixin:
    async def _generate_paragraph_suggestion(self, prompt: str, sources,
                                             attachment_ctx, user_id: str) -> str:
        if not self.assistant:
            raise HTTPException(status_code=503, detail="模型服务不可用")
        system = (
            (self._agent_prompt(user_id) or "") +
            "\n你正在为写作台选中的单个正文段落提出修改建议。"
            "仅返回这一段的最终建议文本，不返回整篇文稿、说明、标题、列表或 Markdown。"
            "保持用户未要求改变的事实、数字、日期、人物和政策口径；不得编造。"
        )
        card = self._example_style_block(prompt, user_id)
        self._record_prompt(system, card, prompt, sources, attachment_ctx, user_id,
                            kind="paragraph_suggestion")
        return await self.assistant.achat(
            message=prompt, history=[], sources=sources, user_role="user",
            system_prompt=system + card, attachment_context=attachment_ctx,
        ) or ""

    def _visible_lines(self, task: WritingTaskModel) -> list[tuple[int, int, str, str]]:
        """Map displayed body lines back to stored lines, including legacy title prefixes."""
        raw = _lines(task.current_content or "")
        visible_text = self._to_dict(task)["current_content"]
        visible = _lines(visible_text)
        if not visible or (len(visible) == 1 and not visible[0]):
            return []
        if raw == visible:
            start = 0
        else:
            normalized = "\n".join(line.rstrip("\r") for line in raw)
            offset = normalized.rfind(visible_text)
            if offset < 0:
                return []
            start = normalized[:offset].count("\n")
            if (start + len(visible) > len(raw) or
                    any(raw[start + j].strip() != line.strip()
                        for j, line in enumerate(visible))):
                return []
        return [(display_index, start + display_index, raw[start + display_index], line)
                for display_index, line in enumerate(visible) if line.strip()]

    def list_paragraphs(self, task_id: str, user_id: str) -> dict[str, Any]:
        task = self._get_owned(task_id, user_id)
        rows = self.db.scalars(select(WritingSuggestionModel).where(
            WritingSuggestionModel.task_id == task_id,
            WritingSuggestionModel.user_id == user_id,
            WritingSuggestionModel.status.in_(("pending", "rejected", "accepted")),
        ).order_by(WritingSuggestionModel.created_at.desc())).all()
        by_index: dict[int, list[WritingSuggestionModel]] = {}
        for row in rows:
            by_index.setdefault(row.line_index, []).append(row)
        current_hash = content_hash(task.current_content or "")
        result = []
        for display_index, index, content, displayed in self._visible_lines(task):
            pid = paragraph_id(task_id, index, content)
            # Accepted suggestions refer to the original paragraph ID, but the edited
            # content now has a new ID. Keep its status visible until that line changes.
            match = next((row for row in by_index.get(index, ()) if (
                (row.paragraph_id == pid and row.base_content_hash == current_hash and
                 row.status in ("pending", "rejected")) or
                (row.status == "accepted" and row.final_content == content)
            )), None)
            result.append({"id": pid, "line_index": display_index, "content": displayed,
                           "status": match.status if match else "unhandled",
                           "suggestion": _suggestion_dict(match) if match else None})
        return {"version_no": task.version_no or 0, "items": result}

    def _current_suggestion(self, task_id: str, user_id: str, suggestion_id: str):
        row = self.db.scalar(select(WritingSuggestionModel).where(
            WritingSuggestionModel.id == suggestion_id,
            WritingSuggestionModel.task_id == task_id,
            WritingSuggestionModel.user_id == user_id,
        ))
        if row is None:
            raise HTTPException(status_code=404, detail="逐段建议不存在")
        return row

    @staticmethod
    def _assert_current_line(task: WritingTaskModel, row: WritingSuggestionModel) -> None:
        lines = _lines(task.current_content or "")
        if (row.base_content_hash != content_hash(task.current_content or "") or
                row.line_index >= len(lines) or
                lines[row.line_index] != row.original_content or
                paragraph_id(task.id, row.line_index, row.original_content) != row.paragraph_id):
            raise HTTPException(status_code=409, detail="该段已改变，请重新获取建议")

    def _event(self, row: WritingSuggestionModel, action: str, final: str | None = None) -> None:
        before = row.original_content
        diff = "" if final is None else "".join(difflib.unified_diff(
            [before + "\n"], [final + "\n"], fromfile="原文", tofile="最终文本"))
        self.db.add(WritingSuggestionEventModel(
            user_id=row.user_id, task_id=row.task_id, suggestion_id=row.id,
            paragraph_id=row.paragraph_id, action=action,
            original_content=before, final_content=final, diff_text=diff,
        ))

    def _accepted_style_memory(self, user_id: str, document_type: str) -> str:
        """A small same-user, same-genre few-shot card; facts remain task-specific."""
        if not document_type:
            return ""
        rows = self.db.scalars(select(WritingSuggestionModel).where(
            WritingSuggestionModel.user_id == user_id,
            WritingSuggestionModel.document_type == document_type,
            WritingSuggestionModel.status == "accepted",
            WritingSuggestionModel.final_content.is_not(None),
        ).order_by(WritingSuggestionModel.updated_at.desc()).limit(3)).all()
        pairs = [f"原：{row.original_content[:160]}\n采纳：{row.final_content[:160]}"
                 for row in rows if row.final_content != row.original_content]
        if not pairs:
            return ""
        return ("\n\n【该用户曾采纳的同文种修改习惯】\n" + "\n".join(pairs) +
                "\n只参考语气、结构与表达习惯；历史稿的事实、时间、数字、人名和对象"
                "绝不能移入本次文稿。本次明确要求优先。")

    async def suggest_paragraph_async(self, task_id: str, user_id: str,
                                      pid: str, instruction: str = "",
                                      regenerate: bool = False) -> dict[str, Any]:
        task = self._get_owned(task_id, user_id)
        lines = _lines(task.current_content or "")
        initial_hash = content_hash(task.current_content or "")
        matches = [(raw_index, line) for _, raw_index, line, _ in self._visible_lines(task)
                   if paragraph_id(task_id, raw_index, line) == pid]
        if not matches:
            raise HTTPException(status_code=409, detail="该段已改变，请刷新正文后重试")
        index, original = matches[0]
        instruction = instruction.strip()[:500]
        previous = self.db.scalar(select(WritingSuggestionModel).where(
            WritingSuggestionModel.user_id == user_id,
            WritingSuggestionModel.task_id == task_id,
            WritingSuggestionModel.paragraph_id == pid,
            WritingSuggestionModel.status == "pending",
        ).order_by(WritingSuggestionModel.created_at.desc()))
        if previous and previous.instruction == instruction and not regenerate:
            if previous.base_content_hash == initial_hash:
                return _suggestion_dict(previous)

        ctx = dict(task.context or {})
        memory = self._accepted_style_memory(user_id, str(ctx.get("document_type") or ""))
        prompt = (
            "你是公文写作助手。只处理下面的一个正文段落，不要输出标题、解释、引号或 Markdown。"
            "保留原段事实、数字、时间、人名、政策口径和基本意思；不得编造。"
            "只返回修改后的单段纯文本；如果原段已经合适，原样返回。\n"
            f"文种：{str(ctx.get('document_type') or '')[:100]}\n"
            f"本次主题：{str(ctx.get('topic') or ctx.get('title') or '')[:200]}\n"
            f"前一段（仅作衔接）：{lines[index - 1][:250] if index else ''}\n"
            f"原段：{original}\n"
            f"后一段（仅作衔接）：{lines[index + 1][:250] if index + 1 < len(lines) else ''}\n"
            f"用户要求：{instruction or '在忠于原意的前提下检查并优化表达'}"
            + memory
        )
        sources = self._retrieve(ctx, user_id, extra_query=instruction or original[:100])
        proposed_body = (await self._generate_paragraph_suggestion(
            prompt, sources, self._attachment_context(task, ctx), user_id)).strip()
        indentation = re.match(r"^[ \t\u3000]*", original).group()
        proposed = indentation + proposed_body.lstrip(" \t\u3000")
        if (not proposed or "\n" in proposed or "\r" in proposed or
                len(proposed) > max(3000, len(original) * 3)):
            raise HTTPException(status_code=502, detail="模型未返回有效的单段建议，原文未更改")
        numbers = lambda value: set(re.findall(r"\d+(?:[.,]\d+)*%?", value))
        if numbers(proposed) - numbers(original + instruction):
            raise HTTPException(status_code=502, detail="建议引入了未经提供的数字，原文未更改")
        self.db.refresh(task)
        current_lines = _lines(task.current_content or "")
        if (content_hash(task.current_content or "") != initial_hash or
                index >= len(current_lines) or current_lines[index] != original):
            raise HTTPException(status_code=409, detail="生成期间该段已改变，请重新获取建议")
        if previous and previous.status == "pending":
            previous.status = "superseded"
            self._event(previous, "supersede")
        row = WritingSuggestionModel(
            user_id=user_id, task_id=task_id, paragraph_id=pid, line_index=index,
            document_type=str(ctx.get("document_type") or "")[:100],
            base_version=task.version_no or 0, base_content_hash=initial_hash,
            original_content=original,
            proposed_content=proposed, instruction=instruction, status="pending",
        )
        self.db.add(row)
        self.db.flush()
        self._event(row, "generate", proposed)
        self.db.commit()
        return _suggestion_dict(row)

    def accept_paragraph_suggestion(self, task_id: str, user_id: str,
                                    suggestion_id: str, final_content: str) -> dict[str, Any]:
        row = self._current_suggestion(task_id, user_id, suggestion_id)
        if row.status != "pending":
            raise HTTPException(status_code=409, detail="这条建议已处理，请刷新后重试")
        final = final_content
        if not final.strip() or "\n" in final or "\r" in final or len(final) > 5000:
            raise HTTPException(status_code=422, detail="修改后内容必须是非空的单段文本")
        task = self._get_owned(task_id, user_id)
        self._assert_current_line(task, row)
        before = task.current_content or ""
        lines = _lines(before)
        lines[row.line_index] = final
        after = "\n".join(lines)
        if after != before:
            # Compare-and-swap protects against a simultaneous manual save or another accept.
            result = self.db.execute(update(WritingTaskModel).where(
                WritingTaskModel.id == task_id,
                WritingTaskModel.user_id == user_id,
                WritingTaskModel.current_content == before,
                WritingTaskModel.version_no == task.version_no,
            ).values(current_content=after, updated_at=now_local()))
            if result.rowcount != 1:
                self.db.rollback()
                raise HTTPException(status_code=409, detail="正文已变化，请刷新后重试")
            self.db.refresh(task)
            doc_id, version = self._snapshot(task, user_id, note="采纳逐段建议",
                                             commit=False)
            task.document_id = doc_id
            task.version_no = version
            old_hash, new_hash = content_hash(before), content_hash(after)
            for pending in self.db.scalars(select(WritingSuggestionModel).where(
                WritingSuggestionModel.task_id == task_id,
                WritingSuggestionModel.user_id == user_id,
                WritingSuggestionModel.status == "pending",
                WritingSuggestionModel.id != row.id,
                WritingSuggestionModel.base_content_hash == old_hash,
            )).all():
                if (pending.line_index < len(lines) and
                        lines[pending.line_index] == pending.original_content):
                    pending.base_content_hash = new_hash
                    pending.base_version = version
                else:
                    pending.status = "superseded"
                    self._event(pending, "supersede")
        row.status = "accepted"
        row.final_content = final
        self._draft_memory_cache.pop((user_id, row.document_type), None)
        self._event(row, "accept_edited" if final != row.proposed_content else "accept", final)
        self.db.commit()
        return {**self._to_dict(task), "content_changed": after != before,
                "suggestion": _suggestion_dict(row)}

    def reject_paragraph_suggestion(self, task_id: str, user_id: str,
                                    suggestion_id: str) -> dict[str, Any]:
        row = self._current_suggestion(task_id, user_id, suggestion_id)
        if row.status != "pending":
            raise HTTPException(status_code=409, detail="这条建议已处理，请刷新后重试")
        task = self._get_owned(task_id, user_id)
        self._assert_current_line(task, row)
        row.status = "rejected"
        self._event(row, "reject")
        self.db.commit()
        return {"suggestion": _suggestion_dict(row), "content_changed": False}
