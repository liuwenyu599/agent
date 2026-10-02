#!/usr/bin/env python3
"""Prefix-caching acceptance probe for the production 14B OpenAI-compatible endpoint.

This does not benchmark quality in the abstract. It sends three requests with an identical long
system prefix and deliberately different document topics, then fails closed on obvious cache
corruption symptoms: empty/truncated output, exact paragraph repetition, missing expected topic,
or leakage from another request's unique marker/topic.

Examples:
  python deploy/verify-prefix-caching.py --base-url http://127.0.0.1:8003/v1 --model Qwen2.5-14B-Instruct
  MODEL_SERVICE_URL=http://127.0.0.1:8003/v1 MODEL_NAME=... python deploy/verify-prefix-caching.py

Use --require-cache-hit only when the deployed vLLM exposes cached-token usage in its OpenAI
response. Some versions perform prefix caching without returning that field.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional

import requests


SYSTEM_PREFIX = """你是司法行政机关公文写作助手。严格遵守以下稳定规则：
1. 只根据本轮用户给出的主题、事实和要求写作，不得把其他任务的人名、主题、数字或事项带入当前文稿。
2. 不得编造政策文号、统计数据、联系人、电话号码、日期或既有成效。
3. 使用正式、克制、可执行的机关公文语言；避免口号堆砌和同义句反复。
4. 各部分职责清楚，段落之间不得机械复读；同一完整句子不得连续重复。
5. 本测试只验证服务稳定性与上下文隔离，不要求输出标题、文号、落款或日期。
6. 必须保留用户给出的唯一校验标记，以证明当前请求没有与其他并发/缓存请求串线。
7. 输出 600—900 字左右的完整正文，至少三部分，每部分写成完整段落，不得只列提纲。
8. 不要解释写作过程，不要输出 Markdown 代码块。

下面这些规则构成三个请求完全相同的稳定前缀，用于触发 prefix caching。缓存只能复用模型的前缀 KV，
绝不能复用上一请求的生成结果、用户主题或后缀状态。若当前用户主题与先前请求不同，只能依据当前后缀继续推理。
"""


CASES = [
    {
        "id": "A",
        "marker": "PCACHE-A-7301",
        "topic": "社区矫正对象教育帮扶专项行动",
        "forbidden": ["行政复议案卷评查", "公共法律服务进园区", "PCACHE-B-8426", "PCACHE-C-9154"],
    },
    {
        "id": "B",
        "marker": "PCACHE-B-8426",
        "topic": "行政复议案卷质量评查工作",
        "forbidden": ["社区矫正对象教育帮扶", "公共法律服务进园区", "PCACHE-A-7301", "PCACHE-C-9154"],
    },
    {
        "id": "C",
        "marker": "PCACHE-C-9154",
        "topic": "公共法律服务进园区活动",
        "forbidden": ["社区矫正对象教育帮扶", "行政复议案卷评查", "PCACHE-A-7301", "PCACHE-B-8426"],
    },
]


@dataclass
class CaseResult:
    case_id: str
    ok: bool
    latency_s: float
    char_count: int
    cached_tokens: Optional[int]
    issues: List[str]
    preview: str


def _endpoint(base_url: str) -> str:
    base = base_url.rstrip("/")
    return base + "/chat/completions"


def _headers(api_key: str) -> Dict[str, str]:
    out = {"Content-Type": "application/json"}
    if api_key:
        out["Authorization"] = f"Bearer {api_key}"
    return out


def _cached_tokens(usage: Dict[str, Any]) -> Optional[int]:
    details = usage.get("prompt_tokens_details") or {}
    value = details.get("cached_tokens")
    if isinstance(value, int):
        return value
    # A few compatible servers expose a flat cache counter instead.
    for key in ("cached_tokens", "cache_read_input_tokens", "prompt_cached_tokens"):
        value = usage.get(key)
        if isinstance(value, int):
            return value
    return None


def _duplicate_paragraphs(text: str) -> List[str]:
    paragraphs = [re.sub(r"\s+", "", p) for p in re.split(r"\n\s*\n+", text) if p.strip()]
    seen = set()
    dup = []
    for p in paragraphs:
        if len(p) < 20:
            continue
        if p in seen and p not in dup:
            dup.append(p)
        seen.add(p)
    return dup


def _consecutive_sentence_repeat(text: str) -> bool:
    sentences = [s.strip() for s in re.split(r"(?<=[。！？；])", text) if s.strip()]
    for left, right in zip(sentences, sentences[1:]):
        if len(left) >= 12 and re.sub(r"\s+", "", left) == re.sub(r"\s+", "", right):
            return True
    return False


def _request_case(session: requests.Session, args: argparse.Namespace,
                  case: Dict[str, Any]) -> CaseResult:
    user = (
        f"校验标记：{case['marker']}。\n"
        f"请起草一份关于“{case['topic']}”的工作通知正文。"
        "写清工作目标、主要任务、组织实施和工作要求。"
        "除校验标记外，不要引用任何未提供的数字或具体政策文号。"
    )
    payload = {
        "model": args.model,
        "messages": [
            {"role": "system", "content": SYSTEM_PREFIX},
            {"role": "user", "content": user},
        ],
        "temperature": 0.2,
        "top_p": 0.9,
        "max_tokens": args.max_tokens,
    }
    started = time.perf_counter()
    response = session.post(
        _endpoint(args.base_url),
        headers=_headers(args.api_key),
        json=payload,
        timeout=args.timeout,
    )
    latency = time.perf_counter() - started
    response.raise_for_status()
    data = response.json()
    choice = (data.get("choices") or [{}])[0]
    text = str((choice.get("message") or {}).get("content") or "").strip()
    finish_reason = choice.get("finish_reason")
    issues: List[str] = []

    if len(text) < args.min_chars:
        issues.append(f"output_too_short:{len(text)}<{args.min_chars}")
    if finish_reason == "length":
        issues.append("finish_reason_length")
    if case["marker"] not in text:
        issues.append("expected_marker_missing")
    # Match the stable semantic core rather than requiring punctuation-identical title text.
    topic_core = case["topic"].replace("工作", "").replace("活动", "").replace("专项行动", "")
    if topic_core and topic_core not in text.replace(" ", ""):
        issues.append("expected_topic_missing")
    leaked = [term for term in case["forbidden"] if term and term in text]
    if leaked:
        issues.append("cross_request_leak:" + ",".join(leaked))
    duplicates = _duplicate_paragraphs(text)
    if duplicates:
        issues.append(f"duplicate_paragraphs:{len(duplicates)}")
    if _consecutive_sentence_repeat(text):
        issues.append("consecutive_sentence_repeat")

    cached = _cached_tokens(data.get("usage") or {})
    return CaseResult(
        case_id=case["id"],
        ok=not issues,
        latency_s=round(latency, 3),
        char_count=len(text),
        cached_tokens=cached,
        issues=issues,
        preview=text[:160].replace("\n", " "),
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--base-url",
        default=os.getenv("MODEL_SERVICE_URL", "http://127.0.0.1:8003/v1"),
        help="OpenAI-compatible base URL, normally ending in /v1",
    )
    parser.add_argument("--model", default=os.getenv("MODEL_NAME", "Qwen2.5-14B-Instruct"))
    parser.add_argument("--api-key", default=os.getenv("MODEL_API_KEY", ""))
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--max-tokens", type=int, default=1600)
    parser.add_argument("--min-chars", type=int, default=350)
    parser.add_argument(
        "--require-cache-hit",
        action="store_true",
        help="Fail if response usage does not expose a positive cached-token count on requests 2/3.",
    )
    args = parser.parse_args()

    session = requests.Session()
    results: List[CaseResult] = []
    try:
        for case in CASES:
            results.append(_request_case(session, args, case))
    except Exception as exc:
        report = {"ok": False, "fatal": str(exc), "results": [asdict(r) for r in results]}
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 2

    cache_issue = None
    if args.require_cache_hit:
        second_third = [r.cached_tokens for r in results[1:]]
        if any(v is None or v <= 0 for v in second_third):
            cache_issue = "cache_hit_not_observable_on_requests_2_or_3"

    ok = all(r.ok for r in results) and cache_issue is None
    report = {
        "ok": ok,
        "endpoint": args.base_url,
        "model": args.model,
        "cache_issue": cache_issue,
        "results": [asdict(r) for r in results],
        "decision": "KEEP_PREFIX_CACHE" if ok else "ROLL_BACK_TO_NOPREFIX",
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
