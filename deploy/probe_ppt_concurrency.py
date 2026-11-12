"""低强度生产压测：模拟 PPT design 构图长请求 + 交互式写作短请求混合。

只读远端推理端点，不写库、不改配置。测量 TTFT / 总耗时 / 429 / vLLM 排队。

用法（开发机或服务器均可，需能访问模型端点）::

    # 隔离前：所有请求打同一个端点
    python deploy/probe_ppt_concurrency.py

    # 隔离后：PPT 长请求打副本，交互式写作打主端点（同一把尺子做前后对比）
    PPT_PROBE_BASE=http://10.128.85.133:8010 \
    PPT_PROBE_PPT_BASE=http://10.128.85.133:8020 \
        python deploy/probe_ppt_concurrency.py

    PPT_PROBE_MODEL=Qwen3.6-35B-A3B-W8A8   # 两个端点须是同一个模型

2026-11-12 生产 35B 单端点实测（本脚本）作为并发整改依据，见
``docs/AI_REVIEW_BRIEF.md`` §2.3；多副本隔离方案见
``deploy/model-pool/README.md`` 第 10 节。压测只发推理请求，不影响业务数据。
"""
from __future__ import annotations

import concurrent.futures
import json
import os
import re
import statistics
import threading
import time
import urllib.request

_BASE = os.getenv("PPT_PROBE_BASE", "http://10.128.85.133:8010").rstrip("/")
_PPT_BASE = os.getenv("PPT_PROBE_PPT_BASE", _BASE).rstrip("/")
MAIN_URL = f"{_BASE}/v1/chat/completions"
PPT_URL = f"{_PPT_BASE}/v1/chat/completions"
METRICS = {"main": f"{_BASE}/metrics"}
ISOLATED = _PPT_BASE != _BASE
if ISOLATED:
    METRICS["ppt"] = f"{_PPT_BASE}/metrics"
MODEL = os.getenv("PPT_PROBE_MODEL", "Qwen3.6-35B-A3B-W8A8")

PARA = (
    "请依据下列政务汇报材料的版式规范为第{page}页生成图文区域：页面尺寸13.333x7.5英寸，"
    "标题区位于上方12%高度，正文区不得覆盖页脚与页眉装饰条；主色为深蓝1F3A5F，"
    "辅助色为暖金C8A062，正文使用28至32磅等线或思源黑体；每个区域需给出x/y/w/h四个归一化坐标、"
    "内容类型（标题、要点、数据、引文、图像）、对齐方式与字号层级；"
    "不得让相邻页使用完全相同的区域划分，不得在正文区叠放半透明大色块；"
    "输出必须是严格JSON，pages数组中每项含index与regions字段，不要输出解释文字。"
    "参考材料：白云区司法局2025年度法治政府建设工作情况报告，含法律援助、行政复议、"
    "社区矫正、普法宣传、人民调解、公共法律服务等六个业务板块的年度数据与典型案例，"
    "要求成稿结构完整、数据准确、措辞符合党政机关公文格式规范，"
    "并在每页保留统一的页眉标识与页码位置。"
)


def make_prompt(page: int, long: bool) -> str:
    if not long:
        return "请用一句话说明什么是行政复议。"
    return "\n".join(PARA.format(page=page + i) for i in range(18))


def one(kind: str, idx: int, max_tokens: int, timeout: int = 180):
    long = kind == "ppt"
    prompt = make_prompt(idx, long)
    url = PPT_URL if long else MAIN_URL
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.1,
        "stream": True,
    }
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    started = time.monotonic()
    ttft = None
    tokens = 0
    finish = None
    status = 0
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = resp.status
            for raw in resp:
                line = raw.decode("utf-8", "ignore").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except Exception:
                    continue
                ch = (chunk.get("choices") or [{}])[0]
                if ch.get("finish_reason"):
                    finish = ch["finish_reason"]
                delta = (ch.get("delta") or {}).get("content") or ""
                if delta:
                    tokens += 1
                    if ttft is None:
                        ttft = time.monotonic() - started
        return {"kind": kind, "idx": idx, "ok": True, "status": status,
                "ttft": ttft, "total": time.monotonic() - started,
                "chunks": tokens, "finish": finish, "err": ""}
    except Exception as exc:
        return {"kind": kind, "idx": idx, "ok": False, "status": status,
                "ttft": ttft, "total": time.monotonic() - started,
                "chunks": tokens, "finish": finish,
                "err": f"{type(exc).__name__}: {exc}"[:160]}


class Watcher(threading.Thread):
    """采样各 vLLM 端点 running / waiting 峰值；隔离后按端点分别统计。"""

    def __init__(self):
        super().__init__(daemon=True)
        self.stop = threading.Event()
        self.peaks = {label: {"running": 0.0, "waiting": 0.0}
                      for label in METRICS}
        self.samples = 0

    def run(self):
        pat_r = re.compile(r'^vllm:num_requests_running\{[^}]*\}\s+([\d.]+)', re.M)
        pat_w = re.compile(r'^vllm:num_requests_waiting\{[^}]*\}\s+([\d.]+)', re.M)
        while not self.stop.is_set():
            for label, url in METRICS.items():
                try:
                    with urllib.request.urlopen(url, timeout=3) as r:
                        text = r.read().decode("utf-8", "ignore")
                    mr, mw = pat_r.search(text), pat_w.search(text)
                    if mr:
                        self.peaks[label]["running"] = max(
                            self.peaks[label]["running"], float(mr.group(1)))
                    if mw:
                        self.peaks[label]["waiting"] = max(
                            self.peaks[label]["waiting"], float(mw.group(1)))
                    self.samples += 1
                except Exception:
                    pass
            self.stop.wait(0.5)


def fmt(rs):
    oks = [r for r in rs if r["ok"]]
    bad = [r for r in rs if not r["ok"]]
    if oks:
        ttfts = [r["ttft"] for r in oks if r["ttft"] is not None]
        totals = [r["total"] for r in oks]
        return (f"成功={len(oks)} 失败={len(bad)} "
                f"TTFT中位={statistics.median(ttfts):.2f}s "
                f"总耗时中位={statistics.median(totals):.2f}s "
                f"总耗时最大={max(totals):.2f}s")
    return f"成功=0 失败={len(bad)}"


def run_case(name, jobs):
    watcher = Watcher()
    watcher.start()
    started = time.monotonic()
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(jobs)) as ex:
        futs = [ex.submit(one, *j) for j in jobs]
        rs = [f.result() for f in futs]
    wall = time.monotonic() - started
    watcher.stop.set()
    watcher.join(timeout=2)
    peaks = " ".join(
        f"{label}:running={v['running']:.0f}/waiting={v['waiting']:.0f}"
        for label, v in watcher.peaks.items())
    print(f"\n=== {name} 墙钟={wall:.2f}s {fmt(rs)} "
          f"vLLM峰值 {peaks} 采样={watcher.samples}", flush=True)
    for r in sorted(rs, key=lambda x: (x["kind"], x["idx"])):
        print(f"  {r['kind']:<5}#{r['idx']} ok={r['ok']} "
              f"ttft={r['ttft'] and round(r['ttft'], 2)} "
              f"total={r['total']:.2f}s chunks={r['chunks']} "
              f"finish={r['finish']} {r['err']}", flush=True)
    return rs


if __name__ == "__main__":
    print("写作端点:", MAIN_URL, "| PPT端点:", PPT_URL, "| 模型:", MODEL, flush=True)
    print("模式:", "按用途隔离（多副本）" if ISOLATED else "单端点混批", flush=True)
    print("说明: ppt=长上下文构图请求(~3k token输入/800输出), "
          "chat=交互式写作短请求(64输出)", flush=True)

    # 1) 单条长构图基线
    run_case("基线 单条长构图", [("ppt", 1, 800)])

    # 2) 两条长构图并行（对应两批构图批次并发）
    run_case("构图并行=2", [("ppt", 2, 800), ("ppt", 3, 800)])

    # 3) 四条长构图并行（对应 12-16 页 PPT 多批同时构图）
    run_case("构图并行=4", [("ppt", 4 + i, 800) for i in range(4)])

    # 4) 混合：2 条 PPT 长请求 + 4 条交互式短请求，看写作是否被拖慢
    mixed = run_case("混合 2×PPT + 4×写作",
                     [("ppt", 8, 800), ("ppt", 9, 800)] +
                     [("chat", 10 + i, 64) for i in range(4)])

    # 5) 纯写作短请求基线（用于和混合场景对比）
    baseline = run_case("基线 写作短请求×4",
                        [("chat", 20 + i, 64) for i in range(4)])

    def _median_ttft(rows):
        values = [r["ttft"] for r in rows
                  if r["ok"] and r["kind"] == "chat" and r["ttft"] is not None]
        return statistics.median(values) if values else None

    mixed_ttft, base_ttft = _median_ttft(mixed), _median_ttft(baseline)
    if mixed_ttft and base_ttft:
        print(f"\n判定: 混合场景写作 TTFT={mixed_ttft:.2f}s / "
              f"纯写作基线={base_ttft:.2f}s = {mixed_ttft / base_ttft:.2f}x",
              flush=True)
        if ISOLATED:
            print("隔离验收: 倍率应接近 1.0；仍 >2 说明流量没真正分开，"
                  "检查后端 .env 的 PPT_MODEL_URL / VISION_MODEL_URL 是否仍指向主端点",
                  flush=True)
        else:
            print("单端点基线: 倍率显著 >1 即证明长短请求被 vLLM 合批；"
                  "起独立副本后应回落到接近 1.0", flush=True)
