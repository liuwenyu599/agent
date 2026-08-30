"""PPT 助手路由。路径与响应结构与旧系统一致（/ppt/...）。"""
import os
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.application.ppt.dto import (
    BlankIn,
    CloudCfgIn,
    CloudGenIn,
    DraftIn,
    GenerateIn,
    ImportUrlIn,
    OutlineIn,
    SlideActionIn,
    StructureIn,
    TemplateIn,
    VisualIn,
)
from app.application.ppt.service import PPTService
from app.application.shared.writing_assistant import WritingAssistant
from app.domain.identity.entities import User
from app.infrastructure.ai import get_llm_gateway
from app.infrastructure.database import get_db
from app.interfaces.deps import get_current_user

router = APIRouter(prefix="/ppt", tags=["智能PPT"])


def get_ppt_service(db: Session = Depends(get_db)) -> PPTService:
    return PPTService(db, WritingAssistant(get_llm_gateway()))


# ================= 模板 =================

@router.get("/templates")
def list_templates(scope: str = "all", category: Optional[str] = None,
                   keyword: Optional[str] = Query(None),
                   user: User = Depends(get_current_user),
                   svc: PPTService = Depends(get_ppt_service)):
    return svc.list_templates(user, scope, category, keyword)


@router.get("/templates/categories")
def template_categories(user: User = Depends(get_current_user),
                        svc: PPTService = Depends(get_ppt_service)):
    return svc.list_categories()


@router.post("/templates/seed")
def seed_builtin_templates(user: User = Depends(get_current_user),
                         svc: PPTService = Depends(get_ppt_service)):
    return svc.seed_builtin_templates()


@router.post("/templates")
def create_template(body: TemplateIn,
                    user: User = Depends(get_current_user),
                    svc: PPTService = Depends(get_ppt_service)):
    return svc.create_template(body, user)


@router.put("/templates/{template_id}")
def update_template(template_id: str, body: TemplateIn,
                    user: User = Depends(get_current_user),
                    svc: PPTService = Depends(get_ppt_service)):
    return svc.update_template(template_id, body, user)


@router.delete("/templates/{template_id}")
def delete_template(template_id: str, user: User = Depends(get_current_user),
                  svc: PPTService = Depends(get_ppt_service)):
    return svc.delete_template(template_id, user)


@router.post("/templates/{template_id}/favorite")
def toggle_favorite(template_id: str, user: User = Depends(get_current_user),
                    svc: PPTService = Depends(get_ppt_service)):
    return svc.toggle_favorite(template_id, user)


@router.post("/templates/upload")
async def upload_template(file: UploadFile = File(...), name: str = Form(""),
                          category: str = Form("其他"),
                          user: User = Depends(get_current_user),
                          svc: PPTService = Depends(get_ppt_service)):
    return await svc.upload_template(file, name, category, user)


@router.get("/templates/{template_id}/layout-preview/{layout_id}")
def layout_preview(template_id: str, layout_id: str,
                   svc: PPTService = Depends(get_ppt_service)):
    p = svc.get_layout_preview(template_id, layout_id)
    return FileResponse(str(p), media_type="image/png")


@router.get("/templates/{template_id}")
def template_detail(template_id: str, user: User = Depends(get_current_user),
                    svc: PPTService = Depends(get_ppt_service)):
    return svc.template_detail(template_id, user)


@router.post("/templates/{template_id}/copy")
def copy_template(template_id: str, user: User = Depends(get_current_user),
                svc: PPTService = Depends(get_ppt_service)):
    return svc.copy_template(template_id, user)


@router.post("/templates/import-url")
def import_template_url(body: ImportUrlIn,
                      user: User = Depends(get_current_user),
                      svc: PPTService = Depends(get_ppt_service)):
    return svc.import_template_url(body, user)


@router.get("/themes")
def list_themes(user: User = Depends(get_current_user),
                svc: PPTService = Depends(get_ppt_service)):
    return svc.list_themes()


# ================= 素材库 =================

@router.get("/materials")
def list_materials(user: User = Depends(get_current_user),
                   svc: PPTService = Depends(get_ppt_service)):
    return svc.list_materials(user)


@router.post("/materials")
async def upload_material(name: str = Form(...), caption: str = Form(""),
                          file: UploadFile = File(...),
                          user: User = Depends(get_current_user),
                          svc: PPTService = Depends(get_ppt_service)):
    return await svc.upload_material(name, caption, file, user)


@router.put("/materials/{mid}")
def update_material(mid: str, name: str = Form(...), caption: str = Form(""),
                    user: User = Depends(get_current_user),
                    svc: PPTService = Depends(get_ppt_service)):
    return svc.update_material(mid, name, caption, user)


@router.delete("/materials/{mid}")
def delete_material(mid: str, user: User = Depends(get_current_user),
                    svc: PPTService = Depends(get_ppt_service)):
    return svc.delete_material(mid, user)


@router.get("/materials/{mid}/file")
def material_file(mid: str, user: User = Depends(get_current_user),
                  svc: PPTService = Depends(get_ppt_service)):
    path, mime = svc.material_file(mid, user)
    return FileResponse(str(path), media_type=mime)


# ================= 文档（我的PPT） =================

@router.get("/documents")
def list_documents(tab: str = "all", keyword: Optional[str] = Query(None),
                   user: User = Depends(get_current_user),
                   svc: PPTService = Depends(get_ppt_service)):
    return svc.list_documents(user, tab, keyword)


@router.get("/documents/{doc_id}")
def get_document(doc_id: str, user: User = Depends(get_current_user),
               svc: PPTService = Depends(get_ppt_service)):
    return svc.get_document(doc_id, user)


@router.put("/documents/{doc_id}/draft")
def save_draft(doc_id: str, body: DraftIn,
               user: User = Depends(get_current_user),
               svc: PPTService = Depends(get_ppt_service)):
    return svc.save_draft(doc_id, body, user)


@router.post("/documents/{doc_id}/copy")
def copy_document(doc_id: str, user: User = Depends(get_current_user),
                svc: PPTService = Depends(get_ppt_service)):
    return svc.copy_document(doc_id, user)


@router.post("/documents/{doc_id}/favorite")
def toggle_doc_favorite(doc_id: str, user: User = Depends(get_current_user),
                      svc: PPTService = Depends(get_ppt_service)):
    return svc.toggle_doc_favorite(doc_id, user)


@router.delete("/documents/{doc_id}")
def delete_document(doc_id: str, user: User = Depends(get_current_user),
                  svc: PPTService = Depends(get_ppt_service)):
    return svc.delete_document(doc_id, user)


# ================= 生成流程 =================

@router.get("/kbs")
def list_kbs(user: User = Depends(get_current_user),
             svc: PPTService = Depends(get_ppt_service)):
    return svc.list_kbs()


@router.post("/outline-from-kb")
def outline_from_kb(kb_ids: str = Form(...), topic: str = Form(""),
                    audience: str = Form(""), scene: str = Form(""),
                    slide_count: int = Form(10),
                    user: User = Depends(get_current_user),
                    svc: PPTService = Depends(get_ppt_service)):
    # 前端可能传逗号分隔或多个同名参数；这里按逗号拆
    ids = [i for i in kb_ids.replace(",", " ").split() if i]
    return svc.outline_from_kb(ids, topic, audience, scene, slide_count, user)


@router.post("/extract-text")
async def extract_text(file: UploadFile = File(...),
                     user: User = Depends(get_current_user),
                     svc: PPTService = Depends(get_ppt_service)):
    return await svc.extract_text(file)


@router.post("/outline")
def make_outline(body: OutlineIn,
               user: User = Depends(get_current_user),
               svc: PPTService = Depends(get_ppt_service)):
    return svc.make_outline(body, user)


@router.post("/outline-from-doc")
async def outline_from_doc(file: UploadFile = File(...), topic: str = Form(""),
                         audience: str = Form(""), scene: str = Form(""),
                         slide_count: int = Form(10),
                         user: User = Depends(get_current_user),
                         svc: PPTService = Depends(get_ppt_service)):
    return await svc.outline_from_doc(file, topic, audience, scene, slide_count, user)


@router.post("/generate")
def generate(body: GenerateIn,
           user: User = Depends(get_current_user),
           svc: PPTService = Depends(get_ppt_service)):
    return svc.generate(body, user)


@router.post("/documents/{doc_id}/export")
def export_document(doc_id: str, user: User = Depends(get_current_user),
                  svc: PPTService = Depends(get_ppt_service)):
    path, download_name = svc.export_document(doc_id, user)
    return FileResponse(str(path), media_type=_PPTX_MIME, filename=download_name)


@router.get("/documents/{doc_id}/download")
def download_document(doc_id: str, user: User = Depends(get_current_user),
                    svc: PPTService = Depends(get_ppt_service)):
    path, download_name = svc.download_document(doc_id, user)
    return FileResponse(str(path), media_type=_PPTX_MIME, filename=download_name)


@router.post("/blank")
def create_blank(body: BlankIn, user: User = Depends(get_current_user),
               svc: PPTService = Depends(get_ppt_service)):
    return svc.create_blank(body, user)


# ================= AI 编辑器操作 =================

@router.post("/ai/slide-action")
def ai_slide_action(body: SlideActionIn,
                    user: User = Depends(get_current_user),
                    svc: PPTService = Depends(get_ppt_service)):
    return svc.ai_slide_action(body)


@router.post("/ai/visual")
def ai_visual(body: VisualIn,
              user: User = Depends(get_current_user),
              svc: PPTService = Depends(get_ppt_service)):
    return svc.ai_visual(body)


@router.post("/ai/structure")
def ai_structure(body: StructureIn,
                 user: User = Depends(get_current_user),
                 svc: PPTService = Depends(get_ppt_service)):
    return svc.ai_structure(body)


# ================= 云端生成 =================

@router.get("/cloud-config")
def get_cloud_config(user: User = Depends(get_current_user),
                   svc: PPTService = Depends(get_ppt_service)):
    return svc.get_cloud_config()


@router.put("/cloud-config")
def put_cloud_config(body: CloudCfgIn,
                   user: User = Depends(get_current_user),
                   svc: PPTService = Depends(get_ppt_service)):
    return svc.put_cloud_config(body)


@router.post("/generate-cloud")
def generate_cloud(body: CloudGenIn,
                 user: User = Depends(get_current_user),
                 svc: PPTService = Depends(get_ppt_service)):
    return svc.generate_cloud(body, user)
