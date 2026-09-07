"""数据资产中心 + 模型训练 —— 应用服务。

链路：真实业务数据 + 历史成熟公文 + 批量导入
      → 数据资产 → 候选样本(candidate) → 人工审核(approved)
      → Dataset Version（质量检查 + train/val jsonl）
      → 独立进程 LoRA/QLoRA 训练 → Model Version(Adapter)

隐私约束：全部本地完成，不上传任何文档 / 训练数据 / 模型到第三方；
AI 辅助构造只调用本地模型网关（get_llm_gateway）。
"""
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import AppError
from app.core.logging import get_logger
from app.infrastructure.ai import get_llm_gateway
from app.infrastructure.database.models.training import (
    DataAssetModel,
    DatasetModel,
    DatasetVersionModel,
    ModelVersionModel,
    TrainingJobModel,
    TrainingSampleModel,
)

from .docparse import parse_document, scan_directory

logger = get_logger(__name__)

# 训练模块目录：默认 仓库根/training，可用 TRAINING_DIR 覆盖
TRAINING_DIR = Path(os.getenv("TRAINING_DIR", str(settings.DATA_DIR.parent / "training"))).resolve()

MIN_TEXT_LEN = 20        # 低于此长度视为空文本/异常
MAX_TEXT_LEN = 32000     # 超过此长度视为异常长度


def _pid_alive(pid: Optional[int]) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


class TrainingService:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # 数据资产
    # ------------------------------------------------------------------
    def list_assets(self, source_type: str = "", keyword: str = "",
                    page: int = 1, page_size: int = 20) -> Dict[str, Any]:
        q = self.db.query(DataAssetModel)
        if source_type:
            q = q.filter(DataAssetModel.source_type == source_type)
        if keyword:
            like = f"%{keyword}%"
            q = q.filter(DataAssetModel.title.like(like) | DataAssetModel.name.like(like))
        total = q.count()
        items = (q.order_by(DataAssetModel.created_at.desc())
                 .offset((page - 1) * page_size).limit(page_size).all())
        return {"total": total, "items": [self._asset_dict(a, with_content=False) for a in items]}

    def get_asset(self, asset_id: str) -> Dict[str, Any]:
        return self._asset_dict(self._get_asset(asset_id), with_content=True)

    def import_directory(self, path: str, source_type: str, recursive: bool,
                         user_id: str) -> Dict[str, int]:
        """批量导入外部目录：扫描 → 提取正文 → 识别标题/文种 → 登记资产。"""
        files = scan_directory(path, recursive)
        if not files:
            raise AppError(400, f"目录中没有可导入的文件（支持 docx/pdf/txt/md）: {path}")
        created = skipped = 0
        for f in files:
            fp = str(f)
            exists = (self.db.query(DataAssetModel)
                      .filter(DataAssetModel.file_path == fp).first())
            if exists:
                skipped += 1
                continue
            info = parse_document(f)
            if info["char_count"] < MIN_TEXT_LEN:
                skipped += 1
                continue
            self.db.add(DataAssetModel(
                **info, source_type=source_type, created_by=user_id,
                extra={"source_dir": path},
            ))
            created += 1
        self.db.commit()
        logger.info("[数据资产] 目录导入 %s: 新增 %d, 跳过 %d", path, created, skipped)
        return {"created": created, "skipped": skipped}

    def import_zip(self, file_path: Path, filename: str, user_id: str) -> Dict[str, int]:
        """导入 ZIP（documents/001.docx ... 可选 dataset.xlsx 元数据）。
        ZIP 解压到 training/data/raw/<批次>/，原始文件保存在该外部目录。"""
        batch_dir = TRAINING_DIR / "data" / "raw" / datetime.now().strftime("batch_%Y%m%d_%H%M%S")
        batch_dir.mkdir(parents=True, exist_ok=True)
        try:
            with zipfile.ZipFile(file_path) as zf:
                zf.extractall(batch_dir)
        except zipfile.BadZipFile:
            raise AppError(400, "ZIP 文件损坏或格式不正确")
        result = self.import_directory(str(batch_dir), "batch", True, user_id)
        # ZIP 内若带 dataset.xlsx，一并按 Excel 导入样本
        for xlsx in batch_dir.glob("**/*.xlsx"):
            result["samples"] = self.import_excel(xlsx, user_id).get("created", 0)
        return result

    def import_excel(self, file_path: Path, user_id: str) -> Dict[str, int]:
        """导入 Excel/CSV：只需少量字段。列名支持 title/content/instruction/input/output。
        有 content 列 → 登记数据资产；有 output 列 → 直接形成候选样本。"""
        import pandas as pd
        try:
            if str(file_path).lower().endswith(".csv"):
                df = pd.read_csv(file_path)
            else:
                df = pd.read_excel(file_path)
        except Exception as e:
            raise AppError(400, f"表格读取失败: {e}")
        df.columns = [str(c).strip().lower() for c in df.columns]
        created = 0
        for _, row in df.iterrows():
            r = {k: ("" if pd.isna(v) else str(v).strip()) for k, v in row.items()}
            content = r.get("content", "") or r.get("output", "")
            if len(content) < MIN_TEXT_LEN:
                continue
            asset = DataAssetModel(
                name=r.get("title", "") or f"表格导入-{created + 1}",
                source_type="excel",
                file_path=str(file_path),
                file_type=Path(file_path).suffix.lstrip("."),
                title=r.get("title", ""),
                doc_type=r.get("doc_type", ""),
                content=content,
                char_count=len(content),
                extra={k: v for k, v in r.items()
                       if k not in ("title", "content", "instruction", "input", "output", "doc_type") and v},
                created_by=user_id,
            )
            self.db.add(asset)
            self.db.flush()
            # 表格自带 instruction/output 时直接形成候选样本
            if r.get("output"):
                self.db.add(TrainingSampleModel(
                    instruction=r.get("instruction", "") or f"请起草：{asset.title}",
                    input=r.get("input", ""),
                    output=r["output"],
                    source="import",
                    asset_id=asset.id,
                    biz_type=asset.doc_type,
                    created_by=user_id,
                ))
                asset.sample_generated = 1
            created += 1
        self.db.commit()
        return {"created": created}

    def import_jsonl(self, file_path: Path, user_id: str) -> Dict[str, int]:
        """导入 JSON/JSONL：每条需含 output（instruction/input 可选）。"""
        created = 0
        for obj in self._read_json_records(file_path):
            output = str(obj.get("output", "")).strip()
            if len(output) < MIN_TEXT_LEN:
                continue
            self.db.add(TrainingSampleModel(
                instruction=str(obj.get("instruction", "")).strip(),
                input=str(obj.get("input", "")).strip(),
                output=output,
                source="import",
                biz_type=str(obj.get("biz_type", "")),
                created_by=user_id,
            ))
            created += 1
        self.db.commit()
        return {"created": created}

    @staticmethod
    def _read_json_records(path: Path) -> List[dict]:
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            return []
        if text.startswith("["):
            return [o for o in json.loads(text) if isinstance(o, dict)]
        return [json.loads(line) for line in text.splitlines() if line.strip()]

    def set_asset_status(self, asset_id: str, status: str) -> None:
        asset = self._get_asset(asset_id)
        asset.status = status
        self.db.commit()

    def delete_asset(self, asset_id: str) -> None:
        asset = self._get_asset(asset_id)
        self.db.delete(asset)
        self.db.commit()

    # ------------------------------------------------------------------
    # AI 辅助构造候选样本（本地模型，结果必须人工审核）
    # ------------------------------------------------------------------
    def generate_sample_from_asset(self, asset_id: str, user_id: str) -> Dict[str, Any]:
        asset = self._get_asset(asset_id)
        if not asset.content:
            raise AppError(400, "该资产没有可用正文")
        gateway = get_llm_gateway()
        prompt = (
            "你是司法公文写作助手。请根据下面这篇成熟公文，构造一条写作训练数据。\n"
            "要求：\n"
            "1. 推测工作人员最可能提出的原始写作需求（一句话，口语化但任务明确）；\n"
            "2. 给出完成该任务所需的背景信息要点（时间、单位、事项等，若原文没有则不编造）；\n"
            "3. 严格按以下格式输出三行：\n"
            "任务：...\n背景：...\n（正文不需要输出）\n\n"
            f"公文标题：{asset.title}\n\n公文正文（节选）：\n{asset.content[:2000]}"
        )
        try:
            reply = gateway.complete(
                [{"role": "user", "content": prompt}], temperature=0.3, max_tokens=800)
        except Exception as e:
            raise AppError(500, f"本地模型调用失败: {e}")
        instruction = self._parse_line(reply, "任务") or f"请起草：{asset.title}"
        background = self._parse_line(reply, "背景")
        sample = TrainingSampleModel(
            instruction=instruction,
            input=background,
            output=asset.content,
            source="ai_generated",
            asset_id=asset.id,
            biz_type=asset.doc_type,
            created_by=user_id,
        )
        self.db.add(sample)
        asset.sample_generated = 1
        self.db.commit()
        self.db.refresh(sample)
        return self._sample_dict(sample)

    @staticmethod
    def _parse_line(text: str, key: str) -> str:
        for line in text.splitlines():
            line = line.strip()
            if line.startswith(key + "：") or line.startswith(key + ":"):
                return line.split("：", 1)[-1].split(":", 1)[-1].strip()
        return ""

    # ------------------------------------------------------------------
    # 训练样本审核
    # ------------------------------------------------------------------
    def list_samples(self, status: str = "", source: str = "",
                     page: int = 1, page_size: int = 20) -> Dict[str, Any]:
        q = self.db.query(TrainingSampleModel)
        if status:
            q = q.filter(TrainingSampleModel.status == status)
        if source:
            q = q.filter(TrainingSampleModel.source == source)
        total = q.count()
        items = (q.order_by(TrainingSampleModel.created_at.desc())
                 .offset((page - 1) * page_size).limit(page_size).all())
        counts = dict(
            self.db.query(TrainingSampleModel.status, func.count())
            .group_by(TrainingSampleModel.status).all()
        )
        return {"total": total, "counts": counts,
                "items": [self._sample_dict(s) for s in items]}

    def review_sample(self, sample_id: str, action: str, user_id: str) -> None:
        """action: approve / disable。approved 才能进入数据集版本。"""
        sample = self._get_sample(sample_id)
        if action == "approve":
            sample.status = "approved"
        elif action == "disable":
            sample.status = "disabled"
        elif action == "candidate":
            sample.status = "candidate"
        else:
            raise AppError(400, f"未知操作: {action}")
        sample.reviewed_by = user_id
        sample.reviewed_at = datetime.utcnow()
        self.db.commit()

    def edit_sample(self, sample_id: str, fields: Dict[str, Any]) -> Dict[str, Any]:
        sample = self._get_sample(sample_id)
        for k in ("instruction", "input", "output", "draft", "biz_type"):
            v = fields.get(k)
            if v is not None:
                setattr(sample, k, v)
        self.db.commit()
        self.db.refresh(sample)
        return self._sample_dict(sample)

    def delete_sample(self, sample_id: str) -> None:
        self.db.delete(self._get_sample(sample_id))
        self.db.commit()

    def add_sample_from_chat(self, req, user_id: str) -> Dict[str, Any]:
        """Chat「加入训练集」：真实需求 + AI 初稿 + 人工最终稿 → candidate。
        不立即训练，需人工审核通过后才进入数据集。"""
        sample = TrainingSampleModel(
            instruction=req.instruction,
            input="",
            draft=req.draft,
            output=req.output,
            source="chat",
            session_id=req.session_id,
            biz_type=req.biz_type,
            created_by=user_id,
        )
        self.db.add(sample)
        # 同步登记业务过程数据资产
        self.db.add(DataAssetModel(
            name=req.instruction[:60] or "业务过程数据",
            source_type="business",
            file_type="chat",
            title=req.instruction[:120],
            doc_type=req.biz_type,
            content=req.output,
            char_count=len(req.output),
            extra={"session_id": req.session_id, "has_draft": bool(req.draft)},
            sample_generated=1,
            created_by=user_id,
        ))
        self.db.commit()
        self.db.refresh(sample)
        return self._sample_dict(sample)

    # ------------------------------------------------------------------
    # 数据集 / 数据集版本
    # ------------------------------------------------------------------
    def list_datasets(self) -> List[Dict[str, Any]]:
        datasets = self.db.query(DatasetModel).order_by(DatasetModel.created_at.desc()).all()
        result = []
        for d in datasets:
            versions = (self.db.query(DatasetVersionModel)
                        .filter(DatasetVersionModel.dataset_id == d.id)
                        .order_by(DatasetVersionModel.created_at.desc()).all())
            result.append({
                "id": d.id, "name": d.name, "description": d.description,
                "created_at": d.created_at.isoformat() if d.created_at else "",
                "versions": [self._version_dict(v) for v in versions],
            })
        return result

    def create_dataset(self, name: str, description: str, user_id: str) -> Dict[str, Any]:
        d = DatasetModel(name=name, description=description, created_by=user_id)
        self.db.add(d)
        self.db.commit()
        self.db.refresh(d)
        return {"id": d.id, "name": d.name, "description": d.description}

    def create_dataset_version(self, dataset_id: str, version: str,
                               val_ratio: float, user_id: str) -> Dict[str, Any]:
        """生成 Dataset Version：取全部 approved 样本 → 质量检查 → 导出 train/val jsonl。"""
        dataset = self.db.get(DatasetModel, dataset_id)
        if not dataset:
            raise AppError(404, "数据集不存在")
        dup = (self.db.query(DatasetVersionModel)
               .filter(DatasetVersionModel.dataset_id == dataset_id,
                       DatasetVersionModel.version == version).first())
        if dup:
            raise AppError(400, f"版本 {version} 已存在")

        samples = (self.db.query(TrainingSampleModel)
                   .filter(TrainingSampleModel.status == "approved").all())
        if not samples:
            raise AppError(400, "没有已审核（approved）的样本，无法生成数据集版本")

        check = self._quality_check(samples)
        valid_ids: List[str] = check["valid_ids"]
        if not valid_ids:
            raise AppError(400, "质量检查后没有有效样本")

        # 统计
        stats = self._dataset_stats(samples)
        stats["total"] = len(samples)
        stats["valid"] = len(valid_ids)
        counts = dict(
            self.db.query(TrainingSampleModel.status, func.count())
            .group_by(TrainingSampleModel.status).all())
        stats["candidate"] = counts.get("candidate", 0)
        stats["disabled"] = counts.get("disabled", 0)

        # 导出 train/val jsonl（JSONL 仅为训练框架内部格式）
        out_dir = TRAINING_DIR / "datasets" / f"{dataset.name}_{version}"
        out_dir.mkdir(parents=True, exist_ok=True)
        train_path, val_path = self._export_jsonl(
            [s for s in samples if s.id in set(valid_ids)], out_dir, val_ratio)

        dv = DatasetVersionModel(
            dataset_id=dataset_id, version=version, status="ready",
            stats=stats, check_report=check["report"], sample_ids=valid_ids,
            train_jsonl=str(train_path), val_jsonl=str(val_path),
            created_by=user_id,
        )
        self.db.add(dv)
        self.db.commit()
        self.db.refresh(dv)
        logger.info("[数据集] %s %s: 有效 %d/%d", dataset.name, version,
                    len(valid_ids), len(samples))
        return self._version_dict(dv, detail=True)

    # ------------------------------------------------------------------
    # 训练任务（独立进程，不阻塞 FastAPI）
    # ------------------------------------------------------------------
    def list_jobs(self) -> List[Dict[str, Any]]:
        jobs = (self.db.query(TrainingJobModel)
                .order_by(TrainingJobModel.created_at.desc()).all())
        changed = False
        for j in jobs:
            if j.status in ("pending", "running"):
                changed |= self._refresh_job(j)
        if changed:
            self.db.commit()
        return [self._job_dict(j) for j in jobs]

    def create_job(self, req, user_id: str) -> Dict[str, Any]:
        dv = self.db.get(DatasetVersionModel, req.dataset_version_id)
        if not dv:
            raise AppError(404, "数据集版本不存在")
        if not Path(dv.train_jsonl).is_file():
            raise AppError(400, "数据集版本的训练文件缺失，请重新生成版本")
        if req.method not in ("lora", "qlora"):
            raise AppError(400, "训练方式仅支持 lora / qlora")
        if not Path(req.base_model).exists():
            raise AppError(400, f"基础模型路径不存在: {req.base_model}")

        resume_from = ""
        parent_mv = None
        if req.parent_model_version_id:
            parent_mv = self.db.get(ModelVersionModel, req.parent_model_version_id)
            if not parent_mv or not parent_mv.adapter_path:
                raise AppError(400, "父版本没有可用的 Adapter")
            resume_from = parent_mv.adapter_path

        output_dir = TRAINING_DIR / "outputs" / f"{req.name}_{datetime.now():%Y%m%d_%H%M%S}"
        log_path = TRAINING_DIR / "logs" / f"job_{datetime.now():%Y%m%d_%H%M%S}_{req.name}.log"
        output_dir.mkdir(parents=True, exist_ok=True)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        job = TrainingJobModel(
            name=req.name, dataset_version_id=dv.id, base_model=req.base_model,
            method=req.method,
            params={
                "epochs": req.epochs, "batch_size": req.batch_size,
                "gradient_accumulation": req.gradient_accumulation,
                "learning_rate": req.learning_rate, "max_length": req.max_length,
                "lora_r": req.lora_r, "lora_alpha": req.lora_alpha,
                "lora_dropout": req.lora_dropout,
            },
            status="pending", log_path=str(log_path), output_dir=str(output_dir),
            resume_from=resume_from, created_by=user_id, started_at=datetime.utcnow(),
        )
        self.db.add(job)
        self.db.flush()

        # 预创建模型版本（Training 状态）
        mv = ModelVersionModel(
            name=req.model_version_name or f"Judicial-Model-{req.name}",
            base_model=req.base_model, job_id=job.id,
            parent_id=parent_mv.id if parent_mv else None,
            status="Training",
        )
        self.db.add(mv)
        self.db.flush()
        job.model_version_id = mv.id

        # 启动独立训练进程
        cmd = self._build_train_cmd(job, dv)
        try:
            log_f = open(log_path, "w", encoding="utf-8")
            proc = subprocess.Popen(
                cmd, cwd=str(TRAINING_DIR), stdout=log_f, stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            job.pid = proc.pid
            job.status = "running"
        except Exception as e:
            job.status = "failed"
            job.error = f"训练进程启动失败: {e}"
            job.finished_at = datetime.utcnow()
            mv.status = "Failed"
        self.db.commit()
        logger.info("[训练] 任务 %s 启动 pid=%s", job.name, job.pid)
        return self._job_dict(job)

    def cancel_job(self, job_id: str) -> None:
        job = self._get_job(job_id)
        if job.status not in ("pending", "running"):
            return
        if _pid_alive(job.pid):
            try:
                os.killpg(os.getpgid(job.pid), signal.SIGTERM)
            except Exception as e:
                logger.warning("[训练] 终止进程组失败 pid=%s: %s", job.pid, e)
        job.status = "canceled"
        job.finished_at = datetime.utcnow()
        mv = self.db.get(ModelVersionModel, job.model_version_id or "")
        if mv and mv.status == "Training":
            mv.status = "Failed"
        self.db.commit()

    def get_job_log(self, job_id: str, tail: int = 200) -> Dict[str, str]:
        job = self._get_job(job_id)
        self._refresh_job(job)
        self.db.commit()
        content = ""
        if job.log_path and Path(job.log_path).is_file():
            lines = Path(job.log_path).read_text(
                encoding="utf-8", errors="ignore").splitlines()
            content = "\n".join(lines[-tail:])
        return {"job": self._job_dict(job), "log": content}

    @staticmethod
    def _build_train_cmd(job: TrainingJobModel, dv: DatasetVersionModel) -> List[str]:
        p = job.params or {}
        cmd = [
            "bash", str(TRAINING_DIR / "train.sh"), job.method,
            "--model", job.base_model,
            "--train-file", dv.train_jsonl,
            "--val-file", dv.val_jsonl,
            "--output-dir", job.output_dir,
            "--epochs", str(p.get("epochs", 3)),
            "--batch-size", str(p.get("batch_size", 1)),
            "--gradient-accumulation", str(p.get("gradient_accumulation", 8)),
            "--learning-rate", str(p.get("learning_rate", 2e-4)),
            "--max-length", str(p.get("max_length", 2048)),
            "--lora-r", str(p.get("lora_r", 64)),
            "--lora-alpha", str(p.get("lora_alpha", 128)),
            "--lora-dropout", str(p.get("lora_dropout", 0.05)),
        ]
        if job.resume_from:
            cmd += ["--adapter-path", job.resume_from]
        return cmd

    def _refresh_job(self, job: TrainingJobModel) -> bool:
        """轮询进程与 training_summary.json，更新状态与 loss。返回是否有变更。"""
        changed = False
        summary_path = Path(job.output_dir) / "training_summary.json"
        if summary_path.is_file():
            try:
                summary = json.loads(summary_path.read_text(encoding="utf-8"))
                tl = summary.get("final_train_loss")
                vl = summary.get("final_eval_loss")
                if tl is not None and str(tl) != job.train_loss:
                    job.train_loss = str(tl)
                    changed = True
                if vl is not None and str(vl) != job.val_loss:
                    job.val_loss = str(vl)
                    changed = True
                adapter = summary.get("adapter_dir", "")
                mv = self.db.get(ModelVersionModel, job.model_version_id or "")
                if adapter and mv and not mv.adapter_path:
                    mv.adapter_path = adapter
                    changed = True
            except Exception:
                pass

        if job.status in ("pending", "running") and not _pid_alive(job.pid):
            job.finished_at = datetime.utcnow()
            changed = True
            mv = self.db.get(ModelVersionModel, job.model_version_id or "")
            adapter_dir = Path(job.output_dir) / "adapter"
            if summary_path.is_file() and adapter_dir.is_dir():
                job.status = "succeeded"
                if mv:
                    mv.status = "Ready"
                    mv.adapter_path = mv.adapter_path or str(adapter_dir)
                    mv.metrics = {"train_loss": job.train_loss, "val_loss": job.val_loss}
            else:
                job.status = "failed"
                if not job.error and job.log_path and Path(job.log_path).is_file():
                    tail = Path(job.log_path).read_text(
                        encoding="utf-8", errors="ignore").splitlines()[-20:]
                    job.error = "\n".join(tail)
                if mv:
                    mv.status = "Failed"
        return changed

    # ------------------------------------------------------------------
    # 模型版本
    # ------------------------------------------------------------------
    def list_model_versions(self) -> List[Dict[str, Any]]:
        mvs = (self.db.query(ModelVersionModel)
               .order_by(ModelVersionModel.created_at.desc()).all())
        # 顺带刷新 Training 状态（对应 job 可能已完成）
        for mv in mvs:
            if mv.status == "Training" and mv.job_id:
                job = self.db.get(TrainingJobModel, mv.job_id)
                if job and self._refresh_job(job):
                    self.db.commit()
        return [{
            "id": m.id, "name": m.name, "base_model": m.base_model,
            "job_id": m.job_id, "parent_id": m.parent_id,
            "adapter_path": m.adapter_path, "status": m.status,
            "metrics": m.metrics or {},
            "created_at": m.created_at.isoformat() if m.created_at else "",
        } for m in mvs]

    def set_model_version_status(self, mv_id: str, action: str) -> None:
        """发布 / 归档。本期不接入 Chat 模型调用，仅管理状态。"""
        mv = self.db.get(ModelVersionModel, mv_id)
        if not mv:
            raise AppError(404, "模型版本不存在")
        if action == "publish":
            if mv.status != "Ready":
                raise AppError(400, "只有 Ready 状态的版本可以发布")
            # 同一基础模型只允许一个 Published
            others = (self.db.query(ModelVersionModel)
                      .filter(ModelVersionModel.base_model == mv.base_model,
                              ModelVersionModel.status == "Published",
                              ModelVersionModel.id != mv.id).all())
            for o in others:
                o.status = "Archived"
            mv.status = "Published"
        elif action == "archive":
            mv.status = "Archived"
        else:
            raise AppError(400, f"未知操作: {action}")
        self.db.commit()

    def overview(self) -> Dict[str, Any]:
        """数据资产中心总览统计。"""
        assets = self.db.query(func.count(DataAssetModel.id)).scalar() or 0
        asset_by_source = dict(
            self.db.query(DataAssetModel.source_type, func.count())
            .group_by(DataAssetModel.source_type).all())
        sample_counts = dict(
            self.db.query(TrainingSampleModel.status, func.count())
            .group_by(TrainingSampleModel.status).all())
        doc_types = dict(
            self.db.query(DataAssetModel.doc_type, func.count())
            .filter(DataAssetModel.doc_type != "")
            .group_by(DataAssetModel.doc_type).all())
        jobs = dict(
            self.db.query(TrainingJobModel.status, func.count())
            .group_by(TrainingJobModel.status).all())
        models = self.db.query(func.count(ModelVersionModel.id)).scalar() or 0
        return {
            "asset_count": assets,
            "asset_by_source": asset_by_source,
            "sample_counts": sample_counts,
            "doc_types": doc_types,
            "job_counts": jobs,
            "model_count": models,
        }

    # ------------------------------------------------------------------
    # 内部：质量检查 / 导出 / 统计
    # ------------------------------------------------------------------
    @staticmethod
    def _quality_check(samples: List[TrainingSampleModel]) -> Dict[str, Any]:
        """自动检查：空文本、缺失字段、异常长度、重复（完全 + 近似）。"""
        seen_hash = set()
        seen_prefix = set()
        valid_ids: List[str] = []
        dup = missing = abnormal = empty = 0
        for s in samples:
            out = (s.output or "").strip()
            ins = (s.instruction or "").strip()
            if not out:
                empty += 1
                continue
            if not ins:
                missing += 1
                continue
            if len(out) < MIN_TEXT_LEN or len(out) > MAX_TEXT_LEN:
                abnormal += 1
                continue
            h = hashlib.md5((ins + out).encode("utf-8")).hexdigest()
            if h in seen_hash:
                dup += 1
                continue
            # 近似重复：正文前 200 字相同
            prefix = hashlib.md5(out[:200].encode("utf-8")).hexdigest()
            if prefix in seen_prefix:
                dup += 1
                continue
            seen_hash.add(h)
            seen_prefix.add(prefix)
            valid_ids.append(s.id)
        return {
            "valid_ids": valid_ids,
            "report": {
                "total": len(samples), "valid": len(valid_ids),
                "duplicate": dup, "missing": missing,
                "abnormal": abnormal, "empty": empty,
            },
        }

    @staticmethod
    def _export_jsonl(samples: List[TrainingSampleModel], out_dir: Path,
                      val_ratio: float) -> tuple:
        """导出 train.jsonl / val.jsonl。draft 保留，供训练脚本拼装 user 内容。"""
        import random
        records = []
        for s in samples:
            rec = {"instruction": s.instruction or "", "input": s.input or "",
                   "output": s.output or ""}
            if s.draft:
                rec["draft"] = s.draft
            records.append(rec)
        rng = random.Random(42)
        rng.shuffle(records)
        n_val = max(1, int(len(records) * val_ratio)) if len(records) > 1 else 0
        val, train = records[:n_val], records[n_val:]
        train_path = out_dir / "train.jsonl"
        val_path = out_dir / "val.jsonl"
        with open(train_path, "w", encoding="utf-8") as f:
            for r in train:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        with open(val_path, "w", encoding="utf-8") as f:
            for r in val:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        return train_path, val_path

    @staticmethod
    def _dataset_stats(samples: List[TrainingSampleModel]) -> Dict[str, Any]:
        by_source: Dict[str, int] = {}
        by_type: Dict[str, int] = {}
        for s in samples:
            by_source[s.source or "import"] = by_source.get(s.source or "import", 0) + 1
            if s.biz_type:
                by_type[s.biz_type] = by_type.get(s.biz_type, 0) + 1
        return {"by_source": by_source, "by_doc_type": by_type}

    # ------------------------------------------------------------------
    # 序列化
    # ------------------------------------------------------------------
    @staticmethod
    def _asset_dict(a: DataAssetModel, with_content: bool) -> Dict[str, Any]:
        d = {
            "id": a.id, "name": a.name, "source_type": a.source_type,
            "file_path": a.file_path, "file_type": a.file_type,
            "title": a.title, "doc_type": a.doc_type,
            "char_count": a.char_count, "status": a.status,
            "sample_generated": a.sample_generated,
            "extra": a.extra or {},
            "created_at": a.created_at.isoformat() if a.created_at else "",
        }
        if with_content:
            d["content"] = a.content
        return d

    @staticmethod
    def _sample_dict(s: TrainingSampleModel) -> Dict[str, Any]:
        return {
            "id": s.id, "instruction": s.instruction, "input": s.input,
            "output": s.output, "draft": s.draft, "source": s.source,
            "asset_id": s.asset_id, "session_id": s.session_id,
            "biz_type": s.biz_type, "status": s.status,
            "reviewed_by": s.reviewed_by,
            "created_at": s.created_at.isoformat() if s.created_at else "",
        }

    @staticmethod
    def _version_dict(v: DatasetVersionModel, detail: bool = False) -> Dict[str, Any]:
        d = {
            "id": v.id, "dataset_id": v.dataset_id, "version": v.version,
            "status": v.status, "stats": v.stats or {},
            "check_report": v.check_report or {},
            "sample_count": len(v.sample_ids or []),
            "train_jsonl": v.train_jsonl, "val_jsonl": v.val_jsonl,
            "created_at": v.created_at.isoformat() if v.created_at else "",
        }
        return d

    @staticmethod
    def _job_dict(j: TrainingJobModel) -> Dict[str, Any]:
        return {
            "id": j.id, "name": j.name, "dataset_version_id": j.dataset_version_id,
            "base_model": j.base_model, "method": j.method, "params": j.params or {},
            "status": j.status, "pid": j.pid, "log_path": j.log_path,
            "output_dir": j.output_dir, "resume_from": j.resume_from,
            "train_loss": j.train_loss, "val_loss": j.val_loss, "error": j.error,
            "model_version_id": j.model_version_id,
            "started_at": j.started_at.isoformat() if j.started_at else "",
            "finished_at": j.finished_at.isoformat() if j.finished_at else "",
            "created_at": j.created_at.isoformat() if j.created_at else "",
        }

    def _get_asset(self, asset_id: str) -> DataAssetModel:
        a = self.db.get(DataAssetModel, asset_id)
        if not a:
            raise AppError(404, "数据资产不存在")
        return a

    def _get_sample(self, sample_id: str) -> TrainingSampleModel:
        s = self.db.get(TrainingSampleModel, sample_id)
        if not s:
            raise AppError(404, "样本不存在")
        return s

    def _get_job(self, job_id: str) -> TrainingJobModel:
        j = self.db.get(TrainingJobModel, job_id)
        if not j:
            raise AppError(404, "训练任务不存在")
        return j
"""数据资产中心 + 模型训练 —— 应用服务。

链路：真实业务数据 + 历史成熟公文 + 批量导入
      → 数据资产 → 候选样本(candidate) → 人工审核(approved)
      → Dataset Version（质量检查 + train/val jsonl）
      → 独立进程 LoRA/QLoRA 训练 → Model Version(Adapter)

隐私约束：全部本地完成，不上传任何文档 / 训练数据 / 模型到第三方；
AI 辅助构造只调用本地模型网关（get_llm_gateway）。
"""
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import AppError
from app.core.logging import get_logger
from app.infrastructure.ai import get_llm_gateway
from app.infrastructure.database.models.training import (
    DataAssetModel,
    DatasetModel,
    DatasetVersionModel,
    ModelVersionModel,
    TrainingJobModel,
    TrainingSampleModel,
)

from .docparse import parse_document, scan_directory

logger = get_logger(__name__)

# 训练模块目录：默认 仓库根/training，可用 TRAINING_DIR 覆盖
TRAINING_DIR = Path(os.getenv("TRAINING_DIR", str(settings.DATA_DIR.parent / "training"))).resolve()

MIN_TEXT_LEN = 20        # 低于此长度视为空文本/异常
MAX_TEXT_LEN = 32000     # 超过此长度视为异常长度


def _pid_alive(pid: Optional[int]) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


class TrainingService:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # 数据资产
    # ------------------------------------------------------------------
    def list_assets(self, source_type: str = "", keyword: str = "",
                    page: int = 1, page_size: int = 20) -> Dict[str, Any]:
        q = self.db.query(DataAssetModel)
        if source_type:
            q = q.filter(DataAssetModel.source_type == source_type)
        if keyword:
            like = f"%{keyword}%"
            q = q.filter(DataAssetModel.title.like(like) | DataAssetModel.name.like(like))
        total = q.count()
        items = (q.order_by(DataAssetModel.created_at.desc())
                 .offset((page - 1) * page_size).limit(page_size).all())
        return {"total": total, "items": [self._asset_dict(a, with_content=False) for a in items]}

    def get_asset(self, asset_id: str) -> Dict[str, Any]:
        return self._asset_dict(self._get_asset(asset_id), with_content=True)

    def import_directory(self, path: str, source_type: str, recursive: bool,
                         user_id: str) -> Dict[str, int]:
        """批量导入外部目录：扫描 → 提取正文 → 识别标题/文种 → 登记资产。"""
        files = scan_directory(path, recursive)
        if not files:
            raise AppError(400, f"目录中没有可导入的文件（支持 docx/pdf/txt/md）: {path}")
        created = skipped = 0
        for f in files:
            fp = str(f)
            exists = (self.db.query(DataAssetModel)
                      .filter(DataAssetModel.file_path == fp).first())
            if exists:
                skipped += 1
                continue
            info = parse_document(f)
            if info["char_count"] < MIN_TEXT_LEN:
                skipped += 1
                continue
            self.db.add(DataAssetModel(
                **info, source_type=source_type, created_by=user_id,
                extra={"source_dir": path},
            ))
            created += 1
        self.db.commit()
        logger.info("[数据资产] 目录导入 %s: 新增 %d, 跳过 %d", path, created, skipped)
        return {"created": created, "skipped": skipped}

    def import_zip(self, file_path: Path, filename: str, user_id: str) -> Dict[str, int]:
        """导入 ZIP（documents/001.docx ... 可选 dataset.xlsx 元数据）。
        ZIP 解压到 training/data/raw/<批次>/，原始文件保存在该外部目录。"""
        batch_dir = TRAINING_DIR / "data" / "raw" / datetime.now().strftime("batch_%Y%m%d_%H%M%S")
        batch_dir.mkdir(parents=True, exist_ok=True)
        try:
            with zipfile.ZipFile(file_path) as zf:
                zf.extractall(batch_dir)
        except zipfile.BadZipFile:
            raise AppError(400, "ZIP 文件损坏或格式不正确")
        result = self.import_directory(str(batch_dir), "batch", True, user_id)
        # ZIP 内若带 dataset.xlsx，一并按 Excel 导入样本
        for xlsx in batch_dir.glob("**/*.xlsx"):
            result["samples"] = self.import_excel(xlsx, user_id).get("created", 0)
        return result

    def import_excel(self, file_path: Path, user_id: str) -> Dict[str, int]:
        """导入 Excel/CSV：只需少量字段。列名支持 title/content/instruction/input/output。
        有 content 列 → 登记数据资产；有 output 列 → 直接形成候选样本。"""
        import pandas as pd
        try:
            if str(file_path).lower().endswith(".csv"):
                df = pd.read_csv(file_path)
            else:
                df = pd.read_excel(file_path)
        except Exception as e:
            raise AppError(400, f"表格读取失败: {e}")
        df.columns = [str(c).strip().lower() for c in df.columns]
        created = 0
        for _, row in df.iterrows():
            r = {k: ("" if pd.isna(v) else str(v).strip()) for k, v in row.items()}
            content = r.get("content", "") or r.get("output", "")
            if len(content) < MIN_TEXT_LEN:
                continue
            asset = DataAssetModel(
                name=r.get("title", "") or f"表格导入-{created + 1}",
                source_type="excel",
                file_path=str(file_path),
                file_type=Path(file_path).suffix.lstrip("."),
                title=r.get("title", ""),
                doc_type=r.get("doc_type", ""),
                content=content,
                char_count=len(content),
                extra={k: v for k, v in r.items()
                       if k not in ("title", "content", "instruction", "input", "output", "doc_type") and v},
                created_by=user_id,
            )
            self.db.add(asset)
            self.db.flush()
            # 表格自带 instruction/output 时直接形成候选样本
            if r.get("output"):
                self.db.add(TrainingSampleModel(
                    instruction=r.get("instruction", "") or f"请起草：{asset.title}",
                    input=r.get("input", ""),
                    output=r["output"],
                    source="import",
                    asset_id=asset.id,
                    biz_type=asset.doc_type,
                    created_by=user_id,
                ))
                asset.sample_generated = 1
            created += 1
        self.db.commit()
        return {"created": created}

    def import_jsonl(self, file_path: Path, user_id: str) -> Dict[str, int]:
        """导入 JSON/JSONL：每条需含 output（instruction/input 可选）。"""
        created = 0
        for obj in self._read_json_records(file_path):
            output = str(obj.get("output", "")).strip()
            if len(output) < MIN_TEXT_LEN:
                continue
            self.db.add(TrainingSampleModel(
                instruction=str(obj.get("instruction", "")).strip(),
                input=str(obj.get("input", "")).strip(),
                output=output,
                source="import",
                biz_type=str(obj.get("biz_type", "")),
                created_by=user_id,
            ))
            created += 1
        self.db.commit()
        return {"created": created}

    @staticmethod
    def _read_json_records(path: Path) -> List[dict]:
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            return []
        if text.startswith("["):
            return [o for o in json.loads(text) if isinstance(o, dict)]
        return [json.loads(line) for line in text.splitlines() if line.strip()]

    def set_asset_status(self, asset_id: str, status: str) -> None:
        asset = self._get_asset(asset_id)
        asset.status = status
        self.db.commit()

    def delete_asset(self, asset_id: str) -> None:
        asset = self._get_asset(asset_id)
        self.db.delete(asset)
        self.db.commit()

    # ------------------------------------------------------------------
    # AI 辅助构造候选样本（本地模型，结果必须人工审核）
    # ------------------------------------------------------------------
    def generate_sample_from_asset(self, asset_id: str, user_id: str) -> Dict[str, Any]:
        asset = self._get_asset(asset_id)
        if not asset.content:
            raise AppError(400, "该资产没有可用正文")
        gateway = get_llm_gateway()
        prompt = (
            "你是司法公文写作助手。请根据下面这篇成熟公文，构造一条写作训练数据。\n"
            "要求：\n"
            "1. 推测工作人员最可能提出的原始写作需求（一句话，口语化但任务明确）；\n"
            "2. 给出完成该任务所需的背景信息要点（时间、单位、事项等，若原文没有则不编造）；\n"
            "3. 严格按以下格式输出三行：\n"
            "任务：...\n背景：...\n（正文不需要输出）\n\n"
            f"公文标题：{asset.title}\n\n公文正文（节选）：\n{asset.content[:2000]}"
        )
        try:
            reply = gateway.complete(
                [{"role": "user", "content": prompt}], temperature=0.3, max_tokens=800)
        except Exception as e:
            raise AppError(500, f"本地模型调用失败: {e}")
        instruction = self._parse_line(reply, "任务") or f"请起草：{asset.title}"
        background = self._parse_line(reply, "背景")
        sample = TrainingSampleModel(
            instruction=instruction,
            input=background,
            output=asset.content,
            source="ai_generated",
            asset_id=asset.id,
            biz_type=asset.doc_type,
            created_by=user_id,
        )
        self.db.add(sample)
        asset.sample_generated = 1
        self.db.commit()
        self.db.refresh(sample)
        return self._sample_dict(sample)

    @staticmethod
    def _parse_line(text: str, key: str) -> str:
        for line in text.splitlines():
            line = line.strip()
            if line.startswith(key + "：") or line.startswith(key + ":"):
                return line.split("：", 1)[-1].split(":", 1)[-1].strip()
        return ""

    # ------------------------------------------------------------------
    # 训练样本审核
    # ------------------------------------------------------------------
    def list_samples(self, status: str = "", source: str = "",
                     page: int = 1, page_size: int = 20) -> Dict[str, Any]:
        q = self.db.query(TrainingSampleModel)
        if status:
            q = q.filter(TrainingSampleModel.status == status)
        if source:
            q = q.filter(TrainingSampleModel.source == source)
        total = q.count()
        items = (q.order_by(TrainingSampleModel.created_at.desc())
                 .offset((page - 1) * page_size).limit(page_size).all())
        counts = dict(
            self.db.query(TrainingSampleModel.status, func.count())
            .group_by(TrainingSampleModel.status).all()
        )
        return {"total": total, "counts": counts,
                "items": [self._sample_dict(s) for s in items]}

    def review_sample(self, sample_id: str, action: str, user_id: str) -> None:
        """action: approve / disable。approved 才能进入数据集版本。"""
        sample = self._get_sample(sample_id)
        if action == "approve":
            sample.status = "approved"
        elif action == "disable":
            sample.status = "disabled"
        elif action == "candidate":
            sample.status = "candidate"
        else:
            raise AppError(400, f"未知操作: {action}")
        sample.reviewed_by = user_id
        sample.reviewed_at = datetime.utcnow()
        self.db.commit()

    def edit_sample(self, sample_id: str, fields: Dict[str, Any]) -> Dict[str, Any]:
        sample = self._get_sample(sample_id)
        for k in ("instruction", "input", "output", "draft", "biz_type"):
            v = fields.get(k)
            if v is not None:
                setattr(sample, k, v)
        self.db.commit()
        self.db.refresh(sample)
        return self._sample_dict(sample)

    def delete_sample(self, sample_id: str) -> None:
        self.db.delete(self._get_sample(sample_id))
        self.db.commit()

    def add_sample_from_chat(self, req, user_id: str) -> Dict[str, Any]:
        """Chat「加入训练集」：真实需求 + AI 初稿 + 人工最终稿 → candidate。
        不立即训练，需人工审核通过后才进入数据集。"""
        sample = TrainingSampleModel(
            instruction=req.instruction,
            input="",
            draft=req.draft,
            output=req.output,
            source="chat",
            session_id=req.session_id,
            biz_type=req.biz_type,
            created_by=user_id,
        )
        self.db.add(sample)
        # 同步登记业务过程数据资产
        self.db.add(DataAssetModel(
            name=req.instruction[:60] or "业务过程数据",
            source_type="business",
            file_type="chat",
            title=req.instruction[:120],
            doc_type=req.biz_type,
            content=req.output,
            char_count=len(req.output),
            extra={"session_id": req.session_id, "has_draft": bool(req.draft)},
            sample_generated=1,
            created_by=user_id,
        ))
        self.db.commit()
        self.db.refresh(sample)
        return self._sample_dict(sample)

    # ------------------------------------------------------------------
    # 数据集 / 数据集版本
    # ------------------------------------------------------------------
    def list_datasets(self) -> List[Dict[str, Any]]:
        datasets = self.db.query(DatasetModel).order_by(DatasetModel.created_at.desc()).all()
        result = []
        for d in datasets:
            versions = (self.db.query(DatasetVersionModel)
                        .filter(DatasetVersionModel.dataset_id == d.id)
                        .order_by(DatasetVersionModel.created_at.desc()).all())
            result.append({
                "id": d.id, "name": d.name, "description": d.description,
                "created_at": d.created_at.isoformat() if d.created_at else "",
                "versions": [self._version_dict(v) for v in versions],
            })
        return result

    def create_dataset(self, name: str, description: str, user_id: str) -> Dict[str, Any]:
        d = DatasetModel(name=name, description=description, created_by=user_id)
        self.db.add(d)
        self.db.commit()
        self.db.refresh(d)
        return {"id": d.id, "name": d.name, "description": d.description}

    def create_dataset_version(self, dataset_id: str, version: str,
                               val_ratio: float, user_id: str) -> Dict[str, Any]:
        """生成 Dataset Version：取全部 approved 样本 → 质量检查 → 导出 train/val jsonl。"""
        dataset = self.db.get(DatasetModel, dataset_id)
        if not dataset:
            raise AppError(404, "数据集不存在")
        dup = (self.db.query(DatasetVersionModel)
               .filter(DatasetVersionModel.dataset_id == dataset_id,
                       DatasetVersionModel.version == version).first())
        if dup:
            raise AppError(400, f"版本 {version} 已存在")

        samples = (self.db.query(TrainingSampleModel)
                   .filter(TrainingSampleModel.status == "approved").all())
        if not samples:
            raise AppError(400, "没有已审核（approved）的样本，无法生成数据集版本")

        check = self._quality_check(samples)
        valid_ids: List[str] = check["valid_ids"]
        if not valid_ids:
            raise AppError(400, "质量检查后没有有效样本")

        # 统计
        stats = self._dataset_stats(samples)
        stats["total"] = len(samples)
        stats["valid"] = len(valid_ids)
        counts = dict(
            self.db.query(TrainingSampleModel.status, func.count())
            .group_by(TrainingSampleModel.status).all())
        stats["candidate"] = counts.get("candidate", 0)
        stats["disabled"] = counts.get("disabled", 0)

        # 导出 train/val jsonl（JSONL 仅为训练框架内部格式）
        out_dir = TRAINING_DIR / "datasets" / f"{dataset.name}_{version}"
        out_dir.mkdir(parents=True, exist_ok=True)
        train_path, val_path = self._export_jsonl(
            [s for s in samples if s.id in set(valid_ids)], out_dir, val_ratio)

        dv = DatasetVersionModel(
            dataset_id=dataset_id, version=version, status="ready",
            stats=stats, check_report=check["report"], sample_ids=valid_ids,
            train_jsonl=str(train_path), val_jsonl=str(val_path),
            created_by=user_id,
        )
        self.db.add(dv)
        self.db.commit()
        self.db.refresh(dv)
        logger.info("[数据集] %s %s: 有效 %d/%d", dataset.name, version,
                    len(valid_ids), len(samples))
        return self._version_dict(dv, detail=True)

    # ------------------------------------------------------------------
    # 训练任务（独立进程，不阻塞 FastAPI）
    # ------------------------------------------------------------------
    def list_jobs(self) -> List[Dict[str, Any]]:
        jobs = (self.db.query(TrainingJobModel)
                .order_by(TrainingJobModel.created_at.desc()).all())
        changed = False
        for j in jobs:
            if j.status in ("pending", "running"):
                changed |= self._refresh_job(j)
        if changed:
            self.db.commit()
        return [self._job_dict(j) for j in jobs]

    def create_job(self, req, user_id: str) -> Dict[str, Any]:
        dv = self.db.get(DatasetVersionModel, req.dataset_version_id)
        if not dv:
            raise AppError(404, "数据集版本不存在")
        if not Path(dv.train_jsonl).is_file():
            raise AppError(400, "数据集版本的训练文件缺失，请重新生成版本")
        if req.method not in ("lora", "qlora"):
            raise AppError(400, "训练方式仅支持 lora / qlora")
        if not Path(req.base_model).exists():
            raise AppError(400, f"基础模型路径不存在: {req.base_model}")

        resume_from = ""
        parent_mv = None
        if req.parent_model_version_id:
            parent_mv = self.db.get(ModelVersionModel, req.parent_model_version_id)
            if not parent_mv or not parent_mv.adapter_path:
                raise AppError(400, "父版本没有可用的 Adapter")
            resume_from = parent_mv.adapter_path

        output_dir = TRAINING_DIR / "outputs" / f"{req.name}_{datetime.now():%Y%m%d_%H%M%S}"
        log_path = TRAINING_DIR / "logs" / f"job_{datetime.now():%Y%m%d_%H%M%S}_{req.name}.log"
        output_dir.mkdir(parents=True, exist_ok=True)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        job = TrainingJobModel(
            name=req.name, dataset_version_id=dv.id, base_model=req.base_model,
            method=req.method,
            params={
                "epochs": req.epochs, "batch_size": req.batch_size,
                "gradient_accumulation": req.gradient_accumulation,
                "learning_rate": req.learning_rate, "max_length": req.max_length,
                "lora_r": req.lora_r, "lora_alpha": req.lora_alpha,
                "lora_dropout": req.lora_dropout,
            },
            status="pending", log_path=str(log_path), output_dir=str(output_dir),
            resume_from=resume_from, created_by=user_id, started_at=datetime.utcnow(),
        )
        self.db.add(job)
        self.db.flush()

        # 预创建模型版本（Training 状态）
        mv = ModelVersionModel(
            name=req.model_version_name or f"Judicial-Model-{req.name}",
            base_model=req.base_model, job_id=job.id,
            parent_id=parent_mv.id if parent_mv else None,
            status="Training",
        )
        self.db.add(mv)
        self.db.flush()
        job.model_version_id = mv.id

        # 启动独立训练进程
        cmd = self._build_train_cmd(job, dv)
        try:
            log_f = open(log_path, "w", encoding="utf-8")
            proc = subprocess.Popen(
                cmd, cwd=str(TRAINING_DIR), stdout=log_f, stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            job.pid = proc.pid
            job.status = "running"
        except Exception as e:
            job.status = "failed"
            job.error = f"训练进程启动失败: {e}"
            job.finished_at = datetime.utcnow()
            mv.status = "Failed"
        self.db.commit()
        logger.info("[训练] 任务 %s 启动 pid=%s", job.name, job.pid)
        return self._job_dict(job)

    def cancel_job(self, job_id: str) -> None:
        job = self._get_job(job_id)
        if job.status not in ("pending", "running"):
            return
        if _pid_alive(job.pid):
            try:
                os.killpg(os.getpgid(job.pid), signal.SIGTERM)
            except Exception as e:
                logger.warning("[训练] 终止进程组失败 pid=%s: %s", job.pid, e)
        job.status = "canceled"
        job.finished_at = datetime.utcnow()
        mv = self.db.get(ModelVersionModel, job.model_version_id or "")
        if mv and mv.status == "Training":
            mv.status = "Failed"
        self.db.commit()

    def get_job_log(self, job_id: str, tail: int = 200) -> Dict[str, str]:
        job = self._get_job(job_id)
        self._refresh_job(job)
        self.db.commit()
        content = ""
        if job.log_path and Path(job.log_path).is_file():
            lines = Path(job.log_path).read_text(
                encoding="utf-8", errors="ignore").splitlines()
            content = "\n".join(lines[-tail:])
        return {"job": self._job_dict(job), "log": content}

    @staticmethod
    def _build_train_cmd(job: TrainingJobModel, dv: DatasetVersionModel) -> List[str]:
        p = job.params or {}
        cmd = [
            "bash", str(TRAINING_DIR / "train.sh"), job.method,
            "--model", job.base_model,
            "--train-file", dv.train_jsonl,
            "--val-file", dv.val_jsonl,
            "--output-dir", job.output_dir,
            "--epochs", str(p.get("epochs", 3)),
            "--batch-size", str(p.get("batch_size", 1)),
            "--gradient-accumulation", str(p.get("gradient_accumulation", 8)),
            "--learning-rate", str(p.get("learning_rate", 2e-4)),
            "--max-length", str(p.get("max_length", 2048)),
            "--lora-r", str(p.get("lora_r", 64)),
            "--lora-alpha", str(p.get("lora_alpha", 128)),
            "--lora-dropout", str(p.get("lora_dropout", 0.05)),
        ]
        if job.resume_from:
            cmd += ["--adapter-path", job.resume_from]
        return cmd

    def _refresh_job(self, job: TrainingJobModel) -> bool:
        """轮询进程与 training_summary.json，更新状态与 loss。返回是否有变更。"""
        changed = False
        summary_path = Path(job.output_dir) / "training_summary.json"
        if summary_path.is_file():
            try:
                summary = json.loads(summary_path.read_text(encoding="utf-8"))
                tl = summary.get("final_train_loss")
                vl = summary.get("final_eval_loss")
                if tl is not None and str(tl) != job.train_loss:
                    job.train_loss = str(tl)
                    changed = True
                if vl is not None and str(vl) != job.val_loss:
                    job.val_loss = str(vl)
                    changed = True
                adapter = summary.get("adapter_dir", "")
                mv = self.db.get(ModelVersionModel, job.model_version_id or "")
                if adapter and mv and not mv.adapter_path:
                    mv.adapter_path = adapter
                    changed = True
            except Exception:
                pass

        if job.status in ("pending", "running") and not _pid_alive(job.pid):
            job.finished_at = datetime.utcnow()
            changed = True
            mv = self.db.get(ModelVersionModel, job.model_version_id or "")
            adapter_dir = Path(job.output_dir) / "adapter"
            if summary_path.is_file() and adapter_dir.is_dir():
                job.status = "succeeded"
                if mv:
                    mv.status = "Ready"
                    mv.adapter_path = mv.adapter_path or str(adapter_dir)
                    mv.metrics = {"train_loss": job.train_loss, "val_loss": job.val_loss}
            else:
                job.status = "failed"
                if not job.error and job.log_path and Path(job.log_path).is_file():
                    tail = Path(job.log_path).read_text(
                        encoding="utf-8", errors="ignore").splitlines()[-20:]
                    job.error = "\n".join(tail)
                if mv:
                    mv.status = "Failed"
        return changed

    # ------------------------------------------------------------------
    # 模型版本
    # ------------------------------------------------------------------
    def list_model_versions(self) -> List[Dict[str, Any]]:
        mvs = (self.db.query(ModelVersionModel)
               .order_by(ModelVersionModel.created_at.desc()).all())
        # 顺带刷新 Training 状态（对应 job 可能已完成）
        for mv in mvs:
            if mv.status == "Training" and mv.job_id:
                job = self.db.get(TrainingJobModel, mv.job_id)
                if job and self._refresh_job(job):
                    self.db.commit()
        return [{
            "id": m.id, "name": m.name, "base_model": m.base_model,
            "job_id": m.job_id, "parent_id": m.parent_id,
            "adapter_path": m.adapter_path, "status": m.status,
            "metrics": m.metrics or {},
            "created_at": m.created_at.isoformat() if m.created_at else "",
        } for m in mvs]

    def set_model_version_status(self, mv_id: str, action: str) -> None:
        """发布 / 归档。本期不接入 Chat 模型调用，仅管理状态。"""
        mv = self.db.get(ModelVersionModel, mv_id)
        if not mv:
            raise AppError(404, "模型版本不存在")
        if action == "publish":
            if mv.status != "Ready":
                raise AppError(400, "只有 Ready 状态的版本可以发布")
            # 同一基础模型只允许一个 Published
            others = (self.db.query(ModelVersionModel)
                      .filter(ModelVersionModel.base_model == mv.base_model,
                              ModelVersionModel.status == "Published",
                              ModelVersionModel.id != mv.id).all())
            for o in others:
                o.status = "Archived"
            mv.status = "Published"
        elif action == "archive":
            mv.status = "Archived"
        else:
            raise AppError(400, f"未知操作: {action}")
        self.db.commit()

    def overview(self) -> Dict[str, Any]:
        """数据资产中心总览统计。"""
        assets = self.db.query(func.count(DataAssetModel.id)).scalar() or 0
        asset_by_source = dict(
            self.db.query(DataAssetModel.source_type, func.count())
            .group_by(DataAssetModel.source_type).all())
        sample_counts = dict(
            self.db.query(TrainingSampleModel.status, func.count())
            .group_by(TrainingSampleModel.status).all())
        doc_types = dict(
            self.db.query(DataAssetModel.doc_type, func.count())
            .filter(DataAssetModel.doc_type != "")
            .group_by(DataAssetModel.doc_type).all())
        jobs = dict(
            self.db.query(TrainingJobModel.status, func.count())
            .group_by(TrainingJobModel.status).all())
        models = self.db.query(func.count(ModelVersionModel.id)).scalar() or 0
        return {
            "asset_count": assets,
            "asset_by_source": asset_by_source,
            "sample_counts": sample_counts,
            "doc_types": doc_types,
            "job_counts": jobs,
            "model_count": models,
        }

    # ------------------------------------------------------------------
    # 内部：质量检查 / 导出 / 统计
    # ------------------------------------------------------------------
    @staticmethod
    def _quality_check(samples: List[TrainingSampleModel]) -> Dict[str, Any]:
        """自动检查：空文本、缺失字段、异常长度、重复（完全 + 近似）。"""
        seen_hash = set()
        seen_prefix = set()
        valid_ids: List[str] = []
        dup = missing = abnormal = empty = 0
        for s in samples:
            out = (s.output or "").strip()
            ins = (s.instruction or "").strip()
            if not out:
                empty += 1
                continue
            if not ins:
                missing += 1
                continue
            if len(out) < MIN_TEXT_LEN or len(out) > MAX_TEXT_LEN:
                abnormal += 1
                continue
            h = hashlib.md5((ins + out).encode("utf-8")).hexdigest()
            if h in seen_hash:
                dup += 1
                continue
            # 近似重复：正文前 200 字相同
            prefix = hashlib.md5(out[:200].encode("utf-8")).hexdigest()
            if prefix in seen_prefix:
                dup += 1
                continue
            seen_hash.add(h)
            seen_prefix.add(prefix)
            valid_ids.append(s.id)
        return {
            "valid_ids": valid_ids,
            "report": {
                "total": len(samples), "valid": len(valid_ids),
                "duplicate": dup, "missing": missing,
                "abnormal": abnormal, "empty": empty,
            },
        }

    @staticmethod
    def _export_jsonl(samples: List[TrainingSampleModel], out_dir: Path,
                      val_ratio: float) -> tuple:
        """导出 train.jsonl / val.jsonl。draft 保留，供训练脚本拼装 user 内容。"""
        import random
        records = []
        for s in samples:
            rec = {"instruction": s.instruction or "", "input": s.input or "",
                   "output": s.output or ""}
            if s.draft:
                rec["draft"] = s.draft
            records.append(rec)
        rng = random.Random(42)
        rng.shuffle(records)
        n_val = max(1, int(len(records) * val_ratio)) if len(records) > 1 else 0
        val, train = records[:n_val], records[n_val:]
        train_path = out_dir / "train.jsonl"
        val_path = out_dir / "val.jsonl"
        with open(train_path, "w", encoding="utf-8") as f:
            for r in train:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        with open(val_path, "w", encoding="utf-8") as f:
            for r in val:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        return train_path, val_path

    @staticmethod
    def _dataset_stats(samples: List[TrainingSampleModel]) -> Dict[str, Any]:
        by_source: Dict[str, int] = {}
        by_type: Dict[str, int] = {}
        for s in samples:
            by_source[s.source or "import"] = by_source.get(s.source or "import", 0) + 1
            if s.biz_type:
                by_type[s.biz_type] = by_type.get(s.biz_type, 0) + 1
        return {"by_source": by_source, "by_doc_type": by_type}

    # ------------------------------------------------------------------
    # 序列化
    # ------------------------------------------------------------------
    @staticmethod
    def _asset_dict(a: DataAssetModel, with_content: bool) -> Dict[str, Any]:
        d = {
            "id": a.id, "name": a.name, "source_type": a.source_type,
            "file_path": a.file_path, "file_type": a.file_type,
            "title": a.title, "doc_type": a.doc_type,
            "char_count": a.char_count, "status": a.status,
            "sample_generated": a.sample_generated,
            "extra": a.extra or {},
            "created_at": a.created_at.isoformat() if a.created_at else "",
        }
        if with_content:
            d["content"] = a.content
        return d

    @staticmethod
    def _sample_dict(s: TrainingSampleModel) -> Dict[str, Any]:
        return {
            "id": s.id, "instruction": s.instruction, "input": s.input,
            "output": s.output, "draft": s.draft, "source": s.source,
            "asset_id": s.asset_id, "session_id": s.session_id,
            "biz_type": s.biz_type, "status": s.status,
            "reviewed_by": s.reviewed_by,
            "created_at": s.created_at.isoformat() if s.created_at else "",
        }

    @staticmethod
    def _version_dict(v: DatasetVersionModel, detail: bool = False) -> Dict[str, Any]:
        d = {
            "id": v.id, "dataset_id": v.dataset_id, "version": v.version,
            "status": v.status, "stats": v.stats or {},
            "check_report": v.check_report or {},
            "sample_count": len(v.sample_ids or []),
            "train_jsonl": v.train_jsonl, "val_jsonl": v.val_jsonl,
            "created_at": v.created_at.isoformat() if v.created_at else "",
        }
        return d

    @staticmethod
    def _job_dict(j: TrainingJobModel) -> Dict[str, Any]:
        return {
            "id": j.id, "name": j.name, "dataset_version_id": j.dataset_version_id,
            "base_model": j.base_model, "method": j.method, "params": j.params or {},
            "status": j.status, "pid": j.pid, "log_path": j.log_path,
            "output_dir": j.output_dir, "resume_from": j.resume_from,
            "train_loss": j.train_loss, "val_loss": j.val_loss, "error": j.error,
            "model_version_id": j.model_version_id,
            "started_at": j.started_at.isoformat() if j.started_at else "",
            "finished_at": j.finished_at.isoformat() if j.finished_at else "",
            "created_at": j.created_at.isoformat() if j.created_at else "",
        }

    def _get_asset(self, asset_id: str) -> DataAssetModel:
        a = self.db.get(DataAssetModel, asset_id)
        if not a:
            raise AppError(404, "数据资产不存在")
        return a

    def _get_sample(self, sample_id: str) -> TrainingSampleModel:
        s = self.db.get(TrainingSampleModel, sample_id)
        if not s:
            raise AppError(404, "样本不存在")
        return s

    def _get_job(self, job_id: str) -> TrainingJobModel:
        j = self.db.get(TrainingJobModel, job_id)
        if not j:
            raise AppError(404, "训练任务不存在")
        return j
