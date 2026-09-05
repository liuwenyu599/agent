import os
import re
import json
import math
import gc
from pathlib import Path
from collections import Counter

import torch
from transformers import AutoTokenizer, AutoModelForCausalLM
from peft import PeftModel

# ============================================================
# 路径
# ============================================================
ROOT = Path("/home/lwy/Policy_crawler")
BASE_MODEL = Path("/home/lwy/Qwen2.5-14B-Instruct")
ADAPTER = ROOT / "sft_v1/checkpoints/real_sft_v1_qlora_full"
TRAIN_FILE = ROOT / "sft_v1/train/train_real.jsonl"
OLD_RESULTS = ROOT / "sft_v1/evaluation/results_base_vs_v1.jsonl"
OUTPUT_DIR = ROOT / "sft_v1/evaluation/generalization"
OUTPUT_RESULTS = OUTPUT_DIR / "results_t01_t15.jsonl"
OUTPUT_REPORT = OUTPUT_DIR / "similarity_report.txt"

# ============================================================
# 生成参数
# ============================================================
MAX_NEW_TOKENS = 4096
DO_SAMPLE = False  # 确定性生成，保证公平

# ============================================================
# T11-T15：全新主题
# ============================================================
NEW_TESTS = [
    {
        "id": "T11",
        "category": "人工智能治理",
        "prompt": (
            "请起草一份广东省人民政府办公厅关于规范政府部门"
            "人工智能生成内容使用管理的通知。\n"
            "要求：\n"
            "1. 明确适用范围；\n"
            "2. 规范人工智能生成内容审核；\n"
            "3. 涉及敏感信息时加强安全管理；\n"
            "4. 建立人工复核机制；\n"
            "5. 明确相关责任。"
        )
    },
    {
        "id": "T12",
        "category": "行政执法数据",
        "prompt": (
            "请起草一份关于加强行政执法数据质量管理的实施方案。\n"
            "要求：\n"
            "1. 建立数据采集标准；\n"
            "2. 统一数据口径；\n"
            "3. 加强数据审核；\n"
            "4. 推动部门之间的数据共享；\n"
            "5. 建立监督检查机制。"
        )
    },
    {
        "id": "T13",
        "category": "基层公共法律服务",
        "prompt": (
            "请起草一份关于推进基层公共法律服务数字化建设的工作方案。\n"
            "要求：\n"
            "1. 明确建设目标；\n"
            "2. 完善线上服务；\n"
            "3. 加强基层服务站点建设；\n"
            "4. 推进数据共享；\n"
            "5. 明确保障措施。"
        )
    },
    {
        "id": "T14",
        "category": "智能辅助工具",
        "prompt": (
            "请起草一份关于规范行政机关使用智能辅助工具的意见。\n"
            "要求：\n"
            "1. 坚持依法依规；\n"
            "2. 明确人工审核责任；\n"
            "3. 防止错误信息直接用于行政决定；\n"
            "4. 加强数据安全和隐私保护；\n"
            "5. 建立监督机制。"
        )
    },
    {
        "id": "T15",
        "category": "电子材料归档",
        "prompt": (
            "请起草一份广东省政府部门关于加强行政执法"
            "电子材料归档管理的通知。\n"
            "要求明确电子材料归档范围、归档标准、保存要求、"
            "安全管理责任和监督检查机制。"
        )
    },
]

# ============================================================
# 工具函数
# ============================================================
def normalize_text(text):
    if not text:
        return ""
    text = text.replace("\r", "\n")
    text = re.sub(r"\s+", "", text)
    return text

def load_jsonl(path):
    records = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))
    return records

def extract_assistant_text(record):
    for msg in record.get("messages", []):
        if msg.get("role") == "assistant":
            return msg.get("content", "")
    return ""

def extract_title(text):
    lines = [x.strip() for x in text.replace("\r", "\n").split("\n") if x.strip()]
    for line in lines[:12]:
        if "广东省人民政府" in line or "广东省人民政府办公厅" in line:
            if len(line) < 100:
                return line
    return lines[0] if lines else ""

# ============================================================
# 字符 n-gram TF-IDF
# ============================================================
def char_ngrams(text, n=3):
    text = normalize_text(text)
    if len(text) < n:
        return [text] if text else []
    return [text[i:i+n] for i in range(len(text) - n + 1)]

def build_tfidf(documents, n=3):
    doc_counters = []
    for doc in documents:
        grams = char_ngrams(doc, n)
        doc_counters.append(Counter(grams))
    df = Counter()
    for counter in doc_counters:
        for gram in counter:
            df[gram] += 1
    N = len(documents)
    vectors = []
    for counter in doc_counters:
        total = sum(counter.values())
        vector = {}
        if total == 0:
            vectors.append(vector)
            continue
        for gram, count in counter.items():
            tf = count / total
            idf = math.log((N + 1) / (df[gram] + 1)) + 1
            vector[gram] = tf * idf
        vectors.append(vector)
    return vectors

def cosine_similarity(vec_a, vec_b):
    if not vec_a or not vec_b:
        return 0.0
    if len(vec_a) > len(vec_b):
        vec_a, vec_b = vec_b, vec_a
    dot = 0.0
    for k, v in vec_a.items():
        dot += v * vec_b.get(k, 0.0)
    norm_a = math.sqrt(sum(v * v for v in vec_a.values()))
    norm_b = math.sqrt(sum(v * v for v in vec_b.values()))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)

# ============================================================
# 连续片段复现检查
# ============================================================
def longest_common_substring(a, b):
    a = normalize_text(a)
    b = normalize_text(b)
    if not a or not b:
        return 0, ""
    if len(a) > len(b):
        a, b = b, a
    previous = [0] * (len(b) + 1)
    best_len = 0
    best_end = 0
    for i, ca in enumerate(a, 1):
        current = [0] * (len(b) + 1)
        for j, cb in enumerate(b, 1):
            if ca == cb:
                current[j] = previous[j - 1] + 1
                if current[j] > best_len:
                    best_len = current[j]
                    best_end = i
        previous = current
    fragment = a[best_end - best_len:best_end]
    return best_len, fragment

# ============================================================
# 生成模型
# ============================================================
def load_base_model():
    print()
    print("=" * 80)
    print("加载 Base Qwen2.5-14B-Instruct")
    print("=" * 80)
    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL,
        torch_dtype=torch.bfloat16,
        device_map="auto",
        trust_remote_code=True,
        low_cpu_mem_usage=True,
    )
    model.eval()
    return tokenizer, model

def generate(model, tokenizer, prompt):
    messages = [{"role": "user", "content": prompt}]
    text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = tokenizer(text, return_tensors="pt")
    device = next(model.parameters()).device
    inputs = {k: v.to(device) for k, v in inputs.items()}
    with torch.no_grad():
        outputs = model.generate(
            **inputs,
            max_new_tokens=MAX_NEW_TOKENS,
            do_sample=DO_SAMPLE,
            repetition_penalty=1.05,
        )
    generated = outputs[0, inputs["input_ids"].shape[1]:]
    return tokenizer.decode(generated, skip_special_tokens=True)

# ============================================================
# 相似度分析
# ============================================================
def similarity_analysis(output_text, train_texts, train_records, tfidf_train_vectors, n=3):
    output_norm = normalize_text(output_text)
    output_vector = build_tfidf([output_text], n=n)[0]
    scores = []
    for i, train_vec in enumerate(tfidf_train_vectors):
        score = cosine_similarity(output_vector, train_vec)
        scores.append((score, i))
    scores.sort(reverse=True, key=lambda x: x[0])
    top_results = []
    for score, idx in scores[:5]:
        train_text = train_texts[idx]
        common_len, fragment = longest_common_substring(output_text, train_text)
        uid = train_records[idx].get("metadata", {}).get("source_UID", "")
        title = extract_title(train_text)
        top_results.append({
            "uid": uid,
            "title": title,
            "tfidf_cosine": round(score, 6),
            "longest_common_chars": common_len,
            "common_fragment": fragment[:150]
        })
    return top_results

# ============================================================
# 结果打印
# ============================================================
def print_similarity_result(item):
    print()
    print("-" * 100)
    print(f"{item['id']} | {item['category']}")
    print("最高训练集相似度:", item["similarity"]["top1"]["tfidf_cosine"])
    print("最长连续公共片段:", item["similarity"]["top1"]["longest_common_chars"], "chars")
    print("最相似训练文档 UID:", item["similarity"]["top1"]["uid"])
    print("最相似训练文档:", item["similarity"]["top1"]["title"])
    fragment = item["similarity"]["top1"]["common_fragment"]
    if fragment:
        print("公共片段:", fragment[:150])

# ============================================================
# 主程序
# ============================================================
def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # 1. 读取已有 T01-T10
    print("=" * 80)
    print("读取 T01-T10")
    print("=" * 80)
    old_results = load_jsonl(OLD_RESULTS)
    if len(old_results) != 10:
        raise RuntimeError(f"预期 T01-T10 共10条，实际 {len(old_results)} 条")
    old_map = {x["id"]: x for x in old_results}

    # 2. 读取训练集
    print("=" * 80)
    print("读取 2656 条 train_real")
    print("=" * 80)
    train_records = load_jsonl(TRAIN_FILE)
    print("训练记录:", len(train_records))
    train_texts = [extract_assistant_text(x) for x in train_records]
    train_texts_norm = [normalize_text(x) for x in train_texts]

    # 3. 构建训练集 TF-IDF
    print("=" * 80)
    print("构建训练集字符 TF-IDF")
    print("=" * 80)
    tfidf_train_vectors = build_tfidf(train_texts_norm, n=3)

    # 4. 分析 T01-T10
    final_results = []
    print("=" * 80)
    print("分析 T01-T10 与训练集相似度")
    print("=" * 80)
    for item in old_results:
        similarity = similarity_analysis(item["v1"], train_texts_norm, train_records, tfidf_train_vectors)
        record = dict(item)
        record["similarity"] = {"top1": similarity[0], "top5": similarity}
        record["test_group"] = "existing_t01_t10"
        final_results.append(record)
        print_similarity_result(record)

    # 5. 加载 Base
    tokenizer, base_model = load_base_model()

    # 6. 生成 T11-T15 Base
    print()
    print("=" * 80)
    print("生成 T11-T15：Base")
    print("=" * 80)
    new_results = []
    for item in NEW_TESTS:
        print(f"[Base] {item['id']}")
        base_output = generate(base_model, tokenizer, item["prompt"])
        new_results.append({
            "id": item["id"],
            "category": item["category"],
            "prompt": item["prompt"],
            "base": base_output
        })

    # 7. 删除 Base，释放显存
    del base_model
    gc.collect()
    torch.cuda.empty_cache()

    # 8. 再次加载 Base + LoRA
    print()
    print("=" * 80)
    print("加载 V1 LoRA")
    print("=" * 80)
    _, base_model = load_base_model()
    v1_model = PeftModel.from_pretrained(base_model, ADAPTER, is_trainable=False)
    v1_model.eval()

    # 9. 生成 T11-T15 V1
    print()
    print("=" * 80)
    print("生成 T11-T15：V1")
    print("=" * 80)
    for item in new_results:
        print(f"[V1] {item['id']}")
        item["v1"] = generate(v1_model, tokenizer, item["prompt"])
        similarity = similarity_analysis(item["v1"], train_texts_norm, train_records, tfidf_train_vectors)
        item["similarity"] = {"top1": similarity[0], "top5": similarity}
        item["test_group"] = "new_unseen_topics_t11_t15"
        final_results.append(item)
        print_similarity_result(item)

    # 10. 保存 JSONL
    with OUTPUT_RESULTS.open("w", encoding="utf-8") as f:
        for item in final_results:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    # 11. 生成报告
    with OUTPUT_REPORT.open("w", encoding="utf-8") as f:
        f.write("V1 泛化与训练集相似度测试报告\n")
        f.write("=" * 100 + "\n\n")
        f.write("训练集: 2656 条 real_sft\n")
        f.write("测试: T01-T10 + T11-T15\n\n")
        for item in final_results:
            sim = item["similarity"]
            top1 = sim["top1"]
            f.write(f"{item['id']} | {item['category']}\n")
            f.write(f"测试组: {item['test_group']}\n")
            f.write(f"Top1 TF-IDF cosine: {top1['tfidf_cosine']}\n")
            f.write(f"最长公共连续片段: {top1['longest_common_chars']} chars\n")
            f.write(f"Top1 UID: {top1['uid']}\n")
            f.write(f"Top1 title: {top1['title']}\n")
            f.write(f"公共片段: {top1['common_fragment']}\n")
            f.write("\n")

    # 12. 最终汇总
    print()
    print("=" * 100)
    print("测试完成")
    print("=" * 100)
    print(f"总测试数: {len(final_results)}")
    print(f"T01-T10: {sum(1 for x in final_results if x['test_group'] == 'existing_t01_t10')}")
    print(f"T11-T15: {sum(1 for x in final_results if x['test_group'] == 'new_unseen_topics_t11_t15')}")
    print()
    print("结果文件:")
    print(OUTPUT_RESULTS)
    print(OUTPUT_REPORT)

if __name__ == "__main__":
    main()