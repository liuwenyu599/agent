
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
============================================================
政府公文生成能力验收测试 V5
============================================================

目的：
    判断 Base / V1 / V1.1 模型是否具备较成熟的政府公文生成能力。

本版本重点修复：

1. “达到 max_new_tokens”不再直接等于“截断”
2. 增加真正的输出截断判断
3. 禁止当前草稿生成“文件编号待补充”等占位符
4. 禁止当前草稿自行编造文号
5. 禁止当前草稿自行编造成文日期
6. 已有政策文件及其真实文号允许引用
7. 历史政策背景、历史年份、工作目标年份允许
8. 检测机械重复
9. 检测连续重复段落
10. 检测模板占位符
11. 检测异常超长扩写
12. 检测明显未完成结构
13. 输出完整正文到独立 txt 文件

运行：

    python sft_v1/evaluation/run_generation_acceptance.py --model v11

或者：

    CUDA_VISIBLE_DEVICES=0 \
    python sft_v1/evaluation/run_generation_acceptance.py --model v11

支持：

    --model base
    --model v1
    --model v11
    --model all

输出：

    sft_v1/evaluation/generation_acceptance/

    generation_results.jsonl
    generation_acceptance_report.txt

    H01_行政检查.txt
    H02_行政执法.txt
    ...
    H20_法治建设.txt
"""

import os

# ============================================================
# 0. 环境变量
# ============================================================

os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
os.environ.setdefault(
    "PYTORCH_CUDA_ALLOC_CONF",
    "expandable_segments:True"
)
os.environ.setdefault("NCCL_P2P_DISABLE", "1")
os.environ.setdefault("NCCL_IB_DISABLE", "1")

import re
import json
import time
import argparse
import gc
from pathlib import Path
from typing import Dict, List, Any, Tuple

import torch

from transformers import (
    AutoTokenizer,
    AutoModelForCausalLM,
    BitsAndBytesConfig,
)

from peft import PeftModel


# ============================================================
# 1. 路径
# ============================================================

PROJECT_ROOT = Path("/home/lwy/Policy_crawler")

BASE_MODEL = "/home/lwy/Qwen2.5-14B-Instruct"

V1_ADAPTER = (
    "/home/lwy/Policy_crawler/"
    "sft_v1/checkpoints/real_sft_v1_qlora_full"
)

V11_ADAPTER = (
    "/home/lwy/Policy_crawler/"
    "sft_v1/checkpoints/real_sft_v11_qlora_full"
)

OUT_DIR = (
    PROJECT_ROOT
    / "sft_v1"
    / "evaluation"
    / "generation_acceptance"
)

OUT_DIR.mkdir(
    parents=True,
    exist_ok=True,
)

RESULT_FILE = (
    OUT_DIR / "generation_results.jsonl"
)

REPORT_FILE = (
    OUT_DIR / "generation_acceptance_report.txt"
)


# ============================================================
# 2. 生成配置
# ============================================================

# 公文较长。
# 这里提高到 6144，避免正常完整公文被硬性截断。
MAX_NEW_TOKENS = 6144

# 稍微提高重复惩罚。
REPETITION_PENALTY = 1.10

# 确定性生成，方便验收复现。
DO_SAMPLE = False

TEMPERATURE = 1.0
TOP_P = 1.0

# 避免模型无限复制相同 n-gram。
NO_REPEAT_NGRAM_SIZE = 6


QUANTIZATION_CONFIG = BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_quant_type="nf4",
    bnb_4bit_compute_dtype=torch.bfloat16,
    bnb_4bit_use_double_quant=True,
)


# ============================================================
# 3. 测试任务
# ============================================================

TESTS = [
    {
        "id": "H01",
        "category": "行政检查",
        "genre": "通知",
        "prompt": "请起草一份关于规范行政检查工作的通知。",
    },
    {
        "id": "H02",
        "category": "行政执法",
        "genre": "实施方案",
        "prompt": "请起草一份关于规范行政执法行为的实施方案。",
    },
    {
        "id": "H03",
        "category": "政务服务",
        "genre": "工作方案",
        "prompt": "请起草一份关于提升政务服务效能的工作方案。",
    },
    {
        "id": "H04",
        "category": "依法行政",
        "genre": "意见",
        "prompt": "请起草一份关于推进依法行政工作的意见。",
    },
    {
        "id": "H05",
        "category": "规范性文件",
        "genre": "通知",
        "prompt": "请起草一份关于加强行政规范性文件管理的通知。",
    },
    {
        "id": "H06",
        "category": "基层治理",
        "genre": "实施方案",
        "prompt": "请起草一份关于推进基层治理现代化的实施方案。",
    },
    {
        "id": "H07",
        "category": "法治政府",
        "genre": "工作方案",
        "prompt": "请起草一份关于推进法治政府建设的工作方案。",
    },
    {
        "id": "H08",
        "category": "行政复议",
        "genre": "意见",
        "prompt": "请起草一份关于进一步规范行政复议工作的意见。",
    },
    {
        "id": "H09",
        "category": "公共法律服务",
        "genre": "实施方案",
        "prompt": "请起草一份关于加强基层公共法律服务体系建设的实施方案。",
    },
    {
        "id": "H10",
        "category": "政务公开",
        "genre": "通知",
        "prompt": "请起草一份关于进一步推进政务公开工作的通知。",
    },
    {
        "id": "H11",
        "category": "行政执法监督",
        "genre": "实施方案",
        "prompt": "请起草一份关于加强行政执法监督工作的实施方案。",
    },
    {
        "id": "H12",
        "category": "政府法律顾问",
        "genre": "意见",
        "prompt": "请起草一份关于加强政府法律顾问工作的意见。",
    },
    {
        "id": "H13",
        "category": "政府行政行为",
        "genre": "工作方案",
        "prompt": "请起草一份关于规范政府行政行为的工作方案。",
    },
    {
        "id": "H14",
        "category": "数字政府",
        "genre": "实施方案",
        "prompt": "请起草一份关于推进数字政府建设的实施方案。",
    },
    {
        "id": "H15",
        "category": "政务数据",
        "genre": "通知",
        "prompt": "请起草一份关于加强政务数据管理工作的通知。",
    },
    {
        "id": "H16",
        "category": "人工智能",
        "genre": "意见",
        "prompt": "请起草一份关于规范政府部门人工智能应用的意见。",
    },
    {
        "id": "H17",
        "category": "行政审批",
        "genre": "实施方案",
        "prompt": "请起草一份关于深化行政审批制度改革的实施方案。",
    },
    {
        "id": "H18",
        "category": "营商环境",
        "genre": "工作方案",
        "prompt": "请起草一份关于进一步优化营商环境的工作方案。",
    },
    {
        "id": "H19",
        "category": "权力监督",
        "genre": "意见",
        "prompt": "请起草一份关于加强行政权力运行监督的意见。",
    },
    {
        "id": "H20",
        "category": "法治建设",
        "genre": "通知",
        "prompt": "请起草一份关于加强法治政府建设的通知。",
    },
]


# ============================================================
# 4. System Prompt
# ============================================================

SYSTEM_PROMPT = """
你是一名政府机关公文起草人员。

请根据用户给出的主题和文种，直接起草一份正式、完整、规范的政府公文草稿。

【核心要求】

1. 严格围绕用户给出的主题。

2. 严格按照指定文种写作。

3. 使用符合政府公文习惯的结构。

4. 内容必须具有实际行政管理逻辑，不能为了增加篇幅机械扩写。

5. 各级标题必须具有明确逻辑关系。

6. 同一项工作内容不得换一种说法重复多次。

7. 不得复制前面已经出现的段落。

8. 不得为了凑长度生成大量同义的“加强……建设”“加强……监督”条目。

9. 不输出分析、解释、免责声明、写作说明。

10. 只输出最终公文正文。

【文号与日期】

11. 当前用户没有提供正在起草文件的正式文号时：
    不得自行编造当前文件文号。

12. 当前用户没有提供正在起草文件的成文日期时：
    不得自行编造当前文件成文日期。

13. 当前文件没有文号时，直接省略文号。
    不要写：
    “〔文件编号待补充〕”
    “〔文号待补充〕”
    “文号待补充”
    “XX〔2025〕XX号”
    或其他虚构文号。

14. 当前文件没有日期时，直接省略日期。
    不要写：
    “日期待补充”
    “年月日待补充”
    “2025年X月X日”
    或自行猜测具体日期。

15. 如果正文需要引用已经存在的法律法规、政策文件，可以正常引用其名称。

16. 如果已经存在的政策文件在训练材料中具有明确真实文号，可以引用该已有文件的真实文号。

17. 已有政策文件的文号属于被引用文件的文号，不属于当前正在起草文件的文号。

【依据文件】

18. 如果没有明确提供某一具体依据文件，不要制造：
    “〔依据文件待补充〕”
    “国发〔文件编号待补充〕”
    “国办发〔文件编号待补充〕”
    等占位内容。

19. 没有可靠依据文件时，可以使用：
    “根据有关法律法规和政策规定”
    “根据党中央、国务院有关决策部署”
    等一般性、非虚构性表述。

20. 不要把不存在或无法确定的文件写成确定存在的具体政策文件。

【历史政策】

21. 正常引用历史政策文件允许。

22. 正常出现历史年份允许。

23. 正常出现党的历史会议精神允许。

24. 工作目标可以出现合理的目标年份，但不要把目标年份写成当前文件成文日期。

【发布状态】

25. 当前文件是正在起草的草稿。

26. 不得声称当前文件已经正式发布、正式印发或已经生效。

27. 不要使用能够明确证明当前草稿已经正式发布的表述。

【写作质量】

28. 正文应完整，但以内容完整为优先，而不是追求字数。

29. 不得为了达到长度要求重复内容。

30. 结构应自然结束。

31. 最后一项必须完整。

32. 不要突然停止在半句话、半个条款、半个标题或编号上。

33. 如果内容已经完整，应正常结束，不要继续生成无关内容。

【文种】

通知：
通常包括通知缘由、主要事项、工作要求等。

意见：
通常包括总体要求、重点任务、保障措施等。

实施方案：
通常包括总体要求、工作目标、主要任务、实施步骤、保障措施等。

工作方案：
通常包括总体要求、主要任务、工作安排、工作机制、保障措施等。

请直接输出公文正文。
"""


# ============================================================
# 5. 模型加载
# ============================================================

def load_tokenizer():

    tokenizer = AutoTokenizer.from_pretrained(
        BASE_MODEL,
        trust_remote_code=True,
        use_fast=True,
    )

    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    return tokenizer


def load_base_model():

    model = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL,
        quantization_config=QUANTIZATION_CONFIG,
        dtype=torch.bfloat16,
        trust_remote_code=True,
        device_map={"": 0},
    )

    model.eval()

    return model


def load_model(model_name: str):

    tokenizer = load_tokenizer()

    if model_name == "base":

        print("加载 Base Qwen2.5-14B-Instruct ...")

        model = load_base_model()

        return tokenizer, model

    if model_name == "v1":

        print("加载 V1 LoRA ...")

        base_model = load_base_model()

        model = PeftModel.from_pretrained(
            base_model,
            V1_ADAPTER,
        )

        model.eval()

        return tokenizer, model

    if model_name == "v11":

        print("加载 V1.1 LoRA ...")

        base_model = load_base_model()

        model = PeftModel.from_pretrained(
            base_model,
            V11_ADAPTER,
        )

        model.eval()

        return tokenizer, model

    raise ValueError(
        f"未知模型：{model_name}"
    )


# ============================================================
# 6. Prompt
# ============================================================

def build_messages(
    test: Dict[str, Any]
):

    return [
        {
            "role": "system",
            "content": SYSTEM_PROMPT,
        },
        {
            "role": "user",
            "content": test["prompt"],
        },
    ]


# ============================================================
# 7. 文本清理
# ============================================================

def clean_generation(
    text: str
) -> str:

    if not text:
        return ""

    text = text.strip()

    text = re.sub(
        r"^```(?:text|markdown)?\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )

    text = re.sub(
        r"\s*```$",
        "",
        text,
    )

    text = re.sub(
        r"^\s*(assistant|助手)\s*[:：]\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )

    return text.strip()


# ============================================================
# 8. 生成
# ============================================================

@torch.inference_mode()
def generate(
    model,
    tokenizer,
    test: Dict[str, Any],
) -> Tuple[str, Dict[str, Any]]:

    messages = build_messages(test)

    prompt_text = tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=True,
    )

    inputs = tokenizer(
        prompt_text,
        return_tensors="pt",
        padding=True,
        truncation=True,
        max_length=8192,
    )

    device = next(
        model.parameters()
    ).device

    inputs = {
        key: value.to(device)
        for key, value in inputs.items()
    }

    input_length = (
        inputs["input_ids"]
        .shape[-1]
    )

    start = time.time()

    outputs = model.generate(
        **inputs,

        max_new_tokens=MAX_NEW_TOKENS,

        do_sample=DO_SAMPLE,

        temperature=TEMPERATURE,

        top_p=TOP_P,

        repetition_penalty=REPETITION_PENALTY,

        no_repeat_ngram_size=NO_REPEAT_NGRAM_SIZE,

        eos_token_id=tokenizer.eos_token_id,

        pad_token_id=tokenizer.pad_token_id,

        use_cache=True,
    )

    elapsed = time.time() - start

    generated_ids = (
        outputs[0, input_length:]
    )

    generated_token_count = int(
        generated_ids.shape[-1]
    )

    text = tokenizer.decode(
        generated_ids,
        skip_special_tokens=True,
    )

    text = clean_generation(text)

    reached_max_tokens = (
        generated_token_count
        >= MAX_NEW_TOKENS
    )

    if reached_max_tokens:
        finish_reason = "max_new_tokens"
    else:
        finish_reason = "eos_or_model_stop"

    metadata = {
        "input_tokens": int(input_length),
        "generated_tokens": generated_token_count,
        "max_new_tokens": MAX_NEW_TOKENS,
        "finish_reason": finish_reason,
        "reached_max_tokens": reached_max_tokens,
        "generation_seconds": round(
            elapsed,
            2,
        ),
    }

    return text, metadata


# ============================================================
# 9. 标题 / 结构
# ============================================================

FIRST_LEVEL_RE = re.compile(
    r"^\s*[一二三四五六七八九十百]+、"
)

SECOND_LEVEL_RE = re.compile(
    r"^\s*[（(][一二三四五六七八九十百]+[）)]"
)

NUMBERED_ITEM_RE = re.compile(
    r"^\s*\d+[\.．、]"
)


def analyze_structure(
    text: str,
    genre: str,
) -> Dict[str, Any]:

    text = text.strip()

    no_space_text = re.sub(
        r"\s+",
        "",
        text,
    )

    char_count = len(
        no_space_text
    )

    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip()
    ]

    first_level = [
        line
        for line in lines
        if FIRST_LEVEL_RE.match(line)
    ]

    second_level = [
        line
        for line in lines
        if SECOND_LEVEL_RE.match(line)
    ]

    numbered = [
        line
        for line in lines
        if NUMBERED_ITEM_RE.match(line)
    ]

    title = ""

    for line in lines[:20]:

        if (
            len(line) <= 100
            and (
                "关于" in line
                or line.endswith(
                    (
                        "通知",
                        "意见",
                        "方案",
                        "工作方案",
                        "实施方案",
                    )
                )
            )
        ):
            title = line
            break

    if not title and lines:
        title = lines[0]

    return {
        "char_count": char_count,
        "line_count": len(lines),
        "title": title,
        "first_level_headings": len(
            first_level
        ),
        "second_level_headings": len(
            second_level
        ),
        "numbered_items": len(
            numbered
        ),
        "first_level_examples": first_level[:10],
        "second_level_examples": second_level[:10],
    }


# ============================================================
# 10. 文本归一化
# ============================================================

def normalize_text(
    text: str
) -> str:

    text = re.sub(
        r"\s+",
        "",
        text,
    )

    text = re.sub(
        r"[，。；：、、“”‘’（）()【】《》！？,.!?]",
        "",
        text,
    )

    return text


# ============================================================
# 11. 完全重复行
# ============================================================

def detect_duplicate_lines(
    text: str,
) -> Dict[str, Any]:

    lines = []

    for line in text.splitlines():

        line = line.strip()

        if len(line) < 20:
            continue

        normalized = normalize_text(
            line
        )

        if len(normalized) < 20:
            continue

        lines.append(
            (
                normalized,
                line,
            )
        )

    counter = {}

    originals = {}

    for normalized, original in lines:

        counter[normalized] = (
            counter.get(
                normalized,
                0,
            )
            + 1
        )

        originals.setdefault(
            normalized,
            original,
        )

    examples = []

    for normalized, count in counter.items():

        if count >= 2:

            examples.append(
                {
                    "count": count,
                    "text": originals[
                        normalized
                    ],
                }
            )

    return {
        "duplicate_count": len(
            examples
        ),
        "examples": examples[:10],
    }


# ============================================================
# 12. 连续重复
# ============================================================

def detect_repeated_blocks(
    text: str,
) -> Dict[str, Any]:

    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip()
    ]

    blocks = []

    # 连续相同
    for i in range(
        len(lines) - 1
    ):

        a = normalize_text(
            lines[i]
        )

        b = normalize_text(
            lines[i + 1]
        )

        if (
            len(a) >= 20
            and len(b) >= 20
            and a == b
        ):

            blocks.append(
                {
                    "type": "adjacent_duplicate",
                    "index": i,
                    "text": lines[i],
                }
            )

    # A B A B 型重复
    for i in range(
        len(lines) - 3
    ):

        a = normalize_text(
            lines[i]
        )

        b = normalize_text(
            lines[i + 1]
        )

        c = normalize_text(
            lines[i + 2]
        )

        d = normalize_text(
            lines[i + 3]
        )

        if (
            len(a) >= 20
            and len(b) >= 20
            and a == c
            and b == d
        ):

            blocks.append(
                {
                    "type": "abab_duplicate",
                    "index": i,
                    "text": (
                        lines[i]
                        + " | "
                        + lines[i + 1]
                    ),
                }
            )

    return {
        "repeated_block_count": len(
            blocks
        ),
        "examples": blocks[:10],
    }


# ============================================================
# 13. 重复片段检测
# ============================================================

def detect_repeated_phrases(
    text: str,
) -> Dict[str, Any]:

    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip()
    ]

    phrases = {}

    for line in lines:

        normalized = normalize_text(
            line
        )

        if len(normalized) < 60:
            continue

        # 使用 30 字窗口
        step = 10

        for i in range(
            0,
            len(normalized) - 29,
            step,
        ):

            phrase = normalized[
                i:i + 30
            ]

            phrases.setdefault(
                phrase,
                0,
            )

            phrases[phrase] += 1

    repeated = [
        {
            "count": count,
            "phrase": phrase,
        }
        for phrase, count in phrases.items()
        if count >= 3
    ]

    repeated.sort(
        key=lambda x: x["count"],
        reverse=True,
    )

    return {
        "repeated_phrase_count": len(
            repeated
        ),
        "examples": repeated[:10],
    }


# ============================================================
# 14. 当前文件自身文号
# ============================================================

def detect_draft_document_number(
    text: str,
) -> Dict[str, Any]:

    # 典型正式文号
    patterns = [

        r"(?:粤|穗|深|莞|中山)"
        r"(?:府|委|办|发|函|规|政)"
        r"(?:〔|\[)"
        r"\d{4}"
        r"(?:〕|\])"
        r"\d+号",

        r"[\u4e00-\u9fa5]{1,8}"
        r"(?:府办|政府办|办公室|政府)"
        r"(?:〔|\[)"
        r"\d{4}"
        r"(?:〕|\])"
        r"\d+号",
    ]

    numbers = []

    for pattern in patterns:

        numbers.extend(
            re.findall(
                pattern,
                text,
            )
        )

    numbers = list(
        dict.fromkeys(numbers)
    )

    # 只看文头区域。
    early_text = text[:1500]

    early_numbers = [
        number
        for number in numbers
        if number in early_text
    ]

    return {
        "risk": len(
            early_numbers
        ) > 0,
        "numbers": early_numbers,
    }


# ============================================================
# 15. 占位符检测
# ============================================================

PLACEHOLDER_PATTERNS = [

    r"文件编号待补充",
    r"文号待补充",
    r"编号待补充",
    r"依据文件待补充",
    r"日期待补充",
    r"时间待补充",
    r"年月日待补充",

    r"XX〔\d{4}〕XX号",
    r"XX〔\d{4}〕\d+号",
    r"〔文件编号待补充〕",
    r"〔文号待补充〕",
    r"〔依据文件待补充〕",

    r"国发〔文件编号待补充〕",
    r"国办发〔文件编号待补充〕",

    r"202\d年X月X日",
    r"20\d{2}年X月X日",
]


def detect_placeholders(
    text: str,
) -> Dict[str, Any]:

    matches = []

    for pattern in PLACEHOLDER_PATTERNS:

        found = re.findall(
            pattern,
            text,
            flags=re.IGNORECASE,
        )

        matches.extend(found)

    matches = list(
        dict.fromkeys(matches)
    )

    return {
        "risk": len(matches) > 0,
        "matches": matches,
    }


# ============================================================
# 16. 当前文件日期
# ============================================================

def detect_draft_date(
    text: str,
) -> Dict[str, Any]:

    patterns = [

        r"\b20\d{2}年\d{1,2}月\d{1,2}日\b",

        r"[二〇零一二三四五六七八九]{4}"
        r"年"
        r"[一二三四五六七八九十]{1,3}"
        r"月"
        r"[一二三四五六七八九十]{1,3}"
        r"日",
    ]

    dates = []

    for pattern in patterns:

        dates.extend(
            re.findall(
                pattern,
                text,
            )
        )

    dates = list(
        dict.fromkeys(dates)
    )

    # 只判断尾部是否出现具体成文日期。
    tail = text[-1200:]

    tail_dates = [
        date
        for date in dates
        if date in tail
    ]

    return {
        "risk": len(
            tail_dates
        ) > 0,
        "dates": tail_dates,
    }


# ============================================================
# 17. 正式发布状态
# ============================================================

def detect_published_claim(
    text: str,
) -> Dict[str, Any]:

    patterns = [

        r"现予印发",
        r"现予发布",
        r"正式发布",
        r"本文件已经发布",
        r"本通知已经发布",
        r"本意见已经发布",
        r"本方案已经发布",
        r"已经正式印发",
        r"已正式印发",
        r"现已印发",

        # 当前草稿中明确声称已经生效
        r"本文件自.*起施行",
        r"本通知自.*起施行",
        r"本意见自.*起施行",
        r"本方案自.*起施行",
    ]

    matches = []

    for pattern in patterns:

        found = re.findall(
            pattern,
            text,
        )

        matches.extend(
            found
        )

    matches = list(
        dict.fromkeys(matches)
    )

    return {
        "risk": len(matches) > 0,
        "matches": matches,
    }


# ============================================================
# 18. 真正截断检测
# ============================================================

def detect_truncation(
    text: str,
    generation_meta: Dict[str, Any],
) -> Dict[str, Any]:

    reasons = []

    stripped = text.strip()

    if not stripped:

        return {
            "risk": True,
            "confidence": "high",
            "reasons": [
                "没有生成正文"
            ],
            "last_line": "",
            "last_char": "",
        }

    lines = [
        line.strip()
        for line in stripped.splitlines()
        if line.strip()
    ]

    last_line = (
        lines[-1]
        if lines
        else ""
    )

    last_char = stripped[-1]

    reached_max = generation_meta.get(
        "reached_max_tokens",
        False,
    )

    # --------------------------------------------------------
    # 1. 明显停在标题编号
    # --------------------------------------------------------

    if re.match(
        r"^[一二三四五六七八九十百]+、$",
        last_line,
    ):
        reasons.append(
            "最后停在一级标题编号"
        )

    if re.match(
        r"^[（(][一二三四五六七八九十百]+[）)]$",
        last_line,
    ):
        reasons.append(
            "最后停在二级标题编号"
        )

    if re.match(
        r"^\d+[\.．、]$",
        last_line,
    ):
        reasons.append(
            "最后停在编号项目"
        )

    # --------------------------------------------------------
    # 2. 明显未闭合标点
    # --------------------------------------------------------

    if last_char in (
        "，",
        ",",
        "：",
        ":",
        "、",
        "—",
        "-",
        "（",
        "(",
        "《",
        "“",
        "‘",
    ):
        reasons.append(
            "最后一句以明显未完成标点结束"
        )

    # --------------------------------------------------------
    # 3. 最后一行明显像半句
    # --------------------------------------------------------

    sentence_end_chars = (
        "。！？；"
        "）】》”’"
    )

    unfinished_words = (
        "以及",
        "并",
        "并且",
        "其中",
        "包括",
        "通过",
        "按照",
        "对于",
        "根据",
        "切实",
        "进一步",
        "不断",
        "积极",
        "着力",
        "重点",
        "主要",
        "分别",
    )

    if (
        len(last_line) >= 15
        and not last_line.endswith(
            sentence_end_chars
        )
        and not last_line.endswith(
            (
                "号",
                "项",
                "款",
                "条",
                "篇",
            )
        )
    ):

        if any(
            last_line.endswith(
                word
            )
            for word in unfinished_words
        ):
            reasons.append(
                "最后一句疑似停在未完成短语"
            )

    # --------------------------------------------------------
    # 4. 真正关键逻辑：
    #
    # 达到 max_new_tokens 本身不等于截断。
    #
    # 只有：
    #   max_tokens + 明显未完成
    #
    # 才判定为真正截断。
    # --------------------------------------------------------

    explicit_incomplete = len(
        reasons
    ) > 0

    if (
        reached_max
        and explicit_incomplete
    ):
        confidence = "high"

    elif (
        reached_max
        and not explicit_incomplete
    ):
        # 到上限但最后正常结束。
        # 记录为“达到上限”，不判截断。
        confidence = "low"

    else:
        confidence = (
            "high"
            if explicit_incomplete
            else "none"
        )

    risk = explicit_incomplete

    return {
        "risk": risk,
        "confidence": confidence,
        "reasons": reasons,
        "last_line": last_line,
        "last_char": last_char,
        "reached_max_tokens": reached_max,
    }


# ============================================================
# 19. 主题关键词
# ============================================================

CATEGORY_KEYWORDS = {

    "行政检查": [
        "行政检查",
        "检查",
        "监管",
    ],

    "行政执法": [
        "行政执法",
        "执法",
        "执法行为",
    ],

    "政务服务": [
        "政务服务",
        "服务效能",
        "服务",
    ],

    "依法行政": [
        "依法行政",
        "法治",
        "行政权力",
    ],

    "规范性文件": [
        "规范性文件",
        "文件管理",
        "备案",
    ],

    "基层治理": [
        "基层治理",
        "基层",
        "治理",
    ],

    "法治政府": [
        "法治政府",
        "依法行政",
        "法治建设",
    ],

    "行政复议": [
        "行政复议",
        "复议",
        "行政争议",
    ],

    "公共法律服务": [
        "公共法律服务",
        "法律服务",
        "基层法律",
    ],

    "政务公开": [
        "政务公开",
        "政府信息公开",
        "公开",
    ],

    "行政执法监督": [
        "行政执法监督",
        "执法监督",
        "监督",
    ],

    "政府法律顾问": [
        "法律顾问",
        "政府法律",
        "律师",
    ],

    "政府行政行为": [
        "行政行为",
        "政府行为",
        "依法行政",
    ],

    "数字政府": [
        "数字政府",
        "数字化",
        "政务数字化",
    ],

    "政务数据": [
        "政务数据",
        "数据管理",
        "数据治理",
    ],

    "人工智能": [
        "人工智能",
        "AI",
        "智能应用",
    ],

    "行政审批": [
        "行政审批",
        "审批",
        "放管服",
    ],

    "营商环境": [
        "营商环境",
        "企业服务",
        "市场主体",
    ],

    "权力监督": [
        "权力运行",
        "监督",
        "行政权力",
    ],

    "法治建设": [
        "法治政府",
        "法治建设",
        "依法行政",
    ],
}


def check_relevance(
    text: str,
    category: str,
) -> Dict[str, Any]:

    keywords = CATEGORY_KEYWORDS.get(
        category,
        [category],
    )

    matched = [
        keyword
        for keyword in keywords
        if keyword in text
    ]

    score = (
        len(matched)
        / max(
            len(keywords),
            1,
        )
    )

    return {
        "matched_keywords": matched,
        "score": round(
            score,
            3,
        ),
        "risk": score < 0.2,
    }


# ============================================================
# 20. 异常长度
# ============================================================

def detect_length_anomaly(
    text: str,
) -> Dict[str, Any]:

    no_space = re.sub(
        r"\s+",
        "",
        text,
    )

    char_count = len(no_space)

    # 单次验收不以字数硬判失败。
    # 这里只做异常提醒。
    if char_count > 18000:

        return {
            "risk": True,
            "level": "high",
            "reason": "正文异常超长，可能存在机械扩写",
        }

    if char_count > 12000:

        return {
            "risk": True,
            "level": "medium",
            "reason": "正文偏长，建议检查是否存在机械扩写",
        }

    return {
        "risk": False,
        "level": "normal",
        "reason": "",
    }


# ============================================================
# 21. 综合评价
# ============================================================

def evaluate_generation(
    text: str,
    test: Dict[str, Any],
    generation_meta: Dict[str, Any],
) -> Dict[str, Any]:

    text = clean_generation(
        text
    )

    structure = analyze_structure(
        text,
        test["genre"],
    )

    duplicate = detect_duplicate_lines(
        text
    )

    repeated_blocks = detect_repeated_blocks(
        text
    )

    repeated_phrases = detect_repeated_phrases(
        text
    )

    document_number = (
        detect_draft_document_number(
            text
        )
    )

    placeholders = detect_placeholders(
        text
    )

    draft_date = detect_draft_date(
        text
    )

    published_claim = detect_published_claim(
        text
    )

    truncation = detect_truncation(
        text,
        generation_meta,
    )

    relevance = check_relevance(
        text,
        test["category"],
    )

    length_anomaly = detect_length_anomaly(
        text
    )

    critical_issues = []

    review_issues = []

    # ========================================================
    # 核心事实问题
    # ========================================================

    if document_number["risk"]:

        critical_issues.append(
            "当前草稿疑似自行生成正式文号"
        )

    if placeholders["risk"]:

        critical_issues.append(
            "出现“文件编号待补充/依据文件待补充”等模板占位符"
        )

    if draft_date["risk"]:

        critical_issues.append(
            "当前草稿疑似自行生成具体成文日期"
        )

    if published_claim["risk"]:

        critical_issues.append(
            "当前草稿疑似将自身描述为已经正式发布/印发"
        )

    # ========================================================
    # 真正截断
    # ========================================================

    if truncation["risk"]:

        critical_issues.append(
            "输出疑似真正截断"
        )

    # ========================================================
    # 写作质量
    # ========================================================

    if structure["char_count"] < 1000:

        review_issues.append(
            "正文偏短，建议人工检查完整性"
        )

    if structure["first_level_headings"] < 2:

        review_issues.append(
            "一级结构偏少"
        )

    if (
        duplicate["duplicate_count"] >= 2
        or repeated_blocks[
            "repeated_block_count"
        ] >= 1
    ):

        review_issues.append(
            "存在明显重复段落/句子"
        )

    if (
        repeated_phrases[
            "repeated_phrase_count"
        ] >= 2
    ):

        review_issues.append(
            "存在重复短语簇，可能存在机械扩写"
        )

    if relevance["risk"]:

        review_issues.append(
            "主题关键词覆盖较低，建议人工检查是否跑题"
        )

    if length_anomaly["risk"]:

        review_issues.append(
            length_anomaly["reason"]
        )

    # ========================================================
    # 等级
    # ========================================================

    if critical_issues:

        grade = "D"

    elif len(review_issues) >= 2:

        grade = "C"

    elif len(review_issues) == 1:

        grade = "B"

    else:

        grade = "A"

    # ========================================================
    # 基础通过
    #
    # 注意：
    # 基础通过不是“可以直接部署”。
    # 它只表示结构和核心事实检查基本通过。
    # ========================================================

    basic_pass = (
        not critical_issues
        and structure["char_count"] >= 1000
        and structure[
            "first_level_headings"
        ] >= 2
        and not relevance["risk"]
        and not placeholders["risk"]
    )

    return {

        "grade": grade,

        "basic_pass": basic_pass,

        "critical_issues": critical_issues,

        "review_issues": review_issues,

        "title": structure["title"],

        "char_count": structure["char_count"],

        "line_count": structure["line_count"],

        "first_level_headings":
            structure[
                "first_level_headings"
            ],

        "second_level_headings":
            structure[
                "second_level_headings"
            ],

        "numbered_items":
            structure[
                "numbered_items"
            ],

        "duplicate_count":
            duplicate[
                "duplicate_count"
            ],

        "duplicate_examples":
            duplicate[
                "examples"
            ],

        "repeated_block_count":
            repeated_blocks[
                "repeated_block_count"
            ],

        "repeated_block_examples":
            repeated_blocks[
                "examples"
            ],

        "repeated_phrase_count":
            repeated_phrases[
                "repeated_phrase_count"
            ],

        "repeated_phrase_examples":
            repeated_phrases[
                "examples"
            ],

        "draft_document_number_hallucination":
            document_number["risk"],

        "document_numbers":
            document_number["numbers"],

        "placeholder_risk":
            placeholders["risk"],

        "placeholder_matches":
            placeholders["matches"],

        "draft_date_hallucination":
            draft_date["risk"],

        "draft_dates":
            draft_date["dates"],

        "published_policy_claim":
            published_claim["risk"],

        "published_claims":
            published_claim["matches"],

        "truncation":
            truncation["risk"],

        "truncation_confidence":
            truncation["confidence"],

        "truncation_reasons":
            truncation["reasons"],

        "truncation_last_line":
            truncation["last_line"],

        "reached_max_tokens":
            generation_meta.get(
                "reached_max_tokens",
                False,
            ),

        "length_anomaly":
            length_anomaly,

        "relevance_score":
            relevance["score"],

        "matched_keywords":
            relevance["matched_keywords"],

        "generation":
            generation_meta,
    }


# ============================================================
# 22. 写单条完整结果
# ============================================================

def write_single_result(
    test: Dict[str, Any],
    model_name: str,
    generation: str,
    evaluation: Dict[str, Any],
):

    filename = (
        f"{test['id']}_"
        f"{test['category']}.txt"
    )

    path = OUT_DIR / filename

    with open(
        path,
        "w",
        encoding="utf-8",
    ) as f:

        f.write(
            "=" * 80
            + "\n"
        )

        f.write(
            f"{test['id']} | "
            f"{test['category']} | "
            f"{test['genre']}\n"
        )

        f.write(
            f"模型：{model_name}\n"
        )

        f.write(
            f"测试问题：{test['prompt']}\n"
        )

        f.write(
            "=" * 80
            + "\n\n"
        )

        f.write(
            "【生成元信息】\n"
        )

        f.write(
            json.dumps(
                evaluation.get(
                    "generation",
                    {},
                ),
                ensure_ascii=False,
                indent=2,
            )
        )

        f.write(
            "\n\n"
        )

        f.write(
            "【自动评价】\n"
        )

        f.write(
            json.dumps(
                evaluation,
                ensure_ascii=False,
                indent=2,
            )
        )

        f.write(
            "\n\n"
        )

        f.write(
            "=" * 80
            + "\n"
        )

        f.write(
            "【完整生成正文】\n"
        )

        f.write(
            "=" * 80
            + "\n\n"
        )

        f.write(
            generation
        )

        f.write(
            "\n"
        )


# ============================================================
# 23. 单模型测试
# ============================================================

def run_model(
    model_name: str,
    model,
    tokenizer,
) -> List[Dict[str, Any]]:

    print()

    print(
        "=" * 80
    )

    print(
        f"开始公文生成能力验收：{model_name}"
    )

    print(
        "=" * 80
    )

    results = []

    for index, test in enumerate(
        TESTS,
        start=1,
    ):

        print()

        print(
            "-" * 80
        )

        print(
            f"[{index}/{len(TESTS)}] "
            f"{test['id']} "
            f"{test['category']} "
            f"| {test['genre']}"
        )

        print(
            f"问题：{test['prompt']}"
        )

        start_time = time.time()

        try:

            generated, generation_meta = generate(
                model,
                tokenizer,
                test,
            )

            elapsed = (
                time.time()
                - start_time
            )

            generated = clean_generation(
                generated
            )

            evaluation = evaluate_generation(
                generated,
                test,
                generation_meta,
            )

            result = {

                "model": model_name,

                "id": test["id"],

                "category":
                    test["category"],

                "genre":
                    test["genre"],

                "prompt":
                    test["prompt"],

                "generation":
                    generated,

                "evaluation":
                    evaluation,

                "generation_seconds":
                    round(
                        elapsed,
                        2,
                    ),

                "error":
                    None,
            }

            results.append(
                result
            )

            write_single_result(
                test,
                model_name,
                generated,
                evaluation,
            )

            # ------------------------------------------------
            # 终端摘要
            # ------------------------------------------------

            print()

            print(
                f"字符数："
                f"{evaluation['char_count']}"
            )

            print(
                f"生成 Token："
                f"{generation_meta['generated_tokens']}"
                f"/"
                f"{generation_meta['max_new_tokens']}"
            )

            print(
                f"停止原因："
                f"{generation_meta['finish_reason']}"
            )

            print(
                f"达到 Token 上限："
                f"{generation_meta['reached_max_tokens']}"
            )

            print(
                f"真正截断："
                f"{evaluation['truncation']}"
            )

            print(
                f"截断置信度："
                f"{evaluation['truncation_confidence']}"
            )

            print(
                f"占位符："
                f"{evaluation['placeholder_risk']}"
            )

            print(
                f"自身文号："
                f"{evaluation['draft_document_number_hallucination']}"
            )

            print(
                f"自身日期："
                f"{evaluation['draft_date_hallucination']}"
            )

            print(
                f"发布状态误称："
                f"{evaluation['published_policy_claim']}"
            )

            print(
                f"风险等级："
                f"{evaluation['grade']}"
            )

            print(
                f"主题匹配："
                f"{evaluation['relevance_score']}"
            )

            print(
                f"重复行："
                f"{evaluation['duplicate_count']}"
            )

            print(
                f"重复片段："
                f"{evaluation['repeated_phrase_count']}"
            )

            # ------------------------------------------------
            # 首尾预览
            # ------------------------------------------------

            preview_length = 220

            if (
                len(generated)
                <= preview_length * 2
            ):

                print()
                print(
                    "正文："
                )
                print(
                    generated
                )

            else:

                print()
                print(
                    "正文首部："
                )
                print(
                    generated[
                        :preview_length
                    ]
                )

                print()
                print(
                    "正文尾部："
                )
                print(
                    generated[
                        -preview_length:
                    ]
                )

            # ------------------------------------------------
            # 严重问题
            # ------------------------------------------------

            if evaluation[
                "critical_issues"
            ]:

                print()
                print(
                    "严重问题："
                )

                for issue in evaluation[
                    "critical_issues"
                ]:

                    print(
                        f"  - {issue}"
                    )

            if evaluation[
                "review_issues"
            ]:

                print()
                print(
                    "人工复核："
                )

                for issue in evaluation[
                    "review_issues"
                ]:

                    print(
                        f"  - {issue}"
                    )

        except Exception as e:

            elapsed = (
                time.time()
                - start_time
            )

            print()

            print(
                f"{test['id']} 运行失败："
                f"{repr(e)}"
            )

            results.append({

                "model":
                    model_name,

                "id":
                    test["id"],

                "category":
                    test["category"],

                "genre":
                    test["genre"],

                "prompt":
                    test["prompt"],

                "generation":
                    "",

                "evaluation":
                    {},

                "generation_seconds":
                    round(
                        elapsed,
                        2,
                    ),

                "error":
                    repr(e),
            })

    return results


# ============================================================
# 24. 汇总
# ============================================================

def build_summary(
    results: List[Dict[str, Any]]
) -> Dict[str, Any]:

    total = len(results)

    valid = [
        row
        for row in results
        if not row.get("error")
        and row.get("evaluation")
    ]

    A = 0
    B = 0
    C = 0
    D = 0

    basic_pass = 0

    draft_number = 0
    draft_date = 0
    published_claim = 0
    placeholder_count = 0

    short_count = 0
    duplicate_count = 0
    repeated_phrase_count = 0
    relevance_risk = 0
    truncation_count = 0
    max_token_count = 0
    length_anomaly_count = 0

    total_chars = 0

    for row in valid:

        evaluation = row[
            "evaluation"
        ]

        grade = evaluation.get(
            "grade"
        )

        if grade == "A":
            A += 1

        elif grade == "B":
            B += 1

        elif grade == "C":
            C += 1

        elif grade == "D":
            D += 1

        if evaluation.get(
            "basic_pass",
            False,
        ):
            basic_pass += 1

        if evaluation.get(
            "draft_document_number_hallucination",
            False,
        ):
            draft_number += 1

        if evaluation.get(
            "draft_date_hallucination",
            False,
        ):
            draft_date += 1

        if evaluation.get(
            "published_policy_claim",
            False,
        ):
            published_claim += 1

        if evaluation.get(
            "placeholder_risk",
            False,
        ):
            placeholder_count += 1

        if evaluation.get(
            "char_count",
            0,
        ) < 1000:
            short_count += 1

        if (
            evaluation.get(
                "duplicate_count",
                0,
            ) >= 2
            or evaluation.get(
                "repeated_block_count",
                0,
            ) >= 1
        ):
            duplicate_count += 1

        if evaluation.get(
            "repeated_phrase_count",
            0,
        ) >= 2:
            repeated_phrase_count += 1

        if evaluation.get(
            "relevance_score",
            1,
        ) < 0.2:
            relevance_risk += 1

        if evaluation.get(
            "truncation",
            False,
        ):
            truncation_count += 1

        if evaluation.get(
            "reached_max_tokens",
            False,
        ):
            max_token_count += 1

        if evaluation.get(
            "length_anomaly",
            {}
        ).get(
            "risk",
            False,
        ):
            length_anomaly_count += 1

        total_chars += evaluation.get(
            "char_count",
            0,
        )

    valid_count = len(valid)

    avg_chars = (
        total_chars / valid_count
        if valid_count
        else 0
    )

    basic_pass_ratio = (
        basic_pass / valid_count
        if valid_count
        else 0
    )

    # ========================================================
    # 最终判定
    #
    # 核心事实问题：
    #
    # 1. 当前文件文号
    # 2. 当前文件日期
    # 3. 当前文件发布状态
    # 4. 占位符
    # 5. 真正截断
    # 6. D
    #
    # 达到 max_new_tokens 本身不算 FAIL。
    # ========================================================

    core_problem = (
        draft_number > 0
        or draft_date > 0
        or published_claim > 0
        or placeholder_count > 0
        or truncation_count > 0
        or D > 0
    )

    if core_problem:

        final_decision = "FAIL"

    elif (
        valid_count == total
        and basic_pass_ratio >= 0.90
        and duplicate_count == 0
    ):

        final_decision = "PASS"

    else:

        final_decision = "REVIEW"

    return {

        "total":
            total,

        "valid":
            valid_count,

        "error_count":
            total - valid_count,

        "A_mature":
            A,

        "B_review":
            B,

        "C_review":
            C,

        "D_clear_problem":
            D,

        "basic_pass":
            basic_pass,

        "basic_pass_ratio":
            round(
                basic_pass_ratio,
                3,
            ),

        "draft_document_number_hallucination":
            draft_number,

        "draft_date_hallucination":
            draft_date,

        "published_policy_claim":
            published_claim,

        "placeholder_count":
            placeholder_count,

        "short_generation_count":
            short_count,

        "duplicate_generation_count":
            duplicate_count,

        "repeated_phrase_generation_count":
            repeated_phrase_count,

        "relevance_risk_count":
            relevance_risk,

        "truncation_count":
            truncation_count,

        "reached_max_token_count":
            max_token_count,

        "length_anomaly_count":
            length_anomaly_count,

        "average_char_count":
            round(
                avg_chars,
                1,
            ),

        "final_decision":
            final_decision,
    }


# ============================================================
# 25. JSONL
# ============================================================

def write_jsonl(
    results: List[Dict[str, Any]]
):

    with open(
        RESULT_FILE,
        "w",
        encoding="utf-8",
    ) as f:

        for row in results:

            f.write(
                json.dumps(
                    row,
                    ensure_ascii=False,
                )
                + "\n"
            )


# ============================================================
# 26. 报告
# ============================================================

def write_report(
    all_results: List[Dict[str, Any]]
):

    models = sorted(
        set(
            row["model"]
            for row in all_results
        )
    )

    with open(
        REPORT_FILE,
        "w",
        encoding="utf-8",
    ) as f:

        f.write(
            "=" * 80
            + "\n"
        )

        f.write(
            "政府公文生成能力验收报告 V5\n"
        )

        f.write(
            "=" * 80
            + "\n\n"
        )

        f.write(
            "测试目的："
            "判断模型是否具备较成熟的政府公文生成能力。\n"
        )

        f.write(
            f"测试数量：{len(TESTS)} 条\n"
        )

        f.write(
            "重点："
            "结构、完整性、主题相关性、重复、"
            "真正截断、占位符、"
            "当前文件自身文号/日期及发布状态。\n"
        )

        f.write(
            "特别说明："
            "达到 max_new_tokens 本身不等于截断；"
            "只有达到上限且存在明显未完成结构时，"
            "才认定为真正截断。\n"
        )

        f.write(
            "正常政策引用、已有政策文号、"
            "历史政策背景、历史年份、"
            "工作目标年份不直接视为幻觉。\n\n"
        )

        for model in models:

            results = [
                row
                for row in all_results
                if row["model"] == model
            ]

            summary = build_summary(
                results
            )

            f.write(
                "=" * 80
                + "\n"
            )

            f.write(
                f"模型：{model}\n"
            )

            f.write(
                "=" * 80
                + "\n\n"
            )

            f.write(
                json.dumps(
                    summary,
                    ensure_ascii=False,
                    indent=2,
                )
            )

            f.write(
                "\n\n"
            )

            f.write(
                "-" * 80
                + "\n"
            )

            f.write(
                "逐条结果\n"
            )

            f.write(
                "-" * 80
                + "\n\n"
            )

            for row in results:

                evaluation = row.get(
                    "evaluation",
                    {},
                )

                f.write(
                    f"{row['id']} | "
                    f"{row['category']} | "
                    f"{row['genre']}\n"
                )

                f.write(
                    f"风险等级："
                    f"{evaluation.get('grade', 'ERROR')}\n"
                )

                f.write(
                    f"字数："
                    f"{evaluation.get('char_count', 0)}\n"
                )

                f.write(
                    f"一级标题："
                    f"{evaluation.get('first_level_headings', 0)}\n"
                )

                f.write(
                    f"二级标题："
                    f"{evaluation.get('second_level_headings', 0)}\n"
                )

                f.write(
                    f"主题匹配："
                    f"{evaluation.get('relevance_score', 0)}\n"
                )

                f.write(
                    f"基本通过："
                    f"{evaluation.get('basic_pass', False)}\n"
                )

                generation = evaluation.get(
                    "generation",
                    {},
                )

                f.write(
                    f"生成Token："
                    f"{generation.get('generated_tokens', 0)}\n"
                )

                f.write(
                    f"生成停止原因："
                    f"{generation.get('finish_reason', '')}\n"
                )

                f.write(
                    f"达到Token上限："
                    f"{generation.get('reached_max_tokens', False)}\n"
                )

                f.write(
                    f"真正截断："
                    f"{evaluation.get('truncation', False)}\n"
                )

                f.write(
                    f"占位符："
                    f"{evaluation.get('placeholder_risk', False)}\n"
                )

                f.write(
                    f"自身文号："
                    f"{evaluation.get('draft_document_number_hallucination', False)}\n"
                )

                f.write(
                    f"自身日期："
                    f"{evaluation.get('draft_date_hallucination', False)}\n"
                )

                f.write(
                    f"正式发布误称："
                    f"{evaluation.get('published_policy_claim', False)}\n"
                )

                f.write(
                    f"重复句行："
                    f"{evaluation.get('duplicate_count', 0)}\n"
                )

                f.write(
                    f"重复片段："
                    f"{evaluation.get('repeated_phrase_count', 0)}\n"
                )

                if evaluation.get(
                    "critical_issues"
                ):

                    f.write(
                        "严重问题：\n"
                    )

                    for issue in evaluation[
                        "critical_issues"
                    ]:

                        f.write(
                            f"  - {issue}\n"
                        )

                if evaluation.get(
                    "review_issues"
                ):

                    f.write(
                        "人工复核：\n"
                    )

                    for issue in evaluation[
                        "review_issues"
                    ]:

                        f.write(
                            f"  - {issue}\n"
                        )

                f.write(
                    "\n"
                )

        # ====================================================
        # 部署建议
        # ====================================================

        f.write(
            "=" * 80
            + "\n"
        )

        f.write(
            "部署建议\n"
        )

        f.write(
            "=" * 80
            + "\n\n"
        )

        for model in models:

            results = [
                row
                for row in all_results
                if row["model"] == model
            ]

            summary = build_summary(
                results
            )

            decision = summary[
                "final_decision"
            ]

            if decision == "PASS":

                text = (
                    "PASS："
                    "通过基础公文生成能力验收，"
                    "可进入真实业务人工试用和部署准备。"
                )

            elif decision == "REVIEW":

                text = (
                    "REVIEW："
                    "未发现核心事实安全问题，"
                    "但仍存在重复、结构或生成质量问题，"
                    "建议人工抽检后再决定部署。"
                )

            else:

                text = (
                    "FAIL："
                    "存在当前文件事实、占位符、"
                    "真正截断或明显生成质量问题，"
                    "暂不建议直接部署。"
                )

            f.write(
                f"{model}: {text}\n\n"
            )


# ============================================================
# 27. 终端摘要
# ============================================================

def print_final_summary(
    all_results: List[Dict[str, Any]]
):

    print()

    print(
        "=" * 80
    )

    print(
        "公文生成能力验收完成"
    )

    print(
        "=" * 80
    )

    models = sorted(
        set(
            row["model"]
            for row in all_results
        )
    )

    for model in models:

        results = [
            row
            for row in all_results
            if row["model"] == model
        ]

        summary = build_summary(
            results
        )

        print()

        print(
            f"模型：{model}"
        )

        print(
            f"总数：{summary['total']}"
        )

        print(
            f"A（成熟）："
            f"{summary['A_mature']}"
        )

        print(
            f"B（建议复核）："
            f"{summary['B_review']}"
        )

        print(
            f"C（重点复核）："
            f"{summary['C_review']}"
        )

        print(
            f"D（明显问题）："
            f"{summary['D_clear_problem']}"
        )

        print(
            f"基本通过："
            f"{summary['basic_pass']}/"
            f"{summary['valid']}"
        )

        print(
            f"基本通过率："
            f"{summary['basic_pass_ratio']:.1%}"
        )

        print(
            f"平均字数："
            f"{summary['average_char_count']}"
        )

        print(
            f"自身文号问题："
            f"{summary['draft_document_number_hallucination']}"
        )

        print(
            f"自身日期问题："
            f"{summary['draft_date_hallucination']}"
        )

        print(
            f"占位符问题："
            f"{summary['placeholder_count']}"
        )

        print(
            f"正式发布误称："
            f"{summary['published_policy_claim']}"
        )

        print(
            f"重复生成："
            f"{summary['duplicate_generation_count']}"
        )

        print(
            f"重复片段："
            f"{summary['repeated_phrase_generation_count']}"
        )

        print(
            f"达到 Token 上限："
            f"{summary['reached_max_token_count']}"
        )

        print(
            f"真正截断："
            f"{summary['truncation_count']}"
        )

        print(
            f"主题相关性风险："
            f"{summary['relevance_risk_count']}"
        )

        print(
            f"最终结论："
            f"{summary['final_decision']}"
        )

    print()

    print(
        "=" * 80
    )

    print(
        "完整 JSONL："
    )

    print(
        RESULT_FILE
    )

    print()

    print(
        "完整报告："
    )

    print(
        REPORT_FILE
    )

    print()

    print(
        "每条完整正文目录："
    )

    print(
        OUT_DIR
    )

    print(
        "=" * 80
    )


# ============================================================
# 28. 释放模型
# ============================================================

def release_model(
    model,
    tokenizer,
):

    try:
        del model
    except Exception:
        pass

    try:
        del tokenizer
    except Exception:
        pass

    gc.collect()

    if torch.cuda.is_available():

        try:
            torch.cuda.empty_cache()
        except Exception:
            pass

        try:
            torch.cuda.ipc_collect()
        except Exception:
            pass


# ============================================================
# 29. 参数
# ============================================================

def parse_args():

    parser = argparse.ArgumentParser(
        description="政府公文生成能力验收测试 V5"
    )

    parser.add_argument(
        "--model",
        choices=[
            "base",
            "v1",
            "v11",
            "all",
        ],
        default="v11",
        help="测试模型：base / v1 / v11 / all",
    )

    return parser.parse_args()


# ============================================================
# 30. 主函数
# ============================================================

def main():

    args = parse_args()

    print()

    print(
        "=" * 80
    )

    print(
        "政府公文生成能力验收测试 V5"
    )

    print(
        "=" * 80
    )

    print()

    print(
        f"Base: {BASE_MODEL}"
    )

    print(
        f"V1:   {V1_ADAPTER}"
    )

    print(
        f"V1.1: {V11_ADAPTER}"
    )

    print()

    print(
        f"测试数量：{len(TESTS)}"
    )

    print(
        f"MAX_NEW_TOKENS："
        f"{MAX_NEW_TOKENS}"
    )

    print(
        f"REPETITION_PENALTY："
        f"{REPETITION_PENALTY}"
    )

    print(
        f"NO_REPEAT_NGRAM_SIZE："
        f"{NO_REPEAT_NGRAM_SIZE}"
    )

    print(
        f"输出目录：{OUT_DIR}"
    )

    print()

    if args.model == "all":

        model_names = [
            "base",
            "v1",
            "v11",
        ]

    else:

        model_names = [
            args.model
        ]

    all_results = []

    for model_name in model_names:

        tokenizer = None
        model = None

        try:

            tokenizer, model = load_model(
                model_name
            )

            results = run_model(
                model_name,
                model,
                tokenizer,
            )

            all_results.extend(
                results
            )

        except Exception as e:

            print()

            print(
                "=" * 80
            )

            print(
                f"模型 {model_name} "
                f"加载/运行失败"
            )

            print(
                repr(e)
            )

            print(
                "=" * 80
            )

            for test in TESTS:

                all_results.append({

                    "model":
                        model_name,

                    "id":
                        test["id"],

                    "category":
                        test["category"],

                    "genre":
                        test["genre"],

                    "prompt":
                        test["prompt"],

                    "generation":
                        "",

                    "evaluation":
                        {},

                    "generation_seconds":
                        0,

                    "error":
                        repr(e),
                })

        finally:

            release_model(
                model,
                tokenizer,
            )

            model = None
            tokenizer = None

    write_jsonl(
        all_results
    )

    write_report(
        all_results
    )

    print_final_summary(
        all_results
    )


# ============================================================
# 31. Entry
# ============================================================

if __name__ == "__main__":

    main()
