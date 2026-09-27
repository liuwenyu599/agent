"""一次性修补脚本：给「要素被清空」的科室/个人模板补回填写要素。

背景
----
桌面端「按本科室写作习惯调整」在早期版本里只把 6 个字段（名称、正文、分类等）
提交给后端，``params_schema`` / ``structure`` / ``system_prompt`` / ``writing_guide``
等字段全部丢失；后端 ``save_department_template`` 又用 ``or []`` / ``or ""`` 兜底，
于是落库的科室模板没有任何填写要素，详情页显示「该模板无需填写要素」，模板不可用。

根因已在两处修掉：
- 桌面端 ``TemplatesViewModel`` 改为透传后端草案的完整字段；
- 后端 ``save_department_template`` 增加从源模板继承要素的兜底。

本脚本只修补**历史脏数据**：把 ``is_builtin=0`` 且要素为空、且能通过名称
（去掉「（办公室）」这类括号后缀）匹配到同名内置模板的记录，从该内置模板继承
要素与写作配置。**正文 ``content_template`` 一律不动**（那是科室化改写的结果）。

用法
----
    # 1) 先扫描（默认，只读，不改库），确认将要改什么
    D:/apps/anaconda3/python.exe scripts/backfill_dept_template_fields.py

    # 2) 确认后写回（自动先备份到 data/backups_manual_<时间戳>.db，单事务提交）
    D:/apps/anaconda3/python.exe scripts/backfill_dept_template_fields.py --apply

    # 指定数据库 / 只处理某条模板
    D:/apps/anaconda3/python.exe scripts/backfill_dept_template_fields.py --db path/to.db
    D:/apps/anaconda3/python.exe scripts/backfill_dept_template_fields.py --id 23d23a09-...

幂等性
------
只有 ``params_schema`` 解析后为空的记录才会被选中；修补后该列非空，再次执行
不会命中，也不会覆盖已有数据。脚本可重复执行。
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# server/ 目录（本文件位于 server/scripts/ 下）
SERVER_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = SERVER_ROOT / "data" / "judicial_app.db"
BACKUP_DIR = SERVER_ROOT / "data"

TABLE = "writing_templates"

# 需要从源（内置）模板继承的列：正文 content_template 不在其中，保持不动
INHERIT_COLUMNS: Tuple[str, ...] = (
    "params_schema",
    "structure",
    "system_prompt",
    "writing_guide",
    "writing_style",
    "word_count",
    "need_red_header",
    "need_signature",
    "need_date",
    "need_doc_number",
    "template_kind",
    "tags",
    "base_type",
)

# 名称里的括号科室后缀，如「请示（办公室）」「通知(办公室)」
_SUFFIX_RE = re.compile(r"[（(][^（(）)]*[）)]\s*$")


def _load_json(raw: Any) -> Any:
    """把数据库里的 JSON 文本解析成 Python 对象；解析失败返回 ``None``。"""
    if raw is None:
        return None
    if isinstance(raw, (list, dict)):
        return raw
    text = str(raw).strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return None


def _is_empty_schema(raw: Any) -> bool:
    """判定要素列是否为空（``None`` / ``''`` / ``'[]'`` / ``[]`` / 解析失败）。"""
    if raw is None:
        return True
    if isinstance(raw, (list, dict)):
        return len(raw) == 0
    text = str(raw).strip()
    if not text:
        return True
    parsed = _load_json(text)
    if parsed is None:  # 非法 JSON 也视为需要修补
        return True
    return len(parsed) == 0


def _dump_json(value: Any) -> str:
    """统一按 UTF-8 JSON 文本落库（与 SQLAlchemy JSON 列保持一致）。"""
    if value is None:
        return "[]"
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def base_name_of(name: str) -> str:
    """去掉名称尾部的括号科室后缀，得到可能的源模板名。

    Examples:
        >>> base_name_of("请示（办公室）")
        '请示'
        >>> base_name_of("请示")
        '请示'
    """
    text = (name or "").strip()
    stripped = _SUFFIX_RE.sub("", text).strip()
    return stripped or text


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r[1] == column for r in rows)


def _fetch_builtin_index(conn: sqlite3.Connection) -> Dict[str, List[sqlite3.Row]]:
    """按名称索引内置模板；同名多条时保留全部，优先取要素非空的那条。"""
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        f"SELECT * FROM {TABLE} WHERE is_builtin=1"
    ).fetchall()
    index: Dict[str, List[sqlite3.Row]] = {}
    for row in rows:
        index.setdefault(str(row["name"]).strip(), []).append(row)
    return index


def _pick_source(candidates: List[sqlite3.Row]) -> Optional[sqlite3.Row]:
    """在同名内置模板里挑一条要素最完整的作为继承源。"""
    if not candidates:
        return None
    with_schema = [r for r in candidates if not _is_empty_schema(r["params_schema"])]
    pool = with_schema or candidates
    return pool[0]


def find_targets(conn: sqlite3.Connection, only_id: Optional[str] = None
                 ) -> Tuple[List[sqlite3.Row], Dict[str, List[sqlite3.Row]]]:
    """找出所有需要修补的记录，返回 ``(待修补行, 内置模板索引)``。"""
    conn.row_factory = sqlite3.Row
    if only_id:
        rows = conn.execute(
            f"SELECT * FROM {TABLE} WHERE is_builtin=0 AND id=?", (only_id,)
        ).fetchall()
    else:
        rows = conn.execute(f"SELECT * FROM {TABLE} WHERE is_builtin=0").fetchall()
    index = _fetch_builtin_index(conn)
    targets = [r for r in rows if _is_empty_schema(r["params_schema"])]
    return targets, index


def plan_changes(targets: List[sqlite3.Row],
                 index: Dict[str, List[sqlite3.Row]]
                 ) -> Tuple[List[Dict[str, Any]], int]:
    """生成修补计划。

    Returns:
        ``(变更列表, 未匹配到源模板的记录数)``；变更项含 ``id``/``name``/
        ``source_name``/``values``（列名 → 新值）与 ``before``/``after`` 要素条数。
    """
    changes: List[Dict[str, Any]] = []
    unmatched = 0
    for row in targets:
        name = str(row["name"] or "").strip()
        src = _pick_source(index.get(base_name_of(name), []))
        if src is None:
            src = _pick_source(index.get(name, []))
        if src is None:
            unmatched += 1
            continue
        values: Dict[str, Any] = {}
        for col in INHERIT_COLUMNS:
            values[col] = src[col]
        before = len(_load_json(row["params_schema"]) or [])
        after = len(_load_json(src["params_schema"]) or [])
        changes.append({
            "id": row["id"],
            "name": name,
            "source_name": str(src["name"]),
            "values": values,
            "before": before,
            "after": after,
        })
    return changes, unmatched


def apply_changes(conn: sqlite3.Connection, changes: List[Dict[str, Any]]) -> int:
    """按计划写回，整批在一个事务内提交。

    Returns:
        实际更新的行数。
    """
    updated = 0
    for change in changes:
        values = change["values"]
        assignments = []
        params: List[Any] = []
        for col in INHERIT_COLUMNS:
            value = values[col]
            if col in ("params_schema", "structure", "tags"):
                assignments.append(f"{col}=?")
                params.append(_dump_json(_load_json(value) or []))
            elif col == "word_count":
                assignments.append(f"{col}=?")
                try:
                    params.append(int(value or 1000))
                except (TypeError, ValueError):
                    params.append(1000)
            elif col.startswith("need_"):
                assignments.append(f"{col}=?")
                params.append(1 if int(value or 0) else 0)
            else:
                assignments.append(f"{col}=?")
                params.append("" if value is None else str(value))
        assignments.append("updated_at=?")
        params.append(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        params.append(change["id"])
        conn.execute(
            f"UPDATE {TABLE} SET {', '.join(assignments)} WHERE id=?", params
        )
        updated += 1
    conn.commit()
    return updated


def backup(db_path: Path) -> Path:
    """备份数据库（连同 WAL/SHM，避免只拷主库丢掉未 checkpoint 的页）。"""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = BACKUP_DIR / f"backups_manual_{stamp}.db"
    shutil.copy2(db_path, dst)
    for suffix in ("-wal", "-shm"):
        src = db_path.with_name(db_path.name + suffix)
        if src.exists() and src.stat().st_size > 0:
            shutil.copy2(src, dst.with_name(dst.name + suffix))
    return dst


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="给要素被清空的科室/个人模板补回填写要素（默认只读扫描）")
    parser.add_argument("--apply", action="store_true",
                        help="真正写回数据库；不带此参数只扫描不修改")
    parser.add_argument("--db", default=str(DB_PATH), help="数据库路径")
    parser.add_argument("--id", default=None, help="只处理指定模板 id")
    parser.add_argument("--no-backup", action="store_true", help="写回前不备份（不建议）")
    args = parser.parse_args(argv)

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"[错误] 数据库不存在: {db_path}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(str(db_path))
    try:
        if not _table_exists(conn, TABLE):
            print(f"[错误] 表不存在: {TABLE}", file=sys.stderr)
            return 1
        missing = [c for c in INHERIT_COLUMNS if not _column_exists(conn, TABLE, c)]
        if missing:
            print(f"[错误] 缺少列: {', '.join(missing)}", file=sys.stderr)
            return 1

        targets, index = find_targets(conn, args.id)
        changes, unmatched = plan_changes(targets, index)

        print(f"数据库: {db_path}")
        print(f"模式  : {'写回(--apply)' if args.apply else '只读扫描(默认)'}")
        print(f"候选  : 非内置且要素为空的记录 {len(targets)} 条"
              f"（内置模板索引 {len(index)} 个名称）\n")

        if not targets:
            print("没有需要修补的记录（要素均已非空），未做修改。")
            return 0

        print("待修补记录:")
        for row in targets:
            print(f"  - {row['id']}  name={row['name']!r}  "
                  f"params_schema={str(row['params_schema'])[:40]!r}")

        print("\n继承计划:")
        for change in changes:
            print(f"  - {change['id']}  {change['name']!r} "
                  f"← 内置模板 {change['source_name']!r}")
            print(f"      要素条数: {change['before']} → {change['after']}")
            for col in INHERIT_COLUMNS:
                raw = change["values"][col]
                text = str(raw)
                print(f"      {col:<16} = {text[:70]}")
        if unmatched:
            print(f"\n未匹配到同名内置模板、保持不动的记录: {unmatched} 条")

        if not args.apply:
            print("\n只读扫描结束，未修改任何数据。确认无误后加 --apply 写回。")
            return 0

        updated = apply_changes(conn, changes)
        print(f"\n已写回并提交，更新 {updated} 条记录（正文 content_template 未改动）。")
        return 0
    finally:
        conn.close()


def run(argv: Optional[List[str]] = None) -> int:
    """入口：写回模式下先备份再执行。"""
    argv = argv if argv is not None else sys.argv[1:]
    if "--apply" in argv and "--no-backup" not in argv:
        dst = backup(Path(DB_PATH))
        print(f"已备份: {dst}")
    return main(argv)


if __name__ == "__main__":
    raise SystemExit(run())
