"""PPT 长模型请求的进程级准入闸门 + 排队可观测。

生产实测（2026-11-12，35B 单端点 10.128.85.133:8010，800 输出 token）：

============================= ========== =========================
场景                           墙钟        交互式写作短请求 TTFT
============================= ========== =========================
单条长构图基线                 27.8s       -
2 条构图并行                   52.1s       -（串行约 55.6s，几乎无收益）
4 条构图并行                   64.0s       -（串行约 111s，省 47s）
2×PPT 长构图 + 4×写作          54.2s       9.39s
4×写作基线                     5.0s        2.47s
============================= ========== =========================

结论：单 35B 端点的 decode 吞吐是瓶颈，不是应用层的并发数。**盲目把构图
批次并行化只会拖慢交互式写作**——vLLM 会把长请求和短请求 batch 在一起，
应用层只能约束「发出去几个请求」，管不了 vLLM 内部的 batch 调度。

因此这里提供一个全局闸门：所有 PPT 专用模型调用（大纲 / 逐页构图 / 修复）
都必须过闸，限制同时在途的 PPT 长请求数；剩余模型池名额留给交互式写作。
构图批次并行只在闸门内按配置灰度开启，不会突破总量上限。

根治办法是给 PPT / VISION 起独立 35B 副本，按业务用途隔离 vLLM 调度队列。
此时 PPT 端点与文本主端点不重叠，QwenGateway 本就按 URL 列表划分独立容量池，
闸门不再套「给写作留 1 个主池名额」的约束（见 dedicated_ppt_pool），
副本算力才用得满；此时才建议灰度 PPT_COMPOSITION_PARALLEL=2。

本模块只依赖 settings 与异常类型，不引入 ppt_engine / service，避免循环导入。
"""
from __future__ import annotations

import os
import threading
import time
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional

from app.core.config import settings
from app.core.exceptions import AIServiceError

__all__ = ["ppt_model_slot", "composition_parallel", "configure",
           "dedicated_ppt_pool", "stats"]


def _urls(raw: str) -> List[str]:
    return [v.strip().rstrip("/") for v in (raw or "").split(",") if v.strip()]


def dedicated_ppt_pool() -> bool:
    """PPT 是否指向与交互式文本主模型完全不重叠的独立端点。

    共享同一端点时，PPT 长请求必须与写作抢同一个 vLLM 调度队列，闸门上限
    必须小于主模型池总量。若已给 PPT 起了独立 35B 副本（PPT_MODEL_URL(S)
    与 MODEL_SERVICE_URL(S) 无交集），QwenGateway 本就按 URL 列表划分独立
    容量池，此时再套主池的「留 1 个名额」约束只会白白浪费副本算力。
    """
    main = set(_urls(getattr(settings, "MODEL_SERVICE_URL", "")))
    main.update(_urls(os.getenv("MODEL_SERVICE_URLS", "")))
    ppt = set(_urls(getattr(settings, "PPT_MODEL_URL", "")))
    ppt.update(_urls(os.getenv("PPT_MODEL_URLS", "")))
    return bool(ppt) and not (ppt & main)


def _configured_limit() -> int:
    """共享端点时给写作留名额；独立副本时按副本容量放开。"""
    configured = max(1, int(getattr(settings, "PPT_MODEL_MAX_CONCURRENCY", 2)))
    if dedicated_ppt_pool():
        # PPT 网关自身的 QwenGateway 容量池仍按 MODEL_MAX_CONCURRENCY 收口，
        # 这里不会无限放大；副本数与每副本并发由部署侧统一规划。
        return configured
    model_limit = max(1, int(getattr(settings, "MODEL_MAX_CONCURRENCY", 4)))
    return min(configured, max(1, model_limit - 1))


_lock = threading.Lock()
_slots = threading.BoundedSemaphore(_configured_limit())
_limit = _configured_limit()
_inflight = 0
_waiting = 0
_total_waits = 0
_total_wait_seconds = 0.0


def configure(limit: Optional[int] = None) -> int:
    """重建闸门并返回生效上限。供测试与运行时调参使用。

    调用方应确保没有在途请求；生产环境只在启动时按 .env 配置一次。
    """
    global _slots, _limit, _inflight, _waiting, _total_waits, _total_wait_seconds
    with _lock:
        value = _configured_limit() if limit is None else _configured_limit_from(limit)
        _slots = threading.BoundedSemaphore(value)
        _limit = value
        _inflight = 0
        _waiting = 0
        _total_waits = 0
        _total_wait_seconds = 0.0
        return value


def _configured_limit_from(value: int) -> int:
    requested = max(1, int(value))
    if dedicated_ppt_pool():
        return requested
    model_limit = max(1, int(getattr(settings, "MODEL_MAX_CONCURRENCY", 4)))
    return min(requested, max(1, model_limit - 1))


@contextmanager
def ppt_model_slot(timeout: Optional[float] = None) -> Iterator[None]:
    """占用一个 PPT 长模型请求名额；拿不到就排队，超时明确报错。"""
    global _inflight, _waiting, _total_waits, _total_wait_seconds
    started = time.monotonic()
    with _lock:
        _waiting += 1
    acquired = (_slots.acquire(timeout=timeout) if timeout is not None
                else _slots.acquire())
    waited = time.monotonic() - started
    with _lock:
        _waiting -= 1
        _total_waits += 1
        _total_wait_seconds += waited
        if acquired:
            _inflight += 1
    if not acquired:
        raise AIServiceError("PPT 模型请求排队超时，请稍后重试")
    try:
        yield
    finally:
        _slots.release()
        with _lock:
            _inflight = max(0, _inflight - 1)


def composition_parallel() -> int:
    """首轮构图批次并行度。默认 1（串行），且永远不会超过闸门总量。"""
    configured = max(1, int(getattr(settings, "PPT_COMPOSITION_PARALLEL", 1)))
    with _lock:
        limit = _limit
    return max(1, min(configured, limit))


def stats() -> Dict[str, Any]:
    """给健康检查 / 排障用的实时快照。"""
    with _lock:
        return {
            "limit": _limit,
            "inflight": _inflight,
            "waiting": _waiting,
            "total_waits": _total_waits,
            "avg_wait_seconds": round(
                _total_wait_seconds / max(1, _total_waits), 3),
        }
