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

无 PPTAgent 时的正式路径
------------------------
``PPT_AGENT_URL`` 为空时，submit_job **不再拒绝**，
而是登记同一条异步 job、由 :class:`LocalRenderJobRunner` 按内容自适应排版；
只有用户显式选模板时才使用模板底稿。
客户端仍按 ``/ppt/jobs`` 轮询，接口与终态语义完全一致。
"""
import os
import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.application.ppt.service import PPTService
from app.infrastructure.ppt.ppt_agent_client import (
    PPTAgentClient, PPTAgentOutcome, build_outline_markdown, looks_like_pptx,
)
from app.core.config import settings
from app.core.logging import get_logger
from app.core.timeutil import CN_TZ, now_local
from app.domain.ppt.entities import PPTDocument
import app.infrastructure.database as _db  # 动态访问，隔离换库后仍能命中新引擎
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
    db: Session = _db.SessionLocal()
    try:
        m = db.get(PPTDocumentModel, doc_id)
        return _doc(m) if m else None
    finally:
        db.close()


def uses_local_renderer(doc_id: str) -> bool:
    """Free-layout documents stay on 35B + Draw.io even if a legacy URL remains set."""
    if not (settings.PPT_AGENT_URL or "").strip():
        return True
    doc = _open(doc_id)
    return doc is not None and not doc.template_id


def _update_job(doc_id: str, **fields: Any) -> Optional[PPTDocument]:
    """更新 job 字段（短事务：开→写→提交→关，绝不长时间持锁）。"""
    db: Session = _db.SessionLocal()
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


# ============================================================ 本地渲染（无 PPTAgent）

# 本地渲染是确定性排版，秒级完成，所以它既是「PPTAgent 失败后的兜底」，
# 也是「没有 PPTAgent 时的正式路径」——两条路共用同一段落盘逻辑。
def _render_local_previews(pptx_path: Path, doc_id: str) -> int:
    """把生成的 pptx 逐页转 PNG（尽力而为，复用 soffice + pdftoppm 工具链）。

    产出写入 ``ppt_dir/preview/{doc_id}/pg-*.png`` —— 与
    :meth:`PPTService.preview_document` 的缓存目录与命名**完全一致**，
    ``list_previews`` 优先从这里取图。命令缺失 / 超时 / 转换失败一律记日志
    后返回 0：预览缺失只影响工作台缩略图（前端有降级文案），不影响导出。
    """
    import glob
    import subprocess
    import tempfile

    soffice = shutil.which("soffice")
    pdftoppm = shutil.which("pdftoppm")
    if not (soffice and pdftoppm):
        logger.info("PPT 本地页图跳过：容器缺 soffice/pdftoppm（doc_id=%s）", doc_id)
        return 0
    prev_dir = settings.ppt_dir / "preview" / doc_id
    prev_dir.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory() as td:
            src = os.path.join(td, "gen.pptx")
            shutil.copyfile(pptx_path, src)
            subprocess.run([soffice, "--headless", "--convert-to", "pdf",
                            "--outdir", td, src], timeout=180, capture_output=True)
            pdf = os.path.join(td, "gen.pdf")
            if not os.path.exists(pdf):
                logger.info("PPT 本地页图失败：LibreOffice 未产出 PDF（doc_id=%s）", doc_id)
                return 0
            for old in prev_dir.glob("pg-*.png"):
                old.unlink()
            subprocess.run([pdftoppm, "-png", "-r", "90", pdf,
                            os.path.join(str(prev_dir), "pg")],
                           timeout=120, capture_output=True)
        # pdftoppm 会在总页数≥10 时补零（pg-01…），数字序排序两种都正确
        pages = sorted(glob.glob(os.path.join(str(prev_dir), "pg-*.png")),
                       key=lambda p: (len(os.path.basename(p)), p))
        logger.info("PPT 本地页图完成：%d 张（doc_id=%s）", len(pages), doc_id)
        return len(pages)
    except Exception as e:  # noqa: BLE001 - 预览失败绝不能拖垮 job
        logger.warning("PPT 本地页图渲染失败（不影响导出，doc_id=%s）：%s: %s",
                       doc_id, type(e).__name__, e)
        return 0


def _render_local_and_store(doc_id: str, renderer: str = "local") -> Tuple[bool, str]:
    """按用户选择的排版方式渲染并落盘，把 job 置为成功。

    Args:
        doc_id: 文档 ID。
        renderer: 写进 ``job_renderer`` 的来源标记，客户端据此决定提示语。
            ``local`` = 没配 PPTAgent、本地模板就是正式路径（不该报警）；
            ``local_fallback`` = AI 智能设计尝试过但没拿到合格成品，回退本地（要报警）。

    Returns:
        ``(True, "")`` 成功；``(False, 失败说明)`` 失败（调用方决定怎么对外表达）。
    """
    db: Session = _db.SessionLocal()
    try:
        svc = PPTService(db, None)  # assistant 只被模型链路使用，本地渲染用不到
        doc = svc.documents.get(doc_id)
        if doc is None:
            return False, "文档不存在"
        if not doc.outline:
            return False, "本地渲染缺少大纲"
        if doc.template_id:
            data = svc.render_strict_template_pptx(doc, doc.outline, doc.user_id)
            adjusted_outline = doc.outline
        else:
            data, adjusted_outline = svc.render_adaptive_pptx(
                doc, doc.outline, doc.user_id)
        ok, why = looks_like_pptx(data)
        if not ok:
            return False, f"本地渲染产物非法：{why}"
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
        # 逐页预览图（尽力而为）：与 preview_document 共用同一缓存目录约定
        # （ppt_dir/preview/{doc_id}/pg-*.png）。缺 soffice/pdftoppm 或渲染失败
        # 只影响工作台缩略图（前端有降级文案），绝不影响 job 成功与 pptx 导出。
        _render_local_previews(path, doc_id)
        _update_job(doc_id, file_path=str(path), outline=adjusted_outline,
                    status="generated",
                    slide_count=slides, job_status="succeeded",
                    job_phase="succeeded", job_renderer=renderer,
                    job_event_id="", job_error="", job_question="",
                    job_total_pages=slides, job_current_page=slides,
                    job_finished_at=now_local(), job_progress_at=now_local())
        logger.info("PPT 本地渲染完成：job_id=%s，%d 字节", doc_id, len(data))
        return True, ""
    except Exception as e:  # noqa: BLE001 - 落盘失败要变成可读的 job 错误
        logger.exception("PPT 本地渲染失败：%s", e)
        return False, f"{type(e).__name__}: {e}"
    finally:
        db.close()


class LocalRenderJobRunner:
    """无 PPTAgent 时的 job 执行体：本地自适应/显式模板渲染 → 落盘 → 置成功。

    与 :class:`PPTAgentJobRunner` 共用 ``_RUNNING`` 登记与终态语义，
    前端轮询的是同一套 ``/ppt/jobs`` 接口，无需任何客户端改动。
    """

    def __init__(self, doc_id: str) -> None:
        self.doc_id = doc_id

    def run(self) -> None:
        try:
            doc = _open(self.doc_id)
            if doc is None:
                self._fail("文档不存在")
                return
            if doc.job_cancel_requested:
                self._set(job_status="cancelled", job_phase="cancelled",
                          job_finished_at=now_local())
                return
            self._set(job_status="running", job_phase="designing",
                      job_progress_at=now_local())
            ok, why = _render_local_and_store(self.doc_id)
            if not ok:
                self._fail(why)
        except Exception as e:  # noqa: BLE001 - 后台线程绝不能把异常抛穿
            logger.exception("PPT 本地渲染任务异常：%s", e)
            self._fail(f"{type(e).__name__}: {e}")
        finally:
            with _RUNNING_LOCK:
                _RUNNING.pop(self.doc_id, None)

    def _set(self, **fields: Any) -> None:
        _update_job(self.doc_id, **fields)

    def _fail(self, reason: str) -> None:
        self._set(status="failed", job_status="failed", job_phase="failed",
                  job_error=reason[:1000], job_finished_at=now_local())
        logger.error("PPT 本地渲染失败：job_id=%s，原因=%s", self.doc_id, reason)


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

    # 自由排版始终走本地可编辑渲染；旧地址残留不能改变用户已选的生成方式。
    # 显式模板且启用旧服务时仍保留兼容路由。
    if uses_local_renderer(doc_id):
        _update_job(doc_id, job_status="pending", job_phase="submitting",
                    job_error="", job_question="", job_current_page=0,
                    job_total_pages=0, job_cancel_requested=False,
                    job_started_at=now_local(), job_progress_at=now_local(),
                    job_finished_at=None)
        runner = LocalRenderJobRunner(doc_id)
        t = threading.Thread(target=runner.run, name=f"ppt-local-{doc_id[:8]}",
                             daemon=True)
        with _RUNNING_LOCK:
            _RUNNING[doc_id] = t
        t.start()
        logger.info("PPT job 走本地渲染：job_id=%s", doc_id)
        return {"job_id": doc_id, "status": "pending", "phase": "submitting",
                "renderer": "local"}

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
    # 多 worker 下 _RUNNING 是进程内状态，不能用于跨进程判断任务是否存活。
    # 以数据库心跳为准：只有心跳超过 stall timeout 未刷新才对外判失败。
    if status in ("pending", "running"):
        heartbeat = doc.job_progress_at or doc.job_started_at
        stall_limit = max(60, settings.PPT_AGENT_STALL_TIMEOUT)
        if heartbeat is not None:
            stale_seconds = max(0.0, (now_local() - heartbeat).total_seconds())
            if stale_seconds > stall_limit:
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

            # 用户确认后的大纲是唯一内容源。提交前只做确定性净化：
            # 封面/结束页去脏字段，但不重新强制目录，尊重用户“目录改正文”等调整。
            original_outline = doc.outline or {}
            clean_outline = PPTService.sanitize_outline(
                original_outline,
                target_count=len(original_outline.get("slides") or []) or None,
                ensure_toc=False)
            if clean_outline != original_outline:
                updated = _update_job(
                    self.doc_id, outline=clean_outline,
                    slide_count=len(clean_outline.get("slides") or []))
                if updated is not None:
                    doc = updated
                logger.info("[PPT] 提交前规则净化完成：job_id=%s", self.doc_id)

            message = self._build_message(doc)
            num_pages = len((doc.outline or {}).get("slides") or []) or None
            attachments = self._build_attachments()
            if attachments:
                logger.info("PPT job 携带 %d 个附件", len(attachments))

            # AI 智能设计路径：PPTAgent 负责创意设计；后续有自动质量闸与严格模板兜底。
            worker = threading.Thread(
                target=self._consume, args=(client, message, attachments, num_pages, deadline),
                name=f"ppt-sse-{self.doc_id[:8]}", daemon=True)
            worker.start()
            self._progress_loop(client, deadline)
            worker.join(timeout=5)

            self._finish(doc, client, message, attachments, num_pages, deadline)
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

    def _retry_generate(self, client: PPTAgentClient, message: str,
                        attachments: List[Any], num_pages: Optional[int],
                        deadline: float, extra_instruction: str) -> Optional[PPTAgentOutcome]:
        """系统内部自动重试；不再把模型追问或质量修复要求甩给用户。"""
        if time.monotonic() >= deadline - 30:
            logger.warning("[PPT] 剩余时间不足，跳过自动重试：job_id=%s", self.doc_id)
            return None
        self._set(job_status="running", job_phase="designing",
                  job_question="", job_progress_at=now_local())
        try:
            return client.generate_deck(
                message + "\n\n# 系统自动修正要求\n" + extra_instruction,
                history=self.history or None,
                attachments=attachments or None,
                num_pages=num_pages, deadline=deadline)
        except Exception as e:  # noqa: BLE001
            logger.warning("[PPT] 自动重试失败：job_id=%s %s: %s",
                           self.doc_id, type(e).__name__, e)
            self.slot["retry_error"] = f"{type(e).__name__}: {str(e) or '上游服务未提供具体原因'}"
            return None

    def _accept_or_retry_quality(self, data: bytes, event_id: str,
                                 client: PPTAgentClient, message: str,
                                 attachments: List[Any], num_pages: Optional[int],
                                 deadline: float) -> bool:
        expected = int(num_pages or 0)
        db: Session = _db.SessionLocal()
        try:
            quality_rules = PPTService(db, None).active_quality_rules(self.user_id)
        finally:
            db.close()
        issues = PPTService.assess_generated_pptx(data, expected, quality_rules)
        if not issues:
            self._store(data, renderer="pptagent", event_id=event_id)
            return True

        logger.warning("[PPT] AI 智能设计未通过质量闸：job_id=%s issues=%s",
                       self.doc_id, "；".join(issues))
        retry = self._retry_generate(
            client, message, attachments, num_pages, deadline,
            "上一次成品未通过系统质量检查。请完整重新生成一次，并修复以下问题："
            + "；".join(issues)
            + "。必须保持已确认页数，不得新增封面或结束页，不得编造数据。")
        if retry and retry.pptx:
            retry_issues = PPTService.assess_generated_pptx(retry.pptx, expected, quality_rules)
            if not retry_issues:
                logger.info("[PPT] AI 智能设计自动重试通过质量闸：job_id=%s", self.doc_id)
                self._store(retry.pptx, renderer="pptagent_retry",
                            event_id=retry.event_id)
                return True
            logger.warning("[PPT] AI 智能设计重试仍未通过：job_id=%s issues=%s",
                           self.doc_id, "；".join(retry_issues))
        return False

    def _finish(self, doc: PPTDocument, client: PPTAgentClient, message: str,
                attachments: List[Any], num_pages: Optional[int],
                deadline: float) -> None:
        error = self.slot.get("error")
        outcome: Optional[PPTAgentOutcome] = self.slot.get("outcome")

        if error is not None and outcome is None:
            logger.warning("PPT job 调用 PPTAgent 失败，自动切换严格模板渲染：%s", error)
            self._fallback_local(f"{type(error).__name__}: {error}")
            return
        if outcome is None:
            self._fallback_local("PPTAgent 未返回任何结果")
            return
        if outcome.pptx:
            if self._accept_or_retry_quality(
                    outcome.pptx, outcome.event_id, client, message,
                    attachments, num_pages, deadline):
                return
            reason = "AI 智能设计质量检查未通过"
            if self.slot.get("retry_error"):
                reason += "；自动重试失败：" + self.slot["retry_error"]
            self._fallback_local(reason)
            return
        if outcome.question.strip():
            # 用户已确认过大纲，中间追问由系统按默认策略自动回答一次。
            logger.info("[PPT] PPTAgent 追问已由系统自动处理：job_id=%s", self.doc_id)
            retry = self._retry_generate(
                client, message, attachments, num_pages, deadline,
                "用户已经确认大纲。请按已确认大纲、默认政务设计约束和现有材料直接继续，"
                "采用合理默认值，不要再次向用户提问。")
            if retry and retry.pptx and self._accept_or_retry_quality(
                    retry.pptx, retry.event_id, client, message,
                    attachments, num_pages, deadline):
                return
            self._fallback_local("AI 智能设计需要额外确认，已自动采用严格模板")
            return
        self._fallback_local("PPTAgent 未返回可用产物")

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
        """严格套模板兜底：AI 智能设计失败/低质时自动切换，用户无感。"""
        # 与「没有 PPTAgent 时的正式路径」共用同一段落盘逻辑，避免两份实现漂移；
        # 但要区分来源：这里确实是「AI 尝试过且没成」，客户端必须如实告知用户。
        ok, why = _render_local_and_store(self.doc_id, renderer="local_fallback")
        if ok:
            logger.warning("[PPT] 已切换严格套模板并完成：job_id=%s，内部原因=%s",
                           self.doc_id, reason)
            return
        self._fail(f"{reason}；{why}")

    # ---------------- 工具 ----------------

    def _load_doc(self) -> Optional[PPTDocument]:
        return _open(self.doc_id)

    def _set(self, **fields: Any) -> None:
        _update_job(self.doc_id, **fields)

    def _fail(self, reason: str) -> None:
        self._set(status="failed", job_status="failed", job_phase="failed",
                  job_error=reason[:1000], job_finished_at=now_local())
        logger.error("PPT job 失败：job_id=%s，原因=%s", self.doc_id, reason)

    def _design_guidance(self, doc: PPTDocument) -> str:
        """服务端统一设计约束；客户端无需再拼任何风格提示词。"""
        db: Session = _db.SessionLocal()
        try:
            svc = PPTService(db, None)
            return svc.design_prompt_for_document(doc)
        except Exception as e:  # noqa: BLE001
            logger.warning("[PPT] 读取服务端设计约束失败：%s", e)
            return ""
        finally:
            db.close()

    def _build_message(self, doc: PPTDocument) -> str:
        """用户内容在前，系统设计约束在后；最终输入由服务端统一完成。"""
        outline_md = build_outline_markdown(doc.outline or {})
        parts = [f"# {doc.title or '演示文稿'}"]
        if doc.subtitle:
            parts.append(f"> {doc.subtitle}")
        parts.append("# 已确认页面大纲\n" + outline_md)

        material = (doc.source_content or "").strip()
        if material:
            parts.append(f"# 原始素材\n{material[:8000]}")

        # 用户只需要表达业务补充要求；风格、页数、封面、质量规则均由服务端接管。
        if self.message.strip():
            parts.append(f"# 用户补充要求\n{self.message.strip()}")

        design = self._design_guidance(doc)
        parts.append(
            "# 系统设计约束（必须执行）\n"
            + (design or "采用庄重、清晰、可直接汇报的政务演示风格。")
            + "\n严格按已确认大纲页数和页面角色生成；不得额外增加封面/结束页；"
              "不得编造材料中不存在的数据、荣誉、比例、年份或结论。"
        )
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
        db: Session = _db.SessionLocal()
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
    """列出已生成的页预览图（绝对路径；找不到返回空列表，不抛异常）。

    取图顺序：
    1. 本地渲染路径的页图（``ppt_dir/preview/{doc_id}/pg-*.png``，与
       ``preview_document`` 缓存同目录）——无 PPTAgent 的正式链路走这里；
    2. 都没有时再扫 PPTAgent 工作区（原逻辑，配置了 URL 才扫）。
    """
    doc = _open(doc_id)
    if doc is None or doc.job_started_at is None:
        return []
    # 本地渲染路径：pg-*.png 按页序排好（pdftoppm 在 ≥10 页时会补零，
    # 先按文件名长度再按名称排，两种命名都得到正确页序）
    local_dir = settings.ppt_dir / "preview" / doc_id
    if local_dir.is_dir():
        local = sorted(local_dir.glob("pg-*.png"),
                       key=lambda p: (len(p.name), p.name))
        if local:
            return [str(p) for p in local]
    if not (settings.PPT_AGENT_URL or "").strip():
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
    try:
        target = Path(files[index]).resolve()
    except OSError:
        return None
    if not target.is_file():
        return None
    # 目录穿越防护：目标必须落在允许的根之内。字符串 startswith 会把
    # /data/work-evil 错当成 /data/work 的子目录，不能用于边界判断。
    # 两个合法根：本地页图目录（preview_document 同款）+ PPTAgent 工作区。
    roots = [(settings.ppt_dir / "preview").resolve()]
    ws = (settings.PPT_AGENT_WORKSPACE_DIR or "").strip()
    if ws:
        roots.append(Path(ws).resolve())
    for root in roots:
        try:
            target.relative_to(root)
            return target
        except ValueError:
            continue
    logger.warning("预览路径越界被拒绝：%s", target)
    return None
