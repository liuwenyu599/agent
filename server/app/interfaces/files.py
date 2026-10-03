"""Authenticated file download endpoints.

Uploaded chat originals are private judicial materials. They must never be exposed by a
plain StaticFiles mount; every download resolves the attachment through the database
and checks owner identity before opening the backing path.
"""
from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.domain.identity.entities import User
from app.infrastructure.database import get_db
from app.infrastructure.repositories.chat import SqlAlchemyChatAttachmentRepository
from app.interfaces.deps import get_current_user

router = APIRouter(prefix="/files", tags=["文件"])


def _safe_attachment_path(raw_path: str) -> Path:
    root = Path(settings.uploads_dir).resolve()
    path = Path(raw_path).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise NotFoundError("文件不存在") from exc
    if not path.is_file():
        raise NotFoundError("文件不存在")
    return path


@router.get("/{attachment_id}")
def download_owned_attachment(
    attachment_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    attachment = SqlAlchemyChatAttachmentRepository(db).get_for_user(
        attachment_id, user.id
    )
    if not attachment:
        # Deliberately return the same response for non-existent vs non-owned IDs.
        raise NotFoundError("文件不存在")
    path = _safe_attachment_path(attachment.file_path)
    return FileResponse(
        str(path),
        filename=Path(attachment.filename or path.name).name,
        media_type="application/octet-stream",
    )
