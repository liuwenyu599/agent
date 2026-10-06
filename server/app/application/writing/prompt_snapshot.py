"""起草上下文快照：把「当时真正喂给模型的输入」原样留下来。

用途
----
那张 1100 字风格卡是**推理期注入**的 few-shot（`_example_style_block`）。
要把它从推理时撤掉、改由权重承担，做法是把这张卡蒸馏进 LoRA：

    训练输入 = 撤掉卡之后的完整提示
    训练输出 = 用户最终认可的那版正文

这条链路成立的前提是输入侧能**逐字还原**。少了输入，样本就退化成
「给我一个标题，写出这一整篇」——事实部分不再有出处，训练等于系统性
鼓励虚构，风格还没学会先把可信度赔进去。

为什么单独存文件而不是写库
--------------------------
样本是**事后**才建的：用户看到 AI 稿、改完保存那一刻才落成
`training_samples` 一行。而当时的检索结果在执行完模型调用后就丢了。
所以在模型调用发生的瞬间留一份旁路快照，键是 task_id，出样本时回填。

开关
----
环境变量 ``SFT_SNAPSHOT_DIR`` 未配置时所有 API 为空操作，生产默认不落盘。
沿用项目里 PPT_AGENT_URL 那套「配了才启用」的安全约定。
"""
from __future__ import annotations

import datetime
import json
import logging
import os
import threading
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_LOCK = threading.Lock()

# 当前正在处理的写作任务。`_llm_draft_async` 被五处调用（非流式起草、流式起草、
# 章节生成、质量重试、二次重写），把 task_id 层层透传下去会污染它们的签名；
# 用 ContextVar 携带，asyncio 每个 Task 自带 context 副本，天然互不干扰。
_CURRENT_TASK: ContextVar[str] = ContextVar("sft_snapshot_task", default="")
_CURRENT_USER: ContextVar[str] = ContextVar("sft_snapshot_user", default="")
# session_id 也得带上：training_samples 表只有 session_id 没有 task_id，
# 导出时要靠它把快照和样本对起来，留了 task_id 却对不上等于白记。
_CURRENT_SESSION: ContextVar[str] = ContextVar("sft_snapshot_session", default="")

# 留痕必须覆盖模型实际看到的资料，否则训练输入与成稿会错配。
_SOURCE_CHARS_PER_ITEM = 800


def _root() -> Optional[Path]:
    raw = (os.getenv("SFT_SNAPSHOT_DIR") or "").strip()
    if not raw:
        return None
    try:
        return Path(raw)
    except Exception:
        return None


def enabled() -> bool:
    return _root() is not None


def _now() -> str:
    try:
        from app.core.timeutil import now_local
        return now_local().isoformat()
    except Exception:
        return datetime.datetime.now().isoformat()


def enter_task(task_id: str, user_id: str = "", session_id: str = "") -> None:
    """标记当前 asyncio 任务正在处理哪个写作任务。见 _CURRENT_TASK 注释。"""
    if task_id:
        _CURRENT_TASK.set(task_id)
        _CURRENT_USER.set(user_id or "")
    if session_id:
        _CURRENT_SESSION.set(session_id)


def current_task() -> str:
    return _CURRENT_TASK.get()


def current_user() -> str:
    return _CURRENT_USER.get()


def _trim_sources(sources: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for item in sources or []:
        if not isinstance(item, dict):
            continue
        rows.append({
            "title": str(item.get("title") or "")[:200],
            "content": str(item.get("content") or "")[:_SOURCE_CHARS_PER_ITEM],
        })
    return rows


def _path(task_id: str) -> Optional[Path]:
    root = _root()
    if root is None or not task_id:
        return None
    return root / "ctx" / f"{task_id}.jsonl"


def record(task_id: str, *, base_system: str, style_card: str, instruction: str,
           sources: Optional[List[Dict[str, Any]]] = None,
           attachment_context: Optional[str] = None,
           kind: str = "draft", user_id: str = "") -> bool:
    """留一份起草上下文。返回是否真的写了（未启用或写失败都为 False）。"""
    path = _path(task_id)
    if path is None:
        return False
    payload = {
        "task_id": task_id,
        "session_id": _CURRENT_SESSION.get() or "",
        "user_id": user_id,
        "kind": kind,
        "ts": _now(),
        "base_system": base_system or "",
        "style_card": style_card or "",
        "instruction": instruction or "",
        "sources": _trim_sources(sources),
        "attachment_context": attachment_context or "",
    }
    try:
        with _LOCK:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
        return True
    except Exception as exc:  # 旁路功能，任何失败都不许冒泡到写作流程
        logger.warning("[SFT快照] 写入失败 task=%s err=%s", task_id, exc)
        return False


def latest(task_id: str) -> Optional[Dict[str, Any]]:
    """取该任务最近一次起草的上下文。文件不存在或格式损坏一律返回 None。"""
    path = _path(task_id)
    if path is None or not path.exists():
        return None
    try:
        lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        if not lines:
            return None
        return json.loads(lines[-1])
    except Exception:
        return None


def build_inputs(snapshot: Optional[Dict[str, Any]], assistant: Any = None,
                 *, keep_style_card: bool = False) -> Dict[str, str]:
    """把快照还原成可直接训练的一对 (system, user)。

    system 走的是**生产同一套**拼装逻辑（`WritingAssistant._build_system_prompt`），
    而不是另写一份。否则两边迟早漂移：训练用的是 A 版拼接，线上跑的是 B 版，
    蒸馏自然失效，而且很难排查。

    keep_style_card=False（默认）产出「撤卡」版本，这才是要训练的输入；
    置 True 可产出「带卡」版本，用于事后做「有卡/无卡」对照评测。
    """
    if not snapshot:
        return {}
    base_system = snapshot.get("base_system") or ""
    if keep_style_card and snapshot.get("style_card"):
        base_system = base_system + snapshot.get("style_card")

    sources = snapshot.get("sources") or []
    if assistant is not None and hasattr(assistant, "_build_system_prompt"):
        try:
            system = assistant._build_system_prompt(
                snapshot.get("instruction") or "",
                sources,
                system_prompt=base_system or None,
                attachment_context=snapshot.get("attachment_context") or "",
            )
        except Exception:
            system = base_system
    else:
        # 没有 assistant 实例时退化到这里：至少把资料原文拼上，保证事实有出处，
        # 只是拼接措辞可能与线上略有差异。
        blocks = [f"[参考资料{i+1}]\n{s['content']}" for i, s in enumerate(sources)]
        parts = [base_system]
        if blocks:
            parts.append("以下是从单位知识库检索到的资料：\n" + "\n\n".join(blocks))
        if snapshot.get("attachment_context"):
            parts.append(str(snapshot["attachment_context"]))
        system = "\n\n".join(p for p in parts if p)

    return {"system": system, "user": snapshot.get("instruction") or ""}


def build_material_text(snapshot: Optional[Dict[str, Any]]) -> str:
    """把当时的检索资料与附件压成一Text，回填到样本 input 字段供人工审阅。

    input 字段是给**人**看的（Review 时判断这篇成稿到底依据了什么），
    真正喂给模型的是 build_inputs 产出的 system——资料在推理时也是拼在
    system 里的，这点必须保持一致，否则又是一次训练/推理不一致。
    """
    if not snapshot:
        return ""
    parts: List[str] = []
    for i, item in enumerate(snapshot.get("sources") or []):
        title = item.get("title") or "未命名"
        parts.append(f"[参考资料{i+1}] {title}\n{item.get('content') or ''}")
    if snapshot.get("attachment_context"):
        parts.append(f"[用户附件]\n{snapshot['attachment_context']}")
    return "\n\n".join(parts)
