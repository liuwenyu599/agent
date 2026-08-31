#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
训练数据预处理脚本
功能：读取 JSON/JSONL，校验数据，删除空样本，去重，统计，划分 train/validation，输出标准 JSONL。

支持格式：
  1. 标准 SFT: {"instruction":"...", "input":"...", "output":"..."}
  2. Qwen messages: {"messages":[{"role":"user","content":"..."},{"role":"assistant","content":"..."}]}
  3. 扩展 draft: {"instruction":"...", "input":"...", "draft":"...", "output":"..."}

用法：
  python training/scripts/prepare_dataset.py \
      --input training/data/raw/data.jsonl \
      --output-dir training/data/processed \
      --val-ratio 0.1 \
      --seed 42
"""

import argparse
import hashlib
import json
import os
import random
import sys
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="司法AI训练数据预处理")
    parser.add_argument("--input", required=True, help="输入 JSON/JSONL 文件路径")
    parser.add_argument("--output-dir", required=True, help="输出目录")
    parser.add_argument("--val-ratio", type=float, default=0.1, help="验证集比例 (默认 0.1)")
    parser.add_argument("--seed", type=int, default=42, help="随机种子")
    parser.add_argument("--max-length", type=int, default=8192, help="最大序列长度，用于统计")
    return parser.parse_args()


def load_records(path: str) -> list[dict[str, Any]]:
    """读取 JSON 或 JSONL 文件。"""
    records = []
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"输入文件不存在: {path}")

    with p.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                pass

    if not records:
        with p.open("r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                records = data
            elif isinstance(data, dict):
                records = [data]

    return records


def normalize_record(record: dict[str, Any]) -> dict[str, Any] | None:
    """将各种输入格式统一转换为标准 messages 格式。返回 None 表示无效样本。"""
    if not isinstance(record, dict):
        return None

    # 格式 2: Qwen messages 格式
    if "messages" in record and isinstance(record["messages"], list):
        msgs = record["messages"]
        if len(msgs) < 2:
            return None
        if msgs[-1].get("role") != "assistant":
            return None
        has_user = any(m.get("role") == "user" for m in msgs)
        if not has_user:
            return None
        return {"messages": msgs}

    # 格式 1 和 3: instruction/input/output(/draft)
    instruction = record.get("instruction", "")
    input_text = record.get("input", "")
    output_text = record.get("output", "")
    draft = record.get("draft", "")

    if not output_text or (not instruction and not input_text):
        return None

    user_content = instruction
    if input_text:
        user_content = (user_content + "\n\n" + input_text) if user_content else input_text

    if draft:
        user_content += f"\n\n【参考初稿】\n{draft}"

    messages = [
        {"role": "user", "content": user_content},
        {"role": "assistant", "content": output_text},
    ]
    return {"messages": messages}


def compute_hash(record: dict[str, Any]) -> str:
    content = json.dumps(record.get("messages", []), ensure_ascii=False, sort_keys=True)
    return hashlib.md5(content.encode("utf-8")).hexdigest()


def deduplicate(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    result = []
    for r in records:
        h = compute_hash(r)
        if h not in seen:
            seen.add(h)
            result.append(r)
    return result


def split_train_val(records: list[dict[str, Any]], val_ratio: float, seed: int):
    random.seed(seed)
    shuffled = records.copy()
    random.shuffle(shuffled)
    val_size = max(1, int(len(shuffled) * val_ratio)) if val_ratio > 0 else 0
    if val_size >= len(shuffled):
        val_size = max(1, len(shuffled) // 10)
    return shuffled[val_size:], shuffled[:val_size]


def compute_length_stats(records: list[dict[str, Any]], max_length: int) -> dict[str, Any]:
    lengths = []
    for r in records:
        msgs = r.get("messages", [])
        total_len = sum(len(m.get("content", "")) for m in msgs)
        lengths.append(total_len)

    if not lengths:
        return {"avg": 0, "max": 0, "min": 0, "over_max": 0}

    return {
        "avg": round(sum(lengths) / len(lengths), 1),
        "max": max(lengths),
        "min": min(lengths),
        "over_max": sum(1 for l in lengths if l > max_length),
    }


def save_jsonl(records: list[dict[str, Any]], path: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def main() -> int:
    args = parse_args()

    print(f"[prepare] 输入文件: {args.input}")
    print(f"[prepare] 输出目录: {args.output_dir}")
    print(f"[prepare] 验证集比例: {args.val_ratio}")
    print(f"[prepare] 随机种子: {args.seed}")
    print("-" * 50)

    raw_records = load_records(args.input)
    print(f"[prepare] 原始样本数: {len(raw_records)}")

    normalized = [nr for r in raw_records if (nr := normalize_record(r)) is not None]
    print(f"[prepare] 有效样本数: {len(normalized)} (丢弃 {len(raw_records) - len(normalized)})")

    deduped = deduplicate(normalized)
    print(f"[prepare] 去重后样本数: {len(deduped)} (重复 {len(normalized) - len(deduped)})")

    if not deduped:
        print("[prepare] 错误: 没有有效样本，退出。")
        return 1

    train_records, val_records = split_train_val(deduped, args.val_ratio, args.seed)
    print(f"[prepare] 训练集: {len(train_records)}, 验证集: {len(val_records)}")

    train_stats = compute_length_stats(train_records, args.max_length)
    val_stats = compute_length_stats(val_records, args.max_length)

    print(f"[prepare] 训练集长度 — 平均: {train_stats['avg']}, 最大: {train_stats['max']}, 最小: {train_stats['min']}, 超{args.max_length}: {train_stats['over_max']}")
    print(f"[prepare] 验证集长度 — 平均: {val_stats['avg']}, 最大: {val_stats['max']}, 最小: {val_stats['min']}, 超{args.max_length}: {val_stats['over_max']}")

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    train_path = output_dir / "train.jsonl"
    val_path = output_dir / "val.jsonl"

    save_jsonl(train_records, str(train_path))
    save_jsonl(val_records, str(val_path))

    print(f"[prepare] 已保存: {train_path}")
    print(f"[prepare] 已保存: {val_path}")
    print("[prepare] 完成。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
