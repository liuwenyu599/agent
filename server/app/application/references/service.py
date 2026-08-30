"""参考材料业务服务（移植旧 api/references.py 的业务规则）。

A. 模板固定参考材料：管理员维护，风格学习用，不进知识库。
B. 当前任务佐证材料：归属用户本人，不进知识库；主动 promote 才入库。
"""
import os
import uuid
from pathlib import Path
from typing import List, Optional

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.application.chat.attachment_service import TEXT_MAX_CHARS, AttachmentService
from app.application.knowledge.web_fetcher import fetch_webpage, looks_like_url
from app.core.config import settings
from app.core.exceptions import AppError, NotFoundError, PermissionDeniedError
from app.domain.identity.entities import ADMIN_OR_ABOVE, User
from app.domain.references.entities import TaskReference, TemplateReference
from app.infrastructure.database.models.templates import WritingTemplateModel
from app.infrastructure.repositories.references import (
    SqlAlchemyTaskReferenceRepository,
    SqlAlchemyTemplateReferenceRepository,
)


def ref_to_dict(r) -> dict:
    return {
        "id": r.id,
        "name": r.name,
        "ref_type": r.ref_type,
        "source_url": r.source_url,
        "char_count": r.char_count or len(r.text_content or ""),
        "parse_status": r.parse_status,
        "parse_note": r.parse_note,
        "template_id": r.template_id,
        "created_at": r.created_at,
    }


class ReferenceService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.trefs = SqlAlchemyTemplateReferenceRepository(db)
        self.tasks = SqlAlchemyTaskReferenceRepository(db)

    # ---- 公共 ----
    def _check_template_exists(self, template_id: str) -> None:
        if not self.db.get(WritingTemplateModel, template_id):
            raise NotFoundError("Template not found")

    async def parse_upload(self, file: UploadFile, user_id: str, subdir: str):
        """保存并解析上传文件。返回 (filename, file_path, size, text, status, note)。"""
        filename = file.filename or "unnamed"
        suffix = "." + filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
        if suffix not in settings.CHAT_SUPPORTED_TYPES:
            raise AppError(400, f"不支持的文件类型 {suffix or '(无扩展名)'}，"
                                f"支持：{'、'.join(settings.CHAT_SUPPORTED_TYPES)}")
        data = await file.read()
        if len(data) > settings.UPLOAD_MAX_SIZE:
            raise AppError(400, "文件超过 50MB 限制")
        if not data:
            raise AppError(400, "文件为空")

        ref_id = uuid.uuid4().hex
        save_dir = settings.uploads_dir / "references" / subdir / user_id
        save_dir.mkdir(parents=True, exist_ok=True)
        file_path = save_dir / f"{ref_id}{suffix}"
        file_path.write_bytes(data)

        kind = "image" if suffix in settings.CHAT_IMAGE_TYPES else "doc"
        text, status, note = AttachmentService().extract(file_path, suffix, kind)
        return filename, str(file_path), len(data), text, status, note

    def _fetch_as_ref(self, url: str) -> dict:
        fetched = fetch_webpage(url)
        if not fetched.get("ok"):
            raise AppError(400, f"网页获取失败：{fetched.get('error', '未知原因')}")
        title = fetched.get("title") or url
        return {
            "name": title[:500],
            "ref_type": "url",
            "source_url": url,
            "text_content": fetched["content"][:TEXT_MAX_CHARS],
            "parse_status": "ok",
            "parse_note": f"来源：{fetched.get('source_name') or '网页'}；刊发时间：{fetched.get('publish_time') or '未知'}",
        }

    # ---- A. 模板固定参考材料 ----
    def list_template_refs(self, template_id: str) -> dict:
        self._check_template_exists(template_id)
        refs = self.trefs.list_active_by_template(template_id)
        return {"template_id": template_id, "count": len(refs),
                "references": [ref_to_dict(r) for r in refs]}

    def add_template_ref_file(self, template_id: str, parsed: tuple, admin: User) -> dict:
        self._check_template_exists(template_id)
        filename, file_path, size, text, status, note = parsed
        ref = self.trefs.add(TemplateReference(
            template_id=template_id, name=filename, ref_type="file",
            file_path=file_path, file_size=size, text_content=text,
            char_count=len(text or ""), parse_status=status, parse_note=note,
            created_by=admin.id,
        ))
        return {"reference": ref_to_dict(ref)}

    def add_template_ref_text(self, template_id: str, name: str, text: str,
                              admin: User) -> dict:
        self._check_template_exists(template_id)
        text = (text or "").strip()
        if not text:
            raise AppError(400, "文本为空")
        ref = self.trefs.add(TemplateReference(
            template_id=template_id, name=name or "粘贴的参考文本", ref_type="text",
            text_content=text[:TEXT_MAX_CHARS], char_count=len(text[:TEXT_MAX_CHARS]),
            parse_status="ok", created_by=admin.id,
        ))
        return {"reference": ref_to_dict(ref)}

    def add_template_ref_url(self, template_id: str, url: str, name: Optional[str],
                             admin: User) -> dict:
        self._check_template_exists(template_id)
        if not looks_like_url(url):
            raise AppError(400, "不是合法的 http(s) 链接")
        fields = self._fetch_as_ref(url.strip())
        if name:
            fields["name"] = name
        ref = self.trefs.add(TemplateReference(
            template_id=template_id, created_by=admin.id,
            char_count=len(fields["text_content"]), **fields,
        ))
        return {"reference": ref_to_dict(ref)}

    def delete_template_ref(self, ref_id: str) -> dict:
        ref = self.trefs.get(ref_id)
        if not ref:
            raise NotFoundError("Reference not found")
        self.trefs.delete(ref)  # is_active=False
        return {"message": "已移除"}

    # ---- B. 当前任务佐证材料 ----
    def _get_task_ref_checked(self, ref_id: str, user: User) -> TaskReference:
        ref = self.tasks.get(ref_id)
        if not ref:
            raise NotFoundError("Reference not found")
        if ref.user_id != user.id and user.role not in ADMIN_OR_ABOVE:
            raise PermissionDeniedError("No permission")
        return ref

    def list_task_refs(self, user: User, template_id: Optional[str] = None,
                       session_id: Optional[str] = None) -> dict:
        refs = self.tasks.list_by_user(user.id, template_id, session_id)
        return {"count": len(refs), "references": [ref_to_dict(r) for r in refs]}

    def add_task_ref_file(self, user: User, parsed: tuple,
                          template_id: Optional[str] = None) -> dict:
        if template_id:
            self._check_template_exists(template_id)
        filename, file_path, size, text, status, note = parsed
        ref = self.tasks.add(TaskReference(
            user_id=user.id, template_id=template_id,
            name=filename, ref_type="file", file_path=file_path, file_size=size,
            text_content=text, char_count=len(text or ""),
            parse_status=status, parse_note=note,
        ))
        return {"reference": ref_to_dict(ref)}

    def add_task_ref_text(self, user: User, text: str, name: Optional[str] = None,
                          template_id: Optional[str] = None) -> dict:
        text = (text or "").strip()
        if not text:
            raise AppError(400, "文本为空")
        if template_id:
            self._check_template_exists(template_id)
        ref = self.tasks.add(TaskReference(
            user_id=user.id, template_id=template_id,
            name=name or "用户粘贴材料", ref_type="text",
            text_content=text[:TEXT_MAX_CHARS], char_count=len(text[:TEXT_MAX_CHARS]),
            parse_status="ok",
        ))
        return {"reference": ref_to_dict(ref)}

    def add_task_ref_url(self, user: User, url: str, name: Optional[str] = None,
                         template_id: Optional[str] = None) -> dict:
        if not looks_like_url(url):
            raise AppError(400, "不是合法的 http(s) 链接")
        if template_id:
            self._check_template_exists(template_id)
        fields = self._fetch_as_ref(url.strip())
        if name:
            fields["name"] = name
        ref = self.tasks.add(TaskReference(
            user_id=user.id, template_id=template_id,
            char_count=len(fields["text_content"]), **fields,
        ))
        return {"reference": ref_to_dict(ref),
                "message": "已添加为本次写作参考材料（未进入知识库）"}

    def delete_task_ref(self, ref_id: str, user: User) -> dict:
        ref = self._get_task_ref_checked(ref_id, user)
        if ref.file_path and os.path.exists(ref.file_path):
            os.remove(ref.file_path)
        self.tasks.hard_delete(ref)
        return {"message": "已删除"}

    def promote_task_ref(self, ref_id: str, kb_id: str, user: User,
                         doc_service) -> dict:
        """加入知识库：只有用户主动操作才把任务材料转换为知识库文档。"""
        from app.infrastructure.repositories.knowledge import SqlAlchemyKnowledgeBaseRepository

        ref = self._get_task_ref_checked(ref_id, user)
        if ref.promoted_doc_id:
            return {"message": "该材料已在知识库中", "doc_id": ref.promoted_doc_id}

        kb = SqlAlchemyKnowledgeBaseRepository(self.db).get(kb_id)
        if not kb:
            raise NotFoundError("Knowledge base not found")
        if kb.kb_type == "personal" and kb.owner_id != user.id:
            raise PermissionDeniedError("No permission")

        text = (ref.text_content or "").strip()
        if not text:
            raise AppError(400, "该材料没有可用文本内容，无法入库")

        if ref.ref_type == "url" and ref.source_url:
            # 网页材料：与"导入链接"完全同一条入库路径（含 source_url 查重）
            existing = doc_service.find_by_source_url(self.db, ref.source_url)
            if existing:
                ref.promoted_doc_id = existing.id
                self.tasks.update(ref)
                return {"message": "知识库中已存在相同链接，已关联", "doc_id": existing.id}
            result = doc_service.process_web_document(
                db=self.db, kb_id=kb.id, user_id=user.id, user_role=user.role,
                url=ref.source_url,
                fetched={"ok": True, "title": ref.name, "content": text,
                         "publish_time": "", "source_name": ""},
            )
        else:
            result = doc_service._persist_document(
                db=self.db, kb_id=kb.id, title=ref.name, text=text,
                user_id=user.id, user_role=user.role, doc_type=None,
                file_path=ref.file_path, file_size=ref.file_size or 0,
                doc_metadata={"source_type": ref.ref_type,
                              "original_filename": ref.name if ref.ref_type == "file" else None},
            )

        ref.promoted_doc_id = result["doc_id"]
        self.tasks.update(ref)
        return {"message": "已加入知识库", "doc_id": result["doc_id"], "status": result["status"]}
