"""Production structured-field takeover.

Title, recipient, document number, issuing authority and document date are document chrome,
not body prose. Earlier semantic service still reconstructed authority/date into the body tail for
legacy UI compatibility. This final layer removes that compatibility behavior: current_content is
body-only and all five fields live exclusively in task context / render-export parameters.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List

from app.application.writing.quality_retry_service import QualityRetryWritingTaskService

_DATE_ONLY_RE = re.compile(
    r"^(?:20\d{2}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日|"
    r"[二〇零○一二三四五六七八九]{4}\s*年.+日)$"
)
_SIGNOFF_ONLY_RE = re.compile(
    r"^[\u4e00-\u9fa5（）()]{2,40}(?:政府|办公厅|办公室|委员会|局|厅|部|署|所|处|院|中心)$"
)
_DOCNUM_ONLY_RE = re.compile(
    r"^[\u4e00-\u9fa5A-Za-z]{1,16}[〔\[【［].{2,18}[〕\]】］]\s*[0-9０-９]{1,8}\s*号$"
)


class StructuredFieldWritingTaskService(QualityRetryWritingTaskService):
    """Keep ``current_content`` body-only; render chrome from structured context exactly once."""

    @staticmethod
    def _canonicalize_body(text: str, ctx: Dict[str, Any]) -> str:
        lines = [line.rstrip() for line in (text or "").replace("\r\n", "\n").split("\n")]
        title = str(ctx.get("title") or "").strip()
        recipient = str(ctx.get("recipient") or "").strip().rstrip("：:")
        docnum = str(ctx.get("document_number") or "").strip()
        authority = str(ctx.get("authority") or "").strip()
        doc_date = str(ctx.get("document_date") or "").strip()

        cleaned: List[str] = []
        nonempty_seen = 0
        for raw in lines:
            s = raw.strip()
            in_header = nonempty_seen < 10
            if s:
                nonempty_seen += 1
            if in_header and s:
                if title and s == title:
                    continue
                if recipient and s.rstrip("：:") == recipient:
                    continue
                if docnum and s == docnum:
                    continue
                if docnum and _DOCNUM_ONLY_RE.fullmatch(s):
                    continue
            cleaned.append(raw)

        while cleaned and not cleaned[-1].strip():
            cleaned.pop()

        # Structural tail values are removed, never reconstructed into body.
        tail_start = max(0, len(cleaned) - 12)
        body = cleaned[:tail_start]
        tail: List[str] = []
        for raw in cleaned[tail_start:]:
            s = raw.strip()
            if not s:
                tail.append(raw)
                continue
            if authority and s == authority:
                continue
            if doc_date and s == doc_date:
                continue
            if _SIGNOFF_ONLY_RE.fullmatch(s) or _DATE_ONLY_RE.fullmatch(s):
                continue
            tail.append(raw)
        cleaned = body + tail

        out: List[str] = []
        blank = False
        for raw in cleaned:
            is_blank = not raw.strip()
            if is_blank and blank:
                continue
            out.append(raw)
            blank = is_blank
        while out and not out[-1].strip():
            out.pop()
        return "\n".join(out).strip()

    def _postprocess(self, text: str, ctx: Dict[str, Any]):
        # Parent still performs program-owned doc-number/date generation and all mature cleanup.
        # It may temporarily append authority/date through the legacy semantic layer; strip all
        # chrome again before any quality gate / snapshot sees the authoritative current_content.
        processed, events, doc_number, doc_date = super()._postprocess(text, ctx)
        canonical_ctx = dict(ctx)
        if doc_number:
            canonical_ctx["document_number"] = doc_number
        if doc_date:
            canonical_ctx["document_date"] = doc_date
        body_only = self._canonicalize_body(processed, canonical_ctx)
        return body_only, events, doc_number, doc_date
