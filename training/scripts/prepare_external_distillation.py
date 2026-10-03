#!/usr/bin/env python3
"""Validate strong-model distillation output before it can enter local SFT/few-shot data.

This script never calls an external provider. Generation can happen on any approved external
compute environment; only the returned JSONL is brought back. The accepted output is deliberately
compatible with TrainingService.import_jsonl and remains a candidate requiring human review.

Expected input JSONL fields:
  instruction: original user-style writing request
  input: optional factual/background material supplied to the teacher
  output: teacher-produced official-document body
  biz_type: optional document type
  teacher_model: optional provenance label
  sample_id: optional external id

Usage:
  python training/scripts/prepare_external_distillation.py \
      --input teacher_raw.jsonl --output training/data/distill_candidates.jsonl \
      --report training/data/distill_report.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

_MIN_OUTPUT_CHARS = 300
_MAX_OUTPUT_CHARS = 16000
_MAX_INSTRUCTION_CHARS = 1200
_BAD_MARKERS = (
    "作为一个AI", "作为AI", "作为人工智能", "I am an AI", "As an AI",
    "以下是根据您的要求", "希望对您有所帮助", "```",
)
_PLACEHOLDER_RE = re.compile(
    r"(?:此处略去|仅保留思路|待补充|待完善|TODO|TBD|Lorem ipsum)", re.IGNORECASE
)
_EXCESS_REPEAT_RE = re.compile(r"(.{20,120})\1{2,}", re.DOTALL)


def _records(path: Path) -> Iterable[Tuple[int, Dict]]:
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                yield line_no, {"__parse_error__": str(exc)}
                continue
            yield line_no, obj if isinstance(obj, dict) else {"__parse_error__": "record is not object"}


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", text or "").lower()


def _fingerprint(text: str) -> str:
    return hashlib.sha256(_norm(text).encode("utf-8")).hexdigest()


def validate_record(obj: Dict) -> List[str]:
    issues: List[str] = []
    if obj.get("__parse_error__"):
        return ["invalid_json"]
    instruction = str(obj.get("instruction") or "").strip()
    output = str(obj.get("output") or "").strip()
    if not instruction:
        issues.append("missing_instruction")
    elif len(instruction) > _MAX_INSTRUCTION_CHARS:
        issues.append("instruction_too_long")
    if len(output) < _MIN_OUTPUT_CHARS:
        issues.append("output_too_short")
    if len(output) > _MAX_OUTPUT_CHARS:
        issues.append("output_too_long")
    if any(marker.lower() in output.lower() for marker in _BAD_MARKERS):
        issues.append("assistant_meta_language")
    if _PLACEHOLDER_RE.search(output):
        issues.append("placeholder_or_outline")
    if _EXCESS_REPEAT_RE.search(output):
        issues.append("degenerate_repetition")
    if output and output.count("#") >= 3:
        issues.append("markdown_heavy")
    return issues


def prepare(input_path: Path, output_path: Path, report_path: Path) -> Dict:
    accepted: List[Dict] = []
    rejected: List[Dict] = []
    reasons = Counter()
    seen = set()

    for line_no, obj in _records(input_path):
        issues = validate_record(obj)
        output = str(obj.get("output") or "").strip()
        if not issues and output:
            fp = _fingerprint(output)
            if fp in seen:
                issues.append("duplicate_output")
            else:
                seen.add(fp)
        if issues:
            reasons.update(issues)
            rejected.append({
                "line": line_no,
                "sample_id": obj.get("sample_id"),
                "issues": issues,
            })
            continue

        accepted.append({
            "instruction": str(obj.get("instruction") or "").strip(),
            "input": str(obj.get("input") or "").strip(),
            "output": output,
            "biz_type": str(obj.get("biz_type") or "").strip(),
            # import_jsonl ignores unknown fields, but provenance remains in the portable file.
            "teacher_model": str(obj.get("teacher_model") or "").strip(),
            "external_sample_id": str(obj.get("sample_id") or "").strip(),
            "distillation_fingerprint": _fingerprint(output),
        })

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        for row in accepted:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    report = {
        "input": str(input_path),
        "output": str(output_path),
        "total": len(accepted) + len(rejected),
        "accepted": len(accepted),
        "rejected": len(rejected),
        "accept_rate": round(len(accepted) / max(1, len(accepted) + len(rejected)), 4),
        "rejection_reasons": dict(sorted(reasons.items())),
        "rejected_samples": rejected[:200],
        "policy": {
            "human_review_required": True,
            "auto_approve": False,
            "min_output_chars": _MIN_OUTPUT_CHARS,
            "max_output_chars": _MAX_OUTPUT_CHARS,
        },
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    report = prepare(args.input, args.output, args.report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["accepted"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
