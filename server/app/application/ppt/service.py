"""PPT 助手应用服务：模板/素材/文档/生成/导出/云端生成的编排。"""
import io
import json as _json
import os
import re
import shutil
import uuid
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.application.ppt import ppt_engine
from app.application.ppt.ppt_engine import BUILTIN_TEMPLATES, DEFAULT_COLORS, DEFAULT_LAYOUTS
from app.application.shared.writing_assistant import WritingAssistant
from app.core.config import settings
from app.core.exceptions import AppError, AIServiceError, NotFoundError, PermissionDeniedError
from app.core.logging import get_logger
from app.domain.identity.entities import User
from app.domain.ppt.entities import PPTDocument, PPTMaterial, PPTTemplate, PPTTemplateFavorite
from app.infrastructure.database.models.knowledge import DocumentModel, KnowledgeBaseModel
from app.infrastructure.repositories.ppt import (
    SqlAlchemyPPTDocumentRepository,
    SqlAlchemyPPTMaterialRepository,
    SqlAlchemyPPTTemplateFavoriteRepository,
    SqlAlchemyPPTTemplateRepository,
)

logger = get_logger(__name__)

_PPTX_MIME = ("application/vnd.openxmlformats-officedocument."
              "presentationml.presentation")

_CLOUD_DEFAULT = {
    "enabled": False,
    "api_key": "",
    "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "mode": "general",               # general=模板模式 / creative=创意模式
    "template_id": "summary_01",
}


class PPTService:
    def __init__(self, db: Session, assistant: WritingAssistant) -> None:
        self.db = db
        self.assistant = assistant
        self.templates = SqlAlchemyPPTTemplateRepository(db)
        self.favorites = SqlAlchemyPPTTemplateFavoriteRepository(db)
        self.materials = SqlAlchemyPPTMaterialRepository(db)
        self.documents = SqlAlchemyPPTDocumentRepository(db)

    # ---- 存储路径 ----
    @property
    def ppt_dir(self) -> Path:
        d = settings.ppt_dir
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _tpl_source_path(self, template_id: str) -> Path:
        return self.ppt_dir / "tpl_src" / f"{template_id}.pptx"

    def _save_tpl_source(self, template_id: str, data: bytes) -> None:
        d = self.ppt_dir / "tpl_src"
        d.mkdir(parents=True, exist_ok=True)
        self._tpl_source_path(template_id).write_bytes(data)

    def _tpl_base_bytes(self, trow: Optional[PPTTemplate]) -> Optional[bytes]:
        """读取上传模板的原始 pptx 作为渲染底版；官方内置模板没有底版。"""
        if not trow:
            return None
        p = self._tpl_source_path(trow.id)
        if p.exists():
            try:
                return p.read_bytes()
            except Exception:
                return None
        return None

    def _layout_preview_path(self, template_id: str, layout_id: str) -> Path:
        return self.ppt_dir / "tpl_prev" / template_id / f"{layout_id}.png"

    # ================= 模板 =================
    def template_dto(self, t: PPTTemplate, user_id: str) -> dict:
        fav = self.favorites.get(user_id, t.id) is not None
        library = t.layout_library or []
        preview_url = ""
        for lay in library:
            if lay.get("preview"):
                preview_url = f"/api/v1/ppt/templates/{t.id}/layout-preview/{lay['id']}"
                break
        return {
            "id": t.id, "name": t.name, "category": t.category, "description": t.description,
            "is_official": bool(t.is_official), "is_mine": t.created_by == user_id,
            "colors": t.colors, "font": t.font, "layouts": t.layouts,
            "use_count": t.use_count, "is_favorite": fav,
            "layout_count": len(library),
            "preview_url": preview_url,
            "created_at": t.created_at.strftime("%Y-%m-%d %H:%M") if t.created_at else "",
        }

    def list_templates(self, user: User, scope: str = "all",
                       category: Optional[str] = None,
                       keyword: Optional[str] = None) -> dict:
        rows = self.templates.list_for_user(user.id, scope, category, keyword)
        return {"items": [self.template_dto(t, user.id) for t in rows]}

    def list_categories(self) -> dict:
        return {"items": self.templates.list_categories()}

    def seed_builtin_templates(self) -> dict:
        """初始化内置官方模板（upsert 模式，可重复调用刷新）。"""
        created = 0
        for spec in BUILTIN_TEMPLATES:
            existing = self.templates.get_by_builtin_id(spec["id"])
            if existing:
                existing.name = spec["name"]
                existing.category = spec["category"]
                existing.description = spec.get("description")
                existing.colors = spec["colors"]
                existing.layouts = spec["layouts"]
                self.templates.update(existing)
            else:
                self.templates.add(PPTTemplate(
                    builtin_id=spec["id"], name=spec["name"], category=spec["category"],
                    description=spec.get("description"), is_official=True,
                    colors=spec["colors"], layouts=spec["layouts"]))
                created += 1
        return {"message": f"官方模板已同步（新增 {created} 个）"}

    def create_template(self, body, user: User) -> dict:
        t = self.templates.add(PPTTemplate(
            name=body.name, category=body.category, description=body.description,
            is_official=False, created_by=user.id,
            colors={**DEFAULT_COLORS, **(body.colors or {})},
            font=body.font, layouts={**DEFAULT_LAYOUTS, **(body.layouts or {})}))
        return {"id": t.id, "message": "模板已创建"}

    def _get_editable_template(self, template_id: str, user: User) -> PPTTemplate:
        t = self.templates.get(template_id)
        if not t:
            raise NotFoundError("模板不存在")
        if t.is_official:
            raise PermissionDeniedError("官方模板只能使用，不能修改或删除")
        if t.created_by != user.id:
            raise PermissionDeniedError("只能修改自己创建的模板")
        return t

    def update_template(self, template_id: str, body, user: User) -> dict:
        t = self._get_editable_template(template_id, user)
        t.name, t.category, t.description = body.name, body.category, body.description
        if body.colors:
            t.colors = {**(t.colors or {}), **body.colors}
        t.font = body.font or t.font
        if body.layouts:
            t.layouts = {**(t.layouts or {}), **body.layouts}
        self.templates.update(t)
        return {"message": "模板已更新"}

    def delete_template(self, template_id: str, user: User) -> dict:
        t = self._get_editable_template(template_id, user)
        self.favorites.delete_by_template(t.id)
        self.templates.hard_delete(t)
        p = self._tpl_source_path(template_id)
        if p.exists():
            try:
                p.unlink()
            except Exception:
                pass
        return {"message": "模板已删除"}

    def toggle_favorite(self, template_id: str, user: User) -> dict:
        fav = self.favorites.get(user.id, template_id)
        if fav:
            self.favorites.delete(fav)
            return {"is_favorite": False}
        self.favorites.add(PPTTemplateFavorite(user_id=user.id, template_id=template_id))
        return {"is_favorite": True}

    async def upload_template(self, file, name: str, category: str, user: User) -> dict:
        """上传 .pptx 作为个人模板：提取主题色与字体，沿用默认版式体系。"""
        if not (file.filename or "").lower().endswith(".pptx"):
            raise AppError(400, "仅支持 .pptx 文件")
        data = await file.read()
        if not data:
            raise AppError(400, "文件内容为空")
        if len(data) > 50 * 1024 * 1024:
            raise AppError(400, "文件过大（限 50MB）")
        if not zipfile.is_zipfile(io.BytesIO(data)):
            raise AppError(400, "文件损坏或不是有效的 .pptx 文件")
        try:
            learned = ppt_engine.analyze_template(data)
        except Exception as e:
            raise AppError(400, f"模板解析失败：{e}")
        try:
            t = self.templates.add(PPTTemplate(
                name=name or os.path.splitext(file.filename)[0], category=category,
                description="用户上传的模板", is_official=False, created_by=user.id,
                colors=learned["colors"], font=learned["font"],
                layouts=DEFAULT_LAYOUTS.copy(),
                source_file=file.filename))
            self._save_tpl_source(t.id, data)
            library = learned.get("layouts") or []
            self._gen_tpl_previews(t.id, data, library)
            t.layout_library = library
            self.templates.update(t)
        except (AppError, PermissionDeniedError):
            raise
        except Exception as e:
            self.db.rollback()
            raise AppError(500, f"模板保存失败：{e}")
        n = len(t.layout_library or [])
        return {"id": t.id,
                "message": f"模板「{t.name}」已创建，自动识别出 {n} 种版式",
                "layout_count": n}

    def _gen_tpl_previews(self, template_id: str, data: bytes, layouts: list) -> None:
        """用 LibreOffice 把上传的 pptx 渲染成图片，截取各版式源页作为预览图。
        失败不影响上传（前端回退到结构示意图）。"""
        try:
            import glob
            import subprocess
            import tempfile
            d = self.ppt_dir / "tpl_prev" / template_id
            d.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory() as td:
                src = os.path.join(td, "tpl.pptx")
                with open(src, "wb") as f:
                    f.write(data)
                subprocess.run(["soffice", "--headless", "--convert-to", "pdf",
                                "--outdir", td, src], timeout=180, capture_output=True)
                pdf = os.path.join(td, "tpl.pdf")
                if not os.path.exists(pdf):
                    return
                subprocess.run(["pdftoppm", "-png", "-r", "60", pdf,
                                os.path.join(td, "pg")], timeout=120, capture_output=True)
                pages = sorted(glob.glob(os.path.join(td, "pg-*.png")))
                for lay in layouts:
                    i = lay.get("source_slide_index", 0)
                    if i < len(pages):
                        shutil.copy(pages[i], str(d / f"{lay['id']}.png"))
                        lay["preview"] = f"{lay['id']}.png"
        except Exception as e:
            logger.warning("模板预览图生成失败（不影响使用）: %s", e)

    def get_layout_preview(self, template_id: str, layout_id: str) -> Path:
        p = self._layout_preview_path(template_id, layout_id)
        if not p.exists():
            raise NotFoundError("预览图不存在")
        return p

    def template_detail(self, template_id: str, user: User) -> dict:
        t = self.templates.get(template_id)
        if not t:
            raise NotFoundError("模板不存在")
        d = self.template_dto(t, user.id)
        library = []
        for lay in (t.layout_library or []):
            item = dict(lay)
            item.pop("element_schema", None)  # 结构 schema 不给前端，太大
            if item.get("preview"):
                item["preview_url"] = f"/api/v1/ppt/templates/{t.id}/layout-preview/{item['id']}"
            library.append(item)
        d["layout_library"] = library
        return d

    def copy_template(self, template_id: str, user: User) -> dict:
        """复制模板（官方模板复制为个人模板，可在我的模板中编辑）。"""
        t = self.templates.get(template_id)
        if not t:
            raise NotFoundError("模板不存在")
        nt = self.templates.add(PPTTemplate(
            name=t.name + "（副本）", category=t.category, description=t.description,
            is_official=False, created_by=user.id, colors=dict(t.colors or {}),
            font=t.font, layouts=dict(t.layouts or {})))
        src = self._tpl_base_bytes(t)
        if src:
            self._save_tpl_source(nt.id, src)
        return {"id": nt.id, "message": "已复制到「我的模板」"}

    def import_template_url(self, body, user: User) -> dict:
        """从在线链接导入 pptx 模板（仅提取版式风格，不保存原始内容）。"""
        if not body.url.lower().startswith(("http://", "https://")):
            raise AppError(400, "请输入有效的 http(s) 链接")
        try:
            import requests
            resp = requests.get(body.url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
            resp.raise_for_status()
            data = resp.content
        except Exception as e:
            raise AppError(400, f"下载失败：{e}")
        if len(data) > 50 * 1024 * 1024:
            raise AppError(400, "文件超过 50MB")
        learned = ppt_engine.analyze_template(data)
        name = body.name or os.path.splitext(
            os.path.basename(body.url.split("?")[0]))[0] or "在线导入模板"
        t = self.templates.add(PPTTemplate(
            name=name, category=body.category, description="从在线链接导入的模板",
            is_official=False, created_by=user.id,
            colors=learned["colors"], font=learned["font"],
            layouts=DEFAULT_LAYOUTS.copy(),
            source_file=body.url[:500]))
        self._save_tpl_source(t.id, data)
        library = learned.get("layouts") or []
        self._gen_tpl_previews(t.id, data, library)
        t.layout_library = library
        self.templates.update(t)
        return {"id": t.id, "message": f"模板「{t.name}」已导入，自动识别出 {len(library)} 种版式"}

    def list_themes(self) -> dict:
        """旧首页兼容：主题 = 内置官方模板。"""
        return {"items": [{"id": s["id"], "name": s["name"], "category": s["category"],
                           "description": s.get("description", ""), "colors": s["colors"]}
                          for s in BUILTIN_TEMPLATES]}

    # ================= 素材库 =================
    def list_materials(self, user: User) -> dict:
        rows = self.materials.list_by_user(user.id)
        return {"items": [{"id": m.id, "name": m.name, "caption": m.caption,
                           "url": f"/api/v1/ppt/materials/{m.id}/file"} for m in rows]}

    async def upload_material(self, name: str, caption: str, file, user: User) -> dict:
        ext = os.path.splitext(file.filename or "")[1].lower()
        if ext not in [".jpg", ".jpeg", ".png", ".webp", ".gif"]:
            raise AppError(400, "仅支持图片文件")
        fname = f"{uuid.uuid4().hex}{ext}"
        path = self.ppt_dir / "materials" / fname
        path.parent.mkdir(parents=True, exist_ok=True)
        data = await file.read()
        path.write_bytes(data)
        m = self.materials.add(PPTMaterial(
            user_id=user.id, name=name, caption=caption,
            file_path=str(path), file_size=len(data),
            mime_type=file.content_type or ""))
        return {"id": m.id, "message": "素材已上传"}

    def update_material(self, mid: str, name: str, caption: str, user: User) -> dict:
        m = self.materials.get_for_user(mid, user.id)
        if not m:
            raise NotFoundError("素材不存在")
        m.name, m.caption = name, caption
        self.materials.update(m)
        return {"message": "素材已更新"}

    def delete_material(self, mid: str, user: User) -> dict:
        m = self.materials.get_for_user(mid, user.id)
        if not m:
            raise NotFoundError("素材不存在")
        if os.path.exists(m.file_path):
            os.remove(m.file_path)
        self.materials.delete(m)
        return {"message": "素材已删除"}

    def material_file(self, mid: str, user: User) -> Tuple[Path, str]:
        m = self.materials.get_for_user(mid, user.id)
        if not m or not os.path.exists(m.file_path):
            raise NotFoundError("文件不存在")
        return Path(m.file_path), m.mime_type or "image/jpeg"

    def _user_images(self, user_id: str) -> List[Dict]:
        return [{"name": m.name, "caption": m.caption, "file_path": m.file_path}
                for m in self.materials.list_by_user(user_id)]

    # ================= 文档（我的PPT） =================
    @staticmethod
    def _doc_dto(d: PPTDocument, template_name: str = "") -> dict:
        slides = (d.outline or {}).get("slides") or []
        return {
            "id": d.id, "title": d.title, "subtitle": d.subtitle,
            "status": d.status, "is_favorite": bool(d.is_favorite),
            "template_id": d.template_id, "template_name": template_name,
            "theme_id": d.theme_id, "slide_count": len(slides),
            "created_at": d.created_at.strftime("%Y-%m-%d %H:%M") if d.created_at else "",
            "updated_at": d.updated_at.strftime("%Y-%m-%d %H:%M") if d.updated_at else "",
        }

    def list_documents(self, user: User, tab: str = "all",
                       keyword: Optional[str] = None) -> dict:
        rows = self.documents.list_by_user(user.id, tab, keyword)
        tmap = {t.id: t.name for t in self.templates.list_for_user(user.id, "all")}
        return {"items": [self._doc_dto(d, tmap.get(d.template_id, "")) for d in rows]}

    def _get_doc_checked(self, doc_id: str, user: User) -> PPTDocument:
        d = self.documents.get_for_user(doc_id, user.id)
        if not d:
            raise NotFoundError("文档不存在")
        return d

    def get_document(self, doc_id: str, user: User) -> dict:
        d = self._get_doc_checked(doc_id, user)
        template = None
        if d.template_id:
            t = self.templates.get(d.template_id)
            if t:
                template = ppt_engine.template_to_dict(t)
        elif d.theme_id:  # 兼容旧文档（theme_id 即内置模板 id）
            spec = next((s for s in BUILTIN_TEMPLATES if s["id"] == d.theme_id), None)
            if spec:
                template = ppt_engine.template_to_dict(spec)
        if not template:
            template = ppt_engine.template_to_dict(BUILTIN_TEMPLATES[0])
        return {**self._doc_dto(d, template["name"]), "outline": d.outline, "template": template}

    def save_draft(self, doc_id: str, body, user: User) -> dict:
        """自动保存草稿（编辑器定时调用）：只更新内容，不改变状态。"""
        d = self._get_doc_checked(doc_id, user)
        if body.outline is not None:
            d.outline = ppt_engine.normalize_outline(body.outline)
            d.title = body.title or d.outline.get("title") or d.title
            d.subtitle = d.outline.get("subtitle") or d.subtitle
        elif body.title:
            d.title = body.title
        if body.template_id:
            t = self.templates.get(body.template_id)
            if t:
                d.template_id = t.id
        d = self.documents.update(d)
        return {"message": "已保存",
                "updated_at": d.updated_at.strftime("%H:%M:%S") if d.updated_at else ""}

    def copy_document(self, doc_id: str, user: User) -> dict:
        d = self._get_doc_checked(doc_id, user)
        nd = self.documents.add(PPTDocument(
            user_id=user.id, title=d.title + "（副本）", subtitle=d.subtitle,
            source_type=d.source_type, source_content=d.source_content,
            outline=d.outline, theme_id=d.theme_id, template_id=d.template_id,
            status="draft"))
        return {"id": nd.id, "message": "已复制"}

    def toggle_doc_favorite(self, doc_id: str, user: User) -> dict:
        d = self._get_doc_checked(doc_id, user)
        d.is_favorite = not d.is_favorite
        d = self.documents.update(d)
        return {"is_favorite": bool(d.is_favorite)}

    def delete_document(self, doc_id: str, user: User) -> dict:
        d = self._get_doc_checked(doc_id, user)
        if d.file_path and os.path.exists(d.file_path):
            os.remove(d.file_path)
        self.documents.delete(d)
        return {"message": "已删除"}

    # ================= 生成流程 =================
    def list_kbs(self) -> dict:
        """PPT 可选知识库列表（含文档数）。"""
        rows = self.db.scalars(select(KnowledgeBaseModel).where(
            KnowledgeBaseModel.is_active == True)).all()  # noqa: E712
        items = []
        for kb in rows:
            cnt = len(self.db.scalars(select(DocumentModel).where(
                DocumentModel.kb_id == kb.id,
                DocumentModel.status == "published")).all())
            items.append({"id": kb.id, "name": kb.name,
                          "description": kb.description or "", "doc_count": cnt})
        return {"items": items}

    def _kb_content(self, kb_ids: list, limit: int = 6000) -> str:
        """汇总所选知识库已发布文档的内容（按文档截断拼接）。"""
        docs = self.db.scalars(select(DocumentModel).where(
            DocumentModel.kb_id.in_(kb_ids),
            DocumentModel.status == "published")
            .order_by(DocumentModel.created_at.desc()).limit(20)).all()
        parts = []
        total = 0
        for d in docs:
            text = (d.content or "")[:1200]
            if not text.strip():
                continue
            seg = f"《{d.title}》\n{text}"
            if total + len(seg) > limit:
                break
            parts.append(seg)
            total += len(seg)
        return "\n\n".join(parts)

    def outline_from_kb(self, kb_ids: List[str], topic: str, audience: str,
                        scene: str, slide_count: int, user: User) -> dict:
        content = self._kb_content(kb_ids)
        if not content:
            raise AppError(400, "所选知识库没有可用的已发布文档内容")
        return self._do_outline(user, "kb", topic, content, slide_count, audience, scene)

    async def extract_text(self, file) -> dict:
        """提取单个文档文本（前端多文件时循环调用，自行拼接后走 /outline）。"""
        data = await file.read()
        text = self._extract_upload_text(file.filename or "unnamed", data)
        return {"filename": file.filename, "text": text[:3000]}

    def _extract_upload_text(self, filename: str, data: bytes) -> str:
        from app.application.chat.attachment_service import AttachmentService
        suffix = "." + filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
        tmp = self.ppt_dir / "tmp" / f"{uuid.uuid4().hex}{suffix}"
        tmp.parent.mkdir(parents=True, exist_ok=True)
        try:
            tmp.write_bytes(data)
            text, status, note = AttachmentService().extract(tmp, suffix, "doc")
        except Exception as e:
            raise AppError(400, f"文件「{filename}」解析失败：{e}")
        finally:
            tmp.unlink(missing_ok=True)
        if status != "ok" and not text.strip():
            raise AppError(400, f"未能从「{filename}」提取到文字内容")
        return text

    def _do_outline(self, user: User, source_type: str, topic: str, content: str,
                    slide_count: int, audience: str = "", scene: str = "") -> dict:
        images = self._user_images(user.id)
        try:
            outline = ppt_engine.generate_outline(
                self.assistant, source_type, topic, content, images,
                max(6, min(slide_count, 18)), audience, scene)
        except RuntimeError as e:
            raise AIServiceError(str(e))
        d = self.documents.add(PPTDocument(
            user_id=user.id, title=outline.get("title", "未命名PPT"),
            subtitle=outline.get("subtitle", ""), source_type=source_type,
            source_content=(topic or content or "")[:2000],
            outline=outline, status="draft"))
        return {"doc_id": d.id, "outline": outline}

    def make_outline(self, body, user: User) -> dict:
        return self._do_outline(user, body.source_type, body.topic, body.content,
                                body.slide_count, body.audience, body.scene)

    async def outline_from_doc(self, file, topic: str, audience: str, scene: str,
                               slide_count: int, user: User) -> dict:
        data = await file.read()
        text = self._extract_upload_text(file.filename or "unnamed", data)
        return self._do_outline(user, "document", topic, text, slide_count, audience, scene)

    def _resolve_template(self, template_id: Optional[str],
                          fallback_theme: str = "") -> Tuple[Dict, Optional[PPTTemplate]]:
        if template_id:
            t = self.templates.get(template_id)
            if t:
                return ppt_engine.template_to_dict(t), t
        spec = next((s for s in BUILTIN_TEMPLATES if s["id"] == fallback_theme), None)
        if not spec:
            spec = BUILTIN_TEMPLATES[0]
            t = self.templates.get_by_builtin_id(spec["id"])
            if t:
                return ppt_engine.template_to_dict(t), t
        return ppt_engine.template_to_dict(spec), None

    def _render_and_store(self, d: PPTDocument, outline: dict, user: User,
                          template_id: Optional[str]) -> str:
        """渲染 pptx 并落盘，更新文档状态。返回文件路径。"""
        template, trow = self._resolve_template(template_id or d.template_id, d.theme_id or "")
        outline = ppt_engine.resolve_slide_images(outline, self._user_images(user.id))
        data = ppt_engine.render_pptx(outline, template, base_pptx=self._tpl_base_bytes(trow))
        fname = f"{uuid.uuid4().hex}.pptx"
        path = self.ppt_dir / "generated" / fname
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        if d.file_path and os.path.exists(d.file_path):
            os.remove(d.file_path)
        d.outline = {k: v for k, v in outline.items()}  # 保存解析后的大纲
        d.title = outline.get("title") or d.title
        d.subtitle = outline.get("subtitle") or d.subtitle
        d.file_path = str(path)
        d.status = "generated"
        d.slide_count = len(outline.get("slides") or [])
        if trow:
            d.template_id = trow.id
            trow.use_count = (trow.use_count or 0) + 1
            self.templates.update(trow)
        self.documents.update(d)
        return str(path)

    def generate(self, body, user: User) -> dict:
        """渲染并保存 pptx 文件（编辑器中的'生成/重新生成'动作）。"""
        d = self._get_doc_checked(body.doc_id, user)
        outline = ppt_engine.normalize_outline(body.outline) if body.outline else d.outline
        if not outline:
            raise AppError(400, "大纲为空")
        self._render_and_store(d, outline, user, body.template_id)
        return {"message": "已生成",
                "download_url": f"/api/v1/ppt/documents/{d.id}/download"}

    def export_document(self, doc_id: str, user: User) -> Tuple[Path, str]:
        """导出可编辑 .pptx：按当前草稿重新渲染（保证导出的是最新编辑内容）。"""
        d = self._get_doc_checked(doc_id, user)
        if not d.outline:
            raise NotFoundError("文档不存在或内容为空")
        path = self._render_and_store(d, d.outline, user, None)
        return Path(path), f"{d.title or 'PPT'}.pptx"

    def download_document(self, doc_id: str, user: User) -> Tuple[Path, str]:
        d = self._get_doc_checked(doc_id, user)
        if not d.file_path or not os.path.exists(d.file_path):
            raise NotFoundError("文件不存在，请先生成或导出")
        return Path(d.file_path), f"{d.title or 'PPT'}.pptx"

    def create_blank(self, body, user: User) -> dict:
        outline = ppt_engine.normalize_outline({
            "title": body.title, "subtitle": body.subtitle,
            "slides": [
                {"type": "cover", "title": body.title, "subtitle": body.subtitle},
                {"type": "content", "title": "第一页", "points": ["点击右侧 AI 助手或双击文字开始编辑"]},
                {"type": "closing", "title": "谢谢聆听，请批评指正"},
            ]})
        d = self.documents.add(PPTDocument(
            user_id=user.id, title=body.title, subtitle=body.subtitle,
            source_type="blank", outline=outline, template_id=body.template_id,
            status="draft"))
        return {"doc_id": d.id, "message": "已创建空白PPT"}

    # ================= AI 编辑器操作 =================
    def ai_slide_action(self, body) -> dict:
        try:
            return {"slide": ppt_engine.ai_slide_action(
                self.assistant, body.action, body.slide, body.instruction)}
        except RuntimeError as e:
            raise AIServiceError(str(e))

    def ai_visual(self, body) -> dict:
        try:
            return {"slide": ppt_engine.ai_generate_visual(
                self.assistant, body.kind, body.slide, body.instruction)}
        except RuntimeError as e:
            raise AIServiceError(str(e))

    def ai_structure(self, body) -> dict:
        try:
            slides = ppt_engine.ai_structure_action(
                self.assistant, body.action, body.slides, body.index, body.instruction)
            return {"slides": slides}
        except (RuntimeError, IndexError) as e:
            raise AIServiceError(str(e))

    # ================= 云端生成（qwen-doc-turbo，可选开关，仅脱敏验证用） =================
    @property
    def _cloud_cfg_path(self) -> Path:
        return self.ppt_dir / "cloud_config.json"

    def _load_cloud(self) -> dict:
        cfg = dict(_CLOUD_DEFAULT)
        if self._cloud_cfg_path.exists():
            try:
                cfg.update(_json.loads(self._cloud_cfg_path.read_text(encoding="utf-8")))
            except Exception:
                pass
        return cfg

    def _save_cloud(self, cfg: dict) -> None:
        self._cloud_cfg_path.write_text(
            _json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")

    def get_cloud_config(self) -> dict:
        cfg = self._load_cloud()
        key = cfg.get("api_key") or ""
        return {"enabled": cfg["enabled"],
                "api_key_masked": ("****" + key[-4:]) if key else "",
                "has_key": bool(key),
                "base_url": cfg["base_url"], "mode": cfg["mode"],
                "template_id": cfg["template_id"]}

    def put_cloud_config(self, body) -> dict:
        cfg = self._load_cloud()
        cfg.update(body.dict())
        if not body.api_key:          # 留空表示不修改已有 Key
            cfg["api_key"] = self._load_cloud().get("api_key", "")
        self._save_cloud(cfg)
        return {"message": "云端生成配置已保存"}

    @staticmethod
    def _outline_to_text(outline: dict) -> str:
        parts = [f"《{outline.get('title', '演示文稿')}》"]
        if outline.get("subtitle"):
            parts.append(outline["subtitle"])
        for i, s in enumerate(outline.get("slides") or [], 1):
            seg = f"第{i}页（{s.get('type')}）：{s.get('title', '')}"
            pts = "；".join(s.get("points") or [])
            if pts:
                seg += "——" + pts
            parts.append(seg)
        return "\n".join(parts)[:8000]

    def generate_cloud(self, body, user: User) -> dict:
        """调用阿里云 qwen-doc-turbo PPT skill 生成 PPTX（内容会出网，仅限脱敏材料）。"""
        import requests as _req

        cfg = self._load_cloud()
        if not cfg["enabled"] or not cfg.get("api_key"):
            raise AppError(400, "云端生成未启用或未配置 API Key，请先在「云生成设置」中配置")
        d = self._get_doc_checked(body.doc_id, user)
        if not d.outline:
            raise NotFoundError("文档不存在或内容为空")

        mode = body.mode or cfg["mode"]
        skill = {"type": "ppt", "mode": mode}
        if mode == "general":
            skill["template_id"] = body.template_id or cfg["template_id"]
        n_pages = len(d.outline.get("slides") or [])

        payload = {
            "model": "qwen-doc-turbo",
            "messages": [
                {"role": "system", "content": "you are a helpful assistant."},
                {"role": "system", "content": self._outline_to_text(d.outline)},
                {"role": "user", "content": f"根据以上大纲生成一个{max(n_pages, 6)}到{n_pages + 4}页的ppt"},
            ],
            "skill": [skill],
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        try:
            resp = _req.post(cfg["base_url"].rstrip("/") + "/chat/completions",
                             headers={"Authorization": f"Bearer {cfg['api_key']}",
                                      "Content-Type": "application/json"},
                             json=payload, stream=True, timeout=(15, 300))
        except Exception as e:
            raise AIServiceError(f"云端接口连接失败：{e}")
        if resp.status_code != 200:
            raise AIServiceError(f"云端接口返回 {resp.status_code}：{resp.text[:300]}")

        content = ""
        try:
            for line in resp.iter_lines(decode_unicode=True):
                if not line or not line.startswith("data:"):
                    continue
                data_str = line[5:].strip()
                if data_str == "[DONE]":
                    break
                try:
                    chunk = _json.loads(data_str)
                    delta = (chunk.get("choices") or [{}])[0].get("delta") or {}
                    if delta.get("content"):
                        content += delta["content"]
                except Exception:
                    continue
        finally:
            resp.close()

        m = re.search(r"https?://[^\s\)\"'>]+\.pptx[^\s\)\"'>]*", content)
        if not m:
            raise AIServiceError("云端未返回 PPT 下载链接，返回内容：" + content[:200])
        try:
            file_resp = _req.get(m.group(0), timeout=120)
            file_resp.raise_for_status()
            data = file_resp.content
        except Exception as e:
            raise AIServiceError(f"PPT 文件下载失败：{e}")

        fname = f"{uuid.uuid4().hex}.pptx"
        path = self.ppt_dir / "generated" / fname
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        if d.file_path and os.path.exists(d.file_path):
            os.remove(d.file_path)
        d.file_path = str(path)
        d.status = "generated"
        self.documents.update(d)
        return {"message": "云端生成完成（注意：材料已发送至阿里云，请勿用于真实业务数据）",
                "download_url": f"/api/v1/ppt/documents/{d.id}/download"}
