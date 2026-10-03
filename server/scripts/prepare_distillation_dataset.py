#!/usr/bin/env python3
"""Prepare externally generated official-document data for few-shot and LoRA use.

Input is JSONL produced outside the production network by an explicitly chosen strong model.
This script NEVER calls an external API. It is a deterministic ingress gate: schema validation,
placeholder/degeneration rejection, exact-output deduplication, document-type balancing hints,
and stable train/validation/few-shot splits.

Accepted row contract:
    {
      "instruction": "...",
      "input": "...",                  # optional
      "output": "完整公文正文...",
      "document_type": "通知",
      "source_model": "...",           # required provenance
      "source_id": "..."               # optional upstream trace id
    }

Usage:
    python -m scripts.prepare_distillation_dataset external.jsonl data/distilled
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

MIN_OUTPUT_CHARS = 180
MAX_FEWSHOT_PER_TYPE = 8
VAL_BUCKETS = {0}  # sha256 prefix bucket, deterministic ~1/16 validation
PLACEHOLDER_RE = re.compile(
    r"(?:待补充|此处略去|仅保留思路|请补充|TODO|TBD|\[待填|【待填|×{3,}|X{3,})",
    re.IGNORECASE,
)
DEGEN_RE = re.compile(r"(.{12,80}?)(?:\1){2,}", re.DOTALL)
KNOWN_TYPES = {
    "通知", "通报", "报告", "请示", "批复", "函", "纪要", "决定", "意见",
    "公告", "通告", "方案", "计划", "总结", "讲话稿", "工作要点", "情况汇报",
}


def _norm(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _output_hash(text: str) -> str:
    normalized = re.sub(r"\s+", "", text)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def validate_row(raw: Dict) -> Tuple[bool, str, Dict]:
    instruction = _norm(raw.get("instruction"))
    output = str(raw.get("output") or "").strip()
    doc_type = _norm(raw.get("document_type"))
    source_model = _norm(raw.get("source_model"))
    if not instruction:
        return False, "missing_instruction", {}
    if not source_model:
        return False, "missing_source_model", {}
    if len(output) < MIN_OUTPUT_CHARS:
        return False, "output_too_short", {}
    if PLACEHOLDER_RE.search(output):
        return False, "placeholder", {}
    if DEGEN_RE.search(output):
        return False, "degeneration", {}
    if not doc_type:
        return False, "missing_document_type", {}
    if doc_type not in KNOWN_TYPES:
        # Unknown types are not silently rewritten; keep the external label auditable.
        return False, "unknown_document_type", {}
    row = {
        "instruction": instruction,
        "input": str(raw.get("input") or "").strip(),
        "output": output,
        "document_type": doc_type,
        "source_model": source_model,
        "source_id": _norm(raw.get("source_id")),
    }
    row["sample_id"] = _output_hash(output)[:24]
    return True, "ok", row


def load_rows(path: Path) -> Tuple[List[Dict], Counter]:
    accepted: List[Dict] = []
    rejected = Counter()
    seen = set()
    with path.open("r", encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, start=1):
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                rejected["invalid_json"] += 1
                continue
            ok, reason, row = validate_row(raw)
            if not ok:
                rejected[reason] += 1
                continue
            digest = _output_hash(row["output"])
            if digest in seen:
                rejected["duplicate_output"] += 1
                continue
            seen.add(digest)
            row["source_line"] = lineno
            accepted.append(row)
    return accepted, rejected


def split_rows(rows: Iterable[Dict]):
    train, val = [], []
    for row in rows:
        bucket = int(hashlib.sha256(row["sample_id"].encode()).hexdigest()[0], 16)
        (val if bucket in VAL_BUCKETS else train).append(row)
    return train, val


def select_fewshot(rows: Iterable[Dict]) -> List[Dict]:
    by_type = Counter()
    chosen = []
    # Stable order by sample id makes repeated builds byte-for-byte reproducible.
    for row in sorted(rows, key=lambda item: item["sample_id"]):
        doc_type = row["document_type"]
        if by_type[doc_type] >= MAX_FEWSHOT_PER_TYPE:
            continue
        by_type[doc_type] += 1
        chosen.append(row)
    return chosen


def write_jsonl(path: Path, rows: Iterable[Dict]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def main(argv=None) -> int:
    args = list(argv or sys.argv[1:])
    if len(args) != 2:
        print("usage: prepare_distillation_dataset.py INPUT.jsonl OUTPUT_DIR", file=sys.stderr)
        return 2
    source, out_dir = Path(args[0]), Path(args[1])
    if not source.is_file():
        print(f"input not found: {source}", file=sys.stderr)
        return 2
    out_dir.mkdir(parents=True, exist_ok=True)

    rows, rejected = load_rows(source)
    train, val = split_rows(rows)
    fewshot = select_fewshot(train)
    write_jsonl(out_dir / "train.jsonl", train)
    write_jsonl(out_dir / "val.jsonl", val)
    write_jsonl(out_dir / "fewshot.jsonl", fewshot)

    report = {
        "input": str(source),
        "accepted": len(rows),
        "train": len(train),
        "val": len(val),
        "fewshot": len(fewshot),
        "rejected": dict(sorted(rejected.items())),
        "document_types": dict(sorted(Counter(r["document_type"] for r in rows).items())),
        "source_models": dict(sorted(Counter(r["source_model"] for r in rows).items())),
        "policy": {
            "external_generation_only": True,
            "min_output_chars": MIN_OUTPUT_CHARS,
            "fewshot_per_type": MAX_FEWSHOT_PER_TYPE,
            "dedupe": "sha256(normalized_output)",
        },
    }
    (out_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False))
    return 0 if rows else 1


if __name__ == "__main__":
    raise SystemExit(main())
