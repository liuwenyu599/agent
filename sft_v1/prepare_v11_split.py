#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
from pathlib import Path


ROOT = Path("/home/lwy/Policy_crawler")

V11_FILE = (
    ROOT / "sft_v1/data/real_sft_v11.jsonl"
)

# 原 V1 的 train / val
V1_TRAIN = (
    ROOT / "sft_v1/train/train_real.jsonl"
)

V1_VAL = (
    ROOT / "sft_v1/val/val_real.jsonl"
)

# V1.1 输出
V11_TRAIN = (
    ROOT / "sft_v1/train/train_real_v11.jsonl"
)

V11_VAL = (
    ROOT / "sft_v1/val/val_real_v11.jsonl"
)


def get_uid(obj):
    """
    兼容 metadata.source_UID / 顶层 source_UID / UID
    """

    metadata = obj.get("metadata", {})

    if isinstance(metadata, dict):
        uid = metadata.get("source_UID")
        if uid:
            return str(uid)

    for key in ["source_UID", "UID"]:
        uid = obj.get(key)
        if uid:
            return str(uid)

    return None


def load_jsonl(path):

    rows = []

    with open(
        path,
        "r",
        encoding="utf-8",
    ) as f:

        for line_no, line in enumerate(f, 1):

            if not line.strip():
                continue

            obj = json.loads(line)

            uid = get_uid(obj)

            if uid is None:
                raise ValueError(
                    f"{path} 第 {line_no} 条没有 UID"
                )

            rows.append((uid, obj))

    return rows


def main():

    print("=" * 70)
    print("V1.1 Train / Val Split")
    print("=" * 70)

    # --------------------------------------------------------
    # 读取原 V1 split
    # --------------------------------------------------------

    train_rows = load_jsonl(V1_TRAIN)
    val_rows = load_jsonl(V1_VAL)

    train_uids = {
        uid for uid, _ in train_rows
    }

    val_uids = {
        uid for uid, _ in val_rows
    }

    print(
        "V1 train:",
        len(train_uids)
    )

    print(
        "V1 val:",
        len(val_uids)
    )

    overlap = train_uids & val_uids

    if overlap:
        raise RuntimeError(
            f"V1 train/val UID 重叠: {len(overlap)}"
        )

    # --------------------------------------------------------
    # 读取 V1.1
    # --------------------------------------------------------

    v11_rows = load_jsonl(V11_FILE)

    print(
        "V1.1 total:",
        len(v11_rows)
    )

    v11_by_uid = {}

    for uid, obj in v11_rows:

        if uid in v11_by_uid:
            raise RuntimeError(
                f"V1.1 出现重复 UID: {uid}"
            )

        v11_by_uid[uid] = obj

    # --------------------------------------------------------
    # UID 完整性
    # --------------------------------------------------------

    expected_uids = (
        train_uids | val_uids
    )

    actual_uids = set(
        v11_by_uid.keys()
    )

    missing = expected_uids - actual_uids
    extra = actual_uids - expected_uids

    if missing:
        print(
            "缺少 UID:",
            len(missing)
        )

        print(
            list(sorted(missing))[:20]
        )

        raise RuntimeError(
            "V1.1 缺少原始 V1 UID"
        )

    if extra:
        print(
            "多出的 UID:",
            len(extra)
        )

        print(
            list(sorted(extra))[:20]
        )

        raise RuntimeError(
            "V1.1 存在原 V1 split 之外的 UID"
        )

    # --------------------------------------------------------
    # 写 train
    # --------------------------------------------------------

    train_count = 0

    with open(
        V11_TRAIN,
        "w",
        encoding="utf-8",
    ) as f:

        for uid, _ in train_rows:

            obj = v11_by_uid[uid]

            f.write(
                json.dumps(
                    obj,
                    ensure_ascii=False,
                )
                + "\n"
            )

            train_count += 1

    # --------------------------------------------------------
    # 写 val
    # --------------------------------------------------------

    val_count = 0

    with open(
        V11_VAL,
        "w",
        encoding="utf-8",
    ) as f:

        for uid, _ in val_rows:

            obj = v11_by_uid[uid]

            f.write(
                json.dumps(
                    obj,
                    ensure_ascii=False,
                )
                + "\n"
            )

            val_count += 1

    # --------------------------------------------------------
    # 最终检查
    # --------------------------------------------------------

    print()
    print("=" * 70)
    print("完成")
    print("=" * 70)

    print(
        "V1.1 train:",
        train_count
    )

    print(
        "V1.1 val:",
        val_count
    )

    print(
        "V1.1 total:",
        train_count + val_count
    )

    print()

    print(
        "Train:",
        V11_TRAIN
    )

    print(
        "Val:",
        V11_VAL
    )

    print()

    if train_count != len(train_uids):
        raise RuntimeError(
            "V1.1 train 数量异常"
        )

    if val_count != len(val_uids):
        raise RuntimeError(
            "V1.1 val 数量异常"
        )

    if train_count + val_count != len(
        actual_uids
    ):
        raise RuntimeError(
            "V1.1 train + val != total"
        )

    print("UID split 检查通过。")


if __name__ == "__main__":
    main()
