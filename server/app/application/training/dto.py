"""数据资产中心 / 模型训练 —— 请求 DTO。"""
from typing import Optional

from pydantic import BaseModel, Field


class ImportDirRequest(BaseModel):
    """批量导入历史成熟公文：直接指定外部目录，不复制原始文件。"""
    path: str = Field(..., description="外部目录，如 /data/judicial_documents")
    source_type: str = "historical"
    recursive: bool = True


class SampleEditRequest(BaseModel):
    instruction: Optional[str] = None
    input: Optional[str] = None
    output: Optional[str] = None
    draft: Optional[str] = None
    biz_type: Optional[str] = None


class SampleFromChatRequest(BaseModel):
    """从 Chat 对话「加入训练集」：用户真实需求 + AI 初稿 + 人工最终稿。"""
    session_id: str
    instruction: str                 # 用户真实请求
    draft: str = ""                  # AI 初稿
    output: str                      # 人工修改后的最终稿
    biz_type: str = ""


class DatasetCreateRequest(BaseModel):
    name: str
    description: str = ""


class DatasetVersionCreateRequest(BaseModel):
    version: str = "v1.0"
    val_ratio: float = 0.05


class JobCreateRequest(BaseModel):
    """创建训练任务。普通用户只需前 4 项，高级配置可选。"""
    name: str
    dataset_version_id: str
    base_model: str                  # 本地基础模型路径，如 /home/lwy/Qwen2.5-7B-Instruct
    method: str = "qlora"            # lora / qlora
    model_version_name: str = ""     # 训练完成后的模型版本名，如 Judicial-Qwen-7B v1.0
    parent_model_version_id: str = ""  # 从已有版本继续训练（可选）
    # ===== 高级配置（技术人员）=====
    epochs: int = 3
    batch_size: int = 1
    gradient_accumulation: int = 8
    learning_rate: float = 2.0e-4
    max_length: int = 2048
    lora_r: int = 64
    lora_alpha: int = 128
    lora_dropout: float = 0.05
