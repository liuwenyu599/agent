#!/usr/bin/env bash
set -euo pipefail

# Verify a backup by restoring into an isolated temporary target.
# Never writes into the production database or production vector_index directory.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# 与 backup-production.sh 保持一致：生产 .env 在 /opt/justice-office/deploy/，
# 不在代码目录 /opt/judicial_app/deploy/。详见 backup-production.sh 里的说明。
ENV_FILE="${ENV_FILE:-/opt/justice-office/deploy/.env}"
read_env_value() {
  local key="$1" raw=""
  [[ -f "$ENV_FILE" ]] || return 0
  raw="$(grep -E "^${key}=" "$ENV_FILE" | tail -n 1 | cut -d= -f2- || true)"
  raw="${raw%$'\r'}"
  if [[ "$raw" == \"*\" && "$raw" == *\" ]]; then raw="${raw:1:${#raw}-2}"; fi
  if [[ "$raw" == \'*\' && "$raw" == *\' ]]; then raw="${raw:1:${#raw}-2}"; fi
  printf '%s' "$raw"
}
# 演练必须针对真实备份；配置读不到就立刻失败，不要拿空目录走一遍"成功"流程。
if [[ ! -f "$ENV_FILE" ]]; then
  echo "生产 .env 不存在: $ENV_FILE" >&2
  echo "生产配置固定在 /opt/justice-office/deploy/.env；请确认磁盘已挂载，或用 ENV_FILE=... 指定。" >&2
  exit 2
fi
HOST_DATA_DIR="${HOST_DATA_DIR:-$(read_env_value HOST_DATA_DIR)}"; HOST_DATA_DIR="${HOST_DATA_DIR:-$ROOT_DIR/data}"
# 相对路径按 .env 所在目录归一化（与 backup-production.sh / docker compose 一致）。
# systemd 单元的 WorkingDirectory 是代码目录，不归一化会让 ../data 变成 /opt/data。
if [[ "$HOST_DATA_DIR" != /* ]]; then
  HOST_DATA_DIR="$(cd "$(dirname "$ENV_FILE")" && cd "$HOST_DATA_DIR" && pwd)"
fi
[[ -d "$HOST_DATA_DIR" ]] || { echo "HOST_DATA_DIR 不存在: $HOST_DATA_DIR" >&2; exit 2; }
BACKUP_DIR="${BACKUP_DIR:-$(read_env_value BACKUP_DIR)}"; BACKUP_DIR="${BACKUP_DIR:-$HOST_DATA_DIR/backups}"
DATABASE_URL="${DATABASE_URL:-$(read_env_value DATABASE_URL)}"; DATABASE_URL="${DATABASE_URL:-sqlite:///$HOST_DATA_DIR/judicial_app.db}"
POSTGRES_CONTAINER="${POSTGRES_CONTAINER:-$(read_env_value POSTGRES_CONTAINER)}"; POSTGRES_CONTAINER="${POSTGRES_CONTAINER:-justice-db}"
POSTGRES_USER="${POSTGRES_USER:-$(read_env_value POSTGRES_USER)}"; POSTGRES_USER="${POSTGRES_USER:-justice}"
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

normalize_pg_url() { printf '%s' "$1" | sed -E 's#^postgresql\+[^:]+://#postgresql://#'; }
container_running() {
  command -v docker >/dev/null 2>&1 &&
    [[ "$(docker inspect -f '{{.State.Running}}' "$POSTGRES_CONTAINER" 2>/dev/null || true)" == "true" ]]
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
elif [[ -f "$TARGET/database.dump" ]] && container_running; then
  DRILL_DB="justice_restore_drill_$(date +%s)_$$"
  docker exec "$POSTGRES_CONTAINER" createdb -U "$POSTGRES_USER" "$DRILL_DB"
  docker_pg_cleanup() {
    docker exec "$POSTGRES_CONTAINER" dropdb --if-exists -U "$POSTGRES_USER" "$DRILL_DB" >/dev/null 2>&1 || true
    cleanup
  }
  trap docker_pg_cleanup EXIT
  cat "$TARGET/database.dump" | docker exec -i "$POSTGRES_CONTAINER" pg_restore \
    --no-owner --no-acl -U "$POSTGRES_USER" -d "$DRILL_DB"
  TABLES="$(docker exec "$POSTGRES_CONTAINER" psql -U "$POSTGRES_USER" -d "$DRILL_DB" -Atqc \
    "select count(*) from pg_catalog.pg_tables where schemaname='public';")"
  [[ "${TABLES:-0}" -gt 0 ]] || { echo "postgres restore drill found no public tables" >&2; exit 5; }
  echo "postgres_restore_ok tables=$TABLES source=container:$POSTGRES_CONTAINER"
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
u = urlsplit(sys.argv[1]); print(urlunsplit((u.scheme, u.netloc, '/postgres', u.query, u.fragment)))
PY
)"
  DRILL_URL="$(python3 - "$PG_URL" "$DRILL_DB" <<'PY'
import sys
from urllib.parse import urlsplit, urlunsplit
u = urlsplit(sys.argv[1]); print(urlunsplit((u.scheme, u.netloc, '/' + sys.argv[2], u.query, u.fragment)))
PY
)"
  createdb --maintenance-db="$MAINT_URL" "$DRILL_DB"
  pg_cleanup() { dropdb --if-exists --maintenance-db="$MAINT_URL" "$DRILL_DB" >/dev/null 2>&1 || true; cleanup; }
  trap pg_cleanup EXIT
  pg_restore --no-owner --no-acl --dbname="$DRILL_URL" "$TARGET/database.dump"
  TABLES="$(psql "$DRILL_URL" -Atqc "select count(*) from pg_catalog.pg_tables where schemaname='public';")"
  [[ "${TABLES:-0}" -gt 0 ]] || { echo "postgres restore drill found no public tables" >&2; exit 5; }
  echo "postgres_restore_ok tables=$TABLES source=url"
else
  echo "database backup payload missing" >&2
  exit 5
fi

echo "vector_archive_ok"
date -Iseconds > "$BACKUP_DIR/.last-restore-drill"
echo "restore_drill_ok=$TARGET"
