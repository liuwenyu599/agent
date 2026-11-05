"""PPT 助手路由。路径与响应结构与旧系统一致（/ppt/...）。"""
import asyncio
import os
import re
from pathlib import Path
from typing import List, Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse
from sqlalchemy.orm import Session

from app.application.ppt import agent_job
from app.application.ppt.dto import (
    BlankIn,
    CloudCfgIn,
    CloudGenIn,
    DocRenameIn,
    DraftIn,
    GenerateIn,
    ImageCaptionIn,
    ImportUrlIn,
    JobClarifyIn,
    JobSubmitIn,
    OutlineAdjustIn,
    OutlineIn,
    SlideActionIn,
    StructureIn,
    TemplateIn,
    VisualIn,
)
from app.application.ppt.service import PPTService
from app.application.shared.writing_assistant import WritingAssistant
from app.core.exceptions import AppError, NotFoundError
from app.domain.identity.entities import User
from app.infrastructure.ai import get_llm_gateway
from app.infrastructure.database import get_db
from app.interfaces.deps import get_current_user, require_admin_or_above

# PPTX（OOXML 演示文稿）MIME，供导出/下载响应使用
_PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"

# 预览图页码：纯数字，或数字 + 图片扩展名（PPTAgent 实测产出 jpg，老客户端按 png 请求）
_PREVIEW_PAGE_RE = re.compile(r"^(\d+)(\.[A-Za-z0-9]{1,5})?$")

# 允许的预览图扩展名 → MIME；未知后缀一律按 jpeg 返回（文件本体由白名单保证安全）
_IMAGE_MIMES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".webp": "image/webp", ".gif": "image/gif"}


def _ext_of(path_like: str) -> str:
    """取预览图真实扩展名（小写），取不到时退化为空串。

    预览列表的 url 必须带上**真实**扩展名：PPTAgent 实测产出的是 ``slide_NN.jpg``，
    若一律写成 ``.png``，部分图片解码器的 sniffing 会失败。
    """
    suffix = Path(str(path_like)).suffix.lower()
    return suffix if suffix in _IMAGE_MIMES else ""

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
                          category: str = Form("其他"), shared: bool = Form(False),
                          license_note: str = Form(""),
                          user: User = Depends(get_current_user),
                          svc: PPTService = Depends(get_ppt_service)):
    return await svc.upload_template(file, name, category, user,
                                     shared=shared, license_note=license_note)


@router.get("/templates/{template_id}/layout-preview/{layout_id}")
def layout_preview(template_id: str, layout_id: str,
                   user: User = Depends(get_current_user),
                   svc: PPTService = Depends(get_ppt_service)):
    p = svc.get_layout_preview(template_id, layout_id, user)
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

@router.get("/library/images")
def list_library_images(category: str = "", keyword: str = "",
                        user: User = Depends(get_current_user),
                        svc: PPTService = Depends(get_ppt_service)):
    return svc.list_library_images(category, keyword)


@router.post("/library/images")
async def upload_library_image(file: UploadFile = File(...), name: str = Form(""),
                               caption: str = Form(""), category: str = Form("其他"),
                               tags: str = Form(""), source: str = Form(""),
                               license_note: str = Form(""),
                               admin: User = Depends(require_admin_or_above),
                               svc: PPTService = Depends(get_ppt_service)):
    return await svc.upload_library_image(file, name, caption, category, tags,
                                          source, license_note)


@router.get("/library/images/{image_id}/file")
def library_image_file(image_id: str, user: User = Depends(get_current_user),
                       svc: PPTService = Depends(get_ppt_service)):
    path, mime = svc.library_image_file(image_id)
    return FileResponse(str(path), media_type=mime)


@router.get("/library/images/{image_id}/thumb")
def library_image_thumb(image_id: str, user: User = Depends(get_current_user),
                        svc: PPTService = Depends(get_ppt_service)):
    path, mime = svc.library_image_file(image_id, thumbnail=True)
    return FileResponse(str(path), media_type=mime)


@router.delete("/library/images/{image_id}")
def disable_library_image(image_id: str,
                          admin: User = Depends(require_admin_or_above),
                          svc: PPTService = Depends(get_ppt_service)):
    return svc.disable_library_image(image_id)


@router.patch("/library/images/{image_id}/caption")
def update_library_image_caption(image_id: str, body: ImageCaptionIn,
                                 admin: User = Depends(require_admin_or_above),
                                 svc: PPTService = Depends(get_ppt_service)):
    return svc.update_library_image_caption(image_id, body.caption)


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


@router.post("/materials/analyze")
def analyze_materials(files: List[UploadFile] = File(...),
                      user: User = Depends(get_current_user),
                      svc: PPTService = Depends(get_ppt_service)):
    """上传材料并逐份分析（doc/docx/pdf/txt/md/xlsx/xls/csv/pptx）。

    材料分析内部会同步调用模型 HTTP 客户端，因此这里故意使用同步路由，让
    FastAPI 把整个链路放进 worker thread；service 的 async 签名仅用于 UploadFile.read()。
    """
    return asyncio.run(svc.analyze_materials(files, user))


@router.put("/materials/{mid}")
def update_material(mid: str, name: str = Form(...), caption: str = Form(""),
                    user: User = Depends(get_current_user),
                    svc: PPTService = Depends(get_ppt_service)):
    return svc.update_material(mid, name, caption, user)


@router.patch("/materials/{mid}/caption")
def update_material_caption(mid: str, body: ImageCaptionIn,
                            user: User = Depends(get_current_user),
                            svc: PPTService = Depends(get_ppt_service)):
    return svc.update_material_caption(mid, body.caption, user)


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


@router.post("/documents/import")
async def import_document(file: UploadFile = File(...),
                          user: User = Depends(get_current_user),
                          svc: PPTService = Depends(get_ppt_service)):
    """上传已有 .pptx 继续修改：解析为可编辑大纲，进入同一编辑/AI 修改链路。"""
    return await svc.import_pptx(file, user)


@router.get("/documents/{doc_id}")
def get_document(doc_id: str, user: User = Depends(get_current_user),
               svc: PPTService = Depends(get_ppt_service)):
    return svc.get_document(doc_id, user)


@router.put("/documents/{doc_id}/draft")
def save_draft(doc_id: str, body: DraftIn,
               user: User = Depends(get_current_user),
               svc: PPTService = Depends(get_ppt_service)):
    return svc.save_draft(doc_id, body, user)


@router.post("/documents/{doc_id}/preview")
def preview_document(doc_id: str,
                     user: User = Depends(get_current_user),
                     svc: PPTService = Depends(get_ppt_service)):
    """把当前草稿渲染成逐页 PNG 预览（LibreOffice），供工作台中栏真实版式显示。"""
    return svc.preview_document(doc_id, user)


@router.post("/documents/{doc_id}/visual-review")
def visual_review_document(doc_id: str,
                           user: User = Depends(get_current_user),
                           svc: PPTService = Depends(get_ppt_service)):
    """按当前模板真实渲染并检查越界、重叠、字号和文字密度。"""
    return svc.visual_review_document(doc_id, user)


@router.post("/documents/{doc_id}/copy")
def copy_document(doc_id: str, user: User = Depends(get_current_user),
                svc: PPTService = Depends(get_ppt_service)):
    return svc.copy_document(doc_id, user)


@router.post("/documents/{doc_id}/favorite")
def toggle_doc_favorite(doc_id: str, user: User = Depends(get_current_user),
                  svc: PPTService = Depends(get_ppt_service)):
    return svc.toggle_doc_favorite(doc_id, user)


@router.patch("/documents/{doc_id}")
def rename_document(doc_id: str, body: DocRenameIn,
                    user: User = Depends(get_current_user),
                    svc: PPTService = Depends(get_ppt_service)):
    """重命名自己的 PPT 文档；他人的一律 404。"""
    return svc.rename_document(doc_id, user, body.title)


@router.delete("/documents/{doc_id}")
def delete_document(doc_id: str, user: User = Depends(get_current_user),
                  svc: PPTService = Depends(get_ppt_service)):
    return svc.delete_document(doc_id, user)


# ================= 逐页预览图 =================

@router.get("/preview/{doc_id}/{name}")
def preview_image(doc_id: str, name: str,
                  user: User = Depends(get_current_user),
                  svc: PPTService = Depends(get_ppt_service)):
    p = svc.preview_image(doc_id, name, user)
    return FileResponse(str(p), media_type="image/png")


# ================= 生成流程 =================

@router.get("/kbs")
def list_kbs(user: User = Depends(get_current_user),
             svc: PPTService = Depends(get_ppt_service)):
    return svc.list_kbs(user)


@router.post("/outline-from-kb")
def outline_from_kb(kb_ids: str = Form(...), topic: str = Form(""), audience: str = Form(""), scene: str = Form(""),
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


@router.post("/outline/precheck")
def precheck_outline(body: OutlineIn,
                     user: User = Depends(get_current_user),
                     svc: PPTService = Depends(get_ppt_service)):
    """生成前预检：信息不足时返回需要向用户确认的关键问题（每个问题附默认方案），
    防止 AI 在关键事实上瞎编；信息充足返回 sufficient=true 直接放行。"""
    return svc.precheck_outline(body, user)


@router.post("/outline/stream")
def outline_stream(body: OutlineIn,
                   user: User = Depends(get_current_user),
                   svc: PPTService = Depends(get_ppt_service)):
    """流式大纲（SSE）：先推 stage 事件（正在理解材料/正在梳理大纲/校验保存），
    最后推 done 携带权威大纲（含每页 sources 内容依据）。"""
    return StreamingResponse(svc.outline_stream(body, user),
                             media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


@router.post("/outline-from-doc")
def outline_from_doc(file: UploadFile = File(...), topic: str = Form(""),
                     audience: str = Form(""), scene: str = Form(""),
                     slide_count: int = Form(10),
                     user: User = Depends(get_current_user),
                     svc: PPTService = Depends(get_ppt_service)):
    """上传文档并生成大纲。

    下游 ``_do_outline`` 使用同步模型 HTTP 客户端；保持同步路由可由 FastAPI
    自动在线程池执行，避免长模型请求占住主事件循环。
    """
    return asyncio.run(
        svc.outline_from_doc(file, topic, audience, scene, slide_count, user)
    )


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


@router.get("/documents/{doc_id}/drawio")
def download_drawio_source(doc_id: str, user: User = Depends(get_current_user),
                           svc: PPTService = Depends(get_ppt_service)):
    source, name = svc.download_drawio_source(doc_id, user)
    return Response(source, media_type="application/vnd.jgraph.mxfile",
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name, safe='')}"})


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
    return svc.ai_visual(body, user)


@router.post("/ai/structure")
def ai_structure(body: StructureIn,
                 user: User = Depends(get_current_user),
                 svc: PPTService = Depends(get_ppt_service)):
    return svc.ai_structure(body)


@router.post("/ai/outline-adjust")
def ai_outline_adjust(body: OutlineAdjustIn,
                      user: User = Depends(get_current_user),
                      svc: PPTService = Depends(get_ppt_service)):
    """大纲整体调整：一句自然语言指令（如「把目录页改成正文页」）改写整份大纲。"""
    return svc.ai_outline_adjust(body)


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


# ================= 异步生成任务（PPTAgent） =================
# 说明：本 router 自身前缀是 /ppt，main.py 挂载时会再套一层 /api/v1，
# 因此实际可达路径是 /api/v1/ppt/jobs/...（与桌面端 apiBase + "/ppt" 一致）。

@router.post("/jobs")
def submit_ppt_job(body: JobSubmitIn,
                   user: User = Depends(get_current_user),
                   svc: PPTService = Depends(get_ppt_service)):
    """提交异步生成任务，**立即返回**（后台线程接管，不阻塞十几分钟）。"""
    doc = svc.documents.get_for_user(body.doc_id, user.id)
    if not doc:
        raise NotFoundError("文档不存在")
    return agent_job.submit_job(doc.id, user.id, body.message or "")


@router.get("/jobs/{job_id}/status")
def ppt_job_status(job_id: str,
                   user: User = Depends(get_current_user),
                   svc: PPTService = Depends(get_ppt_service)):
    """轮询任务状态：状态 / 阶段 / 页数 / 耗时 / 预计剩余 / 追问。"""
    doc = svc.documents.get_for_user(job_id, user.id)
    if not doc:
        raise NotFoundError("任务不存在")
    return agent_job.job_status(doc)


@router.get("/jobs/{job_id}/preview")
def ppt_job_preview(job_id: str,
                    user: User = Depends(get_current_user),
                    svc: PPTService = Depends(get_ppt_service)):
    """已生成页的预览图列表；目录结构与预期不符时返回空列表（降级，不报错）。

    ``url`` 里的扩展名取自**真实文件**（PPTAgent 实测产出 ``slide_NN.jpg``），
    因此可能是 ``.jpg`` 而不是 ``.png``——取值时请以返回的 url 为准。
    """
    doc = svc.documents.get_for_user(job_id, user.id)
    if not doc:
        raise NotFoundError("任务不存在")
    files = agent_job.list_previews(job_id)
    pages = [{"index": i, "url": f"/api/v1/ppt/jobs/{job_id}/preview/{i}{_ext_of(f)}"}
             for i, f in enumerate(files)]
    return {"job_id": job_id, "count": len(pages), "pages": pages}


@router.get("/jobs/{job_id}/preview/{page}")
def ppt_job_preview_image(job_id: str, page: str,
                          user: User = Depends(get_current_user),
                          svc: PPTService = Depends(get_ppt_service)):
    """单页预览图。路径经白名单校验（必须落在工作区内），防目录穿越。

    ``page`` 接受 ``0``、``0.png``、``0.jpg`` 三种形式：
    PPTAgent 实测产出 jpg，但老客户端按 ``0.png`` 请求，两者都要能命中。
    """
    doc = svc.documents.get_for_user(job_id, user.id)
    if not doc:
        raise NotFoundError("任务不存在")
    m = _PREVIEW_PAGE_RE.match(page or "")
    if not m:
        raise AppError(400, "页码必须是数字（可带 .png/.jpg 扩展名）")
    suffix = (m.group(2) or "").lower()
    if suffix and suffix not in _IMAGE_MIMES:
        raise AppError(400, "预览图扩展名不支持")
    path = agent_job.resolve_preview(job_id, int(m.group(1)))
    if path is None:
        raise NotFoundError("预览图不存在")
    media = _IMAGE_MIMES.get(path.suffix.lower(), "image/jpeg")
    return FileResponse(str(path), media_type=media)


@router.post("/jobs/{job_id}/cancel")
def ppt_job_cancel(job_id: str,
                   user: User = Depends(get_current_user),
                   svc: PPTService = Depends(get_ppt_service)):
    """请求取消：停止等待（PPTAgent 侧已启动的生成无法远程终止）。"""
    doc = svc.documents.get_for_user(job_id, user.id)
    if not doc:
        raise NotFoundError("任务不存在")
    return agent_job.cancel_job(job_id)


@router.post("/jobs/{job_id}/clarify")
def ppt_job_clarify(job_id: str, body: JobClarifyIn,
                    user: User = Depends(get_current_user),
                    svc: PPTService = Depends(get_ppt_service)):
    """回答 PPTAgent 的追问（R1），带上下文续跑同一任务。"""
    doc = svc.documents.get_for_user(job_id, user.id)
    if not doc:
        raise NotFoundError("任务不存在")
    return agent_job.answer_clarification(job_id, user.id, body.answer or "")


@router.get("/jobs/{job_id}/export")
def ppt_job_export(job_id: str,
                   user: User = Depends(get_current_user),
                   svc: PPTService = Depends(get_ppt_service)):
    """下载任务产物；任务未完成时 404（绝不返回半成品或空文件）。"""
    doc = svc.documents.get_for_user(job_id, user.id)
    if not doc:
        raise NotFoundError("任务不存在")
    if not doc.file_path or not os.path.exists(doc.file_path):
        raise NotFoundError("任务尚未完成，暂无可下载的文件")
    return FileResponse(str(doc.file_path), media_type=_PPTX_MIME,
                        filename=f"{doc.title or 'PPT'}.pptx")
