#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
compare_14b_vs_35b.py — Qwen2.5-14B vs Qwen3.6-35B-A3B-W8A8 公文写作对比验收

用途：35B 上线前的最后一道质量闸门。用同一批公文任务分别打两个模型，
对比「结构合规（落款三件套）/ 无占位符 / 无思考泄漏 / 成文速度」，
给出切换建议。上线后仍可随时重跑做回归。

用法（生产服务器，仅依赖 python3 标准库）：
    python3 compare_14b_vs_35b.py
    URL35B=http://10.128.85.133:8010/v1 URL14B=http://10.128.85.133:8003/v1 \
        python3 compare_14b_vs_35b.py
    OUT=/tmp/report.txt MAXTOK=4096 python3 compare_14b_vs_35b.py

环境变量：
    URL14B / URL35B     两个模型的 OpenAI 兼容端点（默认本机 8003 / 8010）
    MODEL14B / MODEL35B 模型名（默认 Qwen2.5-14B-Instruct / Qwen3.6-35B-A3B-W8A8）
    MAXTOK              单次最大 token（默认 4096，与生产 MODEL_MAX_TOKENS 一致）
    TEMP                采样温度（默认 0.4，与生产 MODEL_TEMPERATURE 一致）
    TIMEOUT             单次请求超时秒（默认 300）
    OUT                 报告输出路径（默认 /tmp/14b-vs-35b-report.txt）
    NO_WARMUP=1         跳过预热请求（默认每个模型先发一次 4-token 预热再计时）

判定口径（与生产质量门一致的方向）：
    - 落款三件套：标题（含文种）+ 落款单位 + 成文日期，缺一即不合格
    - 占位符：×× / XXX / [待补充] / 缺少事实依据 / （参考 等，出现即不合格
    - 思考泄漏：正文含 "thinking process" 等 CoT 痕迹，出现即不合格
    - 成文速度：按 usage.completion_tokens / 耗时 计算 tok/s，只报告不设硬闸门
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

URL14B = os.getenv("URL14B", "http://127.0.0.1:8003/v1")
URL35B = os.getenv("URL35B", "http://127.0.0.1:8010/v1")
MODEL14B = os.getenv("MODEL14B", "Qwen2.5-14B-Instruct")
MODEL35B = os.getenv("MODEL35B", "Qwen3.6-35B-A3B-W8A8")
MAXTOK = int(os.getenv("MAXTOK", "4096"))
TEMP = float(os.getenv("TEMP", "0.4"))
TIMEOUT = float(os.getenv("TIMEOUT", "300"))
OUT = os.getenv("OUT", "/tmp/14b-vs-35b-report.txt")
NO_WARMUP = os.getenv("NO_WARMUP", "") not in ("", "0")

ORG = "广州市白云区司法局"
DATE_RE = re.compile(r"20\d{2}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日")
PLACEHOLDERS = ["××", "XXX", "[待补充]", "【待", "缺少事实依据", "（参考", "[参考", "⚠"]
THINKING_RE = re.compile(r"here'?s a thinking process|thinking process|let me (think|plan)", re.I)

SYSTEM_PROMPT = (
    "你是" + ORG + "的公文写作助手，负责起草规范公文。硬性要求：\n"
    "1. 标题 = 发文机关 + 事由 + 文种，用《》括起；\n"
    "2. 主送机关顶格写在正文之前；\n"
    "3. 正文开头空两格，事项分条用「1. 2. 3.」；\n"
    "4. 落款 = 发文单位署名 + 成文日期，署于正文右下方；\n"
    "5. 禁止输出 ××、XXX、[待补充] 等任何占位符；\n"
    "6. 禁止输出思考过程、自我说明或 Markdown 代码块围栏，直接给公文正文。"
)

TASKS = [
    {
        "name": "通知",
        "user": (
            "请起草《广州市白云区司法局关于开展社区普法宣传活动的通知》。"
            "主送：各司法所、各律师事务所。"
            "事项：1. 活动时间 2026年11月1日至11月30日；"
            "2. 活动形式为法律讲座、现场咨询、发放宣传资料；"
            "3. 各单位于12月5日前报送活动总结。"
            "落款单位：" + ORG + "。成文日期：2026年10月20日。"
        ),
    },
    {
        "name": "请示",
        "user": (
            "请起草《广州市白云区司法局关于修缮办公楼顶的请示》。"
            "主送：白云区人民政府。"
            "理由：办公楼顶长期漏水，影响正常办公且存在安全隐患。"
            "事项：申请专项维修经费约85万元，拟于2026年11月开工。"
            "落款单位：" + ORG + "。成文日期：2026年10月20日。"
        ),
    },
    {
        "name": "讲话稿",
        "user": (
            "请起草一份在全局警示教育大会上的讲话稿，发言人是局党组书记，时长约8分钟。"
            "要点：1. 通报近期系统内违纪典型案例；"
            "2. 剖析理想信念弱化、制度执行不严、监督管理缺位三方面原因；"
            "3. 提出严守政治纪律、压实主体责任、强化日常监督三项要求。"
            "落款单位：" + ORG + "。成文日期：2026年10月20日。"
        ),
    },
]


def chat(url, model, messages, max_tokens, timeout):
    """发一次 chat/completions，返回 (content, usage, elapsed_seconds)。"""
    payload = {
        "model": model,
        "messages": messages,
        "temperature": TEMP,
        "max_tokens": max_tokens,
        "top_p": 0.9,
        "stream": False,
        # 与生产 long_form 网关一致：请求级关闭思考（35B 容器级已默认关闭，双保险）
        "chat_template_kwargs": {"enable_thinking": False},
    }
    req = urllib.request.Request(
        url.rstrip("/") + "/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "ignore")[:300]
        raise RuntimeError("HTTP %s: %s" % (e.code, body))
    elapsed = time.monotonic() - t0
    choice = (data.get("choices") or [{}])[0]
    content = (choice.get("message") or {}).get("content") or ""
    return content, data.get("usage") or {}, elapsed


def warmup(url, model, timeout):
    try:
        chat(url, model, [{"role": "user", "content": "确认在线"}], max_tokens=4, timeout=timeout)
        return True
    except Exception as e:  # noqa: BLE001 - 预热失败只做标记，不中断
        print("  [预热失败] %s -> %s" % (url, e))
        return False


def check(task, text):
    """按公文质量口径检查，返回 (ok, issues, stats)。"""
    issues = []
    hits = [p for p in PLACEHOLDERS if p in text]
    if hits:
        issues.append("占位符: " + ",".join(hits))
    if THINKING_RE.search(text):
        issues.append("思考泄漏")
    if not DATE_RE.search(text):
        issues.append("缺成文日期")
    if ORG not in text:
        issues.append("缺落款单位")
    if "《" not in text:
        issues.append("缺标题")
    if len(text) < 500:
        issues.append("正文过短(%d字)" % len(text))
    stats = {"chars": len(text)}
    return (not issues), issues, stats


def run_model(url, model, timeout):
    rows = []
    for task in TASKS:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": task["user"]},
        ]
        try:
            text, usage, elapsed = chat(url, model, messages, MAXTOK, timeout)
        except Exception as e:  # noqa: BLE001
            print("  [%s] 请求失败: %s" % (task["name"], e))
            rows.append({"task": task["name"], "ok": False, "issues": ["请求失败"],
                         "chars": 0, "tokens": 0, "tok_s": 0.0, "elapsed": 0.0})
            continue
        ok, issues, stats = check(task, text)
        tokens = usage.get("completion_tokens") or 0
        tok_s = tokens / elapsed if elapsed > 0 else 0.0
        rows.append({"task": task["name"], "ok": ok, "issues": issues,
                     "chars": stats["chars"], "tokens": tokens,
                     "tok_s": tok_s, "elapsed": elapsed, "text": text})
        print("  [%s] %.1fs %d tok %.1f tok/s %d 字 %s"
              % (task["name"], elapsed, tokens, tok_s, stats["chars"],
                 "OK" if ok else "问题:" + ";".join(issues)))
    return rows


def fmt_row(r):
    issues = "OK" if r["ok"] else ";".join(r["issues"])
    return "%-6s %7.1fs %6d tok %6.1f tok/s %6d 字  %s" % (
        r["task"], r["elapsed"], r["tokens"], r["tok_s"], r["chars"], issues)


def main():
    lines = []

    def say(s=""):
        print(s)
        lines.append(s)

    say("=" * 78)
    say(" 14B vs 35B 公文写作对比   temp=%s max_tokens=%s" % (TEMP, MAXTOK))
    say(" 14B: %s (%s)" % (URL14B, MODEL14B))
    say(" 35B: %s (%s)" % (URL35B, MODEL35B))
    say("=" * 78)

    if not NO_WARMUP:
        say("[预热] 每个模型先发一次 4-token 请求，避免冷启动污染计时")
    ok14 = ok35 = True
    if not NO_WARMUP:
        ok14 = warmup(URL14B, MODEL14B, TIMEOUT)
        ok35 = warmup(URL35B, MODEL35B, TIMEOUT)
        if not ok14:
            say("  -> 14B 不可达（可能已按切换流程停机），其列将留空")
        if not ok35:
            say("  -> 35B 不可达，检查 deploy/model-pool 容器状态")
    if not (ok14 or ok35):
        say("两个模型都不可达，终止。")
        sys.exit(2)

    rows14 = run_model(URL14B, MODEL14B, TIMEOUT) if ok14 else []
    rows35 = run_model(URL35B, MODEL35B, TIMEOUT) if ok35 else []

    say()
    say("-" * 78)
    say("对比汇总（同一批任务，按 35B 顺序排列）")
    say("-" * 78)
    say("35B:")
    for r in rows35:
        say("  " + fmt_row(r))
    if rows14:
        say("14B:")
        for r in rows14:
            say("  " + fmt_row(r))

    # 速度比（同任务配对）
    say()
    say("-" * 78)
    say("结论建议")
    say("-" * 78)
    if not rows35:
        say("35B 无有效结果，无法评估。")
    else:
        passed = [r for r in rows35 if r["ok"]]
        failed = [r for r in rows35 if not r["ok"]]
        say("35B 质量：%d/%d 任务达标" % (len(passed), len(rows35)))
        for r in failed:
            say("  ✗ %s：%s" % (r["task"], ";".join(r["issues"])))
        if rows14:
            tps14 = {r["task"]: r["tok_s"] for r in rows14}
            for r in rows35:
                base = tps14.get(r["task"]) or 0
                if base > 0:
                    say("  速度比 %s：35B %.1f tok/s vs 14B %.1f tok/s（%.0f%%）"
                        % (r["task"], r["tok_s"], base, 100.0 * r["tok_s"] / base))
        if not failed:
            say("建议：35B 结构合规、无占位符/思考泄漏，可按 deploy/model-pool/README.md 第 3 节执行切换。")
        else:
            say("建议：暂不切换。先看上面 ✗ 项——占位符/三件套问题多为 prompt 或采样问题，"
                "思考泄漏需检查容器 --default-chat-template-kwargs 是否生效。")

    report = "\n".join(lines) + "\n"
    try:
        with open(OUT, "w", encoding="utf-8") as f:
            f.write(report)
        print("\n报告已写入: %s" % OUT)
    except OSError as e:
        print("\n（报告写入失败: %s）" % e)

    sys.exit(0 if rows35 and all(r["ok"] for r in rows35) else 1)


if __name__ == "__main__":
    main()
