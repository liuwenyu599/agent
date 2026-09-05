#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
V1.1 数据转换脚本
================

目的：
    基于 V1 real SFT 数据，生成“去历史事实化”的 V1.1 数据。

核心原则：
    1. 保留公文标题、结构、正式措辞、条款组织方式
    2. 文件编号 -> 占位符
    3. 发布日期 -> 占位符
    4. 明显的历史性政策依据 -> 占位符
    5. 保留机构名称，避免破坏公文体式
    6. 不改变 user prompt
    7. 保留原始 source_UID 等 metadata
    8. 输出转换统计，便于人工抽查

输入：
    sft_v1/data/real_sft_v1.jsonl

输出：
    sft_v1/data/real_sft_v11.jsonl

注意：
    本脚本默认输入是 OpenAI/Qwen 常见 messages 格式：

    {
        "messages": [
            {"role": "user", "content": "..."},
            {"role": "assistant", "content": "..."}
        ],
        ...
    }

    同时兼容 content 为 list 的情况。
"""

import json
import re
import argparse
from pathlib import Path
from collections import Counter


# ============================================================
# 默认路径
# ============================================================

DEFAULT_INPUT = (
    "/home/lwy/Policy_crawler/sft_v1/real_sft/real_sft.jsonl"
)

DEFAULT_OUTPUT = (
    "/home/lwy/Policy_crawler/sft_v1/data/real_sft_v11.jsonl"
)

DEFAULT_AUDIT = (
    "/home/lwy/Policy_crawler/sft_v1/data/real_sft_v11_audit.jsonl"
)


# ============================================================
# 正则
# ============================================================

# 广东常见正式文件编号
FILE_NUMBER_PATTERNS = [

    # 粤府办〔2018〕3号
    re.compile(
        r"粤府办\s*[〔\[\(（]?\s*\d{4}\s*[〕\]\)）]?\s*\d+\s*号"
    ),

    # 粤府〔2018〕3号
    re.compile(
        r"粤府\s*[〔\[\(（]?\s*\d{4}\s*[〕\]\)）]?\s*\d+\s*号"
    ),

    # 粤府函〔2018〕3号
    re.compile(
        r"粤府函\s*[〔\[\(（]?\s*\d{4}\s*[〕\]\)）]?\s*\d+\s*号"
    ),

    # 粤府规〔2018〕3号
    re.compile(
        r"粤府规\s*[〔\[\(（]?\s*\d{4}\s*[〕\]\)）]?\s*\d+\s*号"
    ),

    # 粤府办函〔2018〕3号
    re.compile(
        r"粤府办函\s*[〔\[\(（]?\s*\d{4}\s*[〕\]\)）]?\s*\d+\s*号"
    ),

    # 粤司〔2018〕3号
    re.compile(
        r"粤司\s*[〔\[\(（]?\s*\d{4}\s*[〕\]\)）]?\s*\d+\s*号"
    ),

    # 通用：〔2018〕3号
    re.compile(
        r"[〔\[\(（]\s*\d{4}\s*[〕\]\)）]\s*\d+\s*号"
    ),
]


# ============================================================
# 日期
# ============================================================

# 中文日期：
# 2018年1月26日
# 2023 年 12 月 1 日
DATE_PATTERN_CN = re.compile(
    r"\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日"
)

# 阿拉伯数字日期：
# 2018-01-26
# 2018/01/26
DATE_PATTERN_NUM = re.compile(
    r"\d{4}\s*[-/]\s*\d{1,2}\s*[-/]\s*\d{1,2}"
)


# ============================================================
# 政策依据
# ============================================================

# 明显属于“正式政策/法规文件标题”的引用。
#
# 注意：
# 不直接删除所有《...》，因为公文正文中可能有非常重要的
# 法律法规名称。
#
# 这里主要处理：
#   《国务院办公厅关于……的通知》
#   《广东省人民政府关于……的意见》
#   《广东省……条例》
#   《中华人民共和国……法》
#
# 默认只在“依据/贯彻/根据/按照/依据”等上下文附近处理。
POLICY_REFERENCE_PATTERN = re.compile(
    r"《[^《》]{2,100}"
    r"(?:法|条例|办法|规定|意见|方案|通知|规划|决定|细则|"
    r"指导意见|实施意见|实施方案|工作方案|行动方案)"
    r"》"
)


# ============================================================
# 数字型历史事实
# ============================================================

# 注意：
# 不做全局数字删除。
#
# 只处理比较明显的“硬事实数字”，例如：
#   23项
#   100家
#   5000万元
#   90%
#
# 年份已经由日期规则单独处理。
SPECIFIC_NUMBER_PATTERNS = [

    re.compile(
        r"\b\d+(?:\.\d+)?\s*%"
    ),

    re.compile(
        r"\d+(?:\.\d+)?\s*(?:家|个|项|件|名|人|户|次|条|件)"
    ),

    re.compile(
        r"\d+(?:\.\d+)?\s*(?:亿元|万元|元|亿元人民币|万元人民币)"
    ),

    re.compile(
        r"(?:不少于|不低于|达到|超过|高于|低于)\s*\d+(?:\.\d+)?"
        r"(?:%|家|个|项|件|名|人|户|亿元|万元|元)"
    ),
]


# ============================================================
# 统计
# ============================================================

class Stats:

    def __init__(self):
        self.total = 0
        self.changed = 0

        self.file_number = 0
        self.date = 0
        self.policy_reference = 0
        self.specific_number = 0

        self.messages_changed = 0

    def as_dict(self):
        return {
            "total": self.total,
            "changed": self.changed,
            "unchanged": self.total - self.changed,
            "file_number_replaced": self.file_number,
            "date_replaced": self.date,
            "policy_reference_replaced": self.policy_reference,
            "specific_number_replaced": self.specific_number,
            "messages_changed": self.messages_changed,
        }


# ============================================================
# content 提取
# ============================================================

def get_text_from_content(content):
    """
    兼容：

    content = "xxx"

    或：

    content = [
        {"type": "text", "text": "xxx"}
    ]
    """

    if isinstance(content, str):
        return content

    if isinstance(content, list):
        parts = []

        for item in content:
            if isinstance(item, dict):

                if item.get("type") == "text":
                    parts.append(str(item.get("text", "")))

                elif "text" in item:
                    parts.append(str(item["text"]))

        return "".join(parts)

    return str(content)


def set_content_text(message, text):
    """
    将转换后的文本写回 message。
    """

    content = message.get("content")

    if isinstance(content, str):
        message["content"] = text
        return

    if isinstance(content, list):

        changed = False

        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                item["text"] = text
                changed = True
                break

        if not changed:
            message["content"] = text

        return

    message["content"] = text


# ============================================================
# 文件编号转换
# ============================================================

def replace_file_numbers(text, stats):
    """
    所有明确识别出的正式文件编号统一替换。

    例如：

        粤府办〔2018〕3号

    ->

        〔文件编号待补充〕
    """

    changed = False

    for pattern in FILE_NUMBER_PATTERNS:

        text, n = pattern.subn(
            "〔文件编号待补充〕",
            text
        )

        if n:
            stats.file_number += n
            changed = True

    return text, changed


# ============================================================
# 日期转换
# ============================================================

def replace_dates(text, stats):
    """
    只处理完整日期。

    例如：

        2018年1月26日

    ->

        XXXX年XX月XX日
    """

    changed = False

    text, n1 = DATE_PATTERN_CN.subn(
        "XXXX年XX月XX日",
        text
    )

    text, n2 = DATE_PATTERN_NUM.subn(
        "XXXX年XX月XX日",
        text
    )

    n = n1 + n2

    if n:
        stats.date += n
        changed = True

    return text, changed


# ============================================================
# 判断政策引用是否属于“依据”
# ============================================================

def should_replace_policy_reference(text, start, end):
    """
    判断《xxx法/条例/办法/意见/方案/通知》
    是否处于明显的政策依据语境。

    例如：

        根据《中华人民共和国行政处罚法》

        贯彻落实《国务院办公厅关于……的通知》

        依据《广东省行政检查办法》

    这些应该尽量槽位化。

    但：

        本条例第三条规定……

    不一定要删除。

    """

    context_start = max(0, start - 50)
    context_end = min(len(text), end + 30)

    context = text[context_start:context_end]

    trigger_words = [
        "根据",
        "依据",
        "按照",
        "依照",
        "贯彻落实",
        "贯彻",
        "落实",
        "遵循",
        "按照有关",
        "根据有关",
        "依据有关",
    ]

    return any(word in context for word in trigger_words)


# ============================================================
# 政策依据转换
# ============================================================

def replace_policy_references(text, stats):
    """
    将明显作为“政策依据”的历史引用替换。

    例如：

        根据《国务院办公厅关于进一步规范行政裁量权的指导意见》

    ->

        根据〔依据文件待补充〕
    """

    matches = list(POLICY_REFERENCE_PATTERN.finditer(text))

    if not matches:
        return text, False

    result = []
    last = 0
    changed = False

    for match in matches:

        start, end = match.span()

        if should_replace_policy_reference(text, start, end):

            result.append(text[last:start])

            result.append("〔依据文件待补充〕")

            last = end

            stats.policy_reference += 1
            changed = True

    if changed:
        result.append(text[last:])
        text = "".join(result)

    return text, changed


# ============================================================
# 特定数字转换
# ============================================================

def replace_specific_numbers(text, stats):
    """
    将明显的历史性硬数字替换。

    例如：

        完成100项任务

    ->

        完成〔数量待补充〕项任务

    注意：
        不处理普通条款编号。
        不处理所有数字。
        不处理年份。
    """

    changed = False

    for pattern in SPECIFIC_NUMBER_PATTERNS:

        def repl(match):

            value = match.group(0)

            # 百分比
            if "%" in value:
                replacement = "〔比例待补充〕"

            elif "亿元" in value:
                replacement = "〔金额待补充〕"

            elif "万元" in value:
                replacement = "〔金额待补充〕"

            elif "元" in value:
                replacement = "〔金额待补充〕"

            elif any(
                unit in value
                for unit in [
                    "家",
                    "个",
                    "项",
                    "件",
                    "名",
                    "人",
                    "户",
                    "次",
                    "条",
                ]
            ):
                replacement = "〔数量待补充〕"

            else:
                replacement = "〔数值待补充〕"

            stats.specific_number += 1

            return replacement

        text, n = pattern.subn(repl, text)

        if n:
            changed = True

    return text, changed


# ============================================================
# 单个 assistant 文本转换
# ============================================================

def transform_assistant_text(text, stats):
    """
    转换顺序非常重要：

    1. 文件编号
    2. 日期
    3. 政策依据
    4. 特定数字

    先处理文件编号/日期，可以避免后续规则误伤。
    """

    original = text

    text, _ = replace_file_numbers(
        text,
        stats
    )

    text, _ = replace_dates(
        text,
        stats
    )

    text, _ = replace_policy_references(
        text,
        stats
    )

    text, _ = replace_specific_numbers(
        text,
        stats
    )

    return text, text != original


# ============================================================
# 单条样本
# ============================================================

def transform_sample(sample, stats):
    """
    保留原始 JSON 结构。

    只修改 assistant message。
    """

    sample = json.loads(
        json.dumps(
            sample,
            ensure_ascii=False
        )
    )

    messages = sample.get("messages")

    if not isinstance(messages, list):
        return sample, False, []

    audit_items = []
    sample_changed = False

    for idx, message in enumerate(messages):

        if not isinstance(message, dict):
            continue

        role = message.get("role")

        if role != "assistant":
            continue

        original_content = get_text_from_content(
            message.get("content", "")
        )

        transformed_content, changed = transform_assistant_text(
            original_content,
            stats
        )

        if changed:

            set_content_text(
                message,
                transformed_content
            )

            sample_changed = True
            stats.messages_changed += 1

            audit_items.append({
                "message_index": idx,
                "before": original_content,
                "after": transformed_content,
            })

    return sample, sample_changed, audit_items


# ============================================================
# 主流程
# ============================================================

def main():

    parser = argparse.ArgumentParser(
        description="Generate V1.1 de-factualized SFT dataset."
    )

    parser.add_argument(
        "--input",
        default=DEFAULT_INPUT,
        help="V1 real SFT JSONL"
    )

    parser.add_argument(
        "--output",
        default=DEFAULT_OUTPUT,
        help="V1.1 JSONL"
    )

    parser.add_argument(
        "--audit",
        default=DEFAULT_AUDIT,
        help="Audit JSONL"
    )

    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)
    audit_path = Path(args.audit)

    if not input_path.exists():
        raise FileNotFoundError(
            f"输入文件不存在: {input_path}"
        )

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    stats = Stats()

    print("=" * 70)
    print("V1.1 数据转换")
    print("=" * 70)
    print(f"输入 : {input_path}")
    print(f"输出 : {output_path}")
    print(f"审计 : {audit_path}")
    print()

    with (
        input_path.open(
            "r",
            encoding="utf-8"
        ) as fin,
        output_path.open(
            "w",
            encoding="utf-8"
        ) as fout,
        audit_path.open(
            "w",
            encoding="utf-8"
        ) as faudit
    ):

        for line_no, line in enumerate(fin, 1):

            line = line.strip()

            if not line:
                continue

            try:
                sample = json.loads(line)

            except json.JSONDecodeError as e:

                print(
                    f"[WARN] JSON解析失败，跳过第 {line_no} 行: {e}"
                )

                continue

            stats.total += 1

            transformed, changed, audit_items = transform_sample(
                sample,
                stats
            )

            if changed:
                stats.changed += 1

            fout.write(
                json.dumps(
                    transformed,
                    ensure_ascii=False
                )
                + "\n"
            )

            # 只保存发生变化的样本
            if changed:

                audit_record = {
                    "line": line_no,
                    "source_UID": sample.get(
                        "source_UID",
                        sample.get("UID")
                    ),
                    "changes": audit_items,
                }

                faudit.write(
                    json.dumps(
                        audit_record,
                        ensure_ascii=False
                    )
                    + "\n"
                )

            if stats.total % 500 == 0:
                print(
                    f"已处理 {stats.total} 条..."
                )

    # ========================================================
    # 输出统计
    # ========================================================

    print()
    print("=" * 70)
    print("转换完成")
    print("=" * 70)

    result = stats.as_dict()

    for key, value in result.items():
        print(f"{key:35s}: {value}")

    if stats.total:
        print()

        print(
            f"样本转换率: "
            f"{stats.changed / stats.total * 100:.2f}%"
        )

    print()
    print(f"V1.1 数据集:")
    print(f"  {output_path}")

    print()
    print(f"审计文件:")
    print(f"  {audit_path}")

    print()
    print("下一步建议：")
    print("1. 随机检查 V1.1 assistant 文本")
    print("2. 检查文件编号是否全部变成占位符")
    print("3. 检查日期是否全部变成占位符")
    print("4. 检查政策依据是否过度替换")
    print("5. 确认公文结构没有被破坏")
    print("6. 再开始 V1.1 QLoRA 训练")


if __name__ == "__main__":
    main()