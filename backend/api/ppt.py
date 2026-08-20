# -*- coding: utf-8 -*-
"""智能 PPT 接口 V2（覆盖 backend/api/ppt.py）

分组：
- 模板：/ppt/templates（官方只读、个人可编辑删除）、收藏、上传模板、分类
- 素材：/ppt/materials（保持原有能力）
- 文档：/ppt/documents（草稿自动保存、复制、收藏、状态过滤）
- 生成：/ppt/outline、/ppt/outline-from-doc、/ppt/generate、/ppt/blank
- AI 操作：/ppt/ai/slide-action、/ppt/ai/visual、/ppt/ai/structure
- 导出：/ppt/documents/{id}/export（生成可编辑 pptx，状态置为已生成）

所有接口要求 JWT 认证。
"""
import os
import shutil
import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session

from backend.database.postgres import get_db
from backend.database.models import User
from backend.auth.permission import get_current_user
from backend.services import ppt_service
from backend.services.llm_service import LLMService
from backend.database.models_ppt import PPTMaterial, PPTTemplate, PPTDocument, PPTTemplateFavorite

router = APIRouter(prefix="/ppt", tags=["智能PPT"])
UPLOAD_DIR = "uploads/ppt"
os.makedirs(UPLOAD_DIR, exist_ok=True)

_llm: Optional[LLMService] = None


def get_llm() -> LLMService:
    global _llm
    if _llm is None:
        _llm = LLMService()
    return _llm


def _uid(user) -> int:
    return user["user_id"] if isinstance(user, dict) else user.id


# ================= 模板 =================

def _template_dto(t: PPTTemplate, user_id: int, db: Session) -> dict:
    fav = db.query(PPTTemplateFavorite).filter_by(
        user_id=user_id, template_id=t.id).first() is not None
    library = t.layout_library or []
    preview_url = ""
    for l in library:
        if l.get("preview"):
            preview_url = f"/api/v1/ppt/templates/{t.id}/layout-preview/{l['id']}"
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


@router.get("/templates")
def list_templates(scope: str = "all", category: Optional[str] = None,
                   keyword: Optional[str] = None, db: Session = Depends(get_db),
                   user=Depends(get_current_user)):
    """模板列表。scope: all / official / mine / favorite"""
    uid = _uid(user)
    q = db.query(PPTTemplate)
    if scope == "official":
        q = q.filter(PPTTemplate.is_official == 1)
    elif scope == "mine":
        q = q.filter(PPTTemplate.is_official == 0, PPTTemplate.created_by == uid)
    elif scope == "favorite":
        fav_ids = [f.template_id for f in
                   db.query(PPTTemplateFavorite).filter_by(user_id=uid).all()]
        q = q.filter(PPTTemplate.id.in_(fav_ids or [-1]))
    else:
        q = q.filter(or_(PPTTemplate.is_official == 1, PPTTemplate.created_by == uid))
    if category:
        q = q.filter(PPTTemplate.category == category)
    if keyword:
        q = q.filter(PPTTemplate.name.contains(keyword))
    rows = q.order_by(PPTTemplate.is_official.desc(), PPTTemplate.use_count.desc()).all()
    return {"items": [_template_dto(t, uid, db) for t in rows]}


@router.get("/templates/categories")
def template_categories(db: Session = Depends(get_db), user=Depends(get_current_user)):
    rows = db.query(PPTTemplate.category).distinct().all()
    return {"items": sorted({r[0] for r in rows if r[0]})}


@router.post("/templates/seed")
def seed_builtin_templates(db: Session = Depends(get_db), user=Depends(get_current_user)):
    """初始化内置官方模板（upsert 模式，可重复调用刷新）"""
    created = 0
    for spec in ppt_service.BUILTIN_TEMPLATES:
        existing = db.query(PPTTemplate).filter_by(builtin_id=spec["id"]).first()
        if existing:
            existing.name, existing.category = spec["name"], spec["category"]
            existing.description, existing.colors = spec.get("description"), spec["colors"]
            existing.layouts = spec["layouts"]
        else:
            db.add(PPTTemplate(
                builtin_id=spec["id"], name=spec["name"], category=spec["category"],
                description=spec.get("description"), is_official=1,
                colors=spec["colors"], layouts=spec["layouts"]))
            created += 1
    db.commit()
    return {"message": f"官方模板已同步（新增 {created} 个）"}


class TemplateIn(BaseModel):
    name: str
    category: str = "其他"
    description: str = ""
    colors: Optional[dict] = None
    font: str = "微软雅黑"
    layouts: Optional[dict] = None


@router.post("/templates")
def create_template(body: TemplateIn, db: Session = Depends(get_db),
                    user=Depends(get_current_user)):
    t = PPTTemplate(
        name=body.name, category=body.category, description=body.description,
        is_official=0, created_by=_uid(user),
        colors={**ppt_service.DEFAULT_COLORS, **(body.colors or {})},
        font=body.font, layouts={**ppt_service.DEFAULT_LAYOUTS, **(body.layouts or {})})
    db.add(t)
    db.commit()
    return {"id": t.id, "message": "模板已创建"}


def _get_editable_template(template_id: str, uid: int, db: Session) -> PPTTemplate:
    t = db.query(PPTTemplate).get(template_id)
    if not t:
        raise HTTPException(404, "模板不存在")
    if t.is_official:
        raise HTTPException(403, "官方模板只能使用，不能修改或删除")
    if t.created_by != uid:
        raise HTTPException(403, "只能修改自己创建的模板")
    return t


@router.put("/templates/{template_id}")
def update_template(template_id: str, body: TemplateIn, db: Session = Depends(get_db),
                    user=Depends(get_current_user)):
    t = _get_editable_template(template_id, _uid(user), db)
    t.name, t.category, t.description = body.name, body.category, body.description
    if body.colors:
        t.colors = {**(t.colors or {}), **body.colors}
    t.font = body.font or t.font
    if body.layouts:
        t.layouts = {**(t.layouts or {}), **body.layouts}
    db.commit()
    return {"message": "模板已更新"}


@router.delete("/templates/{template_id}")
def delete_template(template_id: str, db: Session = Depends(get_db),
                    user=Depends(get_current_user)):
    t = _get_editable_template(template_id, _uid(user), db)
    db.query(PPTTemplateFavorite).filter_by(template_id=t.id).delete()
    db.delete(t)
    db.commit()
    # 删除模板底版文件（如有）
    p = _tpl_source_path(template_id)
    if os.path.exists(p):
        try:
            os.remove(p)
        except Exception:
            pass
    return {"message": "模板已删除"}


@router.post("/templates/{template_id}/favorite")
def toggle_favorite(template_id: str, db: Session = Depends(get_db),
                    user=Depends(get_current_user)):
    uid = _uid(user)
    fav = db.query(PPTTemplateFavorite).filter_by(
        user_id=uid, template_id=template_id).first()
    if fav:
        db.delete(fav)
        db.commit()
        return {"is_favorite": False}
    db.add(PPTTemplateFavorite(user_id=uid, template_id=template_id))
    db.commit()
    return {"is_favorite": True}


@router.post("/templates/upload")
async def upload_template(file: UploadFile = File(...), name: str = Form(""),
                          category: str = Form("其他"), db: Session = Depends(get_db),
                          user=Depends(get_current_user)):
    """上传 .pptx 作为个人模板：提取主题色与字体，沿用默认版式体系"""
    if not file.filename.lower().endswith(".pptx"):
        raise HTTPException(400, "仅支持 .pptx 文件")
    data = await file.read()
    if not data:
        raise HTTPException(400, "文件内容为空")
    if len(data) > 50 * 1024 * 1024:
        raise HTTPException(400, "文件过大（限 50MB）")
    import zipfile, io as _io
    if not zipfile.is_zipfile(_io.BytesIO(data)):
        raise HTTPException(400, "文件损坏或不是有效的 .pptx 文件")
    try:
        learned = ppt_service.analyze_template(data)
    except Exception as e:
        raise HTTPException(400, f"模板解析失败：{e}")
    try:
        t = PPTTemplate(
            name=name or os.path.splitext(file.filename)[0], category=category,
            description="用户上传的模板", is_official=0, created_by=_uid(user),
            colors=learned["colors"], font=learned["font"],
            layouts=ppt_service.DEFAULT_LAYOUTS.copy(),  # fallback 版式变体
            source_file=file.filename)
        db.add(t)
        db.commit()
        # 保存原始 pptx 作为渲染底版（生成时完整保留母版/背景/装饰）
        _save_tpl_source(t.id, data)
        # 生成版式预览图并保存版式库
        library = learned.get("layouts") or []
        _gen_tpl_previews(t.id, data, library)
        t.layout_library = library
        db.commit()
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(500, f"模板保存失败：{e}（如提示缺少列，请重启后端完成自动迁移后再试）")
    n = len(t.layout_library or [])
    return {"id": t.id,
            "message": f"模板「{t.name}」已创建，自动识别出 {n} 种版式",
            "layout_count": n}


def _tpl_source_path(template_id: str) -> str:
    return os.path.join(UPLOAD_DIR, "tpl_src", f"{template_id}.pptx")


def _save_tpl_source(template_id: str, data: bytes):
    d = os.path.join(UPLOAD_DIR, "tpl_src")
    os.makedirs(d, exist_ok=True)
    with open(_tpl_source_path(template_id), "wb") as f:
        f.write(data)


def _gen_tpl_previews(template_id: str, data: bytes, layouts: list):
    """用 LibreOffice 把上传的 pptx 渲染成图片，截取各版式源页作为预览图。
    失败不影响上传（前端回退到结构示意图）。直接在 layouts 上写 preview 字段。"""
    try:
        import subprocess, tempfile, glob, shutil
        d = os.path.join(UPLOAD_DIR, "tpl_prev", template_id)
        os.makedirs(d, exist_ok=True)
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
                    shutil.copy(pages[i], os.path.join(d, f"{lay['id']}.png"))
                    lay["preview"] = f"{lay['id']}.png"
    except Exception as e:
        print(f"[PPT] 模板预览图生成失败（不影响使用）: {e}")


@router.get("/templates/{template_id}/layout-preview/{layout_id}")
def layout_preview(template_id: str, layout_id: str):
    """版式预览图（无需登录的静态资源，走 img 标签直接引用）"""
    from fastapi.responses import FileResponse
    p = os.path.join(UPLOAD_DIR, "tpl_prev", template_id, f"{layout_id}.png")
    if not os.path.exists(p):
        raise HTTPException(404, "预览图不存在")
    return FileResponse(p, media_type="image/png")


@router.get("/templates/{template_id}")
def template_detail(template_id: str, db: Session = Depends(get_db),
                    user=Depends(get_current_user)):
    """模板详情：含完整版式库（前端动态展示各版式预览与名称）"""
    t = db.query(PPTTemplate).get(template_id)
    if not t:
        raise HTTPException(404, "模板不存在")
    d = _template_dto(t, _uid(user), db)
    library = []
    for l in (t.layout_library or []):
        item = dict(l)
        item.pop("element_schema", None)  # 结构 schema 不给前端，太大
        if item.get("preview"):
            item["preview_url"] = f"/api/v1/ppt/templates/{t.id}/layout-preview/{item['id']}"
        library.append(item)
    d["layout_library"] = library
    return d


def _tpl_base_bytes(trow) -> bytes:
    """读取上传模板的原始 pptx 作为渲染底版；官方内置模板没有底版，返回 None"""
    if not trow:
        return None
    p = _tpl_source_path(trow.id)
    if os.path.exists(p):
        try:
            with open(p, "rb") as f:
                return f.read()
        except Exception:
            return None
    return None


@router.post("/templates/{template_id}/copy")
def copy_template(template_id: str, db: Session = Depends(get_db),
                  user=Depends(get_current_user)):
    """复制模板（官方模板复制为个人模板，可在我的模板中编辑）"""
    t = db.query(PPTTemplate).get(template_id)
    if not t:
        raise HTTPException(404, "模板不存在")
    nt = PPTTemplate(
        name=t.name + "（副本）", category=t.category, description=t.description,
        is_official=0, created_by=_uid(user), colors=dict(t.colors or {}),
        font=t.font, layouts=dict(t.layouts or {}))
    db.add(nt)
    db.commit()
    # 底版文件一并复制，副本渲染效果与原模板一致
    src = _tpl_base_bytes(t)
    if src:
        _save_tpl_source(nt.id, src)
    return {"id": nt.id, "message": "已复制到「我的模板」"}


class ImportUrlIn(BaseModel):
    url: str
    name: str = ""
    category: str = "其他"


@router.post("/templates/import-url")
def import_template_url(body: ImportUrlIn, db: Session = Depends(get_db),
                        user=Depends(get_current_user)):
    """从在线链接导入 pptx 模板（仅提取版式风格，不保存原始内容）"""
    if not body.url.lower().startswith(("http://", "https://")):
        raise HTTPException(400, "请输入有效的 http(s) 链接")
    try:
        import requests
        resp = requests.get(body.url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        data = resp.content
    except Exception as e:
        raise HTTPException(400, f"下载失败：{e}")
    if len(data) > 50 * 1024 * 1024:
        raise HTTPException(400, "文件超过 50MB")
    learned = ppt_service.analyze_template(data)
    name = body.name or os.path.splitext(os.path.basename(body.url.split("?")[0]))[0] or "在线导入模板"
    t = PPTTemplate(
        name=name, category=body.category, description="从在线链接导入的模板",
        is_official=0, created_by=_uid(user),
        colors=learned["colors"], font=learned["font"],
        layouts=ppt_service.DEFAULT_LAYOUTS.copy(),
        source_file=body.url[:500])
    db.add(t)
    db.commit()
    _save_tpl_source(t.id, data)
    library = learned.get("layouts") or []
    _gen_tpl_previews(t.id, data, library)
    t.layout_library = library
    db.commit()
    return {"id": t.id, "message": f"模板「{t.name}」已导入，自动识别出 {len(library)} 种版式"}


# ================= 素材库 =================

@router.get("/materials")
def list_materials(db: Session = Depends(get_db), user=Depends(get_current_user)):
    rows = db.query(PPTMaterial).filter_by(user_id=_uid(user)) \
        .order_by(PPTMaterial.created_at.desc()).all()
    return {"items": [{"id": m.id, "name": m.name, "caption": m.caption,
                       "url": f"/api/v1/ppt/materials/{m.id}/file"} for m in rows]}


@router.post("/materials")
async def upload_material(name: str = Form(...), caption: str = Form(""),
                          file: UploadFile = File(...), db: Session = Depends(get_db),
                          user=Depends(get_current_user)):
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in [".jpg", ".jpeg", ".png", ".webp", ".gif"]:
        raise HTTPException(400, "仅支持图片文件")
    fname = f"{uuid.uuid4().hex}{ext}"
    path = os.path.join(UPLOAD_DIR, fname)
    with open(path, "wb") as f:
        shutil.copyfileobj(file.file, f)
    m = PPTMaterial(user_id=_uid(user), name=name, caption=caption,
                    file_path=path, mime_type=file.content_type or "")
    db.add(m)
    db.commit()
    return {"id": m.id, "message": "素材已上传"}


@router.put("/materials/{mid}")
def update_material(mid: str, name: str = Form(...), caption: str = Form(""),
                    db: Session = Depends(get_db), user=Depends(get_current_user)):
    m = db.query(PPTMaterial).filter_by(id=mid, user_id=_uid(user)).first()
    if not m:
        raise HTTPException(404, "素材不存在")
    m.name, m.caption = name, caption
    db.commit()
    return {"message": "素材已更新"}


@router.delete("/materials/{mid}")
def delete_material(mid: str, db: Session = Depends(get_db), user=Depends(get_current_user)):
    m = db.query(PPTMaterial).filter_by(id=mid, user_id=_uid(user)).first()
    if not m:
        raise HTTPException(404, "素材不存在")
    if os.path.exists(m.file_path):
        os.remove(m.file_path)
    db.delete(m)
    db.commit()
    return {"message": "素材已删除"}


@router.get("/materials/{mid}/file")
def material_file(mid: str, db: Session = Depends(get_db), user=Depends(get_current_user)):
    m = db.query(PPTMaterial).filter_by(id=mid, user_id=_uid(user)).first()
    if not m or not os.path.exists(m.file_path):
        raise HTTPException(404, "文件不存在")
    return FileResponse(m.file_path, media_type=m.mime_type or "image/jpeg")


# ================= 文档（我的PPT） =================

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


@router.get("/documents")
def list_documents(tab: str = "all", keyword: Optional[str] = None,
                   db: Session = Depends(get_db), user=Depends(get_current_user)):
    """我的PPT列表。tab: all / draft / generated / favorite"""
    uid = _uid(user)
    q = db.query(PPTDocument).filter_by(user_id=uid)
    if tab == "draft":
        q = q.filter(PPTDocument.status == "draft")
    elif tab == "generated":
        q = q.filter(PPTDocument.status == "generated")
    elif tab == "favorite":
        q = q.filter(PPTDocument.is_favorite == 1)
    if keyword:
        q = q.filter(PPTDocument.title.contains(keyword))
    rows = q.order_by(PPTDocument.updated_at.desc()).all()
    tmap = {t.id: t.name for t in db.query(PPTTemplate).all()}
    return {"items": [_doc_dto(d, tmap.get(d.template_id, "")) for d in rows]}


@router.get("/documents/{doc_id}")
def get_document(doc_id: str, db: Session = Depends(get_db), user=Depends(get_current_user)):
    d = db.query(PPTDocument).filter_by(id=doc_id, user_id=_uid(user)).first()
    if not d:
        raise HTTPException(404, "文档不存在")
    template = None
    if d.template_id:
        t = db.query(PPTTemplate).get(d.template_id)
        if t:
            template = ppt_service.template_to_dict(t)
    elif d.theme_id:  # 兼容旧文档（theme_id 即内置模板 id）
        spec = next((s for s in ppt_service.BUILTIN_TEMPLATES if s["id"] == d.theme_id), None)
        if spec:
            template = ppt_service.template_to_dict(spec)
    if not template:
        template = ppt_service.template_to_dict(ppt_service.BUILTIN_TEMPLATES[0])
    return {**_doc_dto(d, template["name"]), "outline": d.outline, "template": template}


class DraftIn(BaseModel):
    title: Optional[str] = None
    subtitle: Optional[str] = None
    outline: Optional[dict] = None
    template_id: Optional[str] = None


@router.put("/documents/{doc_id}/draft")
def save_draft(doc_id: str, body: DraftIn, db: Session = Depends(get_db),
               user=Depends(get_current_user)):
    """自动保存草稿（编辑器定时调用）：只更新内容，不改变状态"""
    d = db.query(PPTDocument).filter_by(id=doc_id, user_id=_uid(user)).first()
    if not d:
        raise HTTPException(404, "文档不存在")
    if body.outline is not None:
        d.outline = ppt_service.normalize_outline(body.outline)
        d.title = body.title or d.outline.get("title") or d.title
        d.subtitle = d.outline.get("subtitle") or d.subtitle
    elif body.title:
        d.title = body.title
    if body.template_id:
        t = db.query(PPTTemplate).get(body.template_id)
        if t:
            d.template_id = t.id
    d.updated_at = datetime.now()
    db.commit()
    return {"message": "已保存", "updated_at": d.updated_at.strftime("%H:%M:%S")}


@router.post("/documents/{doc_id}/copy")
def copy_document(doc_id: str, db: Session = Depends(get_db), user=Depends(get_current_user)):
    d = db.query(PPTDocument).filter_by(id=doc_id, user_id=_uid(user)).first()
    if not d:
        raise HTTPException(404, "文档不存在")
    nd = PPTDocument(user_id=_uid(user), title=d.title + "（副本）", subtitle=d.subtitle,
                     source_type=d.source_type, source_content=d.source_content,
                     outline=d.outline, theme_id=d.theme_id, template_id=d.template_id,
                     status="draft")
    db.add(nd)
    db.commit()
    return {"id": nd.id, "message": "已复制"}


@router.post("/documents/{doc_id}/favorite")
def toggle_doc_favorite(doc_id: str, db: Session = Depends(get_db), user=Depends(get_current_user)):
    d = db.query(PPTDocument).filter_by(id=doc_id, user_id=_uid(user)).first()
    if not d:
        raise HTTPException(404, "文档不存在")
    d.is_favorite = 0 if d.is_favorite else 1
    db.commit()
    return {"is_favorite": bool(d.is_favorite)}


@router.delete("/documents/{doc_id}")
def delete_document(doc_id: str, db: Session = Depends(get_db), user=Depends(get_current_user)):
    d = db.query(PPTDocument).filter_by(id=doc_id, user_id=_uid(user)).first()
    if not d:
        raise HTTPException(404, "文档不存在")
    if d.file_path and os.path.exists(d.file_path):
        os.remove(d.file_path)
    db.delete(d)
    db.commit()
    return {"message": "已删除"}


# ================= 生成流程 =================

class OutlineIn(BaseModel):
    source_type: str = "topic"          # topic / text / document / kb
    topic: str = ""
    content: str = ""
    slide_count: int = 10
    audience: str = ""                  # 汇报对象
    scene: str = ""                     # 场景用途


@router.get("/kbs")
def list_kbs(db: Session = Depends(get_db), user=Depends(get_current_user)):
    """PPT 可选知识库列表（含文档数）"""
    from backend.database.models import KnowledgeBase, Document
    rows = db.query(KnowledgeBase).filter(KnowledgeBase.is_active == True).all()  # noqa: E712
    items = []
    for kb in rows:
        cnt = db.query(Document).filter_by(kb_id=kb.id, status="published").count()
        items.append({"id": kb.id, "name": kb.name, "description": kb.description or "",
                      "doc_count": cnt})
    return {"items": items}


def _kb_content(db: Session, kb_ids: list, limit: int = 6000) -> str:
    """汇总所选知识库已发布文档的内容（按文档截断拼接）"""
    from backend.database.models import Document
    docs = db.query(Document).filter(
        Document.kb_id.in_(kb_ids), Document.status == "published") \
        .order_by(Document.created_at.desc()).limit(20).all()
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


@router.post("/outline-from-kb")
def outline_from_kb(kb_ids: List[str] = Form(...), topic: str = Form(""),
                    audience: str = Form(""), scene: str = Form(""),
                    slide_count: int = Form(10), db: Session = Depends(get_db),
                    user=Depends(get_current_user)):
    """根据知识库生成大纲"""
    content = _kb_content(db, kb_ids)
    if not content:
        raise HTTPException(400, "所选知识库没有可用的已发布文档内容")
    return _do_outline(db, user, "kb", topic, content, slide_count, audience, scene)


@router.post("/extract-text")
async def extract_text(file: UploadFile = File(...), user=Depends(get_current_user)):
    """提取单个文档文本（前端多文件时循环调用，自行拼接后走 /outline）"""
    from backend.services.document_service import AttachmentService
    data = await file.read()
    try:
        text = AttachmentService._extract(file.filename, data)
    except Exception as e:
        raise HTTPException(400, f"文件「{file.filename}」解析失败：{e}")
    if not text.strip():
        raise HTTPException(400, f"未能从「{file.filename}」提取到文字内容")
    return {"filename": file.filename, "text": text[:3000]}


def _do_outline(db, user, source_type, topic, content, slide_count, audience="", scene=""):
    uid = _uid(user)
    images = [{"name": m.name, "caption": m.caption, "file_path": m.file_path}
              for m in db.query(PPTMaterial).filter_by(user_id=uid).all()]
    try:
        outline = ppt_service.generate_outline(
            get_llm(), source_type, topic, content, images,
            max(6, min(slide_count, 18)), audience, scene)
    except RuntimeError as e:
        raise HTTPException(502, str(e))
    d = PPTDocument(user_id=uid, title=outline.get("title", "未命名PPT"),
                    subtitle=outline.get("subtitle", ""), source_type=source_type,
                    source_content=(topic or content or "")[:2000],
                    outline=outline, status="draft")
    db.add(d)
    db.commit()
    return {"doc_id": d.id, "outline": outline}


@router.post("/outline")
def make_outline(body: OutlineIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    return _do_outline(db, user, body.source_type, body.topic, body.content,
                       body.slide_count, body.audience, body.scene)


@router.post("/outline-from-doc")
async def outline_from_doc(file: UploadFile = File(...), topic: str = Form(""),
                           audience: str = Form(""), scene: str = Form(""),
                           slide_count: int = Form(10), db: Session = Depends(get_db),
                           user=Depends(get_current_user)):
    from backend.services.document_service import AttachmentService
    data = await file.read()
    try:
        text = AttachmentService._extract(file.filename, data)
    except Exception as e:
        raise HTTPException(400, f"文件解析失败：{e}")
    if not text.strip():
        raise HTTPException(400, "未能从文件中提取到文字内容")
    return _do_outline(db, user, "document", topic, text, slide_count, audience, scene)


class GenerateIn(BaseModel):
    doc_id: str
    template_id: Optional[str] = None
    outline: Optional[dict] = None       # 用户修改后的大纲


def _resolve_template(db: Session, template_id: Optional[int], fallback_theme: str = ""):
    if template_id:
        t = db.query(PPTTemplate).get(template_id)
        if t:
            return ppt_service.template_to_dict(t), t
    spec = next((s for s in ppt_service.BUILTIN_TEMPLATES if s["id"] == fallback_theme), None)
    if not spec:
        spec = ppt_service.BUILTIN_TEMPLATES[0]
        t = db.query(PPTTemplate).filter_by(builtin_id=spec["id"]).first()
        if t:
            return ppt_service.template_to_dict(t), t
    return ppt_service.template_to_dict(spec), None


@router.post("/generate")
def generate(body: GenerateIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    """渲染并保存 pptx 文件（编辑器中的'生成/重新生成'动作）"""
    uid = _uid(user)
    d = db.query(PPTDocument).filter_by(id=body.doc_id, user_id=uid).first()
    if not d:
        raise HTTPException(404, "文档不存在")
    outline = ppt_service.normalize_outline(body.outline) if body.outline else d.outline
    if not outline:
        raise HTTPException(400, "大纲为空")
    template, trow = _resolve_template(db, body.template_id or d.template_id, d.theme_id or "")
    images = [{"name": m.name, "caption": m.caption, "file_path": m.file_path}
              for m in db.query(PPTMaterial).filter_by(user_id=uid).all()]
    outline = ppt_service.resolve_slide_images(outline, images)
    data = ppt_service.render_pptx(outline, template, base_pptx=_tpl_base_bytes(trow))
    fname = f"{uuid.uuid4().hex}.pptx"
    path = os.path.join(UPLOAD_DIR, fname)
    with open(path, "wb") as f:
        f.write(data)
    if d.file_path and os.path.exists(d.file_path):
        os.remove(d.file_path)
    d.outline = {k: v for k, v in outline.items()}  # 保存解析后的大纲（含 _image 也无妨）
    d.title = outline.get("title") or d.title
    d.subtitle = outline.get("subtitle") or d.subtitle
    d.file_path = path
    d.status = "generated"
    if trow:
        d.template_id = trow.id
        trow.use_count = (trow.use_count or 0) + 1
    d.updated_at = datetime.now()
    db.commit()
    return {"message": "已生成", "download_url": f"/api/v1/ppt/documents/{d.id}/download"}


@router.post("/documents/{doc_id}/export")
def export_document(doc_id: str, db: Session = Depends(get_db), user=Depends(get_current_user)):
    """导出可编辑 .pptx：按当前草稿重新渲染（保证导出的是最新编辑内容）"""
    uid = _uid(user)
    d = db.query(PPTDocument).filter_by(id=doc_id, user_id=uid).first()
    if not d or not d.outline:
        raise HTTPException(404, "文档不存在或内容为空")
    template, trow = _resolve_template(db, d.template_id, d.theme_id or "")
    images = [{"name": m.name, "caption": m.caption, "file_path": m.file_path}
              for m in db.query(PPTMaterial).filter_by(user_id=uid).all()]
    outline = ppt_service.resolve_slide_images(d.outline, images)
    data = ppt_service.render_pptx(outline, template, base_pptx=_tpl_base_bytes(trow))
    fname = f"{uuid.uuid4().hex}.pptx"
    path = os.path.join(UPLOAD_DIR, fname)
    with open(path, "wb") as f:
        f.write(data)
    if d.file_path and os.path.exists(d.file_path):
        os.remove(d.file_path)
    d.file_path = path
    d.status = "generated"
    d.updated_at = datetime.now()
    if trow:
        trow.use_count = (trow.use_count or 0) + 1
    db.commit()
    return FileResponse(path, media_type="application/vnd.openxmlformats-officedocument."
                        "presentationml.presentation",
                        filename=f"{d.title or 'PPT'}.pptx")


@router.get("/documents/{doc_id}/download")
def download_document(doc_id: str, db: Session = Depends(get_db), user=Depends(get_current_user)):
    d = db.query(PPTDocument).filter_by(id=doc_id, user_id=_uid(user)).first()
    if not d or not d.file_path or not os.path.exists(d.file_path):
        raise HTTPException(404, "文件不存在，请先生成或导出")
    return FileResponse(d.file_path, media_type="application/vnd.openxmlformats-officedocument."
                        "presentationml.presentation",
                        filename=f"{d.title or 'PPT'}.pptx")


class BlankIn(BaseModel):
    title: str = "未命名PPT"
    subtitle: str = ""
    template_id: Optional[str] = None


@router.post("/blank")
def create_blank(body: BlankIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    outline = ppt_service.normalize_outline({
        "title": body.title, "subtitle": body.subtitle,
        "slides": [
            {"type": "cover", "title": body.title, "subtitle": body.subtitle},
            {"type": "content", "title": "第一页", "points": ["点击右侧 AI 助手或双击文字开始编辑"]},
            {"type": "closing", "title": "谢谢聆听，请批评指正"},
        ]})
    d = PPTDocument(user_id=_uid(user), title=body.title, subtitle=body.subtitle,
                    source_type="blank", outline=outline, template_id=body.template_id,
                    status="draft")
    db.add(d)
    db.commit()
    return {"doc_id": d.id, "message": "已创建空白PPT"}


# ================= AI 编辑器操作 =================

class SlideActionIn(BaseModel):
    action: str                    # rewrite / expand / condense / custom
    slide: dict
    instruction: str = ""


@router.post("/ai/slide-action")
def ai_slide_action(body: SlideActionIn, user=Depends(get_current_user)):
    try:
        return {"slide": ppt_service.ai_slide_action(
            get_llm(), body.action, body.slide, body.instruction)}
    except RuntimeError as e:
        raise HTTPException(502, str(e))


class VisualIn(BaseModel):
    kind: str                      # chart / timeline / process / data
    slide: dict
    instruction: str = ""


@router.post("/ai/visual")
def ai_visual(body: VisualIn, user=Depends(get_current_user)):
    try:
        return {"slide": ppt_service.ai_generate_visual(
            get_llm(), body.kind, body.slide, body.instruction)}
    except RuntimeError as e:
        raise HTTPException(502, str(e))


class StructureIn(BaseModel):
    action: str                    # add / split / merge
    slides: List[dict]
    index: int
    instruction: str = ""


@router.post("/ai/structure")
def ai_structure(body: StructureIn, user=Depends(get_current_user)):
    try:
        slides = ppt_service.ai_structure_action(
            get_llm(), body.action, body.slides, body.index, body.instruction)
        return {"slides": slides}
    except (RuntimeError, IndexError) as e:
        raise HTTPException(502, str(e))


# ================= 云端生成（qwen-doc-turbo，可选开关，仅脱敏验证用） =================

CLOUD_CFG_PATH = os.path.join(UPLOAD_DIR, "cloud_config.json")
_CLOUD_DEFAULT = {
    "enabled": False,
    "api_key": "",
    # 华北2（北京）地域 OpenAI 兼容地址；如使用业务空间专属地址可改
    "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "mode": "general",               # general=模板模式 / creative=创意模式（图版PPT，每页为图片）
    "template_id": "summary_01",     # news_01 / summary_01 / internet_01 / thesis_01
}


def _load_cloud() -> dict:
    cfg = dict(_CLOUD_DEFAULT)
    if os.path.exists(CLOUD_CFG_PATH):
        try:
            import json as _json
            with open(CLOUD_CFG_PATH, encoding="utf-8") as f:
                cfg.update(_json.load(f))
        except Exception:
            pass
    return cfg


def _save_cloud(cfg: dict):
    import json as _json
    with open(CLOUD_CFG_PATH, "w", encoding="utf-8") as f:
        _json.dump(cfg, f, ensure_ascii=False, indent=2)


class CloudCfgIn(BaseModel):
    enabled: bool = False
    api_key: str = ""
    base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    mode: str = "general"
    template_id: str = "summary_01"


@router.get("/cloud-config")
def get_cloud_config(user=Depends(get_current_user)):
    cfg = _load_cloud()
    key = cfg.get("api_key") or ""
    return {"enabled": cfg["enabled"],
            "api_key_masked": ("****" + key[-4:]) if key else "",
            "has_key": bool(key),
            "base_url": cfg["base_url"], "mode": cfg["mode"], "template_id": cfg["template_id"]}


@router.put("/cloud-config")
def put_cloud_config(body: CloudCfgIn, user=Depends(get_current_user)):
    cfg = _load_cloud()
    cfg.update(body.dict())
    if not body.api_key:          # 留空表示不修改已有 Key
        old = _load_cloud()
        cfg["api_key"] = old.get("api_key", "")
    _save_cloud(cfg)
    return {"message": "云端生成配置已保存"}


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


class CloudGenIn(BaseModel):
    doc_id: str
    mode: str = ""
    template_id: str = ""


@router.post("/generate-cloud")
def generate_cloud(body: CloudGenIn, db: Session = Depends(get_db),
                   user=Depends(get_current_user)):
    """调用阿里云 qwen-doc-turbo PPT skill 生成 PPTX（内容会出网，仅限脱敏材料）。"""
    import json as _json
    import re as _re
    import requests as _req

    cfg = _load_cloud()
    if not cfg["enabled"] or not cfg.get("api_key"):
        raise HTTPException(400, "云端生成未启用或未配置 API Key，请先在「云生成设置」中配置")
    uid = _uid(user)
    d = db.query(PPTDocument).filter_by(id=body.doc_id, user_id=uid).first()
    if not d or not d.outline:
        raise HTTPException(404, "文档不存在或内容为空")

    mode = body.mode or cfg["mode"]
    skill = {"type": "ppt", "mode": mode}
    if mode == "general":
        skill["template_id"] = body.template_id or cfg["template_id"]
    n_pages = len(d.outline.get("slides") or [])

    payload = {
        "model": "qwen-doc-turbo",
        "messages": [
            {"role": "system", "content": "you are a helpful assistant."},
            {"role": "system", "content": _outline_to_text(d.outline)},
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
        raise HTTPException(502, f"云端接口连接失败：{e}")
    if resp.status_code != 200:
        raise HTTPException(502, f"云端接口返回 {resp.status_code}：{resp.text[:300]}")

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

    m = _re.search(r"https?://[^\s\)\"'>]+\.pptx[^\s\)\"'>]*", content)
    if not m:
        raise HTTPException(502, "云端未返回 PPT 下载链接，返回内容：" + content[:200])
    try:
        file_resp = _req.get(m.group(0), timeout=120)
        file_resp.raise_for_status()
        data = file_resp.content
    except Exception as e:
        raise HTTPException(502, f"PPT 文件下载失败：{e}")

    fname = f"{uuid.uuid4().hex}.pptx"
    path = os.path.join(UPLOAD_DIR, fname)
    with open(path, "wb") as f:
        f.write(data)
    if d.file_path and os.path.exists(d.file_path):
        os.remove(d.file_path)
    d.file_path = path
    d.status = "generated"
    d.updated_at = datetime.now()
    db.commit()
    return {"message": "云端生成完成（注意：材料已发送至阿里云，请勿用于真实业务数据）",
            "download_url": f"/api/v1/ppt/documents/{d.id}/download"}


# ================= 兼容旧接口 =================

@router.get("/themes")
def list_themes(user=Depends(get_current_user)):
    """旧首页兼容：主题 = 内置官方模板"""
    return {"items": [{"id": s["id"], "name": s["name"], "category": s["category"],
                       "description": s.get("description", ""), "colors": s["colors"]}
                      for s in ppt_service.BUILTIN_TEMPLATES]}