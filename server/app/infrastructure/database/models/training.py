"""数据资产中心 + 模型训练 ORM 模型。

链路：数据资产 → 候选样本(candidate/approved) → 数据集版本 →
      训练任务（独立进程）→ 训练产出模型版本（adapter）。

注意：训练产出的模型版本表用 trained_model_versions，
避免与 system.py 的 model_versions（模型服务配置表）冲突。
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import (
    Base,
    IdMixin,
    TimestampMixin,
)


class DataAssetModel(Base, IdMixin, TimestampMixin):
    """数据资产：业务过程数据 / 历史公文 / 批量导入文件。"""

    __tablename__ = "data_assets"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    source_type: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # business / batch / excel / chat
    file_path: Mapped[Optional[str]] = mapped_column(String(500))
    file_type: Mapped[Optional[str]] = mapped_column(String(20))
    title: Mapped[Optional[str]] = mapped_column(String(300))
    doc_type: Mapped[Optional[str]] = mapped_column(String(50))
    content: Mapped[Optional[str]] = mapped_column(Text)
    char_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="active")
    sample_generated: Mapped[int] = mapped_column(Integer, default=0)
    extra: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)
    created_by: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id")
    )


class TrainingSampleModel(Base, IdMixin, TimestampMixin):
    """训练样本：candidate → review → approved。"""

    __tablename__ = "training_samples"

    instruction: Mapped[str] = mapped_column(Text, nullable=False)
    input: Mapped[Optional[str]] = mapped_column(Text, default="")
    output: Mapped[str] = mapped_column(Text, nullable=False)
    draft: Mapped[Optional[str]] = mapped_column(Text)
    source: Mapped[str] = mapped_column(
        String(20), default="candidate"
    )  # import / ai_generated / chat
    asset_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("data_assets.id")
    )
    session_id: Mapped[Optional[str]] = mapped_column(String(36))
    biz_type: Mapped[Optional[str]] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(
        String(20), default="candidate"
    )  # candidate / approved / rejected
    reviewed_by: Mapped[Optional[str]] = mapped_column(String(36))
    created_by: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id")
    )


class DatasetModel(Base, IdMixin, TimestampMixin):
    __tablename__ = "datasets"

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    created_by: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id")
    )


class DatasetVersionModel(Base, IdMixin, TimestampMixin):
    __tablename__ = "dataset_versions"

    dataset_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("datasets.id"), nullable=False
    )
    version: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="ready")
    stats: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)
    check_report: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)
    sample_ids: Mapped[Optional[list]] = mapped_column(JSON, default=list)
    train_jsonl: Mapped[Optional[str]] = mapped_column(String(500))
    val_jsonl: Mapped[Optional[str]] = mapped_column(String(500))
    created_by: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id")
    )


class TrainingJobModel(Base, IdMixin, TimestampMixin):
    __tablename__ = "training_jobs"

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    dataset_version_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("dataset_versions.id")
    )
    base_model: Mapped[Optional[str]] = mapped_column(String(200))
    method: Mapped[str] = mapped_column(String(20), default="lora")
    params: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(
        String(20), default="pending"
    )  # pending / running / succeeded / failed / canceled
    pid: Mapped[Optional[int]] = mapped_column(Integer)
    log_path: Mapped[Optional[str]] = mapped_column(String(500))
    output_dir: Mapped[Optional[str]] = mapped_column(String(500))
    resume_from: Mapped[Optional[str]] = mapped_column(String(500))
    train_loss: Mapped[Optional[float]] = mapped_column(Float)
    val_loss: Mapped[Optional[float]] = mapped_column(Float)
    error: Mapped[Optional[str]] = mapped_column(Text)
    model_version_id: Mapped[Optional[str]] = mapped_column(String(36))
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_by: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id")
    )


class ModelVersionModel(Base, IdMixin, TimestampMixin):
    """训练产出的模型版本（LoRA adapter）。

    与 system.py 的 model_versions（模型服务注册配置）不是一回事。
    """

    __tablename__ = "trained_model_versions"

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    base_model: Mapped[Optional[str]] = mapped_column(String(200))
    job_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("training_jobs.id")
    )
    parent_id: Mapped[Optional[str]] = mapped_column(String(36))
    status: Mapped[str] = mapped_column(
        String(20), default="Training"
    )  # Training / Ready / Failed
    adapter_path: Mapped[Optional[str]] = mapped_column(String(500))
    metrics: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)
