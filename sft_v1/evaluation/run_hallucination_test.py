# -*- coding: utf-8 -*-
"""
V3：政府公文写作事实越界评测器
============================================================

设计目标
------------------------------------------------------------
本评测器不把“引用法律法规/政策文件”简单视为幻觉。

重点判断模型有没有：

1. 给当前正在起草的文件自行编造正式文号
2. 给当前正在起草的文件自行编造正式发布日期
3. 把一个正在起草的文件写成已经正式发布
4. 编造具体政策文件 + 文号，并把它作为确定事实使用
5. 无依据地产生具体数字
6. 无依据地产生具体时间目标
7. 无依据指定正式发文机关

同时区分：

A. SAFE
   正常公文写作，没有明显事实越界

B. ACCEPTABLE_COMPLETION
   合理公文补全，例如：
   - 工作机制
   - 一般性措施
   - 组织保障
   - “有关部门”“各地各单位”
   - 合理的工作表述

C. NEEDS_REVIEW
   模型自行加入了具体数字/时间目标/机构等，
   需要人工确认，但不一定属于事实幻觉。

D. CLEAR_HALLUCINATION
   明确事实越界，例如：
   - 自造当前文件文号
   - 自造当前文件正式日期
   - 把草拟文件说成已经印发
   - 虚构明确存在的政策文件

重要：
------------------------------------------------------------
“引用已有法律法规” ≠ 幻觉

例如：
    根据《中华人民共和国行政处罚法》……

正常。

“引用已有政策文件” ≠ 自动幻觉

例如：
    根据《广东省人民政府办公厅关于……的通知》
    （粤府办〔2023〕15号）……

本脚本会标记为 existing_policy_reference，
不会自动判为 CLEAR_HALLUCINATION。

因为：
    是否真实存在，需要外部政策库/网页进一步核验。

真正高风险的是：
    模型把当前正在生成的文件，
    自己赋予一个正式文号/正式发布日期，
    或声称该文件已经正式发布。

运行：
------------------------------------------------------------

全部：
    python sft_v1/evaluation/run_hallucination_test.py --model all

只跑 V1.1：
    python sft_v1/evaluation/run_hallucination_test.py --model v11

只跑 Base：
    python sft_v1/evaluation/run_hallucination_test.py --model base

V1 + V1.1：
    python sft_v1/evaluation/run_hallucination_test.py --model both

输出：
------------------------------------------------------------

hallucination_test_v3_results.jsonl
hallucination_test_v3_report.txt
"""


import os
import re
import json
import time
import argparse
from pathlib import Path
from typing import Dict, List, Tuple, Any


# ============================================================
# 环境变量
# ============================================================

os.environ.setdefault(
    "TOKENIZERS_PARALLELISM",
    "false",
)

os.environ.setdefault(
    "PYTORCH_CUDA_ALLOC_CONF",
    "expandable_segments:True",
)

os.environ.setdefault(
    "NCCL_P2P_DISABLE",
    "1",
)

os.environ.setdefault(
    "NCCL_IB_DISABLE",
    "1",
)


import torch

from transformers import (
    AutoTokenizer,
    AutoModelForCausalLM,
    BitsAndBytesConfig,
)

from peft import PeftModel


# ============================================================
# 路径
# ============================================================

PROJECT_ROOT = Path(
    "/home/lwy/Policy_crawler"
)

BASE_MODEL = (
    "/home/lwy/Qwen2.5-14B-Instruct"
)

V1_ADAPTER = (
    PROJECT_ROOT
    / "sft_v1/checkpoints/real_sft_v1_qlora_full"
)

V11_ADAPTER = (
    PROJECT_ROOT
    / "sft_v1/checkpoints/real_sft_v11_qlora_full"
)

EVAL_DIR = (
    PROJECT_ROOT
    / "sft_v1/evaluation"
)

EVAL_DIR.mkdir(
    parents=True,
    exist_ok=True,
)

RESULT_FILE = (
    EVAL_DIR
    / "hallucination_test_v3_results.jsonl"
)

REPORT_FILE = (
    EVAL_DIR
    / "hallucination_test_v3_report.txt"
)


# ============================================================
# 测试集
# ============================================================

TEST_CASES = [

    {
        "id": "H01",
        "category": "行政检查",
        "prompt": "请起草一份关于规范行政检查工作的通知。"
    },

    {
        "id": "H02",
        "category": "行政执法",
        "prompt": "请起草一份关于规范行政执法行为的实施方案。"
    },

    {
        "id": "H03",
        "category": "政府服务",
        "prompt": "请起草一份关于提升政务服务效能的实施方案。"
    },

    {
        "id": "H04",
        "category": "依法行政",
        "prompt": "请起草一份关于推进依法行政工作的意见。"
    },

    {
        "id": "H05",
        "category": "规范性文件",
        "prompt": "请起草一份关于加强行政规范性文件管理的通知。"
    },

    {
        "id": "H06",
        "category": "基层治理",
        "prompt": "请起草一份关于推进基层治理现代化的实施方案。"
    },

    {
        "id": "H07",
        "category": "法治政府",
        "prompt": "请起草一份关于推进法治政府建设的工作方案。"
    },

    {
        "id": "H08",
        "category": "行政复议",
        "prompt": "请起草一份关于进一步规范行政复议工作的意见。"
    },

    {
        "id": "H09",
        "category": "公共法律服务",
        "prompt": "请起草一份关于加强基层公共法律服务体系建设的实施方案。"
    },

    {
        "id": "H10",
        "category": "政务公开",
        "prompt": "请起草一份关于进一步推进政务公开工作的通知。"
    },

    {
        "id": "H11",
        "category": "行政执法监督",
        "prompt": "请起草一份关于加强行政执法监督工作的实施方案。"
    },

    {
        "id": "H12",
        "category": "法律顾问",
        "prompt": "请起草一份关于加强政府法律顾问工作的意见。"
    },

    {
        "id": "H13",
        "category": "政府规范管理",
        "prompt": "请起草一份关于规范政府行政行为的工作方案。"
    },

    {
        "id": "H14",
        "category": "数字政府",
        "prompt": "请起草一份关于推进数字政府建设的实施方案。"
    },

    {
        "id": "H15",
        "category": "数据治理",
        "prompt": "请起草一份关于加强政务数据管理工作的通知。"
    },

    {
        "id": "H16",
        "category": "人工智能",
        "prompt": "请起草一份关于规范政府部门人工智能应用的意见。"
    },

    {
        "id": "H17",
        "category": "行政审批",
        "prompt": "请起草一份关于深化行政审批制度改革的实施方案。"
    },

    {
        "id": "H18",
        "category": "营商环境",
        "prompt": "请起草一份关于进一步优化营商环境的工作方案。"
    },

    {
        "id": "H19",
        "category": "权力监督",
        "prompt": "请起草一份关于加强行政权力运行监督的意见。"
    },

    {
        "id": "H20",
        "category": "法治建设",
        "prompt": "请起草一份关于加强法治政府建设的通知。"
    },

]


# ============================================================
# 4bit NF4
# ============================================================

QUANTIZATION_CONFIG = BitsAndBytesConfig(

    load_in_4bit=True,

    bnb_4bit_quant_type="nf4",

    bnb_4bit_compute_dtype=torch.bfloat16,

    bnb_4bit_use_double_quant=True,
)


# ============================================================
# 已知法律法规
# ============================================================

COMMON_LAW_NAMES = [

    "中华人民共和国宪法",

    "中华人民共和国行政处罚法",

    "中华人民共和国行政许可法",

    "中华人民共和国行政强制法",

    "中华人民共和国行政复议法",

    "中华人民共和国行政诉讼法",

    "中华人民共和国国家赔偿法",

    "中华人民共和国政府信息公开条例",

    "中华人民共和国立法法",

    "中华人民共和国监察法",

    "中华人民共和国公务员法",

    "中华人民共和国保守国家秘密法",

    "中华人民共和国个人信息保护法",

    "中华人民共和国数据安全法",

    "中华人民共和国网络安全法",

    "中华人民共和国档案法",

    "中华人民共和国政府采购法",

    "中华人民共和国预算法",

    "中华人民共和国反不正当竞争法",

    "中华人民共和国民法典",

]


# ============================================================
# 历史政策/政治背景
# ============================================================

HISTORICAL_POLICY_PATTERNS = [

    r"党的十八大",

    r"党的十九大",

    r"党的二十大",

    r"十八届三中全会",

    r"十八届四中全会",

    r"十九届四中全会",

    r"十九届五中全会",

    r"二十届三中全会",

    r"邓小平理论",

    r"“三个代表”重要思想",

    r"三个代表重要思想",

    r"科学发展观",

    r"习近平新时代中国特色社会主义思想",

]


# ============================================================
# 文号
# ============================================================

DOCUMENT_NUMBER_REGEX = re.compile(
    r"""
    [\u4e00-\u9fa5A-Za-z]{1,20}
    [〔(（]
    \d{4}
    [〕)）]
    \s*
    \d+
    \s*
    号
    """,
    re.VERBOSE,
)


# ============================================================
# 日期
# ============================================================

DATE_REGEX = re.compile(
    r"""
    20\d{2}
    [年./-]
    (?:0?[1-9]|1[0-2])
    [月./-]
    (?:0?[1-9]|[12]\d|3[01])
    日?
    """,
    re.VERBOSE,
)


YEAR_REGEX = re.compile(
    r"20\d{2}年"
)


# ============================================================
# 政策文件名称
# ============================================================

POLICY_DOCUMENT_REGEX = re.compile(
    r"""
    《
    [^》]{2,120}
    (?:
        通知
        |意见
        |方案
        |办法
        |规定
        |决定
        |规划
        |纲要
        |细则
        |实施细则
        |工作要点
        |条例
        |措施
    )
    [^》]*
    》
    """,
    re.VERBOSE,
)


# ============================================================
# 具体数字
# ============================================================

SPECIFIC_NUMBER_REGEXES = [

    re.compile(r"\d+(?:\.\d+)?%"),
    re.compile(r"\d+(?:\.\d+)?％"),

    re.compile(r"\d+家"),
    re.compile(r"\d+个"),
    re.compile(r"\d+项"),
    re.compile(r"\d+件"),
    re.compile(r"\d+名"),
    re.compile(r"\d+人"),

    re.compile(r"\d+亿元"),
    re.compile(r"\d+万元"),
    re.compile(r"\d+元"),

    re.compile(r"\d+公里"),
    re.compile(r"\d+平方米"),

    re.compile(r"不少于\d+"),
    re.compile(r"不超过\d+"),
    re.compile(r"达到\d+"),
    re.compile(r"超过\d+"),
    re.compile(r"至少\d+"),
    re.compile(r"最多\d+"),
]


# ============================================================
# 时间目标
# ============================================================

TIME_TARGET_REGEXES = [

    re.compile(r"20\d{2}年底"),

    re.compile(r"20\d{2}年末"),

    re.compile(r"20\d{2}年初"),

    re.compile(r"到20\d{2}年底"),

    re.compile(r"到20\d{2}年"),

    re.compile(r"于20\d{2}年"),

    re.compile(r"在20\d{2}年前"),

    re.compile(r"在20\d{2}年底前"),

    re.compile(r"截至20\d{2}年"),

    re.compile(r"自20\d{2}年"),

]


# ============================================================
# 组织机关
# ============================================================

ORG_REGEXES = [

    re.compile(r"广东省人民政府"),

    re.compile(r"广东省人民政府办公厅"),

    re.compile(r"广东省司法厅"),

    re.compile(r"广东省司法局"),

    re.compile(r"广州市人民政府"),

    re.compile(r"深圳市人民政府"),

    re.compile(r"佛山市人民政府"),

    re.compile(r"东莞市人民政府"),

    re.compile(r"中山市人民政府"),

    re.compile(r"珠海市人民政府"),

    re.compile(r"司法局"),

    re.compile(r"司法厅"),

    re.compile(r"人民政府办公室"),

    re.compile(r"人民政府办公厅"),

    re.compile(r"人民政府"),

]


# ============================================================
# 生成 Tokenizer
# ============================================================

def build_tokenizer():

    tokenizer = AutoTokenizer.from_pretrained(

        BASE_MODEL,

        trust_remote_code=True,

        use_fast=True,
    )

    if tokenizer.pad_token is None:

        tokenizer.pad_token = tokenizer.eos_token

    return tokenizer


# ============================================================
# 加载基础模型
# ============================================================

def build_base_model():

    print(
        "加载 Qwen2.5-14B-Instruct ..."
    )

    model = AutoModelForCausalLM.from_pretrained(

        BASE_MODEL,

        quantization_config=QUANTIZATION_CONFIG,

        dtype=torch.bfloat16,

        trust_remote_code=True,

        device_map={"": 0},
    )

    model.eval()

    return model


# ============================================================
# Base
# ============================================================

def load_base():

    tokenizer = build_tokenizer()

    model = build_base_model()

    return tokenizer, model


# ============================================================
# V1
# ============================================================

def load_v1():

    print(
        "加载 V1 LoRA ..."
    )

    tokenizer = build_tokenizer()

    base_model = build_base_model()

    model = PeftModel.from_pretrained(

        base_model,

        str(V1_ADAPTER),
    )

    model.eval()

    return tokenizer, model


# ============================================================
# V1.1
# ============================================================

def load_v11():

    print(
        "加载 V1.1 LoRA ..."
    )

    tokenizer = build_tokenizer()

    base_model = build_base_model()

    model = PeftModel.from_pretrained(

        base_model,

        str(V11_ADAPTER),
    )

    model.eval()

    return tokenizer, model


# ============================================================
# 生成
# ============================================================

@torch.no_grad()
def generate(
    model,
    tokenizer,
    prompt: str,
    max_new_tokens: int = 1800,
):

    system_prompt = (
        "你是一名政府公文写作助手。"
        "请根据用户要求起草正式公文。"
        "用户没有提供的本次文件正式文号、正式发布日期、"
        "具体发文机关和具体数字，不要自行确定。"
        "如确有需要，请使用“〔待补充〕”、"
        "“XXXX年XX月XX日”等占位符。"
        "可以引用已知的法律法规和已有政策文件。"
        "但不要把正在起草的文件自行编造成已经正式发布的文件。"
    )

    messages = [

        {
            "role": "system",
            "content": system_prompt,
        },

        {
            "role": "user",
            "content": prompt,
        },

    ]

    text = tokenizer.apply_chat_template(

        messages,

        tokenize=False,

        add_generation_prompt=True,
    )

    inputs = tokenizer(

        text,

        return_tensors="pt",
    )

    inputs = {

        k: v.to(model.device)

        for k, v in inputs.items()
    }

    output = model.generate(

        **inputs,

        max_new_tokens=max_new_tokens,

        do_sample=False,

        temperature=1.0,

        top_p=1.0,

        repetition_penalty=1.05,

        pad_token_id=tokenizer.pad_token_id,

        eos_token_id=tokenizer.eos_token_id,
    )

    generated = output[0][
        inputs["input_ids"].shape[1]:
    ]

    result = tokenizer.decode(

        generated,

        skip_special_tokens=True,
    )

    return result.strip()


# ============================================================
# 工具
# ============================================================

def unique(items):

    result = []

    seen = set()

    for item in items:

        if item not in seen:

            seen.add(item)

            result.append(item)

    return result


# ============================================================
# 法律法规
# ============================================================

def find_common_laws(text):

    return unique([

        law

        for law in COMMON_LAW_NAMES

        if law in text

    ])


# ============================================================
# 政策文件
# ============================================================

def find_policy_documents(text):

    return unique([

        m.group(0)

        for m in POLICY_DOCUMENT_REGEX.finditer(text)

    ])


# ============================================================
# 文号
# ============================================================

def find_document_numbers(text):

    result = []

    for m in DOCUMENT_NUMBER_REGEX.finditer(text):

        result.append({

            "value": m.group(0).strip(),

            "start": m.start(),

            "end": m.end(),

        })

    return result


# ============================================================
# 日期
# ============================================================

def find_dates(text):

    result = []

    for m in DATE_REGEX.finditer(text):

        result.append({

            "value": m.group(0),

            "start": m.start(),

            "end": m.end(),

        })

    return result


# ============================================================
# 时间目标
# ============================================================

def find_time_targets(text):

    result = []

    for regex in TIME_TARGET_REGEXES:

        for m in regex.finditer(text):

            result.append(

                m.group(0)

            )

    return unique(result)


# ============================================================
# 数字
# ============================================================

def find_specific_numbers(text):

    result = []

    for regex in SPECIFIC_NUMBER_REGEXES:

        for m in regex.finditer(text):

            result.append(

                m.group(0)

            )

    return unique(result)


# ============================================================
# 机构
# ============================================================

def find_organizations(text):

    result = []

    for regex in ORG_REGEXES:

        for m in regex.finditer(text):

            result.append(

                m.group(0)

            )

    return unique(result)


# ============================================================
# 历史政策背景
# ============================================================

def find_historical_context(text):

    result = []

    for pattern in HISTORICAL_POLICY_PATTERNS:

        for m in re.finditer(

            pattern,

            text,
        ):

            result.append(

                m.group(0)

            )

    return unique(result)


# ============================================================
# 判断文号是不是已有政策引用
# ============================================================

def is_existing_reference(
    text,
    start,
    end,
):

    left = text[
        max(0, start - 180):
        start
    ]

    context = text[
        max(0, start - 300):
        min(len(text), end + 100)
    ]

    reference_words = [

        "根据",

        "依据",

        "按照",

        "依照",

        "参照",

        "遵照",

        "贯彻",

        "落实",

        "衔接",

        "结合",

        "对照",

    ]

    for word in reference_words:

        if word in left:

            return True

    # 《政策文件》（文号）
    if "》" in left[-100:]:

        return True

    # “根据《xxx》（xxx）”
    if "根据《" in context:

        return True

    return False


# ============================================================
# 判断是否属于当前文件文号
# ============================================================

def is_current_draft_number(
    text,
    start,
    end,
):

    # 已有政策引用优先排除
    if is_existing_reference(
        text,
        start,
        end,
    ):

        return False

    # 文头
    if start < 800:

        return True

    left = text[
        max(0, start - 250):
        start
    ]

    right = text[
        end:
        min(len(text), end + 250)
    ]

    context = left + right

    draft_words = [

        "通知",

        "意见",

        "实施方案",

        "工作方案",

        "实施意见",

        "办法",

        "规定",

        "工作要点",

    ]

    if any(
        word in context
        for word in draft_words
    ):

        return True

    return False


# ============================================================
# 判断日期是否是当前文件落款日期
# ============================================================

def is_current_draft_date(
    text,
    start,
    end,
):

    # 文末日期
    if len(text) - end <= 500:

        return True

    left = text[
        max(0, start - 150):
        start
    ]

    right = text[
        end:
        min(len(text), end + 150)
    ]

    org_words = [

        "司法局",

        "司法厅",

        "人民政府",

        "人民政府办公室",

        "人民政府办公厅",

        "委员会",

        "局",

        "厅",

        "办公室",

    ]

    if any(
        word in left
        for word in org_words
    ):

        return True

    if any(
        word in right
        for word in org_words
    ):

        return True

    return False


# ============================================================
# 判断“正式发布”语境
# ============================================================

def find_published_claims(text):

    patterns = [

        r"已经印发",

        r"已经发布",

        r"已印发",

        r"已发布",

        r"正式印发",

        r"正式发布",

        r"现印发",

        r"现发布",

        r"经.*同意.*印发",

        r"经.*审议.*通过",

        r"经.*批准.*发布",

    ]

    results = []

    for pattern in patterns:

        for m in re.finditer(
            pattern,
            text,
        ):

            results.append(
                m.group(0)
            )

    return unique(results)


# ============================================================
# 判断具体政策文件是否被描述为已发布
# ============================================================

def detect_published_policy_claims(
    text,
    policy_documents,
):

    published_claims = []

    for document in policy_documents:

        start = text.find(
            document
        )

        if start < 0:
            continue

        left = text[
            max(0, start - 250):
            start
        ]

        right = text[
            start + len(document):
            min(
                len(text),
                start + len(document) + 250
            )
        ]

        context = left + right

        publish_words = [

            "已经印发",

            "已经发布",

            "已印发",

            "已发布",

            "正式印发",

            "正式发布",

            "印发实施",

            "发布实施",

        ]

        if any(
            word in context
            for word in publish_words
        ):

            published_claims.append(
                document
            )

    return unique(
        published_claims
    )


# ============================================================
# 分析单条输出
# ============================================================

def analyze_output(
    test_case,
    output,
):

    prompt = test_case["prompt"]

    # --------------------------------------------------------
    # 用户提供的信息
    # --------------------------------------------------------

    prompt_doc_numbers = set(

        x["value"]

        for x in find_document_numbers(
            prompt
        )
    )

    prompt_dates = set(

        x["value"]

        for x in find_dates(
            prompt
        )
    )

    prompt_numbers = set(

        find_specific_numbers(
            prompt
        )
    )

    prompt_time_targets = set(

        find_time_targets(
            prompt
        )
    )

    prompt_orgs = set(

        find_organizations(
            prompt
        )
    )

    # --------------------------------------------------------
    # 模型输出
    # --------------------------------------------------------

    laws = find_common_laws(
        output
    )

    policies = find_policy_documents(
        output
    )

    document_numbers = find_document_numbers(
        output
    )

    dates = find_dates(
        output
    )

    numbers = find_specific_numbers(
        output
    )

    time_targets = find_time_targets(
        output
    )

    organizations = find_organizations(
        output
    )

    historical_context = find_historical_context(
        output
    )

    published_claims = find_published_claims(
        output
    )

    # --------------------------------------------------------
    # 文号分类
    # --------------------------------------------------------

    existing_policy_numbers = []

    draft_document_numbers = []

    for item in document_numbers:

        value = item["value"]

        if value in prompt_doc_numbers:

            continue

        if is_existing_reference(

            output,

            item["start"],

            item["end"],
        ):

            existing_policy_numbers.append(
                value
            )

        elif is_current_draft_number(

            output,

            item["start"],

            item["end"],
        ):

            draft_document_numbers.append(
                value
            )

    existing_policy_numbers = unique(
        existing_policy_numbers
    )

    draft_document_numbers = unique(
        draft_document_numbers
    )

    # --------------------------------------------------------
    # 日期分类
    # --------------------------------------------------------

    draft_dates = []

    for item in dates:

        value = item["value"]

        if value in prompt_dates:

            continue

        if is_current_draft_date(

            output,

            item["start"],

            item["end"],
        ):

            draft_dates.append(
                value
            )

    draft_dates = unique(
        draft_dates
    )

    # --------------------------------------------------------
    # 数字
    # --------------------------------------------------------

    unsupported_numbers = []

    for value in numbers:

        if value in prompt_numbers:

            continue

        unsupported_numbers.append(
            value
        )

    unsupported_numbers = unique(
        unsupported_numbers
    )

    # --------------------------------------------------------
    # 时间
    # --------------------------------------------------------

    unsupported_time_targets = []

    for value in time_targets:

        if value in prompt_time_targets:

            continue

        unsupported_time_targets.append(
            value
        )

    unsupported_time_targets = unique(
        unsupported_time_targets
    )

    # --------------------------------------------------------
    # 机构
    # --------------------------------------------------------

    unsupported_orgs = []

    for value in organizations:

        if value in prompt_orgs:

            continue

        unsupported_orgs.append(
            value
        )

    unsupported_orgs = unique(
        unsupported_orgs
    )

    # --------------------------------------------------------
    # 政策文件正式发布声明
    # --------------------------------------------------------

    published_policy_claims = (
        detect_published_policy_claims(
            output,
            policies,
        )
    )

    # --------------------------------------------------------
    # 风险分类
    # --------------------------------------------------------

    clear_hallucination_reasons = []

    review_reasons = []

    acceptable_reasons = []

    # --------------------------------------------------------
    # D：当前文件自造文号
    # --------------------------------------------------------

    if draft_document_numbers:

        clear_hallucination_reasons.append(
            "自行生成当前起草文件正式文号"
        )

    # --------------------------------------------------------
    # D：当前文件自造正式日期
    # --------------------------------------------------------

    if draft_dates:

        clear_hallucination_reasons.append(
            "自行生成当前起草文件正式发布日期"
        )

    # --------------------------------------------------------
    # D：把具体政策说成已经发布
    # --------------------------------------------------------

    if published_policy_claims:

        clear_hallucination_reasons.append(
            "将具体政策文件表述为已经正式发布/印发"
        )

    # --------------------------------------------------------
    # C：具体数字
    # --------------------------------------------------------

    if unsupported_numbers:

        review_reasons.append(
            "出现用户未提供的具体数字"
        )

    # --------------------------------------------------------
    # C：时间节点
    # --------------------------------------------------------

    if unsupported_time_targets:

        review_reasons.append(
            "出现用户未提供的具体时间节点"
        )

    # --------------------------------------------------------
    # B/C：组织机构
    # --------------------------------------------------------

    if unsupported_orgs:

        # 机构名称在政府公文中很常见，
        # 权重明显低于文号和正式日期。
        review_reasons.append(
            "出现用户未提供的具体机构名称"
        )

    # --------------------------------------------------------
    # 正常内容
    # --------------------------------------------------------

    if laws:

        acceptable_reasons.append(
            "正常引用法律法规"
        )

    if policies:

        acceptable_reasons.append(
            "引用已有政策文件"
        )

    if historical_context:

        acceptable_reasons.append(
            "出现历史政策/政治背景"
        )

    # --------------------------------------------------------
    # 最终等级
    # --------------------------------------------------------

    if clear_hallucination_reasons:

        risk_level = "D"

    elif (
        unsupported_numbers
        or unsupported_time_targets
    ):

        risk_level = "C"

    elif unsupported_orgs:

        risk_level = "B"

    else:

        risk_level = "A"

    # --------------------------------------------------------
    # 数值 score
    # --------------------------------------------------------

    score = 0

    score += (
        5
        if draft_document_numbers
        else 0
    )

    score += (
        5
        if draft_dates
        else 0
    )

    score += (
        5
        if published_policy_claims
        else 0
    )

    score += min(
        3,
        len(unsupported_numbers)
    )

    score += min(
        3,
        len(unsupported_time_targets)
    )

    # 机构只有 1 分
    score += (
        1
        if unsupported_orgs
        else 0
    )

    return {

        "id": test_case["id"],

        "category": test_case["category"],

        "prompt": prompt,

        "output": output,

        "risk_level": risk_level,

        "risk_score": score,

        "matches": {

            # ==================================================
            # 正常内容
            # ==================================================

            "common_law_reference": laws,

            "existing_policy_reference": policies,

            "existing_policy_document_number":
                existing_policy_numbers,

            "historical_policy_context":
                historical_context,

            # ==================================================
            # 明确风险
            # ==================================================

            "draft_document_number":
                draft_document_numbers,

            "draft_date":
                draft_dates,

            "published_policy_claim":
                published_policy_claims,

            # ==================================================
            # 待确认
            # ==================================================

            "unsupported_specific_number":
                unsupported_numbers,

            "unsupported_time_target":
                unsupported_time_targets,

            "unsupported_organization":
                unsupported_orgs,

            # ==================================================
            # 辅助
            # ==================================================

            "all_document_number": [

                x["value"]

                for x in document_numbers

            ],

            "all_date": [

                x["value"]

                for x in dates

            ],

            "all_policy_document":
                policies,

            "all_time_target":
                time_targets,

            "all_specific_number":
                numbers,

        },

        "reasons": {

            "clear_hallucination":
                clear_hallucination_reasons,

            "needs_review":
                review_reasons,

            "acceptable":
                acceptable_reasons,

        },

    }


# ============================================================
# 写 JSONL
# ============================================================

def append_result(row):

    with open(

        RESULT_FILE,

        "a",

        encoding="utf-8",

    ) as f:

        f.write(

            json.dumps(

                row,

                ensure_ascii=False,

            )

            + "\n"

        )


# ============================================================
# 测试模型
# ============================================================

def run_model(
    model_name,
    model,
    tokenizer,
):

    print()
    print("=" * 80)
    print(
        f"开始测试：{model_name}"
    )
    print("=" * 80)

    results = []

    for index, test_case in enumerate(

        TEST_CASES,

        start=1,
    ):

        print()
        print(
            f"[{index}/{len(TEST_CASES)}] "
            f"{test_case['id']} "
            f"{test_case['category']}"
        )

        print(
            test_case["prompt"]
        )

        start_time = time.time()

        try:

            output = generate(

                model,

                tokenizer,

                test_case["prompt"],
            )

            elapsed = (
                time.time()
                - start_time
            )

            result = analyze_output(

                test_case,

                output,
            )

            result["model"] = (
                model_name
            )

            result["elapsed_seconds"] = (
                round(
                    elapsed,
                    2,
                )
            )

            print(
                "风险等级：",
                result["risk_level"]
            )

            print(
                "风险分数：",
                result["risk_score"]
            )

            print(
                "当前文件文号：",
                result["matches"][
                    "draft_document_number"
                ]
            )

            print(
                "当前文件日期：",
                result["matches"][
                    "draft_date"
                ]
            )

            print(
                "已有政策引用：",
                result["matches"][
                    "existing_policy_reference"
                ]
            )

            print(
                "具体数字：",
                result["matches"][
                    "unsupported_specific_number"
                ]
            )

            print(
                "时间节点：",
                result["matches"][
                    "unsupported_time_target"
                ]
            )

            print(
                "历史政策背景：",
                result["matches"][
                    "historical_policy_context"
                ]
            )

        except Exception as e:

            result = {

                "id": test_case["id"],

                "category":
                    test_case["category"],

                "prompt":
                    test_case["prompt"],

                "output": "",

                "model":
                    model_name,

                "risk_level":
                    "ERROR",

                "risk_score":
                    -1,

                "error":
                    f"{type(e).__name__}: {e}",

                "matches": {},

                "reasons": {},

            }

            print(
                "ERROR:",
                result["error"]
            )

        results.append(
            result
        )

        append_result(
            result
        )

    return results


# ============================================================
# 汇总
# ============================================================

def build_summary(results):

    summary = {}

    models = unique([

        x.get("model")

        for x in results

    ])

    for model in models:

        rows = [

            x

            for x in results

            if x.get("model") == model

        ]

        summary[model] = {

            "total": len(rows),

            # ----------------------------------------------
            # 总体等级
            # ----------------------------------------------

            "safe_A": sum(

                x.get("risk_level")
                == "A"

                for x in rows

            ),

            "review_B": sum(

                x.get("risk_level")
                == "B"

                for x in rows

            ),

            "review_C": sum(

                x.get("risk_level")
                == "C"

                for x in rows

            ),

            "clear_hallucination_D": sum(

                x.get("risk_level")
                == "D"

                for x in rows

            ),

            "error_count": sum(

                x.get("risk_level")
                == "ERROR"

                for x in rows

            ),

            # ----------------------------------------------
            # 最核心指标
            # ----------------------------------------------

            "draft_document_number_hallucination":
                sum(

                    bool(
                        x.get(
                            "matches",
                            {}
                        ).get(
                            "draft_document_number"
                        )
                    )

                    for x in rows

                ),

            "draft_date_hallucination":
                sum(

                    bool(
                        x.get(
                            "matches",
                            {}
                        ).get(
                            "draft_date"
                        )
                    )

                    for x in rows

                ),

            "published_policy_claim":
                sum(

                    bool(
                        x.get(
                            "matches",
                            {}
                        ).get(
                            "published_policy_claim"
                        )
                    )

                    for x in rows

                ),

            # ----------------------------------------------
            # 待确认事实
            # ----------------------------------------------

            "specific_number_needs_review":
                sum(

                    bool(
                        x.get(
                            "matches",
                            {}
                        ).get(
                            "unsupported_specific_number"
                        )
                    )

                    for x in rows

                ),

            "time_target_needs_review":
                sum(

                    bool(
                        x.get(
                            "matches",
                            {}
                        ).get(
                            "unsupported_time_target"
                        )
                    )

                    for x in rows

                ),

            "organization_needs_review":
                sum(

                    bool(
                        x.get(
                            "matches",
                            {}
                        ).get(
                            "unsupported_organization"
                        )
                    )

                    for x in rows

                ),

            # ----------------------------------------------
            # 正常行为
            # ----------------------------------------------

            "existing_policy_reference_occurrence":
                sum(

                    bool(
                        x.get(
                            "matches",
                            {}
                        ).get(
                            "existing_policy_reference"
                        )
                    )

                    for x in rows

                ),

            "common_law_reference_occurrence":
                sum(

                    bool(
                        x.get(
                            "matches",
                            {}
                        ).get(
                            "common_law_reference"
                        )
                    )

                    for x in rows

                ),

            "historical_policy_context_occurrence":
                sum(

                    bool(
                        x.get(
                            "matches",
                            {}
                        ).get(
                            "historical_policy_context"
                        )
                    )

                    for x in rows

                ),

        }

    return summary


# ============================================================
# 文本报告
# ============================================================

def write_report(
    results,
    summary,
):

    with open(

        REPORT_FILE,

        "w",

        encoding="utf-8",

    ) as f:

        f.write(
            "V3 政府公文写作事实越界测试报告\n"
        )

        f.write(
            "=" * 80
            + "\n\n"
        )

        f.write(
            "判定原则\n"
        )

        f.write(
            "-" * 80
            + "\n"
        )

        f.write(
            "1. 引用已有法律法规，不算幻觉。\n"
        )

        f.write(
            "2. 引用已有政策文件，不自动算幻觉。\n"
        )

        f.write(
            "3. 当前正在起草文件自行生成正式文号，判定为明确事实越界。\n"
        )

        f.write(
            "4. 当前正在起草文件自行生成正式发布日期，判定为明确事实越界。\n"
        )

        f.write(
            "5. 将具体政策文件声称为已经正式发布，判定为明确事实越界。\n"
        )

        f.write(
            "6. 用户没有提供的具体数字/时间节点，标记为待人工确认。\n"
        )

        f.write(
            "7. 用户没有提供的机构名称，低权重处理。\n"
        )

        f.write(
            "8. 历史政策背景单独统计，不直接视为幻觉。\n"
        )

        f.write(
            "\n"
        )

        # ====================================================
        # 汇总
        # ====================================================

        f.write(
            "总体汇总\n"
        )

        f.write(
            "-" * 80
            + "\n"
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

        # ====================================================
        # 每条
        # ====================================================

        for result in results:

            f.write(
                "=" * 80
                + "\n"
            )

            f.write(
                f"{result.get('id')} | "
                f"{result.get('model')} | "
                f"{result.get('risk_level')} | "
                f"score={result.get('risk_score')}\n"
            )

            f.write(
                f"类别：{result.get('category')}\n"
            )

            f.write(
                f"Prompt：{result.get('prompt')}\n"
            )

            matches = result.get(
                "matches",
                {}
            )

            reasons = result.get(
                "reasons",
                {}
            )

            # ------------------------------------------------
            # 明确风险
            # ------------------------------------------------

            f.write(
                "\n【明确事实越界】\n"
            )

            for key in [

                "draft_document_number",

                "draft_date",

                "published_policy_claim",

            ]:

                values = matches.get(
                    key,
                    []
                )

                if values:

                    f.write(
                        f"{key}: "
                        f"{', '.join(values)}\n"
                    )

            # ------------------------------------------------
            # 待人工确认
            # ------------------------------------------------

            f.write(
                "\n【待人工确认】\n"
            )

            for key in [

                "unsupported_specific_number",

                "unsupported_time_target",

                "unsupported_organization",

            ]:

                values = matches.get(
                    key,
                    []
                )

                if values:

                    f.write(
                        f"{key}: "
                        f"{', '.join(values)}\n"
                    )

            # ------------------------------------------------
            # 正常行为
            # ------------------------------------------------

            f.write(
                "\n【正常/观察项】\n"
            )

            for key in [

                "common_law_reference",

                "existing_policy_reference",

                "existing_policy_document_number",

                "historical_policy_context",

            ]:

                values = matches.get(
                    key,
                    []
                )

                if values:

                    f.write(
                        f"{key}: "
                        f"{', '.join(values)}\n"
                    )

            # ------------------------------------------------
            # 原因
            # ------------------------------------------------

            f.write(
                "\n【判定依据】\n"
            )

            for category in [

                "clear_hallucination",

                "needs_review",

                "acceptable",

            ]:

                values = reasons.get(
                    category,
                    []
                )

                if values:

                    f.write(
                        f"{category}: "
                        f"{'; '.join(values)}\n"
                    )

            # ------------------------------------------------
            # 输出
            # ------------------------------------------------

            f.write(
                "\n【模型输出】\n"
            )

            f.write(
                result.get(
                    "output",
                    ""
                )
            )

            f.write(
                "\n\n"
            )


# ============================================================
# 清理
# ============================================================

def cleanup(
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

    if torch.cuda.is_available():

        torch.cuda.empty_cache()

        try:

            torch.cuda.ipc_collect()

        except Exception:

            pass


# ============================================================
# 主程序
# ============================================================

def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(

        "--model",

        choices=[

            "base",

            "v1",

            "v11",

            "both",

            "all",

        ],

        default="all",
    )

    args = parser.parse_args()

    print("=" * 80)

    print(
        "V3 政府公文事实越界测试"
    )

    print("=" * 80)

    print()

    print(
        "Base:",
        BASE_MODEL
    )

    print(
        "V1:",
        V1_ADAPTER
    )

    print(
        "V1.1:",
        V11_ADAPTER
    )

    print()

    # --------------------------------------------------------
    # 检查
    # --------------------------------------------------------

    if not Path(
        BASE_MODEL
    ).exists():

        raise FileNotFoundError(
            f"Base model 不存在：{BASE_MODEL}"
        )

    if args.model in [
        "v1",
        "both",
        "all",
    ]:

        if not V1_ADAPTER.exists():

            raise FileNotFoundError(
                f"V1 adapter 不存在：{V1_ADAPTER}"
            )

    if args.model in [
        "v11",
        "all",
    ]:

        if not V11_ADAPTER.exists():

            raise FileNotFoundError(
                f"V1.1 adapter 不存在：{V11_ADAPTER}"
            )

    # --------------------------------------------------------
    # 删除旧结果
    # --------------------------------------------------------

    if RESULT_FILE.exists():

        RESULT_FILE.unlink()

    all_results = []

    # --------------------------------------------------------
    # Base
    # --------------------------------------------------------

    if args.model in [

        "base",

        "both",

        "all",

    ]:

        tokenizer, model = load_base()

        results = run_model(

            "base",

            model,

            tokenizer,

        )

        all_results.extend(
            results
        )

        cleanup(
            model,
            tokenizer,
        )

    # --------------------------------------------------------
    # V1
    # --------------------------------------------------------

    if args.model in [

        "v1",

        "both",

        "all",

    ]:

        tokenizer, model = load_v1()

        results = run_model(

            "v1",

            model,

            tokenizer,

        )

        all_results.extend(
            results
        )

        cleanup(
            model,
            tokenizer,
        )

    # --------------------------------------------------------
    # V1.1
    # --------------------------------------------------------

    if args.model in [

        "v11",

        "all",

    ]:

        tokenizer, model = load_v11()

        results = run_model(

            "v1.1",

            model,

            tokenizer,

        )

        all_results.extend(
            results
        )

        cleanup(
            model,
            tokenizer,
        )

    # --------------------------------------------------------
    # 汇总
    # --------------------------------------------------------

    summary = build_summary(
        all_results
    )

    write_report(

        all_results,

        summary,
    )

    # --------------------------------------------------------
    # 输出
    # --------------------------------------------------------

    print()

    print("=" * 80)

    print(
        "测试完成"
    )

    print("=" * 80)

    print()

    print(
        "JSONL：",
        RESULT_FILE
    )

    print(
        "报告：",
        REPORT_FILE
    )

    print()

    print(
        json.dumps(

            summary,

            ensure_ascii=False,

            indent=2,

        )
    )


# ============================================================
# Entry
# ============================================================

if __name__ == "__main__":

    main()