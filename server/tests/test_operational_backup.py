import os
import sqlite3
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
BACKUP = REPO_ROOT / "deploy" / "backup-production.sh"
RESTORE = REPO_ROOT / "deploy" / "restore-drill.sh"


def test_sqlite_backup_includes_vector_index_and_restores(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
    db_path = data / "judicial_app.db"
    conn = sqlite3.connect(db_path)
    conn.execute("create table users(id integer primary key, username text)")
    conn.execute("insert into users(username) values ('admin')")
    conn.commit()
    conn.close()

    vectors = data / "vector_index"
    vectors.mkdir()
    (vectors / "index.faiss").write_bytes(b"fake-index-for-backup-contract")
    (vectors / "metadata.pkl").write_bytes(b"fake-meta-for-backup-contract")

    env = os.environ.copy()
    env.update({
        "HOST_DATA_DIR": str(data),
        "DATABASE_URL": f"sqlite:///{db_path}",
        "BACKUP_RETENTION_DAYS": "14",
    })
    backup = subprocess.run(
        ["bash", str(BACKUP)], env=env, text=True, capture_output=True, check=True
    )
    assert "backup_ok=" in backup.stdout

    backup_dirs = sorted(p for p in (data / "backups").iterdir() if p.is_dir())
    assert len(backup_dirs) == 1
    latest = backup_dirs[0]
    assert (latest / "database.sqlite3").is_file()
    assert (latest / "vector_index.tar.gz").is_file()
    assert (latest / "SHA256SUMS").is_file()

    restored = subprocess.run(
        ["bash", str(RESTORE), str(latest)],
        env=env, text=True, capture_output=True, check=True,
    )
    assert "sqlite_restore_ok" in restored.stdout
    assert "vector_archive_ok" in restored.stdout
    assert "restore_drill_ok=" in restored.stdout
    assert (data / "backups" / ".last-restore-drill").is_file()


def test_backup_scripts_never_source_env_text():
    # A privileged timer must not execute arbitrary .env syntax/content.
    assert "source \"$ENV_FILE\"" not in BACKUP.read_text(encoding="utf-8")
    assert "source \"$ENV_FILE\"" not in RESTORE.read_text(encoding="utf-8")
