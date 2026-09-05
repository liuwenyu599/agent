import os
import json
import torch

from pathlib import Path
from transformers import AutoTokenizer, AutoModelForCausalLM
from peft import PeftModel


BASE_MODEL = Path("/home/lwy/Qwen2.5-14B-Instruct")
ADAPTER = Path(
    "/home/lwy/Policy_crawler/"
    "sft_v1/checkpoints/real_sft_v1_qlora_full"
)

PROMPTS = Path(
    "/home/lwy/Policy_crawler/"
    "sft_v1/evaluation/test_prompts.json"
)

OUTPUT = Path(
    "/home/lwy/Policy_crawler/"
    "sft_v1/evaluation/results_base_vs_v1.jsonl"
)


MAX_NEW_TOKENS = 4096


def load_model():
    tokenizer = AutoTokenizer.from_pretrained(
        BASE_MODEL,
        trust_remote_code=True
    )

    model = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL,
        torch_dtype=torch.bfloat16,
        device_map="auto",
        trust_remote_code=True
    )

    return tokenizer, model


def generate(model, tokenizer, prompt):
    messages = [
        {
            "role": "user",
            "content": prompt
        }
    ]

    text = tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=True
    )

    inputs = tokenizer(
        text,
        return_tensors="pt"
    ).to(model.device)

    with torch.no_grad():
        outputs = model.generate(
            **inputs,
            max_new_tokens=MAX_NEW_TOKENS,
            do_sample=False,
            temperature=None,
            top_p=None,
            repetition_penalty=1.05
        )

    generated = outputs[0][inputs["input_ids"].shape[1]:]

    return tokenizer.decode(
        generated,
        skip_special_tokens=True
    )


def main():

    prompts = json.loads(
        PROMPTS.read_text(encoding="utf-8")
    )

    OUTPUT.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    print("=" * 70)
    print("Loading Base Qwen2.5-14B-Instruct")
    print("=" * 70)

    tokenizer, base_model = load_model()

    print("Base model loaded.")

    print("=" * 70)
    print("Generating Base results")
    print("=" * 70)

    base_results = {}

    for item in prompts:
        print(f"[Base] {item['id']}")

        result = generate(
            base_model,
            tokenizer,
            item["prompt"]
        )

        base_results[item["id"]] = result

    del base_model
    torch.cuda.empty_cache()

    print("=" * 70)
    print("Loading V1 LoRA")
    print("=" * 70)

    _, base_model = load_model()

    v1_model = PeftModel.from_pretrained(
        base_model,
        ADAPTER,
        is_trainable=False
    )

    v1_model.eval()

    print("V1 LoRA loaded.")

    with OUTPUT.open(
        "w",
        encoding="utf-8"
    ) as f:

        for item in prompts:

            print(f"[V1] {item['id']}")

            v1_result = generate(
                v1_model,
                tokenizer,
                item["prompt"]
            )

            record = {
                "id": item["id"],
                "category": item["category"],
                "prompt": item["prompt"],
                "base": base_results[item["id"]],
                "v1": v1_result
            }

            f.write(
                json.dumps(
                    record,
                    ensure_ascii=False
                ) + "\n"
            )

    print()
    print("=" * 70)
    print("DONE")
    print("=" * 70)
    print(f"Output: {OUTPUT}")


if __name__ == "__main__":
    main()
