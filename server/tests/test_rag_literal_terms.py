"""符号化术语（6+6+n / W8A8）在知识库问答中的召回契约。

回归背景：中文 bigram 分词只保留长度 >= 2 的英文数字词，查询
「6+6+n是什么」会被切成 ['是什', '什么']，关键词检索因此按这两个高频疑问词
召回全库噪声，真正含该术语的范文反而进不了候选，模型便回答「未检索到足够依据」。
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.knowledge import rag_service as rag_module
from app.application.knowledge.rag_service import RagService, _literal_tokens
from app.core.config import settings
from app.infrastructure.database.base import Base
from app.infrastructure.database.models.identity import UserModel
from app.infrastructure.database.models.knowledge import (
    ChunkModel,
    DocumentModel,
    KnowledgeBaseModel,
)

KB_ID = "kb1"
TERM_DOC = "白云区司法局6+6+N工作机制实施方案"
NOISE_DOC = "信息会议讲话"
TERM_CHUNK = "6+6+N工作机制是指6项基础指标、6项重点任务和N项自选动作。"
NOISE_CHUNK = "要弄清楚什么是重点、什么是短板，抓好贯彻落实。"


@pytest.fixture(autouse=True)
def _no_feedback_weights(monkeypatch):
    """本模块不建 ai_response_feedback 表，反馈重排与本契约无关。"""
    monkeypatch.setattr(RagService, "_feedback_weights",
                        lambda self, user_id, chunk_ids: {})


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[
        UserModel.__table__,
        KnowledgeBaseModel.__table__,
        DocumentModel.__table__,
        ChunkModel.__table__,
    ])
    session = sessionmaker(bind=engine)()
    session.add(KnowledgeBaseModel(
        id=KB_ID, name="白云司法局公文范文库", kb_type="public",
        department_code="", is_active=True))
    session.add(DocumentModel(
        id="doc1", kb_id=KB_ID, status="published", title=TERM_DOC,
        content=TERM_CHUNK))
    session.add(DocumentModel(
        id="doc2", kb_id=KB_ID, status="published", title=NOISE_DOC,
        content=NOISE_CHUNK))
    session.add(DocumentModel(
        id="doc3", kb_id=KB_ID, status="published",
        title="政法队伍建设形势分析报告",
        content="当前队伍建设存在什么问题，如何解决，是什原因造成的。"))
    session.add(ChunkModel(id="c1", doc_id="doc1", chunk_index=0,
                           content=TERM_CHUNK))
    session.add(ChunkModel(id="c2", doc_id="doc2", chunk_index=0,
                           content=NOISE_CHUNK))
    session.add(ChunkModel(id="c3", doc_id="doc3", chunk_index=0,
                           content="当前队伍建设存在什么问题，如何解决，是什原因造成的。"))
    session.commit()
    yield session
    session.close()
    engine.dispose()


def _svc(db, fast_mode: bool = True) -> RagService:
    return RagService(db, None, None, fast_mode=fast_mode)


def test_literal_tokens_normalize_fullwidth_case_and_spaces():
    assert _literal_tokens("6+6+n是什么") == ["6+6+n"]
    assert _literal_tokens("6＋6＋N的含义") == ["6+6+n"]
    assert _literal_tokens("6 + 6 + n是什么") == ["6+6+n"]
    assert _literal_tokens("W8A8量化是什么意思") == ["w8a8"]
    # 纯年份/纯数字不是强特征，不能把「2026年工作总结」短路到字面检索
    assert _literal_tokens("2026年工作总结") == []
    assert _literal_tokens("什么是社区矫正") == []


def test_bigram_tokenizer_really_drops_the_term():
    """保留这个断言：它记录 bug 根因，防止有人改分词时误以为已修复。"""
    assert RagService._tokenize("6+6+n是什么") == ["是什", "什么"]


def test_literal_query_recalls_the_exact_document_not_question_noise(db):
    hits = _svc(db)._keyword_search("6+6+n是什么", [KB_ID], 30)
    assert [h["chunk_id"] for h in hits] == ["c1"]
    assert hits[0]["match_type"] == "literal"
    assert hits[0]["score"] == 1.0


def test_search_returns_the_term_document_as_source(db):
    results = _svc(db).search("6+6+n是什么", user_id="u1")
    assert results
    assert results[0]["doc_title"] == TERM_DOC
    assert results[0]["match_type"] == "literal"
    assert all(r["doc_title"] != NOISE_DOC for r in results)


def test_fullwidth_and_spaced_writing_still_recalls(db):
    svc = _svc(db)
    for query in ("6＋6＋N的含义", "6 + 6 + n是什么"):
        hits = svc._keyword_search(query, [KB_ID], 30)
        assert [h["chunk_id"] for h in hits] == ["c1"], query


def test_title_only_literal_match_is_recalled(db):
    doc = db.get(DocumentModel, "doc1")
    doc.title = "白云区司法局6＋6＋N工作机制实施方案"
    chunk = db.get(ChunkModel, "c1")
    chunk.content = "本方案明确年度重点任务清单与责任分工，不涉及具体指标缩写。"
    db.commit()
    hits = _svc(db)._keyword_search("6+6+n是什么", [KB_ID], 30)
    assert [h["chunk_id"] for h in hits] == ["c1"]


def test_unpublished_document_is_not_recalled(db):
    db.get(DocumentModel, "doc1").status = "pending"
    db.commit()
    hits = _svc(db)._keyword_search("6+6+n是什么", [KB_ID], 30)
    assert all(h["doc_id"] != "doc1" for h in hits)


def test_falls_back_to_bigram_when_literal_is_absent(db):
    """库里没有 9+9+z 时必须退回原检索逻辑，不能让字面短路把结果清空。"""
    hits = _svc(db)._keyword_search("9+9+z是什么", [KB_ID], 30)
    assert hits
    assert all(h["match_type"] == "keyword" for h in hits)


def test_keyword_examples_prioritize_the_literal_document(db):
    examples = _svc(db)._keyword_examples(
        "6+6+n是什么", [KB_ID], top_k=2, max_chars=2500)
    assert [e["title"] for e in examples] == [TERM_DOC]


def test_rerank_cannot_drop_the_only_literal_hit(db, monkeypatch):
    """cross-encoder 对符号术语不敏感时，精确命中仍必须留在最终结果里。"""
    monkeypatch.setattr(settings, "RAG_RERANK_ENABLED", True)
    monkeypatch.setattr(rag_module.reranker, "rerank",
                        lambda query, candidates, top_k: [])
    results = _svc(db, fast_mode=False).search("6+6+n是什么", user_id="u1")
    assert any(r["doc_title"] == TERM_DOC for r in results)
    assert any(r["match_type"] == "literal" for r in results)
