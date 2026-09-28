"""PPTAgent 异步生成任务（job）编排。

为什么必须是异步
----------------
PPTAgent 一次生成实测 5~15 分钟，而同步 HTTP 请求撑不住（桌面端请求超时默认
120s、反向代理常见 60s）。因此：

    POST /ppt/jobs            → 立即返回 job_id，后台线程接管
    后台线程                   → 提交到 Gradio + 消费 SSE 事件流 + 扫目录更新进度
    前端轮询 status / preview  → 实时看到"正在设计第 N 页"

事务纪律（重要）
----------------
PPTAgent 跑十几分钟，**绝不能开一个跨越全程的数据库事务**——SQLite 下长事务会
写锁，把其它用户全部卡住。本模块所有写入都是"开会话 → 写 → 立即提交 → 关会话"
的短事务（见 :func:`_update_job`）。

产物优先级（铁律不变）
----------------------
1. Gradio 返回体里的 ``📥 下载文件`` FileData；
2. 取不到 → 扫共享卷找 ``presentation.pptx``；
3. 再取不到 → **回退本地 render_pptx**。
任何时候都不会把打不开的文件交给用户。
"""
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.application.ppt.service import PPTService
from app.infrastructure.ppt.ppt_agent_client import (
    PPTAgentClient, PPTAgentOutcome, build_outline_markdown, looks_like_pptx,
)
from app.core.config import settings
from app.core.logging import get_logger
from app.core.timeutil import CN_TZ, now_local
from app.domain.ppt.entities import PPTDocument
from app.infrastructure.database import SessionLocal
from app.infrastructure.database.models.ppt import PPTDocumentModel
from app.infrastructure.repositories.ppt import _doc

logger = get_logger(__name__)

# 进行中的 job 线程（doc_id -> Thread），防止同一文档被重复提交
_RUNNING: Dict[str, threading.Thread] = {}
_RUNNING_LOCK = threading.Lock()

# 终态：不再需要轮询
_TERMINAL = ("succeeded", "failed", "cancelled")


# ============================================================ 短事务读写


def _open(doc_id: str) -> Optional[PPTDocument]:
    """读取文档（短事务）。"""
    db: Session = SessionLocal()
    try:
        m = db.get(PPTDocumentModel, doc_id)
        return _doc(m) if m else None
    finally:
        db.close()


def _update_job(doc_id: str, **fields: Any) -> Optional[PPTDocument]:
    """更新 job 字段（短事务：开→写→提交→关，绝不长时间持锁）。"""
    db: Session = SessionLocal()
    try:
        m = db.get(PPTDocumentModel, doc_id)
        if not m:
            return None
        for k, v in fields.items():
            setattr(m, k, v)
        db.commit()
        db.refresh(m)
        return _doc(m)
    finally:
        db.close()


def _is_active(doc_id: str) -> bool:
    with _RUNNING_LOCK:
        t = _RUNNING.get(doc_id)
        return bool(t and t.is_alive())


# ============================================================ 提交 / 取消 / 追问


def submit_job(doc_id: str, user_id: str, message: str = "",
               history: Optional[List[Any]] = None) -> Dict[str, Any]:
    """提交一个生成 job，立即返回（后台线程接管，不阻塞请求）。

    Args:
        doc_id: 文档 ID（同时作为 job_id，一个文档同时只有一个进行中的 job）。
        user_id: 归属用户，用于取素材与落盘。
        message: 可选的用户补充需求，追加到给 PPTAgent 的 message 末尾。
        history: 追问续跑时的对话历史（R1）；首轮提交为 None。

    Returns:
        ``{"job_id", "status", "phase"}``
    """
    if _is_active(doc_id):
        logger.info("文档 %s 已有进行中的 job，忽略重复提交", doc_id)
        return {"job_id": doc_id, "status": "running", "phase": "submitting",
                "message": "已有进行中的任务"}

    # 未配置 PPTAgent 时不做无意义的异步：直接置为失败，让调用方走现有本地导出
    if not (settings.PPT_AGENT_URL or "").strip():
        _update_job(doc_id, job_status="failed", job_phase="failed",
                    job_error="未配置 PPT_AGENT_URL，异步生成不可用",
                    job_finished_at=now_local())
        return {"job_id": doc_id, "status": "failed", "phase": "failed",
                "message": "未配置 PPT_AGENT_URL"}

    _update_job(doc_id, job_status="pending", job_phase="submitting",
                job_error="", job_question="", job_current_page=0,
                job_total_pages=0, job_cancel_requested=False,
                job_started_at=now_local(), job_progress_at=now_local(),
                job_finished_at=None)

    runner = PPTAgentJobRunner(doc_id, user_id, message, history=history)
    t = threading.Thread(target=runner.run, name=f"ppt-job-{doc_id[:8]}", daemon=True)
    with _RUNNING_LOCK:
        _RUNNING[doc_id] = t
    t.start()
    logger.info("PPT job 已提交：job_id=%s", doc_id)
    return {"job_id": doc_id, "status": "pending", "phase": "submitting"}


def cancel_job(doc_id: str) -> Dict[str, Any]:
    """请求取消：置标志位，后台线程下一轮扫描时退出。

    注意：PPTAgent 侧已经启动的生成无法远程终止，这里只是**停止等待**，
    任务会在服务端跑完（产物无人取用）。
    """
    _update_job(doc_id, job_cancel_requested=True)
    logger.info("PPT job 取消请求：job_id=%s", doc_id)
    return {"job_id": doc_id, "status": "cancelled", "message": "已请求取消"}


def answer_clarification(doc_id: str, user_id: str, answer: str) -> Dict[str, Any]:
    """回答 PPTAgent 的追问（R1），带着历史上下文继续同一次生成。

    Args:
        doc_id: job_id。
        user_id: 用户。
        answer: 用户对追问的答复。

    Returns:
        与 :func:`submit_job` 相同的结构。
    """
    doc = _open(doc_id)
    if not doc:
        return {"job_id": doc_id, "status": "failed", "message": "任务不存在"}
    if doc.job_status != "awaiting_clarification":
        return {"job_id": doc_id, "status": doc.job_status or "unknown",
                "message": "该任务当前不在等待回答状态"}
    # 空答复 = 用户选择「按你的判断继续」。此时不能把空串原样发出去：
    # PPTAgent 会看到一个空的 user 轮次而不知道该干什么，因此显式换成一句指令。
    # 注意这与"后端自动代答"不同——是否作答是用户点的按钮，我们只是把"不补充"
    # 这个意图翻译成它能理解的文字。
    final_answer = (answer or "").strip()
    if not final_answer:
        final_answer = "我不额外补充，请你按自己的专业判断直接生成完整 PPT。"
    # 历史里记下"它问了什么 / 用户答了什么"，让 PPTAgent 能续着上下文走
    history = [
        {"role": "assistant", "content": doc.job_question or ""},
        {"role": "user", "content": final_answer},
    ]
    return submit_job(doc_id, user_id, message=final_answer, history=history)


def job_status(doc: PPTDocument) -> Dict[str, Any]:
    """组装给前端的状态响应。"""
    started = doc.job_started_at
    elapsed = 0.0
    if started is not None:
        elapsed = max(0.0, (now_local() - started).total_seconds())
    status = doc.job_status or "unknown"
    # 线程已结束但未写终态（如进程重启）→ 判定为失败，避免前端无限轮询
    if status in ("pending", "running") and not _is_active(doc.id or ""):
        status = "failed"
    remaining: Optional[float] = None
    if (status in ("pending", "running") and doc.job_current_page > 0
            and doc.job_total_pages > doc.job_current_page):
        per_page = elapsed / doc.job_current_page
        remaining = round((doc.job_total_pages - doc.job_current_page) * per_page, 1)
    return {
        "job_id": doc.id,
        "status": status,
        "total_pages": doc.job_total_pages,
        "current_page": doc.job_current_page,
        "phase": doc.job_phase,
        "elapsed_seconds": round(elapsed, 1),
        "estimated_remaining": remaining,
        "error_msg": doc.job_error or "",
        "question": doc.job_question or "",
        "renderer": doc.job_renderer or "",
    }


# ============================================================ 后台执行


class PPTAgentJobRunner:
    """单个 job 的后台执行体：提交 → 事件流 + 扫目录 → 落盘。

    事件流消费放在子线程（它会阻塞十几分钟），本线程负责周期性扫目录更新
    进度，这样前端才能看到"正在设计第 N 页"而不是干等。
    """

    def __init__(self, doc_id: str, user_id: str, message: str = "",
                 history: Optional[List[Any]] = None) -> None:
        self.doc_id = doc_id
        self.user_id = user_id
        self.message = message or ""
        self.history = history or []
        self.started_at = time.time()
        self.slot: Dict[str, Any] = {}

    # ---------------- 主流程 ----------------

    def run(self) -> None:
        deadline = time.monotonic() + settings.PPT_AGENT_TOTAL_TIMEOUT
        try:
            self._set(job_status="running", job_phase="submitting")
            client = PPTAgentClient.from_settings()
            doc = self._load_doc()
            if doc is None:
                self._fail("文档不存在")
                return
            message = self._build_message(doc)
            num_pages = len((doc.outline or {}).get("slides") or []) or None
            attachments = self._build_attachments()
            if attachments:
                logger.info("PPT job 携带 %d 个附件", len(attachments))

            # 子线程消费事件流（长阻塞），本线程扫目录更新进度
            worker = threading.Thread(
                target=self._consume, args=(client, message, attachments, num_pages, deadline),
                name=f"ppt-sse-{self.doc_id[:8]}", daemon=True)
            worker.start()
            self._progress_loop(client, deadline)
            worker.join(timeout=5)

            self._finish(doc)
        except Exception as e:  # noqa: BLE001 - 后台线程绝不能把异常抛穿
            logger.exception("PPT job 执行异常：%s", e)
            self._fail(f"{type(e).__name__}: {e}")
        finally:
            with _RUNNING_LOCK:
                _RUNNING.pop(self.doc_id, None)

    def _consume(self, client: PPTAgentClient, message: str,
                 attachments: List[Any], num_pages: Optional[int],
                 deadline: float) -> None:
        """子线程：走完整 Gradio 流程并把结果放回 slot。"""
        try:
            outcome = client.generate_deck(
                message, history=self.history or None, attachments=attachments or None,
                num_pages=num_pages, deadline=deadline)
            self.slot["outcome"] = outcome
        except Exception as e:  # noqa: BLE001
            self.slot["error"] = e

    def _progress_loop(self, client: PPTAgentClient, deadline: float) -> None:
        """扫目录更新进度，直到事件流结束 / 取消 / 超时。"""
        interval = max(1, settings.PPT_AGENT_PROGRESS_INTERVAL)
        stall_limit = max(60, settings.PPT_AGENT_STALL_TIMEOUT)
        last_progress = time.monotonic()
        last_signature = ""
        while "outcome" not in self.slot and "error" not in self.slot:
            now = time.monotonic()
            if now >= deadline:
                return
            doc = self._load_doc()
            if doc is not None and doc.job_cancel_requested:
                logger.info("PPT job 收到取消：job_id=%s", self.doc_id)
                self._set(job_status="cancelled", job_phase="cancelled",
                          job_finished_at=now_local())
                return
            scan = client.scan_progress(self.started_at)
            signature = f"{scan['slides']}/{scan['previews']}/{scan['has_pptx']}"
            if signature != last_signature:
                last_signature = signature
                last_progress = now
                self._apply_progress(scan)
            elif now - last_progress > stall_limit:
                logger.warning("PPT job 无进展超时（%ss）：job_id=%s",
                               stall_limit, self.doc_id)
                self._fail(f"超过 {stall_limit}s 无任何进展")
                return
            time.sleep(interval)

    def _apply_progress(self, scan: Dict[str, Any]) -> None:
        """把扫描结果写成进度（页数取 html 与 png 的较大者）。"""
        pages = max(int(scan.get("slides") or 0), int(scan.get("previews") or 0))
        if pages <= 0 and not scan.get("has_pptx"):
            return
        self._set(job_current_page=pages,
                  job_phase=self._infer_phase(scan, pages),
                  job_progress_at=now_local())

    @staticmethod
    def _infer_phase(scan: Dict[str, Any], pages: int) -> str:
        """按目录产物推断阶段（**启发式**，目录结构待真机核实）。

        没有 slides/ 目录时页数恒为 0，此时靠"是否已有 pptx + 已耗时"粗略推进，
        保证前端至少能看到阶段在动，而不是永远卡在 submitting。
        """
        if scan.get("has_pptx"):
            return "finalizing"
        if pages > 0:
            return "designing"
        return "researching"

    # ---------------- 收尾 ----------------

    def _finish(self, doc: PPTDocument) -> None:
        error = self.slot.get("error")
        outcome: Optional[PPTAgentOutcome] = self.slot.get("outcome")

        if error is not None and outcome is None:
            logger.warning("PPT job 调用 PPTAgent 失败，回退本地渲染：%s", error)
            self._fallback_local(f"{type(error).__name__}: {error}")
            return
        if outcome is None:
            self._fallback_local("PPTAgent 未返回任何结果")
            return
        if outcome.pptx:
            self._store(outcome.pptx, renderer="pptagent",
                        event_id=outcome.event_id)
            return
        if outcome.question.strip():
            # R1：PPTAgent 在确认需求，把问题透给用户
            logger.info("PPT job 收到追问，等待用户回答：job_id=%s", self.doc_id)
            self._set(job_status="awaiting_clarification",
                      job_phase="awaiting_clarification",
                      job_question=outcome.question, job_event_id=outcome.event_id,
                      job_progress_at=now_local())
            return
        self._fallback_local("PPTAgent 既未返回产物也未返回追问")

    def _store(self, data: bytes, renderer: str, event_id: str = "") -> None:
        """落盘成品并置为成功。"""
        ok, why = looks_like_pptx(data)
        if not ok:
            logger.warning("PPTAgent 产物非法（%s），回退本地渲染", why)
            self._fallback_local(f"产物非法：{why}")
            return
        doc = self._load_doc()
        if doc is None:
            self._fail("文档不存在")
            return
        fname = f"{uuid.uuid4().hex}.pptx"
        path = settings.ppt_dir / "generated" / fname
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        if doc.file_path and os.path.exists(doc.file_path):
            try:
                os.remove(doc.file_path)
            except OSError:
                pass
        slides = len((doc.outline or {}).get("slides") or [])
        _update_job(self.doc_id, file_path=str(path), status="generated",
                    slide_count=slides, job_status="succeeded", job_phase="succeeded",
                    job_renderer=renderer, job_event_id=event_id, job_error="",
                    job_question="", job_finished_at=now_local(),
                    job_progress_at=now_local())
        logger.info("PPT job 完成：job_id=%s，来源=%s，%d 字节",
                    self.doc_id, renderer, len(data))

    def _fallback_local(self, reason: str) -> None:
        """兜底：真实本地渲染，绝不返回空文件/占位文件。"""
        db: Session = SessionLocal()
        try:
            svc = PPTService(db, None)  # assistant 只被模型链路使用，本地渲染用不到
            doc = svc.documents.get(self.doc_id)
            if doc is None or not doc.outline:
                self._fail(f"{reason}；且本地渲染缺少大纲")
                return
            data = svc.render_local_pptx(doc, doc.outline, doc.user_id)
            ok, why = looks_like_pptx(data)
            if not ok:
                self._fail(f"{reason}；本地渲染产物非法：{why}")
                return
            fname = f"{uuid.uuid4().hex}.pptx"
            path = settings.ppt_dir / "generated" / fname
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            slides = len((doc.outline or {}).get("slides") or [])
            _update_job(self.doc_id, file_path=str(path), status="generated",
                        slide_count=slides, job_status="succeeded",
                        job_phase="succeeded", job_renderer="local",
                        job_error=reason, job_question="",
                        job_finished_at=now_local(), job_progress_at=now_local())
            logger.warning("PPT job 已回退本地渲染完成：job_id=%s，原因=%s",
                           self.doc_id, reason)
        except Exception as e:  # noqa: BLE001
            logger.exception("本地兜底渲染失败：%s", e)
            self._fail(f"{reason}；本地兜底也失败：{type(e).__name__}: {e}")
        finally:
            db.close()

    # ---------------- 工具 ----------------

    def _load_doc(self) -> Optional[PPTDocument]:
        return _open(self.doc_id)

    def _set(self, **fields: Any) -> None:
        _update_job(self.doc_id, **fields)

    def _fail(self, reason: str) -> None:
        self._set(status="failed", job_status="failed", job_phase="failed",
                  job_error=reason[:1000], job_finished_at=now_local())
        logger.error("PPT job 失败：job_id=%s，原因=%s", self.doc_id, reason)

    def _build_message(self, doc: PPTDocument) -> str:
        """拼给 PPTAgent 的 message：标题 + 大纲 Markdown + 原始素材 + 补充需求。"""
        outline_md = build_outline_markdown(doc.outline or {})
        parts = [f"# {doc.title or '演示文稿'}"]
        if doc.subtitle:
            parts.append(f"> {doc.subtitle}")
        parts.append(outline_md)
        material = (doc.source_content or "").strip()
        if material:
            parts.append(f"\n# 原始素材\n{material[:6000]}")
        if self.message.strip():
            parts.append(f"\n# 补充要求\n{self.message.strip()}")
        parts.append("\n请按上面的大纲直接生成完整 PPT，不要反问。")
        return "\n\n".join(parts)

    def _build_attachments(self) -> List[Dict[str, Any]]:
        """（R2）构造 attachments。

        attachments 的 path 必须是 **PPTAgent 容器内** 的路径，跨容器传后端本地
        路径它读不到。只有在两边挂了同一个共享卷、并且知道容器内挂载点时才可用：
        ``PPT_AGENT_ATTACHMENT_MAP="<后端可见目录>:<PPTAgent容器内目录>"``。
        未配置时**不传附件**，材料内容改为内联进 message（见 _build_message）。
        """
        mapping = (settings.PPT_AGENT_ATTACHMENT_MAP or "").strip()
        if ":" not in mapping:
            return []
        backend_dir, agent_dir = mapping.split(":", 1)
        backend_dir, agent_dir = backend_dir.strip(), agent_dir.strip().rstrip("/")
        if not backend_dir or not agent_dir:
            return []
        db: Session = SessionLocal()
        try:
            svc = PPTService(db, None)
            mats = svc.materials.list_by_user(self.user_id)
        finally:
            db.close()
        out: List[Dict[str, Any]] = []
        try:
            target = Path(backend_dir)
            target.mkdir(parents=True, exist_ok=True)
        except OSError as e:  # noqa: BLE001
            logger.warning("附件目录不可用（跳过附件）：%s", e)
            return []
        for m in mats[:8]:
            src = Path(m.file_path or "")
            if not src.is_file():
                continue
            dst = target / src.name
            try:
                if not dst.exists():
                    dst.write_bytes(src.read_bytes())
            except OSError as e:  # noqa: BLE001
                logger.warning("复制附件失败，跳过：%s", e)
                continue
            out.append({"path": f"{agent_dir}/{dst.name}",
                        "orig_name": dst.name,
                        "meta": {"_type": "gradio.FileData"}})
        return out


# ============================================================ 预览


def list_previews(doc_id: str) -> List[str]:
    """列出已生成的页预览 PNG（绝对路径；找不到返回空列表，不抛异常）。"""
    doc = _open(doc_id)
    if doc is None or doc.job_started_at is None:
        return []
    # job_started_at 按系统约定是“东八区本地语义的 naive datetime”。
    # 直接 .timestamp() 会按宿主机本地 TZ 解释：容器/CI 若是 UTC，就会把阈值
    # 错推到未来 8 小时，导致明明已生成的预览图全部被判定为“旧文件”。
    started = doc.job_started_at.replace(tzinfo=CN_TZ).timestamp()
    client = PPTAgentClient.from_settings()
    scan = client.scan_progress(started)
    return list(scan.get("preview_files") or [])


def resolve_preview(doc_id: str, index: int) -> Optional[Path]:
    """按序号解析预览文件路径，并做**目录穿越防护**。

    Returns:
        合法路径；越界 / 不在工作区内 / 文件不存在时返回 None。
    """
    files = list_previews(doc_id)
    if index < 0 or index >= len(files):
        return None
    root = Path((settings.PPT_AGENT_WORKSPACE_DIR or "")).resolve()
    try:
        target = Path(files[index]).resolve()
    except OSError:
        return None
    if not target.is_file():
        return None
    # 必须真正是 root 的子路径。字符串 startswith 会把 /data/work-evil
    # 错当成 /data/work 的子目录，不能用于目录穿越边界判断。
    try:
        target.relative_to(root)
    except ValueError:
        logger.warning("预览路径越界被拒绝：%s", target)
        return None
    return target
