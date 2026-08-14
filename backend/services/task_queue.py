import os
import json
import threading
import queue
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
import uuid

TASK_DIR = Path("/home/lwy/judicial-ai/tasks")
TASK_DIR.mkdir(parents=True, exist_ok=True)

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
        task_file = TASK_DIR / f"{self.id}.json"
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
                "updated_at": self.updated_at
            }, f, ensure_ascii=False, indent=2)
    
    def update(self, current_file: str = None, increment: bool = False, success: bool = True, error: str = None):
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
        task_file = TASK_DIR / f"{task_id}.json"
        if not task_file.exists():
            return None
        with open(task_file, "r", encoding="utf-8") as f:
            return json.load(f)
    
    @classmethod
    def list_by_user(cls, user_id: str) -> List[Dict]:
        tasks = []
        for f in TASK_DIR.glob("*.json"):
            try:
                with open(f, "r", encoding="utf-8") as fh:
                    task = json.load(fh)
                    if task.get("user_id") == user_id:
                        tasks.append(task)
            except:
                pass
        return sorted(tasks, key=lambda x: x.get("created_at", ""), reverse=True)

# 后台处理队列
_task_queue = queue.Queue()
_worker_thread = None

def _process_worker():
    """后台 worker 线程"""
    from backend.services.document_service import DocumentService
    from backend.database.postgres import SessionLocal
    from backend.database.models import Document as DBDocument, Chunk
    from backend.rag.chunker.legal_chunker import LegalChunker
    from backend.rag.chunker.official_chunker import OfficialChunker
    import docx
    
    doc_service = DocumentService()
    legal_chunker = LegalChunker()
    official_chunker = OfficialChunker()
    
    while True:
        try:
            task_id, file_path, kb_id, user_id, user_role, original_name = _task_queue.get(timeout=1)
            
            task = BatchImportTask.get(task_id)
            if not task:
                continue
            
            # 更新状态
            task_obj = BatchImportTask.__new__(BatchImportTask)
            task_obj.__dict__.update(task)
            task_obj.set_status(TaskStatus.PROCESSING)
            task_obj.update(current_file=original_name)
            
            try:
                # 解析文档
                text = doc_service._extract_text(Path(file_path), original_name)
                
                # 判断类型并切片
                if "办法" in text or "规定" in text or "条" in text[:1000]:
                    chunks = legal_chunker.chunk(text, task_id)
                else:
                    chunks = official_chunker.chunk(text, task_id)
                
                # 创建数据库记录
                db = SessionLocal()
                try:
                    doc_id = str(uuid.uuid4())[:8]
                    doc = DBDocument(
                        id=doc_id,
                        kb_id=kb_id,
                        title=original_name.replace(".docx", "").replace(".pdf", "").replace(".txt", ""),
                        doc_type="法规" if "办法" in text else "公文",
                        content=text[:500000],
                        status="pending",
                        uploaded_by=user_id,
                        created_by=user_id
                    )
                    db.add(doc)
                    
                    for chunk_data in chunks:
                        chunk = Chunk(
                            id=str(uuid.uuid4()),
                            doc_id=doc_id,
                            chunk_index=chunk_data["chunk_index"],
                            chunk_type=chunk_data["chunk_type"],
                            title=chunk_data.get("title", ""),
                            content=chunk_data["content"],
                            char_count=chunk_data["metadata"].get("char_count", 0),
                            word_count=chunk_data["metadata"].get("word_count", 0),
                            chunk_metadata=chunk_data["metadata"]
                        )
                        db.add(chunk)
                    
                    db.commit()
                    task_obj.update(current_file=original_name, increment=True, success=True)
                    
                finally:
                    db.close()
                
                # 清理临时文件
                if os.path.exists(file_path):
                    os.remove(file_path)
                    
            except Exception as e:
                task_obj.update(current_file=original_name, increment=True, success=False, error=str(e))
                if os.path.exists(file_path):
                    os.remove(file_path)
            
            # 检查是否完成
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
            print(f"[Worker Error] {e}")
            time.sleep(1)

def start_worker():
    """启动后台 worker"""
    global _worker_thread
    if _worker_thread is None or not _worker_thread.is_alive():
        _worker_thread = threading.Thread(target=_process_worker, daemon=True)
        _worker_thread.start()
        print("[TaskQueue] Worker started")

def submit_task(task_id: str, file_path: str, kb_id: str, user_id: str, user_role: str, original_name: str):
    """提交任务到队列"""
    start_worker()
    _task_queue.put((task_id, file_path, kb_id, user_id, user_role, original_name))

def get_queue_status():
    """获取队列状态"""
    return {
        "queue_size": _task_queue.qsize(),
        "worker_alive": _worker_thread is not None and _worker_thread.is_alive()
    }
