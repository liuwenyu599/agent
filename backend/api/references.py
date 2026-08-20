# -*- coding: utf-8 -*-
"""写作参考材料 API（新文件：backend/api/references.py）

两套能力严格分开（需求四、五）：

A. 模板固定参考材料  /references/template/...
   - 管理员为写作模板配置（如"外宣信息"配历史优秀推文）；
   - 仅供 AI 学习写作风格与结构范式，不作为事实来源，不进入知识库。

B. 当前任务佐证材料  /references/task/...
   - 用户为本次写作上传文件 / 粘贴文本 / 添加网页；
   - 仅归属用户本人可见，不进知识库、不参与 RAG 检索；
   - 用户主动 POST /references/task/{id}/promote 才"加入知识库"。

文件解析复用 AttachmentService._extract（与对话附件同一套解析逻辑），
网页抓取复用 web_fetcher，"加入知识库"复用 DocumentService。
"""
import uuid
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.database.postgres import get_db
from backend.database.models import User, WritingTemplate
from backend.database.models_reference import TemplateReference, TaskReference
from backend.auth.permission import get_current_user, require_admin_or_above
from backend.services.attachment_service import AttachmentService
from backend.services.web_fetcher import fetch_webpage, looks_like_url
from backend.config.settings import CHAT_UPLOAD_DIR, CHAT_UPLOAD_MAX_SIZE, CHAT_DOC_TYPES, CHAT_IMAGE_TYPES

router = APIRouter(prefix="/references", tags=["写作参考材料"])

_attachment_service = AttachmentService()

TEXT_MAX_CHARS = 100000  # 与对话附件一致


# ========== 公共工具 ==========

def _ref_to_dict(r) -> dict:
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


async def _parse_upload(file: UploadFile, user_id: str, subdir: str):
    """保存并解析上传文件，复用对话附件的解析逻辑。返回 (filename, file_path, size, text, status, note)"""
    filename = file.filename or "unnamed"
    suffix = "." + filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if suffix not in CHAT_DOC_TYPES + CHAT_IMAGE_TYPES:
        raise HTTPException(status_code=400,
                            detail=f"不支持的文件类型 {suffix or '(无扩展名)'}，支持：{'、'.join(CHAT_DOC_TYPES + CHAT_IMAGE_TYPES)}")
    data = await file.read()
    if len(data) > CHAT_UPLOAD_MAX_SIZE:
        raise HTTPException(status_code=400, detail="文件超过 50MB 限制")
    if not data:
        raise HTTPException(status_code=400, detail="文件为空")

    ref_id = uuid.uuid4().hex
    save_dir = Path(CHAT_UPLOAD_DIR).parent / "references" / subdir / user_id
    save_dir.mkdir(parents=True, exist_ok=True)
    file_path = save_dir / f"{ref_id}{suffix}"
    file_path.write_bytes(data)

    kind = "image" if suffix in CHAT_IMAGE_TYPES else "doc"
    text, status, note = _attachment_service._extract(file_path, suffix, kind)
    return filename, str(file_path), len(data), text, status, note


def _fetch_as_ref(url: str):
    """抓取网页并返回参考材料字段。失败时抛 400，带明确原因（不伪造正文）。"""
    fetched = fetch_webpage(url)
    if not fetched.get("ok"):
        raise HTTPException(status_code=400,
                            detail=f"网页获取失败：{fetched.get('error', '未知原因')}")
    title = fetched.get("title") or url
    return {
        "name": title[:500],
        "ref_type": "url",
        "source_url": url,
        "text_content": fetched["content"][:TEXT_MAX_CHARS],
        "parse_status": "ok",
        "parse_note": f"来源：{fetched.get('source_name') or '网页'}；刊发时间：{fetched.get('publish_time') or '未知'}",
        "_fetched": fetched,
    }


# ========== A. 模板固定参考材料（管理员维护） ==========

class TemplateTextRefRequest(BaseModel):
    name: str
    text: str

class TemplateUrlRefRequest(BaseModel):
    url: str
    name: Optional[str] = None


def _get_template_or_404(template_id: str, db: Session) -> WritingTemplate:
    tmpl = db.query(WritingTemplate).filter(WritingTemplate.id == template_id).first()
    if not tmpl:
        raise HTTPException(status_code=404, detail="Template not found")
    return tmpl


@router.get("/template/{template_id}")
async def list_template_refs(template_id: str, user: User = Depends(get_current_user),
                             db: Session = Depends(get_db)):
    """查看某模板的固定参考材料（所有登录用户可读，用于写作）"""
    _get_template_or_404(template_id, db)
    refs = db.query(TemplateReference).filter(
        TemplateReference.template_id == template_id,
        TemplateReference.is_active == True,
    ).order_by(TemplateReference.created_at.desc()).all()
    return {"template_id": template_id, "count": len(refs),
            "references": [_ref_to_dict(r) for r in refs]}


@router.post("/template/{template_id}/upload")
async def upload_template_ref(template_id: str, file: UploadFile = File(...),
                              admin: User = Depends(require_admin_or_above),
                              db: Session = Depends(get_db)):
    """为模板上传固定参考材料（仅管理员）"""
    _get_template_or_404(template_id, db)
    filename, file_path, size, text, status, note = await _parse_upload(file, admin.id, "template")
    ref = TemplateReference(
        template_id=template_id, name=filename, ref_type="file",
        file_path=file_path, file_size=size, text_content=text,
        char_count=len(text or ""), parse_status=status, parse_note=note,
        created_by=admin.id,
    )
    db.add(ref)
    db.commit()
    return {"reference": _ref_to_dict(ref)}


@router.post("/template/{template_id}/text")
async def add_template_text_ref(template_id: str, req: TemplateTextRefRequest,
                                admin: User = Depends(require_admin_or_above),
                                db: Session = Depends(get_db)):
    """为模板粘贴文本参考材料（仅管理员）"""
    _get_template_or_404(template_id, db)
    text = (req.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="文本为空")
    ref = TemplateReference(
        template_id=template_id, name=req.name or "粘贴的参考文本", ref_type="text",
        text_content=text[:TEXT_MAX_CHARS], char_count=len(text[:TEXT_MAX_CHARS]),
        parse_status="ok", created_by=admin.id,
    )
    db.add(ref)
    db.commit()
    return {"reference": _ref_to_dict(ref)}


@router.post("/template/{template_id}/url")
async def add_template_url_ref(template_id: str, req: TemplateUrlRefRequest,
                               admin: User = Depends(require_admin_or_above),
                               db: Session = Depends(get_db)):
    """为模板添加网页参考材料（仅管理员）。注意：只存为模板参考，不进知识库。"""
    _get_template_or_404(template_id, db)
    if not looks_like_url(req.url):
        raise HTTPException(status_code=400, detail="不是合法的 http(s) 链接")
    fields = _fetch_as_ref(req.url.strip())
    if req.name:
        fields["name"] = req.name
    fetched = fields.pop("_fetched")
    ref = TemplateReference(template_id=template_id, created_by=admin.id,
                            char_count=len(fields["text_content"]), **fields)
    db.add(ref)
    db.commit()
    return {"reference": _ref_to_dict(ref)}


@router.delete("/template/refs/{ref_id}")
async def delete_template_ref(ref_id: str, admin: User = Depends(require_admin_or_above),
                              db: Session = Depends(get_db)):
    ref = db.query(TemplateReference).filter(TemplateReference.id == ref_id).first()
    if not ref:
        raise HTTPException(status_code=404, detail="Reference not found")
    ref.is_active = False
    db.commit()
    return {"message": "已移除"}


# ========== B. 当前任务佐证材料（归属用户本人，不进知识库） ==========

class TaskTextRefRequest(BaseModel):
    text: str
    name: Optional[str] = None
    template_id: Optional[str] = None

class TaskUrlRefRequest(BaseModel):
    url: str
    name: Optional[str] = None
    template_id: Optional[str] = None

class PromoteRequest(BaseModel):
    kb_id: str


def _get_task_ref_checked(ref_id: str, user: User, db: Session) -> TaskReference:
    ref = db.query(TaskReference).filter(TaskReference.id == ref_id).first()
    if not ref:
        raise HTTPException(status_code=404, detail="Reference not found")
    if ref.user_id != user.id and user.role not in ["developer", "knowledge_admin", "admin"]:
        raise HTTPException(status_code=403, detail="No permission")
    return ref


@router.get("/task")
async def list_task_refs(template_id: Optional[str] = Query(None),
                         session_id: Optional[str] = Query(None),
                         user: User = Depends(get_current_user),
                         db: Session = Depends(get_db)):
    """列出我的当前任务佐证材料（严格按归属用户过滤，需求十三）"""
    q = db.query(TaskReference).filter(TaskReference.user_id == user.id)
    if template_id:
        q = q.filter(TaskReference.template_id == template_id)
    if session_id:
        q = q.filter(TaskReference.session_id == session_id)
    refs = q.order_by(TaskReference.created_at.desc()).all()
    return {"count": len(refs), "references": [_ref_to_dict(r) for r in refs]}


@router.post("/task/upload")
async def upload_task_ref(file: UploadFile = File(...),
                          template_id: Optional[str] = Query(None),
                          user: User = Depends(get_current_user),
                          db: Session = Depends(get_db)):
    """上传本次写作的佐证文件（不进知识库）"""
    if template_id:
        _get_template_or_404(template_id, db)
    filename, file_path, size, text, status, note = await _parse_upload(file, user.id, "task")
    ref = TaskReference(
        user_id=user.id, template_id=template_id,
        name=filename, ref_type="file", file_path=file_path, file_size=size,
        text_content=text, char_count=len(text or ""),
        parse_status=status, parse_note=note,
    )
    db.add(ref)
    db.commit()
    return {"reference": _ref_to_dict(ref)}


@router.post("/task/text")
async def add_task_text_ref(req: TaskTextRefRequest, user: User = Depends(get_current_user),
                            db: Session = Depends(get_db)):
    """粘贴文本作为本次写作材料（不进知识库）"""
    text = (req.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="文本为空")
    if req.template_id:
        _get_template_or_404(req.template_id, db)
    ref = TaskReference(
        user_id=user.id, template_id=req.template_id,
        name=req.name or "用户粘贴材料", ref_type="text",
        text_content=text[:TEXT_MAX_CHARS], char_count=len(text[:TEXT_MAX_CHARS]),
        parse_status="ok",
    )
    db.add(ref)
    db.commit()
    return {"reference": _ref_to_dict(ref)}


@router.post("/task/url")
async def add_task_url_ref(req: TaskUrlRefRequest, user: User = Depends(get_current_user),
                           db: Session = Depends(get_db)):
    """添加网页链接作为本次写作材料。默认不进知识库（需求七）。"""
    if not looks_like_url(req.url):
        raise HTTPException(status_code=400, detail="不是合法的 http(s) 链接")
    if req.template_id:
        _get_template_or_404(req.template_id, db)
    fields = _fetch_as_ref(req.url.strip())
    if req.name:
        fields["name"] = req.name
    fields.pop("_fetched")
    ref = TaskReference(user_id=user.id, template_id=req.template_id,
                        char_count=len(fields["text_content"]), **fields)
    db.add(ref)
    db.commit()
    return {"reference": _ref_to_dict(ref),
            "message": "已添加为本次写作参考材料（未进入知识库）"}


@router.delete("/task/{ref_id}")
async def delete_task_ref(ref_id: str, user: User = Depends(get_current_user),
                          db: Session = Depends(get_db)):
    import os
    ref = _get_task_ref_checked(ref_id, user, db)
    if ref.file_path and os.path.exists(ref.file_path):
        os.remove(ref.file_path)
    db.delete(ref)
    db.commit()
    return {"message": "已删除"}


@router.post("/task/{ref_id}/promote")
async def promote_task_ref(ref_id: str, req: PromoteRequest,
                           user: User = Depends(get_current_user),
                           db: Session = Depends(get_db)):
    """加入知识库：只有用户主动点击，才把当前任务材料转换为知识库文档（需求七、测试5）。"""
    from backend.api.knowledge import doc_service  # 复用 knowledge.py 中带 embedder 的实例
    from backend.database.models import KnowledgeBase

    ref = _get_task_ref_checked(ref_id, user, db)
    if ref.promoted_doc_id:
        return {"message": "该材料已在知识库中", "doc_id": ref.promoted_doc_id}

    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == req.kb_id).first()
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    if kb.kb_type == "personal" and kb.owner_id != user.id:
        raise HTTPException(status_code=403, detail="No permission")

    text = (ref.text_content or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="该材料没有可用文本内容，无法入库")

    if ref.ref_type == "url" and ref.source_url:
        # 网页材料：与"导入链接"完全同一条入库路径（含 source_url 查重）
        existing = doc_service.find_by_source_url(db, ref.source_url)
        if existing:
            ref.promoted_doc_id = existing.id
            db.commit()
            return {"message": "知识库中已存在相同链接，已关联", "doc_id": existing.id}
        result = doc_service.process_web_document(
            db=db, kb_id=kb.id, user_id=user.id, user_role=user.role,
            url=ref.source_url,
            fetched={"ok": True, "title": ref.name, "content": text,
                     "publish_time": "", "source_name": ""},
        )
    else:
        result = doc_service._persist_document(
            db=db, kb_id=kb.id, title=ref.name, text=text,
            user_id=user.id, user_role=user.role, doc_type=None,
            file_path=ref.file_path, file_size=ref.file_size or 0,
            doc_metadata={"source_type": ref.ref_type,
                          "original_filename": ref.name if ref.ref_type == "file" else None},
        )

    ref.promoted_doc_id = result["doc_id"]
    db.commit()
    return {"message": "已加入知识库", "doc_id": result["doc_id"], "status": result["status"]}


# ========== 写作时读取（供 chat 模块调用） ==========

def build_template_reference_context(template_id: str, db: Session,
                                     max_refs: int = 3, per_ref_chars: int = 1500) -> str:
    """模板固定参考材料 → 风格学习上下文（明确禁止照搬事实，需求九、测试6）"""
    refs = db.query(TemplateReference).filter(
        TemplateReference.template_id == template_id,
        TemplateReference.is_active == True,
        TemplateReference.text_content.isnot(None),
    ).order_by(TemplateReference.created_at.desc()).limit(max_refs).all()
    refs = [r for r in refs if (r.text_content or "").strip()]
    if not refs:
        return ""
    blocks = []
    for i, r in enumerate(refs):
        blocks.append(f"【风格范例{i + 1}：{r.name}】\n{r.text_content[:per_ref_chars]}")
    return (
        "以下是本模板配置的固定参考材料（本单位历史优秀稿件）。"
        "它们只用于学习：标题风格、行文方式、常用表达、文章长度、叙事结构；"
        "严禁把范例中的具体事实（单位名、人名、时间、地点、数据、事件经过）写进新文章，"
        "新文章的事实只能来自用户本次提供的材料和知识库检索结果：\n\n"
        + "\n\n".join(blocks)
    )


def build_task_reference_context(ref_ids: List[str], user_id: str, db: Session,
                                 per_ref_chars: int = 2000) -> str:
    """当前任务佐证材料 → 事实依据上下文（优先级最高，需求九）"""
    if not ref_ids:
        return ""
    refs = db.query(TaskReference).filter(
        TaskReference.id.in_(ref_ids),
        TaskReference.user_id == user_id,  # 严格归属校验
    ).all()
    refs = [r for r in refs if (r.text_content or "").strip()]
    if not refs:
        return ""
    blocks = []
    for i, r in enumerate(refs):
        label = {"file": "上传文件", "text": "粘贴文本", "url": "参考网页"}.get(r.ref_type, "材料")
        src = f"（{r.source_url}）" if r.source_url else ""
        blocks.append(f"【本次写作材料{i + 1}（{label}）：{r.name}】{src}\n{r.text_content[:per_ref_chars]}")
    return (
        "以下是用户为本次写作提供的事实材料。文章中的事实、数据、时间、地点、"
        "人物和事件经过以这些材料为准，材料中没有的信息不要虚构：\n\n"
        + "\n\n".join(blocks)
    )
