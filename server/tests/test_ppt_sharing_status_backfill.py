"""迁移 022 的回填回归：在「有数据」的库上验证，纯 SQLite、不碰 client/DB。

空库跑迁移时两条 UPDATE 影响 0 行，验证不了回填条件；这里造多行记录，
重点防止「填过授权说明的个人模板」被误标成待审核共享模板。
"""
from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

_MIGRATION = (Path(__file__).resolve().parents[1]
              / "app" / "migrations" / "versions"
              / "022_ppt_template_sharing_status.py")
_spec = importlib.util.spec_from_file_location("migration_022", _MIGRATION)
migration = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(migration)


def _seed_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE ppt_templates ("
        "id TEXT PRIMARY KEY, is_official INTEGER NOT NULL, "
        "description TEXT, license_note TEXT, "
        "sharing_status TEXT NOT NULL DEFAULT 'private')")
    conn.executemany(
        "INSERT INTO ppt_templates "
        "(id, is_official, description, license_note) VALUES (?, ?, ?, ?)",
        [
            ("official", 1, "政务通用模板", ""),
            ("pending_shared", 0, "待检查的共享模板", "本单位内部工作 PPT，已获使用授权"),
            ("private_with_license", 0, "我的个人模板", "本单位内部工作 PPT，已获使用授权"),
            ("private_plain", 0, "个人草稿", None),
            ("private_empty_license", 0, "个人模板", ""),
        ],
    )
    conn.commit()
    return conn


def _apply_backfill(conn: sqlite3.Connection) -> None:
    conn.execute(
        "UPDATE ppt_templates SET sharing_status = 'published' "
        f"WHERE {migration.PUBLISHED_BACKFILL_WHERE}")
    conn.execute(
        "UPDATE ppt_templates SET sharing_status = 'pending' "
        f"WHERE {migration.PENDING_BACKFILL_WHERE}")
    conn.commit()


def test_backfill_only_marks_official_and_pending_shared() -> None:
    conn = _seed_db()
    try:
        _apply_backfill(conn)
        rows = dict(conn.execute(
            "SELECT id, sharing_status FROM ppt_templates").fetchall())
    finally:
        conn.close()
    assert rows == {
        "official": "published",
        "pending_shared": "pending",
        "private_with_license": "private",
        "private_plain": "private",
        "private_empty_license": "private",
    }


def test_license_note_is_not_a_sharing_signal() -> None:
    """回归护栏：授权说明属于素材合规字段，不能参与共享状态判定。"""
    assert "license_note" not in migration.PENDING_BACKFILL_WHERE
    assert "待检查的共享模板" in migration.PENDING_BACKFILL_WHERE


def test_downgrade_revision_chain_is_intact() -> None:
    assert migration.revision == "022_ppt_template_sharing_status"
    assert migration.down_revision == "021_ppt_library_images"
