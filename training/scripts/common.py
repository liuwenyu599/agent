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


def reconcile_step_config(save_steps: int, eval_steps: int, n_samples: int,
                          batch_size: int, grad_accum: int, epochs: int):
    """把 save/eval 步数收敛到「一定会触发」的范围。

    为什么必须处理：配置里默认 500，但几百条样本下
    总步数 = ceil(N / (batch × accum)) × epochs，往往**不足 500**——
    于是全程一个 checkpoint 都不存、eval 一次都不跑，日志干干净净，
    跑完目录是空的，什么都看不出来。这不是报错失败，是**静默失效**，
    比崩掉难查得多。

    处理办法：超了就按「每 epoch 两次」重算，并明确打印出来，
    让人知道这个值被动过。
    """
    if n_samples <= 0:
        return save_steps, eval_steps
    per_epoch = max(1, n_samples // max(1, batch_size * grad_accum))
    total = per_epoch * max(1, epochs)
    result = []
    for name, value in (("save_steps", save_steps), ("eval_steps", eval_steps)):
        if value and value >= total:
            fixed = max(1, per_epoch // 2)
            what = "存档" if name == "save_steps" else "评估"
            print(f"[train] ⚠ {name}={value} 但全程只有 {total} 步"
                  f"（每 epoch {per_epoch} 步），照原值跑完不会有任何一次{what}。"
                  f"已自动收敛为 {fixed}。")
            result.append(fixed)
        else:
            result.append(value)
    print(f"[train] 每个 epoch {per_epoch} 步，共 {total} 步")
    return result[0], result[1]


def build_dataset(records: list[dict], tokenizer, max_length: int):
    """把 messages 转成带 prompt 掩码的训练数据集。

    原先 train_lora/qlora 各自写了一份 ``labels = input_ids`` 的版本，有两个问题：

    1. system 和 user 段一起进 loss。几百条样本时这点很伤：梯度摊到
       「学着复述检索资料和指令」上，真正想学的风格没学到多少，
       还顺带改了 prompt 段的分布。这里只让 assistant 段算 loss。
    2. 超长样本静默截断。公文的落款、成文日期、结尾（"特此报告"）
       都在文本末尾，截断削掉的恰好是最该学的那一段，所以这里剔除并告警。
    """
    from datasets import Dataset

    kept: list[dict] = []
    invalid = 0
    truncated = 0
    for raw in records:
        norm = normalize_sample(raw)
        if not norm:
            invalid += 1
            continue
        enc = tokenize_sample(tokenizer, norm, max_length)
        if enc["length"] >= max_length:
            truncated += 1
            continue
        kept.append({"input_ids": enc["input_ids"],
                     "labels": enc["labels"],
                     "attention_mask": enc["attention_mask"]})

    if invalid:
        print(f"[数据] 丢弃无效样本 {invalid} 条（缺 assistant 内容或 input/output 皆空）")
    if truncated:
        print(f"[数据] ⚠ 剔除超长样本 {truncated} 条：达到上限 {max_length}，"
              f"继续截断会削掉落款和结尾——那正是要学的部分。建议调大 --max-length。")
    if not kept:
        raise SystemExit("[数据] 没有可用样本，退出。")
    print(f"[数据] 有效样本 {len(kept)} 条，参与 loss 的只有 assistant 段")
    return Dataset.from_list(kept)


def split_train_val(records: List[Dict[str, Any]], val_ratio: float = 0.05,
                    seed: int = 42):
    rng = random.Random(seed)
    items = list(records)
    rng.shuffle(items)
    n_val = max(1, int(len(items) * val_ratio)) if len(items) > 1 else 0
    return items[n_val:], items[:n_val]
