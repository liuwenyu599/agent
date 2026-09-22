"""重建知识库向量索引：按最新分块策略（v2：标题面包屑 + 尺寸约束 + 重叠）
对所有已发布文档重新切块、重写 chunks 表并重建 FAISS 索引。

用法（在 server 目录下）：
    python -m scripts.reindex_vectors          # 全量重建
    python -m scripts.reindex_vectors --dry    # 只统计不写库

注意：重建期间正在进行的检索可能读到旧索引，建议在低峰期执行。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.application.knowledge.access import scope_of_kb  # noqa: E402
from app.application.knowledge.chunkers import LegalChunker, OfficialChunker  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.infrastructure.database.models.knowledge import (  # noqa: E402
    ChunkModel,
    DocumentModel,
    KnowledgeBaseModel,
)
from app.infrastructure.database.session import SessionLocal  # noqa: E402
from app.infrastructure.rag import get_embedder, get_vector_store, reset_rag  # noqa: E402


def main() -> None:
    dry = "--dry" in sys.argv
    db = SessionLocal()
    legal, official = LegalChunker(), OfficialChunker()

    docs = db.scalars(
        select(DocumentModel).where(DocumentModel.status == "published")
    ).all()
    print(f"已发布文档 {len(docs)} 篇")
    if dry:
        for d in docs:
            text = d.content or ""
            if not text.strip():
                continue
            chunker = legal if d.doc_type == "法规" else official
            n = len(chunker.chunk(text, d.id, title=d.title or ""))
            print(f"  {d.id} {d.title[:40]} -> {n} 块")
        return

    # 清空 FAISS 索引文件并重建实例
    for name in ("index.faiss", "metadata.pkl"):
        p = settings.vector_index_dir / name
        if p.exists():
            p.unlink()
    reset_rag()
    vector_store = get_vector_store()
    embedder = get_embedder()

    total_chunks = 0
    for d in docs:
        text = d.content or ""
        if not text.strip():
            print(f"  跳过空文档: {d.id} {d.title[:40]}")
            continue

        db.query(ChunkModel).filter(ChunkModel.doc_id == d.id).delete()
        chunker = legal if d.doc_type == "法规" else official
        chunks = chunker.chunk(text, d.id, title=d.title or "")

        records = []
        for i, c in enumerate(chunks):
            cid = f"{d.id}_{i}"
            db.add(ChunkModel(
                id=cid, doc_id=d.id,
                chunk_index=c["chunk_index"], chunk_type=c["chunk_type"],
                title=c.get("title", ""), content=c["content"],
                char_count=c["metadata"].get("char_count", 0),
                word_count=c["metadata"].get("word_count", 0),
                chunk_metadata=c["metadata"],
            ))
            records.append({
                "chunk_id": cid, "doc_id": d.id, "kb_id": d.kb_id,
                "content": c["content"], "title": c.get("title", ""),
            })
        db.commit()

        if vector_store is not None and records:
            kb = db.get(KnowledgeBaseModel, d.kb_id)
            vectors = embedder.encode([r["content"] for r in records])
            vector_store.add_chunks([
                {**r, "embedding": vectors[i], "scope": scope_of_kb(kb)}
                for i, r in enumerate(records)
            ])
            total_chunks += len(records)
        print(f"  {d.id} {d.title[:40]} -> {len(records)} 块")

    print(f"完成：{len(docs)} 篇文档，{total_chunks} 个向量已重建")


if __name__ == "__main__":
    main()
