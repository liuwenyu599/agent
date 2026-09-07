"""数据资产中心 + 模型训练 API。

路由前缀 /training，挂在 /api/v1 下。
面向工作人员的概念是「数据资产中心」，不出现 JSON/JSONL/LoRA 等技术细节；
高级训练参数对普通用户隐藏（见 desktop 端「高级配置」折叠区）。
"""
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, Query, UploadFile, File
from sqlalchemy.orm import Session

from app.application.training.dto import (
    DatasetCreateRequest,
    DatasetVersionCreateRequest,
    ImportDirRequest,
    JobCreateRequest,
    SampleEditRequest,
    SampleFromChatRequest,
)
from app.application.training.service import TrainingService
from app.core.exceptions import AppError
from app.domain.identity.entities import User
from app.infrastructure.database import get_db
from app.interfaces.deps import get_current_user, require_admin_or_above

router = APIRouter(prefix="/training", tags=["数据资产中心"])


def get_service(db: Session = Depends(get_db)) -> TrainingService:
    return TrainingService(db)


# ==================== 总览 ====================

@router.get("/overview")
def overview(user: User = Depends(get_current_user),
             svc: TrainingService = Depends(get_service)):
    return svc.overview()


# ==================== 数据资产 ====================

@router.get("/assets")
def list_assets(source_type: str = "", keyword: str = "",
                page: int = 1, page_size: int = 20,
                user: User = Depends(get_current_user),
                svc: TrainingService = Depends(get_service)):
    return svc.list_assets(source_type, keyword, page, page_size)


@router.get("/assets/{asset_id}")
def get_asset(asset_id: str, user: User = Depends(get_current_user),
              svc: TrainingService = Depends(get_service)):
    return svc.get_asset(asset_id)


@router.post("/assets/import-dir")
def import_dir(req: ImportDirRequest,
               user: User = Depends(require_admin_or_above),
               svc: TrainingService = Depends(get_service)):
    """批量导入历史成熟公文：指定外部目录（不复制原始文件）。"""
    return svc.import_directory(req.path, req.source_type, req.recursive, user.id)


@router.post("/assets/import-file")
async def import_file(file: UploadFile = File(...),
                      user: User = Depends(require_admin_or_above),
                      svc: TrainingService = Depends(get_service)):
    """上传导入：支持 .zip（批量公文）/ .xlsx/.csv / .json/.jsonl。"""
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in (".zip", ".xlsx", ".csv", ".json", ".jsonl",
                      ".docx", ".pdf", ".txt", ".md"):
        raise AppError(400, f"不支持的文件类型: {suffix}")
    tmp = Path(tempfile.mkdtemp(prefix="training_import_")) / (file.filename or "upload")
    tmp.write_bytes(await file.read())
    if suffix == ".zip":
        return svc.import_zip(tmp, file.filename or "", user.id)
    if suffix in (".xlsx", ".csv"):
        return svc.import_excel(tmp, user.id)
    if suffix in (".json", ".jsonl"):
        return svc.import_jsonl(tmp, user.id)
    # 单个公文文件 → 直接登记资产
    from app.application.training.docparse import parse_document
    from app.infrastructure.database.models.training import DataAssetModel
    info = parse_document(tmp)
    if info["char_count"] < 20:
        raise AppError(400, "文件正文为空或过短")
    svc.db.add(DataAssetModel(**info, source_type="batch", created_by=user.id))
    svc.db.commit()
    return {"created": 1, "skipped": 0}


@router.post("/assets/{asset_id}/generate-sample")
def generate_sample(asset_id: str, user: User = Depends(get_current_user),
                    svc: TrainingService = Depends(get_service)):
    """AI 辅助构造候选样本（调用本地模型，结果为 candidate，需人工审核）。"""
    return svc.generate_sample_from_asset(asset_id, user.id)


@router.post("/assets/{asset_id}/status")
def set_asset_status(asset_id: str, status: str = Query(...),
                     user: User = Depends(require_admin_or_above),
                     svc: TrainingService = Depends(get_service)):
    svc.set_asset_status(asset_id, status)
    return {"ok": True}


@router.delete("/assets/{asset_id}")
def delete_asset(asset_id: str, user: User = Depends(require_admin_or_above),
                 svc: TrainingService = Depends(get_service)):
    svc.delete_asset(asset_id)
    return {"ok": True}


# ==================== 训练样本审核 ====================

@router.get("/samples")
def list_samples(status: str = "", source: str = "",
                 page: int = 1, page_size: int = 20,
                 user: User = Depends(get_current_user),
                 svc: TrainingService = Depends(get_service)):
    return svc.list_samples(status, source, page, page_size)


@router.post("/samples/from-chat")
def add_sample_from_chat(req: SampleFromChatRequest,
                         user: User = Depends(get_current_user),
                         svc: TrainingService = Depends(get_service)):
    """Chat「加入训练集」入口。只登记为候选数据，不触发训练。"""
    return svc.add_sample_from_chat(req, user.id)


@router.post("/samples/{sample_id}/review")
def review_sample(sample_id: str, action: str = Query(...),  # approve/disable/candidate
                  user: User = Depends(get_current_user),
                  svc: TrainingService = Depends(get_service)):
    svc.review_sample(sample_id, action, user.id)
    return {"ok": True}


@router.put("/samples/{sample_id}")
def edit_sample(sample_id: str, req: SampleEditRequest,
                user: User = Depends(get_current_user),
                svc: TrainingService = Depends(get_service)):
    return svc.edit_sample(sample_id, req.model_dump(exclude_none=True))


@router.delete("/samples/{sample_id}")
def delete_sample(sample_id: str, user: User = Depends(get_current_user),
                  svc: TrainingService = Depends(get_service)):
    svc.delete_sample(sample_id)
    return {"ok": True}


# ==================== 数据集 / 版本 ====================

@router.get("/datasets")
def list_datasets(user: User = Depends(get_current_user),
                  svc: TrainingService = Depends(get_service)):
    return svc.list_datasets()


@router.post("/datasets")
def create_dataset(req: DatasetCreateRequest,
                   user: User = Depends(get_current_user),
                   svc: TrainingService = Depends(get_service)):
    return svc.create_dataset(req.name, req.description, user.id)


@router.post("/datasets/{dataset_id}/versions")
def create_version(dataset_id: str, req: DatasetVersionCreateRequest,
                   user: User = Depends(get_current_user),
                   svc: TrainingService = Depends(get_service)):
    """生成数据集版本：自动质量检查，只有通过检查的 approved 数据进入版本。"""
    return svc.create_dataset_version(dataset_id, req.version, req.val_ratio, user.id)


# ==================== 训练任务 ====================

@router.get("/jobs")
def list_jobs(user: User = Depends(get_current_user),
              svc: TrainingService = Depends(get_service)):
    return svc.list_jobs()


@router.post("/jobs")
def create_job(req: JobCreateRequest,
               user: User = Depends(require_admin_or_above),
               svc: TrainingService = Depends(get_service)):
    """创建训练任务：独立进程运行，不阻塞服务。"""
    return svc.create_job(req, user.id)


@router.get("/jobs/{job_id}")
def get_job(job_id: str, tail: int = 200,
            user: User = Depends(get_current_user),
            svc: TrainingService = Depends(get_service)):
    """任务详情 + 最近日志。"""
    return svc.get_job_log(job_id, tail)


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str, user: User = Depends(require_admin_or_above),
               svc: TrainingService = Depends(get_service)):
    svc.cancel_job(job_id)
    return {"ok": True}


# ==================== 模型版本 ====================

@router.get("/models")
def list_models(user: User = Depends(get_current_user),
                svc: TrainingService = Depends(get_service)):
    return svc.list_model_versions()


@router.post("/models/{model_id}/publish")
def publish_model(model_id: str, user: User = Depends(require_admin_or_above),
                  svc: TrainingService = Depends(get_service)):
    """发布模型版本（本期仅状态管理，不替换 Chat 模型）。"""
    svc.set_model_version_status(model_id, "publish")
    return {"ok": True}


@router.post("/models/{model_id}/archive")
def archive_model(model_id: str, user: User = Depends(require_admin_or_above),
                  svc: TrainingService = Depends(get_service)):
    svc.set_model_version_status(model_id, "archive")
    return {"ok": True}
