"""风格自学习（style_learning）单测。

覆盖：终稿门槛、蒸馏落库（source=auto upsert）、24h 冷却、冷却过期后更新
（仍只有一条自动记忆）、模型异常不影响流程、画像清洗（围栏/条目式）、
ScopedWritingMemory.prompt_block 自动消费自动记忆。
"""
import pytest

from app.application.writing.scoped_memory import ScopedWritingMemory
from app.application.writing.style_learning import (
    _sanitize_profile,
    distill_style,
)
from app.core.config import settings
from app.infrastructure.database import Base, engine
from app.infrastructure.database.models.writing_memory import WritingMemoryModel
from app.infrastructure.database.models.writing_task import WritingTaskModel
from app.infrastructure.database.session import SessionLocal
from app.infrastructure.repositories.identity import SqlAlchemyUserRepository
from app.application.identity.service import AuthService

Base.metadata.create_all(bind=engine)


class FakeGateway:
    def __init__(self, reply="画像正文"):
        self.reply = reply
        self.calls = []

    def complete(self, messages, temperature=None, max_tokens=None):
        self.calls.append(messages)
        return self.reply


class BoomGateway:
    def complete(self, messages, temperature=None, max_tokens=None):
        raise RuntimeError("模型抽风")


@pytest.fixture(scope="module")
def user():
    db = SessionLocal()
    try:
        repo = SqlAlchemyUserRepository(db)
        users = repo.list_all()
        if users:
            u = users[0]  # conftest 模块隔离库里的种子用户
        else:
            _, u = AuthService(repo).register_first(
                "styledev", "styledev@test.local", "Passw0rd!2026",
                real_name="风格用户")
        return u.id
    finally:
        db.close()


def _seed_finals(user_id, n, doc_type="通知"):
    db = SessionLocal()
    try:
        for i in range(n):
            db.add(WritingTaskModel(
                user_id=user_id, session_id=None, document_id=None,
                context={"document_type": doc_type, "title": f"第{i}篇"},
                current_content=f"关于某事项的通知。第{i}篇正文，" + "本段文字较长。" * 5,
                ai_draft="", version_no=1, status="final"))
        db.commit()
    finally:
        db.close()


def _auto_rows(user_id, doc_type="通知"):
    db = SessionLocal()
    try:
        from sqlalchemy import select
        return db.scalars(select(WritingMemoryModel).where(
            WritingMemoryModel.owner_user_id == user_id,
            WritingMemoryModel.document_type == doc_type,
            WritingMemoryModel.source == "auto")).all()
    finally:
        db.close()


def test_distill_requires_min_finals(user):
    _seed_finals(user, 2)  # 默认门槛 3
    gw = FakeGateway()
    assert distill_style(user, "通知", gateway=gw) is None
    assert gw.calls == []
    assert _auto_rows(user) == []


def test_distill_creates_auto_memory(user):
    _seed_finals(user, 1)  # 累计 3 篇
    gw = FakeGateway("·条目一：语气庄重\n·条目二：多用短句")
    profile = distill_style(user, "通知", gateway=gw)
    assert profile and profile.startswith("·")
    rows = _auto_rows(user)
    assert len(rows) == 1
    assert rows[0].scope == "personal"
    assert rows[0].source == "auto"
    assert rows[0].content == profile
    assert rows[0].enabled is True
    assert len(gw.calls) == 1


def test_distill_cooldown_skips_recent(user):
    gw = FakeGateway("·另一份画像")
    assert distill_style(user, "通知", gateway=gw) is None
    assert gw.calls == []  # 刚蒸馏过（updated_at 新鲜），冷却期内跳过


def test_distill_cooldown_expired_updates_row(user, monkeypatch):
    monkeypatch.setattr(settings, "WRITING_STYLE_LEARN_COOLDOWN_HOURS", 1)
    from datetime import timedelta

    from app.core.timeutil import now_local
    db = SessionLocal()
    try:
        row = _auto_rows(user)[0]
        m = db.get(WritingMemoryModel, row.id)
        m.updated_at = now_local() - timedelta(hours=2)
        db.commit()
    finally:
        db.close()
    gw = FakeGateway("·更新后的画像")
    profile = distill_style(user, "通知", gateway=gw)
    assert profile == "·更新后的画像"
    assert len(_auto_rows(user)) == 1  # 仍是同一条，覆盖不新增


def test_distill_gateway_failure_is_swallowed(user, monkeypatch):
    monkeypatch.setattr(settings, "WRITING_STYLE_LEARN_COOLDOWN_HOURS", 1)
    from datetime import timedelta

    from app.core.timeutil import now_local
    db = SessionLocal()
    try:
        row = _auto_rows(user)[0]
        m = db.get(WritingMemoryModel, row.id)
        m.updated_at = now_local() - timedelta(hours=2)
        db.commit()
    finally:
        db.close()
    before = _auto_rows(user)[0].content
    with pytest.raises(RuntimeError):
        # 模型异常应向上抛给 _distill_guarded 兜底；直接调用方拿得到异常
        distill_style(user, "通知", gateway=BoomGateway())
    assert _auto_rows(user)[0].content == before  # 落库未被破坏


def test_sanitize_strips_fences_and_prefixes():
    raw = "```text\n风格画像：·庄重\n条目二\n```"
    assert _sanitize_profile(raw) == "·庄重\n·条目二"


def test_prompt_block_consumes_auto_memory(user):
    db = SessionLocal()
    try:
        block = ScopedWritingMemory(db).prompt_block(user, "通知")
        assert "更新后的画像" in block or "条目" in block
        assert "写作习惯记忆" in block
    finally:
        db.close()
