#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
模型测试脚本：加载基础 Qwen + LoRA Adapter，输入测试公文需求并生成结果。
不修改现有 Chat API。

用法：
  python training/scripts/test_adapter.py \
      --model /home/lwy/Qwen2.5-7B-Instruct \
      --adapter training/outputs/judicial-lora/adapter \
      --prompt "起草一份关于加强社区矫正工作的通知"
"""

import argparse
import sys

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer


def parse_args():
    parser = argparse.ArgumentParser(description="司法AI Adapter 测试")
    parser.add_argument("--model", required=True, help="基础模型路径")
    parser.add_argument("--adapter", required=True, help="Adapter 路径")
    parser.add_argument("--prompt", required=True, help="测试提示词")
    parser.add_argument("--max-new-tokens", type=int, default=1024)
    parser.add_argument("--temperature", type=float, default=0.7)
    parser.add_argument("--top-p", type=float, default=0.9)
    parser.add_argument("--device", default="auto")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    print(f"[test] 基础模型: {args.model}")
    print(f"[test] Adapter: {args.adapter}")
    print(f"[test] 测试提示: {args.prompt[:60]}...")
    print("-" * 50)

    # 1. Tokenizer
    tokenizer = AutoTokenizer.from_pretrained(
        args.model, trust_remote_code=True, pad_token="</s>"
    )
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    # 2. 加载基础模型
    print("[test] 加载基础模型 ...")
    model = AutoModelForCausalLM.from_pretrained(
        args.model,
        torch_dtype=torch.bfloat16,
        device_map=args.device,
        trust_remote_code=True,
    )

    # 3. 加载 Adapter
    print("[test] 加载 Adapter ...")
    model = PeftModel.from_pretrained(model, args.adapter)
    model.eval()

    # 4. 构建 messages
    messages = [{"role": "user", "content": args.prompt}]
    text = tokenizer.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True
    )

    inputs = tokenizer(text, return_tensors="pt").to(model.device)

    # 5. 生成
    print("[test] 生成中 ...\n")
    with torch.no_grad():
        outputs = model.generate(
            **inputs,
            max_new_tokens=args.max_new_tokens,
            temperature=args.temperature,
            top_p=args.top_p,
            do_sample=True,
            eos_token_id=tokenizer.eos_token_id,
            pad_token_id=tokenizer.pad_token_id,
        )

    generated = tokenizer.decode(outputs[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True)
    print("=" * 50)
    print("生成结果:")
    print(generated)
    print("=" * 50)
    return 0


if __name__ == "__main__":
    sys.exit(main())