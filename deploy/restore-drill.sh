#!/usr/bin/env bash
set -euo pipefail

# Verify a backup by restoring into an isolated temporary target.
# Never writes into the production database or production vector_index directory.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/deploy/.env}"
read_env_value() {
  local key="$1" raw=""
  [[ -f "$ENV_FILE" ]] || return 0
  raw="$(grep -E "^${key}=" "$ENV_FILE" | tail -n 1 | cut -d= -f2- || true)"
  raw="${raw%$'\r'}"
  if [[ "$raw" == \"*\" && "$raw" == *\" ]]; then raw="${raw:1:${#raw}-2}"; fi
  if [[ "$raw" == \'*\' && "$raw" == *\' ]]; then raw="${raw:1:${#raw}-2}"; fi
  printf '%s' "$raw"
}
HOST_DATA_DIR="${HOST_DATA_DIR:-$(read_env_value HOST_DATA_DIR)}"
HOST_DATA_DIR="${HOST_DATA_DIR:-$ROOT_DIR/data}"
BACKUP_DIR="${BACKUP_DIR:-$(read_env_value BACKUP_DIR)}"
BACKUP_DIR="${BACKUP_DIR:-$HOST_DATA_DIR/backups}"
DATABASE_URL="${DATABASE_URL:-$(read_env_value DATABASE_URL)}"
DATABASE_URL="${DATABASE_URL:-sqlite:///$HOST_DATA_DIR/judicial_app.db}"
TARGET="${1:-}"

if [[ -z "$TARGET" ]]; then
  TARGET="$(find "$BACKUP_DIR" -mindepth 1 -maxdepth 1 -type d -name '20??????-??????' | sort | tail -n 1)"
fi
[[ -n "$TARGET" && -d "$TARGET" ]] || { echo "backup not found" >&2; exit 2; }

(
  cd "$TARGET"
  sha256sum -c SHA256SUMS
)

tmp_root="$(mktemp -d)"
cleanup() { rm -rf "$tmp_root"; }
trap cleanup EXIT

tar -tzf "$TARGET/vector_index.tar.gz" >/dev/null
mkdir -p "$tmp_root/vector"
tar -xzf "$TARGET/vector_index.tar.gz" -C "$tmp_root/vector"

normalize_pg_url() {
  printf '%s' "$1" | sed -E 's#^postgresql\+[^:]+://#postgresql://#'
}

if [[ -f "$TARGET/database.sqlite3" ]]; then
  python3 - "$TARGET/database.sqlite3" <<'PY'
import sqlite3, sys
conn = sqlite3.connect(sys.argv[1])
check = conn.execute("PRAGMA integrity_check").fetchone()[0]
objects = conn.execute("SELECT count(*) FROM sqlite_master").fetchone()[0]
conn.close()
if check != "ok":
    raise SystemExit(f"sqlite integrity_check failed: {check}")
if objects <= 0:
    raise SystemExit("sqlite restore drill found no schema objects")
print(f"sqlite_restore_ok objects={objects}")
PY
elif [[ -f "$TARGET/database.dump" ]]; then
  command -v pg_restore >/dev/null 2>&1 || { echo "pg_restore is required" >&2; exit 4; }
  command -v createdb >/dev/null 2>&1 || { echo "createdb is required" >&2; exit 4; }
  command -v dropdb >/dev/null 2>&1 || { echo "dropdb is required" >&2; exit 4; }
  command -v psql >/dev/null 2>&1 || { echo "psql is required" >&2; exit 4; }
  PG_URL="$(normalize_pg_url "$DATABASE_URL")"
  DRILL_DB="justice_restore_drill_$(date +%s)_$$"
  MAINT_URL="$(python3 - "$PG_URL" <<'PY'
import sys
from urllib.parse import urlsplit, urlunsplit
u = urlsplit(sys.argv[1])
print(urlunsplit((u.scheme, u.netloc, '/postgres', u.query, u.fragment)))
PY
)"
  DRILL_URL="$(python3 - "$PG_URL" "$DRILL_DB" <<'PY'
import sys
from urllib.parse import urlsplit, urlunsplit
u = urlsplit(sys.argv[1])
print(urlunsplit((u.scheme, u.netloc, '/' + sys.argv[2], u.query, u.fragment)))
PY
)"
  createdb --maintenance-db="$MAINT_URL" "$DRILL_DB"
  pg_cleanup() { dropdb --if-exists --maintenance-db="$MAINT_URL" "$DRILL_DB" >/dev/null 2>&1 || true; cleanup; }
  trap pg_cleanup EXIT
  pg_restore --no-owner --no-acl --dbname="$DRILL_URL" "$TARGET/database.dump"
  TABLES="$(psql "$DRILL_URL" -Atqc "select count(*) from pg_catalog.pg_tables where schemaname='public';")"
  [[ "${TABLES:-0}" -gt 0 ]] || { echo "postgres restore drill found no public tables" >&2; exit 5; }
  echo "postgres_restore_ok tables=$TABLES"
else
  echo "database backup payload missing" >&2
  exit 5
fi

echo "vector_archive_ok"
date -Iseconds > "$BACKUP_DIR/.last-restore-drill"
echo "restore_drill_ok=$TARGET"
