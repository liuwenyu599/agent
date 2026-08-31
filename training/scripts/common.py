"""训练模块共享工具：数据格式解析、tokenize、配置加载。

支持数据格式：
1. {"instruction": "...", "input": "...", "output": "..."}
2. {"messages": [{"role": "user", ...}, {"role": "assistant", ...}]}
3. {"instruction": "...", "input": "...", "draft": "...", "output": "..."}
   （draft 为 AI 初稿，output 为人工修改最终稿）
"""
import json
import random
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


def load_config(path: Optional[str]) -> Dict[str, Any]:
    if not path:
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_json_or_jsonl(path: str) -> List[Dict[str, Any]]:
    """读取 JSON 数组或 JSONL。"""
    p = Path(path)
    text = p.read_text(encoding="utf-8").strip()
    if not text:
        return []
    if text.startswith("["):
        data = json.loads(text)
        return [d for d in data if isinstance(d, dict)]
    items = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        if isinstance(obj, dict):
            items.append(obj)
    return items


def _build_user_content(sample: Dict[str, Any]) -> str:
    instruction = (sample.get("instruction") or "").strip()
    input_text = (sample.get("input") or "").strip()
    draft = (sample.get("draft") or "").strip()
    parts = []
    if instruction:
        parts.append(instruction)
    if input_text:
        parts.append(input_text)
    if draft:
        parts.append(f"AI 初稿：\n{draft}")
    return "\n\n".join(parts)


def normalize_sample(sample: Dict[str, Any]) -> Optional[Dict[str, str]]:
    """统一转换为 {prompt_messages, response}。无效样本返回 None。"""
    if "messages" in sample and isinstance(sample["messages"], list):
        msgs = [m for m in sample["messages"]
                if isinstance(m, dict) and m.get("role") and m.get("content")]
        if len(msgs) < 2 or msgs[-1]["role"] != "assistant":
            return None
        return {"messages": msgs[:-1], "response": str(msgs[-1]["content"]).strip()}

    response = (sample.get("output") or "").strip()
    if not response:
        return None
    user_content = _build_user_content(sample)
    if not user_content:
        return None
    return {
        "messages": [{"role": "user", "content": user_content}],
        "response": response,
    }


def sample_key(sample: Dict[str, Any]) -> str:
    norm = normalize_sample(sample)
    if not norm:
        return ""
    msgs = norm["messages"]
    return json.dumps(msgs, ensure_ascii=False) + "||" + norm["response"]


def build_prompt_text(tokenizer: Any, messages: List[Dict[str, str]]) -> str:
    """构造 prompt 文本（含 generation prompt）。优先使用 tokenizer 自带 chat template。"""
    try:
        return tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
    except Exception:
        # 兜底：Qwen 风格模板
        text = ""
        for m in messages:
            text += f"<|im_start|>{m['role']}\n{m['content']}<|im_end|>\n"
        text += "<|im_start|>assistant\n"
        return text


def tokenize_sample(tokenizer: Any, norm: Dict[str, Any], max_length: int) -> Dict[str, Any]:
    prompt = build_prompt_text(tokenizer, norm["messages"])
    eos = tokenizer.eos_token or ""
    full_text = prompt + norm["response"] + eos
    prompt_ids = tokenizer(prompt, add_special_tokens=False)["input_ids"]
    full_ids = tokenizer(full_text, add_special_tokens=False,
                         truncation=True, max_length=max_length)["input_ids"]
    labels = list(full_ids)
    cutoff = min(len(prompt_ids), len(full_ids))
    for i in range(cutoff):
        labels[i] = -100
    return {
        "input_ids": full_ids,
        "labels": labels,
        "attention_mask": [1] * len(full_ids),
        "length": len(full_ids),
    }


class DataCollator:
    """按 batch 内最长长度 padding。"""

    def __init__(self, tokenizer: Any) -> None:
        self.pad_id = tokenizer.pad_token_id
        if self.pad_id is None:
            self.pad_id = tokenizer.eos_token_id or 0

    def __call__(self, features: List[Dict[str, Any]]) -> Dict[str, Any]:
        import torch
        max_len = max(len(f["input_ids"]) for f in features)
        input_ids, labels, attn = [], [], []
        for f in features:
            ids = f["input_ids"]
            lbs = f["labels"]
            pad = max_len - len(ids)
            input_ids.append(ids + [self.pad_id] * pad)
            labels.append(lbs + [-100] * pad)
            attn.append(f["attention_mask"] + [0] * pad)
        return {
            "input_ids": torch.tensor(input_ids, dtype=torch.long),
            "labels": torch.tensor(labels, dtype=torch.long),
            "attention_mask": torch.tensor(attn, dtype=torch.long),
        }


def prepare_records(input_path: str) -> List[Dict[str, str]]:
    """读取并规范化数据，去重、去空样本。"""
    raw = load_json_or_jsonl(input_path)
    seen = set()
    records = []
    for s in raw:
        key = sample_key(s)
        if not key or key in seen:
            continue
        seen.add(key)
        records.append(normalize_sample(s))
    return records


def split_train_val(records: List[Dict[str, Any]], val_ratio: float = 0.05,
                    seed: int = 42):
    rng = random.Random(seed)
    items = list(records)
    rng.shuffle(items)
    n_val = max(1, int(len(items) * val_ratio)) if len(items) > 1 else 0
    return items[n_val:], items[:n_val]
