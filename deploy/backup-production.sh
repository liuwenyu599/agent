#!/usr/bin/env bash
set -euo pipefail

# Production backup for database + FAISS vector index.
# PostgreSQL production deployments prefer the running justice-db container so host DNS/client
# packages are not required. Standalone PostgreSQL URLs and SQLite remain supported.

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

HOST_DATA_DIR="${HOST_DATA_DIR:-$(read_env_value HOST_DATA_DIR)}"; HOST_DATA_DIR="${HOST_DATA_DIR:-$ROOT_DIR/data}"
BACKUP_DIR="${BACKUP_DIR:-$(read_env_value BACKUP_DIR)}"; BACKUP_DIR="${BACKUP_DIR:-$HOST_DATA_DIR/backups}"
BACKUP_RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-$(read_env_value BACKUP_RETENTION_DAYS)}"; BACKUP_RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"
VECTOR_INDEX_DIR="${VECTOR_INDEX_DIR:-$(read_env_value VECTOR_INDEX_DIR)}"; VECTOR_INDEX_DIR="${VECTOR_INDEX_DIR:-$HOST_DATA_DIR/vector_index}"
DATABASE_URL="${DATABASE_URL:-$(read_env_value DATABASE_URL)}"; DATABASE_URL="${DATABASE_URL:-sqlite:///$HOST_DATA_DIR/judicial_app.db}"
POSTGRES_CONTAINER="${POSTGRES_CONTAINER:-$(read_env_value POSTGRES_CONTAINER)}"; POSTGRES_CONTAINER="${POSTGRES_CONTAINER:-justice-db}"
POSTGRES_USER="${POSTGRES_USER:-$(read_env_value POSTGRES_USER)}"; POSTGRES_USER="${POSTGRES_USER:-justice}"
POSTGRES_DB="${POSTGRES_DB:-$(read_env_value POSTGRES_DB)}"; POSTGRES_DB="${POSTGRES_DB:-justice}"

mkdir -p "$BACKUP_DIR"
exec 9>"$BACKUP_DIR/.backup.lock"
if command -v flock >/dev/null 2>&1; then
  flock -n 9 || { echo "backup already running" >&2; exit 3; }
fi

STAMP="$(date '+%Y%m%d-%H%M%S')"
TARGET="$BACKUP_DIR/$STAMP"
mkdir -p "$TARGET"
cleanup_on_error() { rm -rf "$TARGET"; }
trap cleanup_on_error ERR

normalize_pg_url() { printf '%s' "$1" | sed -E 's#^postgresql\+[^:]+://#postgresql://#'; }
container_running() {
  command -v docker >/dev/null 2>&1 &&
    [[ "$(docker inspect -f '{{.State.Running}}' "$POSTGRES_CONTAINER" 2>/dev/null || true)" == "true" ]]
}

DB_KIND=""
DB_SOURCE=""
if container_running; then
  DB_KIND="postgresql"
  DB_SOURCE="container:$POSTGRES_CONTAINER"
  docker exec "$POSTGRES_CONTAINER" pg_dump \
    --format=custom --no-owner --no-acl -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    > "$TARGET/database.dump"
elif [[ "$DATABASE_URL" == postgresql://* || "$DATABASE_URL" == postgres://* || "$DATABASE_URL" == postgresql+*://* ]]; then
  DB_KIND="postgresql"
  DB_SOURCE="url"
  command -v pg_dump >/dev/null 2>&1 || { echo "pg_dump is required for PostgreSQL backup" >&2; exit 4; }
  PG_URL="$(normalize_pg_url "$DATABASE_URL")"
  pg_dump --format=custom --no-owner --no-acl --file "$TARGET/database.dump" "$PG_URL"
elif [[ "$DATABASE_URL" == sqlite:///* ]]; then
  DB_KIND="sqlite"
  DB_SOURCE="file"
  command -v python3 >/dev/null 2>&1 || { echo "python3 is required for SQLite online backup" >&2; exit 4; }
  SQLITE_PATH="${DATABASE_URL#sqlite:///}"
  python3 - "$SQLITE_PATH" "$TARGET/database.sqlite3" <<'PY'
import sqlite3, sys
src, dst = sys.argv[1], sys.argv[2]
source = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
target = sqlite3.connect(dst)
with target:
    source.backup(target)
check = target.execute("PRAGMA integrity_check").fetchone()[0]
source.close(); target.close()
if check != "ok":
    raise SystemExit(f"sqlite integrity_check failed: {check}")
PY
else
  echo "unsupported DATABASE_URL scheme" >&2
  exit 4
fi

if [[ -d "$VECTOR_INDEX_DIR" ]]; then
  tar -C "$(dirname "$VECTOR_INDEX_DIR")" -czf "$TARGET/vector_index.tar.gz" "$(basename "$VECTOR_INDEX_DIR")"
else
  tar -czf "$TARGET/vector_index.tar.gz" --files-from /dev/null
fi

cat > "$TARGET/manifest.env" <<EOF
created_at=$(date -Iseconds)
db_kind=$DB_KIND
db_source=$DB_SOURCE
retention_days=$BACKUP_RETENTION_DAYS
vector_index_dir=$VECTOR_INDEX_DIR
EOF
(
  cd "$TARGET"
  sha256sum database.* vector_index.tar.gz manifest.env > SHA256SUMS
)

RETENTION_MINUTES=$((BACKUP_RETENTION_DAYS * 24 * 60))
find "$BACKUP_DIR" -mindepth 1 -maxdepth 1 -type d \
  -name '20??????-??????' -mmin "+$RETENTION_MINUTES" -print -exec rm -rf -- {} +

trap - ERR
printf 'backup_ok=%s\n' "$TARGET"
