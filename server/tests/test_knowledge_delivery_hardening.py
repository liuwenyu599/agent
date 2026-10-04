import asyncio
from pathlib import Path

import numpy as np
import pytest

from app.application.knowledge.hardened_document_service import HardenedDocumentService
from app.application.knowledge.upload_security import safe_client_filename, stream_upload_to_file
from app.core.exceptions import AppError
from app.infrastructure.rag.vector_store import FAISSVectorStore
from app.main import create_app


class _Upload:
    def __init__(self, data: bytes, filename: str = "a.pdf"):
        self.data = data
        self.filename = filename
        self.pos = 0

    async def read(self, size: int = -1):
        if self.pos >= len(self.data):
            return b""
        if size < 0:
            size = len(self.data) - self.pos
        chunk = self.data[self.pos:self.pos + size]
        self.pos += len(chunk)
        return chunk


def test_client_filename_never_controls_server_path_components():
    name, suffix = safe_client_filename(r"..\..\secret\policy.pdf", [".pdf"])
    assert name == "policy.pdf"
    assert suffix == ".pdf"
    name2, _ = safe_client_filename("../../etc/passwd.pdf", [".pdf"])
    assert name2 == "passwd.pdf"
    assert "/" not in name2 and "\\" not in name2


def test_stream_upload_enforces_limit_and_removes_partial_file(tmp_path: Path):
    target = tmp_path / "upload.bin"
    with pytest.raises(AppError):
        asyncio.run(stream_upload_to_file(_Upload(b"123456"), target, max_bytes=5))
    assert not target.exists()


def _faiss_can_write(directory: Path) -> bool:
    """探测 faiss 能否在本机把索引写进 ``directory``。

    faiss 的原生 ``fopen`` 与 Python 的 ``open()`` 走的是两套权限路径：在本机的
    ``%TEMP%``（``C:\\Users\\<用户名>\\AppData\\Local\\Temp``）下 Python 能正常建文件，
    faiss 却报 "could not open ... No such file or directory"；换到项目内的 D 盘目录
    则中英文路径都能正常写入。**与中文路径无关，也与被测逻辑无关**，是 Windows 上
    faiss wheel 的运行环境限制，故先探测再决定是否跳过；CI（Linux）上照常执行。
    """
    import faiss

    probe_dir = directory / "_faiss_write_probe"
    probe_dir.mkdir(parents=True, exist_ok=True)
    probe_file = probe_dir / "probe.faiss"
    try:
        faiss.write_index(faiss.IndexFlatIP(2), str(probe_file))
        return True
    except Exception:
        return False
    finally:
        if probe_file.exists():
            probe_file.unlink()
        if probe_dir.exists():
            probe_dir.rmdir()


def test_faiss_delete_physically_compacts_and_persists(tmp_path: Path):
    if not _faiss_can_write(tmp_path):
        pytest.skip("faiss 在本机无法写入该临时目录（Windows 用户目录权限限制）")
    store = FAISSVectorStore(index_path=str(tmp_path))
    store.add_chunks([
        {"chunk_id": "a1", "doc_id": "doc-a", "kb_id": "kb", "content": "a",
         "title": "a", "embedding": np.array([1.0, 0.0], dtype="float32")},
        {"chunk_id": "b1", "doc_id": "doc-b", "kb_id": "kb", "content": "b",
         "title": "b", "embedding": np.array([0.0, 1.0], dtype="float32")},
    ])
    assert store.index.ntotal == 2
    assert store.delete_by_document("doc-a") == 1
    assert store.index.ntotal == 1
    assert {m["doc_id"] for m in store.metadata.values()} == {"doc-b"}

    reloaded = FAISSVectorStore(index_path=str(tmp_path))
    assert reloaded.index.ntotal == 1
    assert {m["doc_id"] for m in reloaded.metadata.values()} == {"doc-b"}


def test_vectorization_failure_is_recorded_not_silently_discarded():
    class BadEmbedder:
        def encode(self, texts):
            raise RuntimeError("embedding unavailable")

    class Store:
        def add_chunks(self, chunks):
            raise AssertionError("must not reach store")

    svc = HardenedDocumentService(embedder=BadEmbedder(), vector_store=Store())
    count = svc._vectorize([
        {"chunk_id": "c", "doc_id": "d", "kb_id": "k", "content": "正文", "title": "标题"}
    ])
    assert count == 0
    assert "embedding unavailable" in svc._last_vector_error


def test_reindex_route_is_exposed():
    paths = create_app().openapi()["paths"]
    assert "/api/v1/knowledge/documents/{doc_id}/reindex" in paths
