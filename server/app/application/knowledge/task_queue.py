"""批量导入任务队列（移植自旧 services/task_queue.py）。

任务状态持久化为 DATA_DIR/tasks/<id>.json，后台线程逐个处理。
"""
import json
import os
import queue
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def _task_dir() -> Path:
    d = settings.DATA_DIR / "tasks"
    d.mkdir(parents=True, exist_ok=True)
    return d


class TaskStatus:
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    PARTIAL = "partial"  # 部分成功


class BatchImportTask:
    def __init__(self, kb_id: str, user_id: str, total_files: int):
        self.id = str(uuid.uuid4())[:8]
        self.kb_id = kb_id
        self.user_id = user_id
        self.total_files = total_files
        self.processed = 0
        self.success = 0
        self.failed = 0
        self.status = TaskStatus.PENDING
        self.current_file = ""
        self.errors = []
        self.created_at = datetime.now().isoformat()
        self.updated_at = datetime.now().isoformat()
        self._save()

    def _save(self):
        task_file = _task_dir() / f"{self.id}.json"
        with open(task_file, "w", encoding="utf-8") as f:
            json.dump({
                "id": self.id,
                "kb_id": self.kb_id,
                "user_id": self.user_id,
                "total_files": self.total_files,
                "processed": self.processed,
                "success": self.success,
                "failed": self.failed,
                "status": self.status,
                "current_file": self.current_file,
                "errors": self.errors,
                "created_at": self.created_at,
                "updated_at": self.updated_at,
            }, f, ensure_ascii=False, indent=2)

    def update(self, current_file: str = None, increment: bool = False,
               success: bool = True, error: str = None):
        if current_file:
            self.current_file = current_file
        if increment:
            self.processed += 1
            if success:
                self.success += 1
            else:
                self.failed += 1
                if error:
                    self.errors.append({"file": current_file, "error": error})
        self.updated_at = datetime.now().isoformat()
        self._save()

    def set_status(self, status: str):
        self.status = status
        self.updated_at = datetime.now().isoformat()
        self._save()

    @classmethod
    def get(cls, task_id: str) -> Optional[Dict]:
        task_file = _task_dir() / f"{task_id}.json"
        if not task_file.exists():
            return None
        with open(task_file, "r", encoding="utf-8") as f:
            return json.load(f)

    @classmethod
    def list_by_user(cls, user_id: str) -> List[Dict]:
        tasks = []
        for f in _task_dir().glob("*.json"):
            try:
                with open(f, "r", encoding="utf-8") as fh:
                    task = json.load(fh)
                    if task.get("user_id") == user_id:
                        tasks.append(task)
            except Exception:
                pass
        return sorted(tasks, key=lambda x: x.get("created_at", ""), reverse=True)


_task_queue = queue.Queue()
_worker_thread = None


def _process_worker():
    from pathlib import Path as _Path

    from app.application.knowledge.document_service import DocumentService, new_doc_id
    from app.infrastructure.database import SessionLocal
    from app.infrastructure.database.models.knowledge import ChunkModel, DocumentModel
    from app.infrastructure.rag import get_embedder, get_vector_store

    doc_service = DocumentService()

    while True:
        try:
            task_id, file_path, kb_id, user_id, user_role, original_name = _task_queue.get(timeout=1)

            task = BatchImportTask.get(task_id)
            if not task:
                continue

            task_obj = BatchImportTask.__new__(BatchImportTask)
            task_obj.__dict__.update(task)
            task_obj.set_status(TaskStatus.PROCESSING)
            task_obj.update(current_file=original_name)

            try:
                text = doc_service.extract_text(_Path(file_path), original_name)

                if "办法" in text or "规定" in text or "条" in text[:1000]:
                    chunks = doc_service.legal_chunker.chunk(text, task_id)
                else:
                    chunks = doc_service.official_chunker.chunk(text, task_id)

                db = SessionLocal()
                try:
                    doc_id = new_doc_id()
                    doc = DocumentModel(
                        id=doc_id,
                        kb_id=kb_id,
                        title=original_name.replace(".docx", "").replace(".pdf", "").replace(".txt", ""),
                        doc_type="法规" if "办法" in text else "公文",
                        content=text[:500000],
                        status="pending",
                        uploaded_by=user_id,
                        created_by=user_id,
                    )
                    db.add(doc)

                    chunk_records = []
                    for i, chunk_data in enumerate(chunks):
                        chunk_id = f"{doc_id}_{i}"
                        chunk = ChunkModel(
                            id=chunk_id,
                            doc_id=doc_id,
                            chunk_index=chunk_data["chunk_index"],
                            chunk_type=chunk_data["chunk_type"],
                            title=chunk_data.get("title", ""),
                            content=chunk_data["content"],
                            char_count=chunk_data["metadata"].get("char_count", 0),
                            word_count=chunk_data["metadata"].get("word_count", 0),
                            chunk_metadata=chunk_data["metadata"],
                        )
                        db.add(chunk)
                        chunk_records.append({
                            "chunk_id": chunk_id, "doc_id": doc_id, "kb_id": kb_id,
                            "content": chunk_data["content"], "title": chunk_data.get("title", ""),
                        })

                    db.commit()
                    task_obj.update(current_file=original_name, increment=True, success=True)

                finally:
                    db.close()

                if os.path.exists(file_path):
                    os.remove(file_path)

            except Exception as e:
                task_obj.update(current_file=original_name, increment=True,
                                success=False, error=str(e))
                if os.path.exists(file_path):
                    os.remove(file_path)

            task = BatchImportTask.get(task_id)
            if task["processed"] >= task["total_files"]:
                if task["failed"] == 0:
                    task_obj.set_status(TaskStatus.COMPLETED)
                elif task["success"] == 0:
                    task_obj.set_status(TaskStatus.FAILED)
                else:
                    task_obj.set_status(TaskStatus.PARTIAL)

            _task_queue.task_done()

        except queue.Empty:
            continue
        except Exception as e:
            logger.error("[Worker Error] %s", e)
            time.sleep(1)


def start_worker():
    global _worker_thread
    if _worker_thread is None or not _worker_thread.is_alive():
        _worker_thread = threading.Thread(target=_process_worker, daemon=True)
        _worker_thread.start()
        logger.info("[TaskQueue] Worker started")


def submit_task(task_id: str, file_path: str, kb_id: str, user_id: str,
                user_role: str, original_name: str):
    start_worker()
    _task_queue.put((task_id, file_path, kb_id, user_id, user_role, original_name))


def get_queue_status():
    return {
        "queue_size": _task_queue.qsize(),
        "worker_alive": _worker_thread is not None and _worker_thread.is_alive(),
    }
