#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
QLoRA 训练脚本（4-bit，适用于 7B/14B 显存受限场景）
使用 Transformers + PEFT + bitsandbytes，默认 4-bit NF4 量化。
支持从已有 Adapter 继续训练。

用法：
  python training/scripts/train_qlora.py \
      --model /home/lwy/Qwen2.5-14B-Instruct \
      --train-file training/data/processed/train.jsonl \
      --val-file training/data/processed/val.jsonl \
      --output-dir training/outputs/judicial-qlora \
      --epochs 3 \
      --batch-size 1 \
      --gradient-accumulation 8 \
      --learning-rate 1e-4 \
      --max-length 2048 \
      --lora-r 64 \
      --lora-alpha 16 \
      --lora-dropout 0.05
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

import torch
from datasets import Dataset
from peft import LoraConfig, PeftModel, get_peft_model, prepare_model_for_kbit_training
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    BitsAndBytesConfig,
    DataCollatorForSeq2Seq,
    Trainer,
    TrainingArguments,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="司法AI QLoRA 训练")
    parser.add_argument("--model", required=True, help="基础模型路径或 HuggingFace ID")
    parser.add_argument("--train-file", required=True, help="训练集 JSONL")
    parser.add_argument("--val-file", required=True, help="验证集 JSONL")
    parser.add_argument("--output-dir", required=True, help="输出目录")
    parser.add_argument("--adapter-path", default=None, help="已有 Adapter 路径（继续训练）")
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--gradient-accumulation", type=int, default=8)
    parser.add_argument("--learning-rate", type=float, default=1e-4)
    parser.add_argument("--warmup-ratio", type=float, default=0.03)
    parser.add_argument("--max-length", type=int, default=2048)
    parser.add_argument("--lora-r", type=int, default=64)
    parser.add_argument("--lora-alpha", type=int, default=16)
    parser.add_argument("--lora-dropout", type=float, default=0.05)
    parser.add_argument("--save-steps", type=int, default=500)
    parser.add_argument("--eval-steps", type=int, default=500)
    parser.add_argument("--logging-steps", type=int, default=10)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--resume-from-checkpoint", default=None, help="从 checkpoint 继续")
    # QLoRA 特有
    parser.add_argument("--bnb-4bit-compute-dtype", default="bfloat16", choices=["bfloat16", "float16", "float32"])
    parser.add_argument("--double-quant", action="store_true", default=True, help="嵌套量化")
    return parser.parse_args()


def load_jsonl(path: str) -> list[dict]:
    records = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def build_dataset(records: list[dict], tokenizer, max_length: int):
    def process(example):
        messages = example["messages"]
        text = tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=False,
        )
        model_inputs = tokenizer(
            text,
            max_length=max_length,
            truncation=True,
            padding=False,
        )
        model_inputs["labels"] = model_inputs["input_ids"].copy()
        return model_inputs

    ds = Dataset.from_list(records)
    ds = ds.map(process, remove_columns=ds.column_names, batched=False)
    return ds


def main() -> int:
    args = parse_args()
    start_time = time.time()

    print(f"[train_qlora] 基础模型: {args.model}")
    print(f"[train_qlora] 训练数据: {args.train_file}")
    print(f"[train_qlora] 验证数据: {args.val_file}")
    print(f"[train_qlora] 输出目录: {args.output_dir}")
    if args.adapter_path:
        print(f"[train_qlora] 继续训练从: {args.adapter_path}")
    print("-" * 50)

    # 1. Tokenizer
    tokenizer = AutoTokenizer.from_pretrained(
        args.model,
        trust_remote_code=True,
        pad_token="</s>",
    )
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    # 2. 4-bit 量化配置
    compute_dtype = getattr(torch, args.bnb_4bit_compute_dtype)
    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_use_double_quant=args.double_quant,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=compute_dtype,
    )

    print(f"[train_qlora] 加载 4-bit 量化模型，compute_dtype={compute_dtype} ...")
    model = AutoModelForCausalLM.from_pretrained(
        args.model,
        quantization_config=bnb_config,
        device_map="auto",
        trust_remote_code=True,
        torch_dtype=compute_dtype,
    )

    # 3. 准备模型用于 k-bit 训练
    model = prepare_model_for_kbit_training(model)

    # 4. 加载或创建 LoRA
    lora_config = LoraConfig(
        r=args.lora_r,
        lora_alpha=args.lora_alpha,
        lora_dropout=args.lora_dropout,
        bias="none",
        task_type="CAUSAL_LM",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
    )

    if args.adapter_path and Path(args.adapter_path).exists():
        print(f"[train_qlora] 加载已有 Adapter: {args.adapter_path}")
        model = PeftModel.from_pretrained(model, args.adapter_path, is_trainable=True)
    else:
        print(f"[train_qlora] 创建新 QLoRA (r={args.lora_r}, alpha={args.lora_alpha})")
        model = get_peft_model(model, lora_config)

    model.print_trainable_parameters()

    # 5. 数据
    print(f"[train_qlora] 加载数据集 ...")
    train_records = load_jsonl(args.train_file)
    val_records = load_jsonl(args.val_file)
    print(f"[train_qlora] 训练样本: {len(train_records)}, 验证样本: {len(val_records)}")

    train_ds = build_dataset(train_records, tokenizer, args.max_length)
    val_ds = build_dataset(val_records, tokenizer, args.max_length)

    # 6. 训练参数
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    training_args = TrainingArguments(
        output_dir=str(output_dir),
        num_train_epochs=args.epochs,
        per_device_train_batch_size=args.batch_size,
        per_device_eval_batch_size=args.batch_size,
        gradient_accumulation_steps=args.gradient_accumulation,
        learning_rate=args.learning_rate,
        warmup_ratio=args.warmup_ratio,
        logging_steps=args.logging_steps,
        save_steps=args.save_steps,
        eval_steps=args.eval_steps,
        evaluation_strategy="steps",
        save_strategy="steps",
        load_best_model_at_end=True,
        metric_for_best_model="eval_loss",
        greater_is_better=False,
        seed=args.seed,
        report_to=["tensorboard"],
        logging_dir=str(output_dir / "logs"),
        remove_unused_columns=False,
        dataloader_num_workers=2,
        lr_scheduler_type="cosine",
        optim="paged_adamw_8bit",  # QLoRA 推荐
        group_by_length=True,
    )

    data_collator = DataCollatorForSeq2Seq(
        tokenizer,
        model=model,
        label_pad_token_id=-100,
        pad_to_multiple_of=8,
    )

    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=train_ds,
        eval_dataset=val_ds,
        data_collator=data_collator,
    )

    # 7. 训练
    print("[train_qlora] 开始训练 ...")
    if args.resume_from_checkpoint:
        trainer.train(resume_from_checkpoint=args.resume_from_checkpoint)
    else:
        trainer.train()

    # 8. 保存
    adapter_dir = output_dir / "adapter"
    model.save_pretrained(str(adapter_dir))
    tokenizer.save_pretrained(str(adapter_dir))
    print(f"[train_qlora] Adapter 已保存: {adapter_dir}")

    # 9. 摘要
    train_history = trainer.state.log_history
    final_train_loss = None
    final_eval_loss = None
    for entry in reversed(train_history):
        if final_train_loss is None and "loss" in entry:
            final_train_loss = entry["loss"]
        if final_eval_loss is None and "eval_loss" in entry:
            final_eval_loss = entry["eval_loss"]
        if final_train_loss is not None and final_eval_loss is not None:
            break

    summary = {
        "base_model": args.model,
        "train_file": args.train_file,
        "val_file": args.val_file,
        "train_samples": len(train_records),
        "val_samples": len(val_records),
        "epochs": args.epochs,
        "batch_size": args.batch_size,
        "gradient_accumulation": args.gradient_accumulation,
        "learning_rate": args.learning_rate,
        "max_length": args.max_length,
        "lora_r": args.lora_r,
        "lora_alpha": args.lora_alpha,
        "lora_dropout": args.lora_dropout,
        "quantization": "4bit-nf4",
        "compute_dtype": args.bnb_4bit_compute_dtype,
        "training_time_sec": round(time.time() - start_time, 1),
        "final_train_loss": final_train_loss,
        "final_eval_loss": final_eval_loss,
        "adapter_dir": str(adapter_dir),
    }

    summary_path = output_dir / "training_summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"[train_qlora] 训练摘要: {summary_path}")
    print("[train_qlora] 完成。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
