#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
============================================================
Qwen2.5-14B-Instruct
广东省政策公文 Real SFT V1
============================================================

目标：
    使用 2951 条真实广东省政策公文，
    对 Qwen2.5-14B-Instruct 进行 LoRA 领域适配。

数据：
    train:
        /home/lwy/Policy_crawler/sft_v1/train/train_real.jsonl
        2656 条

    validation:
        /home/lwy/Policy_crawler/sft_v1/val/val_real.jsonl
        295 条

当前 V1：
    只使用 real_sft
    不使用 synthetic dialogue

环境：
    PyTorch 2.5.1+cu124
    Transformers 4.57.6
    PEFT 0.20.0
    TRL 1.12.0

训练：
    --test
        10 条训练数据，用于冒烟测试

    --full
        完整 2656 条训练

============================================================
"""

import os

# ============================================================
# RTX 4090 多卡 NCCL 设置
#
# RTX 4000 系列在当前环境下不支持 NCCL P2P / IB，
# 必须关闭，否则多卡初始化会报错。
#
# 必须放在 import torch 之前。
# ============================================================

os.environ["NCCL_P2P_DISABLE"] = "1"
os.environ["NCCL_IB_DISABLE"] = "1"

# 避免 tokenizer 多进程相关警告
os.environ["TOKENIZERS_PARALLELISM"] = "false"


import json
import argparse
from pathlib import Path

import torch

from datasets import load_dataset

from transformers import (
    AutoTokenizer,
    AutoModelForCausalLM,
)

from peft import LoraConfig

from trl import (
    SFTTrainer,
    SFTConfig,
)


# ============================================================
# 1. 项目路径
# ============================================================

PROJECT_ROOT = Path(
    "/home/lwy/Policy_crawler"
)

# MODEL_PATH = Path(
#     "/home/lwy/Qwen2.5-14B-Instruct"
# )

MODEL_PATH = Path(
    "/home/lwy/Qwen2.5-14B-Instruct"
)
TRAIN_FILE = (
    PROJECT_ROOT
    / "sft_v1/train/train_real.jsonl"
)

VAL_FILE = (
    PROJECT_ROOT
    / "sft_v1/val/val_real.jsonl"
)

OUTPUT_ROOT = (
    PROJECT_ROOT
    / "sft_v1/checkpoints"
)


# ============================================================
# 2. 训练超参数
# ============================================================

MAX_SEQ_LENGTH = 8192

# LoRA
LORA_R = 16
LORA_ALPHA = 32
LORA_DROPOUT = 0.05

TARGET_MODULES = [
    "q_proj",
    "k_proj",
    "v_proj",
    "o_proj",
    "gate_proj",
    "up_proj",
    "down_proj",
]

# 默认训练参数
DEFAULT_EPOCHS = 1.0
DEFAULT_LR = 2e-4

# 每张 GPU
PER_DEVICE_TRAIN_BATCH_SIZE = 1
PER_DEVICE_EVAL_BATCH_SIZE = 1

# 有效 batch size：
#
# 2 GPU × batch 1 × accumulation 8
#
# 如果 DDP 正常工作：
#
# global batch = 2 × 1 × 8 = 16
#
GRADIENT_ACCUMULATION_STEPS = 8


# ============================================================
# 3. 参数
# ============================================================

def parse_args():

    parser = argparse.ArgumentParser(
        description=(
            "Qwen2.5-14B 广东政策公文 Real SFT V1"
        )
    )

    group = parser.add_mutually_exclusive_group(
        required=True
    )

    group.add_argument(
        "--test",
        action="store_true",
        help=(
            "冒烟测试：只使用10条训练数据"
        ),
    )

    group.add_argument(
        "--full",
        action="store_true",
        help=(
            "正式训练：使用完整2656条训练数据"
        ),
    )

    parser.add_argument(
        "--epochs",
        type=float,
        default=DEFAULT_EPOCHS,
        help=(
            f"训练 epoch，默认 {DEFAULT_EPOCHS}"
        ),
    )

    parser.add_argument(
        "--lr",
        type=float,
        default=DEFAULT_LR,
        help=(
            f"学习率，默认 {DEFAULT_LR}"
        ),
    )

    return parser.parse_args()


# ============================================================
# 4. 打印 GPU 信息
# ============================================================

def check_environment():

    print()
    print("=" * 70)
    print("环境检查")
    print("=" * 70)

    print(
        "PyTorch:",
        torch.__version__
    )

    print(
        "CUDA available:",
        torch.cuda.is_available()
    )

    print(
        "CUDA version:",
        torch.version.cuda
    )

    gpu_count = torch.cuda.device_count()

    print(
        "GPU count:",
        gpu_count
    )

    if not torch.cuda.is_available():
        raise RuntimeError(
            "CUDA 不可用，停止训练。"
        )

    if gpu_count < 1:
        raise RuntimeError(
            "没有检测到 GPU。"
        )

    for i in range(gpu_count):

        name = torch.cuda.get_device_name(i)

        props = torch.cuda.get_device_properties(i)

        memory_gb = (
            props.total_memory
            / 1024**3
        )

        print(
            f"GPU {i}: "
            f"{name} | "
            f"{memory_gb:.2f} GB"
        )

    print()

    print(
        "NCCL_P2P_DISABLE:",
        os.environ.get(
            "NCCL_P2P_DISABLE"
        )
    )

    print(
        "NCCL_IB_DISABLE:",
        os.environ.get(
            "NCCL_IB_DISABLE"
        )
    )

    print()


# ============================================================
# 5. 文件检查
# ============================================================

def check_files():

    print()
    print("=" * 70)
    print("文件检查")
    print("=" * 70)

    paths = [
        ("模型", MODEL_PATH),
        ("训练集", TRAIN_FILE),
        ("验证集", VAL_FILE),
    ]

    for name, path in paths:

        exists = path.exists()

        print(
            f"{name}: "
            f"{path} "
            f"[{'OK' if exists else 'NOT FOUND'}]"
        )

        if not exists:

            raise FileNotFoundError(
                f"{name}不存在：{path}"
            )

    print()


# ============================================================
# 6. JSONL 数据完整性检查
# ============================================================

def inspect_jsonl(
    path: Path,
    name: str,
):

    print(
        f"检查 {name}: {path}"
    )

    count = 0

    source_uids = set()

    duplicate_uid = 0

    with open(
        path,
        "r",
        encoding="utf-8",
    ) as f:

        for line_no, line in enumerate(
            f,
            start=1,
        ):

            line = line.strip()

            if not line:
                continue

            try:

                obj = json.loads(line)

            except json.JSONDecodeError as e:

                raise ValueError(
                    f"{name} 第 {line_no} 行 "
                    f"JSON 错误：{e}"
                )

            # ------------------------------------------------
            # messages
            # ------------------------------------------------

            if "messages" not in obj:

                raise ValueError(
                    f"{name} 第 {line_no} 条 "
                    f"缺少 messages"
                )

            messages = obj["messages"]

            if not isinstance(
                messages,
                list,
            ):

                raise ValueError(
                    f"{name} 第 {line_no} 条 "
                    f"messages 不是 list"
                )

            if len(messages) < 2:

                raise ValueError(
                    f"{name} 第 {line_no} 条 "
                    f"messages 少于2条"
                )

            roles = []

            for message in messages:

                if not isinstance(
                    message,
                    dict,
                ):

                    raise ValueError(
                        f"{name} 第 {line_no} 条 "
                        f"message 不是 dict"
                    )

                role = message.get(
                    "role"
                )

                content = message.get(
                    "content"
                )

                if role is None:

                    raise ValueError(
                        f"{name} 第 {line_no} 条 "
                        f"message 缺少 role"
                    )

                if content is None:

                    raise ValueError(
                        f"{name} 第 {line_no} 条 "
                        f"message 缺少 content"
                    )

                if not isinstance(
                    content,
                    str,
                ):

                    raise ValueError(
                        f"{name} 第 {line_no} 条 "
                        f"content 不是字符串"
                    )

                if not content.strip():

                    raise ValueError(
                        f"{name} 第 {line_no} 条 "
                        f"content 为空"
                    )

                roles.append(role)

            if "user" not in roles:

                raise ValueError(
                    f"{name} 第 {line_no} 条 "
                    f"没有 user"
                )

            if "assistant" not in roles:

                raise ValueError(
                    f"{name} 第 {line_no} 条 "
                    f"没有 assistant"
                )

            # ------------------------------------------------
            # metadata
            # ------------------------------------------------

            metadata = obj.get(
                "metadata",
                {}
            )

            if isinstance(
                metadata,
                dict,
            ):

                uid = metadata.get(
                    "source_UID"
                )

                if uid:

                    if uid in source_uids:

                        duplicate_uid += 1

                    source_uids.add(uid)

            count += 1

    print(
        f"{name}: {count} 条"
    )

    print(
        f"{name}: UID {len(source_uids)} 个"
    )

    print(
        f"{name}: 重复 UID {duplicate_uid} 个"
    )

    if duplicate_uid > 0:

        raise ValueError(
            f"{name} 存在重复 UID。"
        )

    print()

    return count


# ============================================================
# 7. 创建 test10 数据
# ============================================================

def create_test_dataset():

    test_file = (
        PROJECT_ROOT
        / "sft_v1/train/train_real_test10.jsonl"
    )

    print(
        "创建测试数据：",
        test_file
    )

    lines = []

    with open(
        TRAIN_FILE,
        "r",
        encoding="utf-8",
    ) as f:

        for line in f:

            if not line.strip():
                continue

            lines.append(line)

            if len(lines) >= 10:
                break

    if len(lines) != 10:

        raise RuntimeError(
            f"无法获取10条训练数据，"
            f"实际只有 {len(lines)} 条。"
        )

    with open(
        test_file,
        "w",
        encoding="utf-8",
    ) as f:

        f.writelines(lines)

    print(
        "测试数据创建完成：10 条"
    )

    print()

    return test_file


# ============================================================
# 8. 加载 Dataset
# ============================================================

def load_data(
    test_mode: bool
):

    train_path = TRAIN_FILE

    if test_mode:

        train_path = create_test_dataset()

    print("=" * 70)
    print("加载 Dataset")
    print("=" * 70)

    print(
        "train:",
        train_path
    )

    print(
        "validation:",
        VAL_FILE
    )

    dataset = load_dataset(
        "json",
        data_files={
            "train": str(train_path),
            "validation": str(VAL_FILE),
        },
    )

    print()

    print(dataset)

    print()

    print(
        "train samples:",
        len(dataset["train"])
    )

    print(
        "validation samples:",
        len(dataset["validation"])
    )

    print()

    return dataset


# ============================================================
# 9. 加载 Tokenizer
# ============================================================

def load_tokenizer():

    print("=" * 70)
    print("加载 Tokenizer")
    print("=" * 70)

    tokenizer = AutoTokenizer.from_pretrained(
        str(MODEL_PATH),
        trust_remote_code=True,
        use_fast=True,
    )

    if tokenizer.pad_token is None:

        tokenizer.pad_token = (
            tokenizer.eos_token
        )

    print(
        "Tokenizer loaded"
    )

    print(
        "pad_token:",
        repr(tokenizer.pad_token)
    )

    print(
        "eos_token:",
        repr(tokenizer.eos_token)
    )

    print(
        "pad_token_id:",
        tokenizer.pad_token_id
    )

    print(
        "eos_token_id:",
        tokenizer.eos_token_id
    )

    print()

    return tokenizer


# ============================================================
# 10. 加载模型
# ============================================================

def load_model():

    print("=" * 70)
    print("加载 Qwen2.5-14B-Instruct")
    print("=" * 70)

    print(
        "Model path:",
        MODEL_PATH
    )

    print(
        "dtype: bfloat16"
    )

    model = AutoModelForCausalLM.from_pretrained(
        str(MODEL_PATH),

        torch_dtype=torch.bfloat16,

        trust_remote_code=True,

        low_cpu_mem_usage=True,

        # 这里不指定 device_map。
        #
        # 如果通过 accelerate launch 多卡启动，
        # Accelerate/DDP 会负责每个进程的 GPU。
        #
        # 如果直接 python 单进程启动，
        # 模型会进入当前设备。
        device_map=None,
    )

    # --------------------------------------------------------
    # Qwen 训练时关闭 cache
    # --------------------------------------------------------

    model.config.use_cache = False

    # 某些模型可能有 generation_config
    if hasattr(
        model,
        "generation_config",
    ):

        model.generation_config.use_cache = False

    print(
        "Model loaded."
    )

    print()

    return model


# ============================================================
# 11. LoRA 配置
# ============================================================

def create_lora_config():

    print("=" * 70)
    print("LoRA 配置")
    print("=" * 70)

    print(
        "r:",
        LORA_R
    )

    print(
        "alpha:",
        LORA_ALPHA
    )

    print(
        "dropout:",
        LORA_DROPOUT
    )

    print(
        "target_modules:",
        ", ".join(TARGET_MODULES)
    )

    peft_config = LoraConfig(
        r=LORA_R,

        lora_alpha=LORA_ALPHA,

        lora_dropout=LORA_DROPOUT,

        bias="none",

        task_type="CAUSAL_LM",

        target_modules=TARGET_MODULES,
    )

    print()

    return peft_config


# ============================================================
# 12. 创建 Training Config
# ============================================================

def create_training_config(
    args,
    output_dir,
):

    print("=" * 70)
    print("Training Config")
    print("=" * 70)

    # test 模式每10 step保存/评估
    #
    # full 模式每100 step评估，
    # 每200 step保存。
    #
    if args.test:

        eval_steps = 10
        save_steps = 10

    else:

        eval_steps = 100
        save_steps = 200

    training_args = SFTConfig(

        # ----------------------------------------------------
        # 输出
        # ----------------------------------------------------

        output_dir=str(
            output_dir
        ),

        # ----------------------------------------------------
        # epoch
        # ----------------------------------------------------

        num_train_epochs=args.epochs,

        # ----------------------------------------------------
        # batch
        # ----------------------------------------------------

        per_device_train_batch_size=(
            PER_DEVICE_TRAIN_BATCH_SIZE
        ),

        per_device_eval_batch_size=(
            PER_DEVICE_EVAL_BATCH_SIZE
        ),

        gradient_accumulation_steps=(
            GRADIENT_ACCUMULATION_STEPS
        ),

        # ----------------------------------------------------
        # learning rate
        # ----------------------------------------------------

        learning_rate=args.lr,

        lr_scheduler_type="cosine",

        warmup_ratio=0.05,

        # ----------------------------------------------------
        # sequence length
        #
        # TRL 1.12.0：
        # max_length 在 SFTConfig 中设置。
        # ----------------------------------------------------

        max_length=MAX_SEQ_LENGTH,

        # ----------------------------------------------------
        # precision
        # ----------------------------------------------------

        bf16=True,

        fp16=False,

        # ----------------------------------------------------
        # gradient checkpointing
        # ----------------------------------------------------

        gradient_checkpointing=True,

        gradient_checkpointing_kwargs={
            "use_reentrant": False
        },

        # ----------------------------------------------------
        # optimizer
        # ----------------------------------------------------

        optim="adamw_torch_fused",

        weight_decay=0.01,

        # ----------------------------------------------------
        # logging
        # ----------------------------------------------------

        logging_strategy="steps",

        logging_steps=1,

        logging_first_step=True,

        # ----------------------------------------------------
        # evaluation
        # ----------------------------------------------------

        eval_strategy="steps",

        eval_steps=eval_steps,

        # ----------------------------------------------------
        # checkpoint
        # ----------------------------------------------------

        save_strategy="steps",

        save_steps=save_steps,

        save_total_limit=2,

        # ----------------------------------------------------
        # misc
        # ----------------------------------------------------

        report_to="none",

        remove_unused_columns=False,

        ddp_find_unused_parameters=False,

        # ----------------------------------------------------
        # reproducibility
        # ----------------------------------------------------

        seed=42,

        data_seed=42,

        # ----------------------------------------------------
        # dataloader
        # ----------------------------------------------------

        dataloader_num_workers=2,

        # ----------------------------------------------------
        # logging / saving
        # ----------------------------------------------------

        logging_nan_inf_filter=True,

        # ----------------------------------------------------
        # 不把模型输出保存成 safetensors 之外的额外东西
        # ----------------------------------------------------

        save_safetensors=True,
    )

    print(
        "output_dir:",
        output_dir
    )

    print(
        "epochs:",
        args.epochs
    )

    print(
        "learning_rate:",
        args.lr
    )

    print(
        "max_length:",
        MAX_SEQ_LENGTH
    )

    print(
        "per_device_train_batch_size:",
        PER_DEVICE_TRAIN_BATCH_SIZE
    )

    print(
        "gradient_accumulation_steps:",
        GRADIENT_ACCUMULATION_STEPS
    )

    print(
        "eval_steps:",
        eval_steps
    )

    print(
        "save_steps:",
        save_steps
    )

    print()

    return training_args


# ============================================================
# 13. 打印 GPU 显存
# ============================================================

def print_gpu_memory(
    title="GPU Memory"
):

    print("=" * 70)
    print(title)
    print("=" * 70)

    for i in range(
        torch.cuda.device_count()
    ):

        allocated = (
            torch.cuda.memory_allocated(i)
            / 1024**3
        )

        reserved = (
            torch.cuda.memory_reserved(i)
            / 1024**3
        )

        print(
            f"GPU {i}: "
            f"allocated={allocated:.2f} GB | "
            f"reserved={reserved:.2f} GB"
        )

    print()


# ============================================================
# 14. 创建 Trainer
# ============================================================

def create_trainer(
    model,
    tokenizer,
    dataset,
    peft_config,
    training_args,
):

    print("=" * 70)
    print("创建 SFTTrainer")
    print("=" * 70)

    trainer = SFTTrainer(

        model=model,

        args=training_args,

        train_dataset=dataset["train"],

        eval_dataset=dataset["validation"],

        processing_class=tokenizer,

        peft_config=peft_config,
    )

    print(
        "SFTTrainer 创建成功."
    )

    print()

    return trainer


# ============================================================
# 15. 保存训练配置
# ============================================================

def save_training_info(
    output_dir,
    args,
    train_count,
    val_count,
):

    info = {

        "model": str(
            MODEL_PATH
        ),

        "train_file": str(
            TRAIN_FILE
        ),

        "val_file": str(
            VAL_FILE
        ),

        "train_count": train_count,

        "val_count": val_count,

        "mode": (
            "test"
            if args.test
            else "full"
        ),

        "epochs": args.epochs,

        "learning_rate": args.lr,

        "max_seq_length": MAX_SEQ_LENGTH,

        "per_device_train_batch_size": (
            PER_DEVICE_TRAIN_BATCH_SIZE
        ),

        "per_device_eval_batch_size": (
            PER_DEVICE_EVAL_BATCH_SIZE
        ),

        "gradient_accumulation_steps": (
            GRADIENT_ACCUMULATION_STEPS
        ),

        "lora": {

            "r": LORA_R,

            "alpha": LORA_ALPHA,

            "dropout": LORA_DROPOUT,

            "target_modules": TARGET_MODULES,
        },

        "environment": {

            "pytorch": torch.__version__,

            "cuda": torch.version.cuda,

            "gpu_count": (
                torch.cuda.device_count()
            ),

            "nccl_p2p_disable": (
                os.environ.get(
                    "NCCL_P2P_DISABLE"
                )
            ),

            "nccl_ib_disable": (
                os.environ.get(
                    "NCCL_IB_DISABLE"
                ),
            ),
        },
    }

    info_file = (
        output_dir
        / "training_config.json"
    )

    with open(
        info_file,
        "w",
        encoding="utf-8",
    ) as f:

        json.dump(
            info,
            f,
            ensure_ascii=False,
            indent=2,
        )

    print(
        "训练配置已保存：",
        info_file
    )

    print()


# ============================================================
# 16. 主程序
# ============================================================

def main():

    args = parse_args()

    # --------------------------------------------------------
    # 环境
    # --------------------------------------------------------

    check_environment()

    # --------------------------------------------------------
    # 文件
    # --------------------------------------------------------

    check_files()

    # --------------------------------------------------------
    # 检查数据
    # --------------------------------------------------------

    train_count = inspect_jsonl(
        TRAIN_FILE,
        "train",
    )

    val_count = inspect_jsonl(
        VAL_FILE,
        "validation",
    )

    # --------------------------------------------------------
    # 输出目录
    # --------------------------------------------------------

    mode = (
        "test"
        if args.test
        else "full"
    )

    output_dir = (
        OUTPUT_ROOT
        / f"real_sft_v1_{mode}"
    )

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    # --------------------------------------------------------
    # 打印总配置
    # --------------------------------------------------------

    print()
    print("=" * 70)
    print("广东政策公文 Real SFT V1")
    print("=" * 70)

    print(
        "Mode:",
        mode
    )

    print(
        "Model:",
        MODEL_PATH
    )

    print(
        "Train:",
        TRAIN_FILE,
        f"({train_count})"
    )

    print(
        "Validation:",
        VAL_FILE,
        f"({val_count})"
    )

    print(
        "Output:",
        output_dir
    )

    print(
        "Max sequence length:",
        MAX_SEQ_LENGTH
    )

    print(
        "LoRA:",
        f"r={LORA_R}, "
        f"alpha={LORA_ALPHA}, "
        f"dropout={LORA_DROPOUT}"
    )

    print(
        "Epochs:",
        args.epochs
    )

    print(
        "Learning rate:",
        args.lr
    )

    print()

    # --------------------------------------------------------
    # Dataset
    # --------------------------------------------------------

    dataset = load_data(
        test_mode=args.test
    )

    # test 模式实际训练数量
    actual_train_count = len(
        dataset["train"]
    )

    actual_val_count = len(
        dataset["validation"]
    )

    # --------------------------------------------------------
    # Tokenizer
    # --------------------------------------------------------

    tokenizer = load_tokenizer()

    # --------------------------------------------------------
    # Model
    # --------------------------------------------------------

    model = load_model()

    print_gpu_memory(
        "模型加载后 GPU 显存"
    )

    # --------------------------------------------------------
    # LoRA
    # --------------------------------------------------------

    peft_config = create_lora_config()

    # --------------------------------------------------------
    # Training Config
    # --------------------------------------------------------

    training_args = create_training_config(
        args,
        output_dir,
    )

    # --------------------------------------------------------
    # 保存配置
    # --------------------------------------------------------

    save_training_info(
        output_dir,
        args,
        actual_train_count,
        actual_val_count,
    )

    # --------------------------------------------------------
    # Trainer
    # --------------------------------------------------------

    trainer = create_trainer(
        model,
        tokenizer,
        dataset,
        peft_config,
        training_args,
    )

    print_gpu_memory(
        "Trainer 创建后 GPU 显存"
    )

    # --------------------------------------------------------
    # 开始训练
    # --------------------------------------------------------

    print("=" * 70)
    print("开始训练")
    print("=" * 70)

    print()

    train_result = trainer.train()

    # --------------------------------------------------------
    # 保存模型
    # --------------------------------------------------------

    print()
    print("=" * 70)
    print("保存 LoRA Adapter")
    print("=" * 70)

    trainer.save_model(
        str(output_dir)
    )

    tokenizer.save_pretrained(
        str(output_dir)
    )

    # --------------------------------------------------------
    # 保存训练指标
    # --------------------------------------------------------

    train_metrics = (
        train_result.metrics
    )

    train_metrics_file = (
        output_dir
        / "train_metrics.json"
    )

    with open(
        train_metrics_file,
        "w",
        encoding="utf-8",
    ) as f:

        json.dump(
            train_metrics,
            f,
            ensure_ascii=False,
            indent=2,
        )

    print(
        "训练指标：",
        train_metrics
    )

    print(
        "训练指标文件：",
        train_metrics_file
    )

    # --------------------------------------------------------
    # 最终验证
    # --------------------------------------------------------

    print()
    print("=" * 70)
    print("最终验证集评估")
    print("=" * 70)

    eval_metrics = trainer.evaluate()

    print(
        json.dumps(
            eval_metrics,
            ensure_ascii=False,
            indent=2,
        )
    )

    eval_metrics_file = (
        output_dir
        / "eval_metrics.json"
    )

    with open(
        eval_metrics_file,
        "w",
        encoding="utf-8",
    ) as f:

        json.dump(
            eval_metrics,
            f,
            ensure_ascii=False,
            indent=2,
        )

    # --------------------------------------------------------
    # 最终 GPU
    # --------------------------------------------------------

    print_gpu_memory(
        "训练完成 GPU 显存"
    )

    # --------------------------------------------------------
    # 完成
    # --------------------------------------------------------

    print("=" * 70)
    print("训练完成")
    print("=" * 70)

    print(
        "LoRA Adapter:",
        output_dir
    )

    print(
        "Train metrics:",
        train_metrics_file
    )

    print(
        "Eval metrics:",
        eval_metrics_file
    )

    print()


# ============================================================
# Entry
# ============================================================

if __name__ == "__main__":

    main()