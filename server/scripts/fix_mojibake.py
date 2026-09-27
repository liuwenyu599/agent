"""一次性修复脚本：把历史上被按 Latin-1 误解码并落库的中文乱码改回 UTF-8 正文。

背景
----
模型网关流式接口（``response.iter_lines(decode_unicode=True)``）在响应头未声明
charset 时被 requests 按 ISO-8859-1 解码，UTF-8 中文因此变成 ``'è¿\\x9bä¸...'``
形态并写入数据库。该变换可逆：``s.encode('latin-1').decode('utf-8')`` 可还原。
根因已在 ``app/infrastructure/ai/qwen.py`` 修复；本脚本只清洗历史脏数据。

用法
----
    # 1) 先扫描（默认，只读，不改库），确认哪些表真的中招
    D:/apps/anaconda3/python.exe scripts/fix_mojibake.py

    # 2) 确认后写回（自动先备份，单事务提交）
    D:/apps/anaconda3/python.exe scripts/fix_mojibake.py --apply

    # 只处理指定表
    D:/apps/anaconda3/python.exe scripts/fix_mojibake.py --apply --table writing_tasks

幂等性
------
判定函数 :func:`fix_mojibake` 只认「纯 latin-1 可编码 + 能解成合法 UTF-8 + 还原后
含中文」这三种条件同时成立的串。已经修好的正常中文不满足第一条
（中文无法用 latin-1 编码），因此不会被二次破坏，脚本可重复执行。
"""
from __future__ import annotations

import argparse
import re
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

# server/ 目录（本文件位于 server/scripts/ 下）
SERVER_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = SERVER_ROOT / "data" / "judicial_app.db"
BACKUP_DIR = SERVER_ROOT / "data" / "backups"

# 候选表/列：先全部扫描，只有确认命中才写回
TARGETS: List[Tuple[str, str]] = [
    ("writing_tasks", "current_content"),
    ("writing_tasks", "ai_draft"),
    ("documents", "content"),
    ("my_document_versions", "content"),
    ("my_document_versions", "content_check"),
    ("chat_messages", "content"),
    ("training_samples", "draft"),
    ("node_instances", "content"),
    ("task_references", "text_content"),
    ("user_memories", "content"),
    ("data_assets", "content"),
    ("chunks", "content"),
    ("ppt_documents", "source_content"),
]

_CJK = re.compile(r"[\u4e00-\u9fff]")

# 典型「UTF-8 被按 Latin-1 解开」的可见碎片，用于发现「部分乱码」的可疑行
_MOJIBAKE_MARKER = re.compile(r"[ÃÂåèéæä][\x80-\xbf-]|[ÐÑ][-¿]")


def fix_mojibake(s: Optional[str]) -> Optional[str]:
    """把被 Latin-1 误解码的 UTF-8 中文还原。

    Args:
        s: 待检测的文本；``None`` 或非 ``str`` 直接返回 ``None``。

    Returns:
        还原后的字符串；若判定不是此类乱码则返回 ``None``（调用方应跳过）。
    """
    if not isinstance(s, str) or not s:
        return None
    # 1) 必须是纯 latin-1 可编码的串；含中文/全角等字符时直接排除（已修好的行就此跳过）
    try:
        raw = s.encode("latin-1")
    except UnicodeEncodeError:
        return None
    # 2) 这段字节必须能解成合法 UTF-8
    try:
        out = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
    # 3) 还原后必须含中文，避免误伤纯英文/数字内容
    if not _CJK.search(out):
        return None
    return out


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r[1] == column for r in rows)


def backup(db_path: Path) -> Path:
    """备份数据库（连同 WAL/SHM，避免只拷主库丢掉未 checkpoint 的页）。"""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = BACKUP_DIR / f"mojibake_fix_{stamp}.db"
    shutil.copy2(db_path, dst)
    for suffix in ("-wal", "-shm"):
        src = db_path.with_name(db_path.name + suffix)
        if src.exists() and src.stat().st_size > 0:
            shutil.copy2(src, dst.with_name(dst.name + suffix))
    return dst


def scan(conn: sqlite3.Connection, table: str,
         column: str) -> Tuple[int, int, List[Tuple[int, str, str]], int]:
    """扫描一张表的一列。

    Returns:
        ``(总行数, 命中乱码行数, 样本[(rowid, 修复前, 修复后)], 可疑但未修复行数)``
        其中「可疑但未修复」指含有乱码碎片、但整串不满足还原条件（多为部分乱码），
        这类行本脚本修不了，需要人工确认。
    """
    rows = conn.execute(
        f"SELECT rowid, {column} FROM {table} WHERE {column} IS NOT NULL"
    ).fetchall()
    hits: List[Tuple[int, str, str]] = []
    suspicious = 0
    hit_count = 0
    for rowid, value in rows:
        fixed = fix_mojibake(value)
        if fixed is not None and fixed != value:
            hit_count += 1
            if len(hits) < 3:  # 只保留 3 条样本用于人工核对
                hits.append((rowid, value[:60], fixed[:60]))
            continue
        if isinstance(value, str) and _MOJIBAKE_MARKER.search(value):
            suspicious += 1
    return len(rows), hit_count, hits, suspicious


def apply_fix(conn: sqlite3.Connection, table: str, column: str) -> Tuple[int, int, int]:
    """写回修复，返回 (扫描行数, 命中行数, 修复行数)。整表在一个事务内完成。"""
    rows = conn.execute(
        f"SELECT rowid, {column} FROM {table} WHERE {column} IS NOT NULL"
    ).fetchall()
    scanned = len(rows)
    payload = []
    for rowid, value in rows:
        fixed = fix_mojibake(value)
        if fixed is not None and fixed != value:
            payload.append((fixed, rowid))
    conn.executemany(
        f"UPDATE {table} SET {column}=? WHERE rowid=?", payload
    )
    conn.commit()
    return scanned, len(payload), len(payload)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="修复 Latin-1 误解码导致的中文乱码历史数据")
    parser.add_argument("--apply", action="store_true",
                        help="真正写回数据库；不带此参数只扫描不修改")
    parser.add_argument("--table", action="append", default=None,
                        help="只处理指定表，可重复传入")
    parser.add_argument("--no-backup", action="store_true", help="写回前不备份（不建议）")
    parser.add_argument("--db", default=str(DB_PATH), help="数据库路径")
    args = parser.parse_args(argv)

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"[错误] 数据库不存在: {db_path}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(str(db_path))
    try:
        targets = [
            (t, c) for (t, c) in TARGETS
            if (args.table is None or t in args.table)
        ]

        print(f"数据库: {db_path}")
        print(f"模式  : {'写回(--apply)' if args.apply else '只读扫描(默认)'}\n")

        results = []
        for table, column in targets:
            if not _table_exists(conn, table):
                print(f"  {table}.{column:<18} 表不存在，跳过")
                continue
            if not _column_exists(conn, table, column):
                print(f"  {table}.{column:<18} 列不存在，跳过")
                continue
            if args.apply:
                scanned, hit, fixed = apply_fix(conn, table, column)
                results.append((table, column, scanned, hit, fixed, 0))
            else:
                scanned, hit, samples, suspicious = scan(conn, table, column)
                results.append((table, column, scanned, hit, hit, suspicious))
                for rowid, before, after in samples:
                    print(f"      样本 rowid={rowid}")
                    print(f"        修复前: {before!r}")
                    print(f"        修复后: {after!r}")

        print("\n" + "=" * 92)
        print(f"{'表.列':<44}{'扫描':>8}{'命中':>8}{'修复':>8}{'可疑未修':>10}")
        print("-" * 92)
        total_hit = 0
        total_susp = 0
        for table, column, scanned, hit, fixed, suspicious in results:
            print(f"{table + '.' + column:<44}{scanned:>8}{hit:>8}{fixed:>8}{suspicious:>10}")
            total_hit += hit
            total_susp += suspicious
        print("=" * 92)
        print(f"命中共计: {total_hit}   可疑但未修复: {total_susp}")
        if total_susp:
            print("注：「可疑但未修复」= 含乱码碎片但整串不满足还原条件（多为局部乱码），"
                  "本脚本不会改动，需人工确认。")

        if args.apply and total_hit > 0:
            print("\n已写回并提交。")
        elif args.apply:
            print("\n没有命中，未做修改。")
        else:
            print("\n只读扫描结束，未修改任何数据。确认无误后加 --apply 写回。")
        return 0
    finally:
        conn.close()


def run(argv: Optional[List[str]] = None) -> int:
    """入口：写回模式下先备份再执行。"""
    if "--apply" in (argv if argv is not None else sys.argv[1:]) and "--no-backup" not in (
            argv if argv is not None else sys.argv[1:]):
        dst = backup(Path(DB_PATH))
        print(f"已备份: {dst}\n")
    return main(argv)


if __name__ == "__main__":
    raise SystemExit(run())
