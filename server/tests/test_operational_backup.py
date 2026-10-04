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

    # 脚本现在要求 .env 真实存在（缺失即 exit 2，不再静默退回代码目录），
    # 所以这里造一个空的临时 .env 并用 ENV_FILE 指向它。
    env_file = tmp_path / "deploy.env"
    env_file.write_text("", encoding="utf-8")

    env = os.environ.copy()
    env.update({
        "ENV_FILE": str(env_file),
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


def test_ops_scripts_default_to_production_env_location():
    """运维脚本的默认 .env 必须指向生产配置目录，不能是代码目录。

    回归 2026-10-04 发现的真实缺陷：backup-production.sh 与 restore-drill.sh 曾把
    ENV_FILE 默认成 ``$ROOT_DIR/deploy/.env``，展开后是 ``/opt/judicial_app/deploy/.env``
    —— 代码包走 tar 覆盖、不含 .env，于是该文件永远不存在。read_env_value 遇缺文件
    会静默返回空串，HOST_DATA_DIR 一路退到 ``$ROOT_DIR/data``（代码目录），备份脚本
    就会对着一个刚创建的空目录"成功"产出不含业务数据的备份包 —— 比直接报错危险得多。
    """
    production_env = "/opt/justice-office/deploy/.env"
    for script in (BACKUP, RESTORE):
        text = script.read_text(encoding="utf-8")
        assert 'ENV_FILE="${ENV_FILE:-$ROOT_DIR/deploy/.env}"' not in text, (
            f"{script.name} 的默认 ENV_FILE 又指回代码目录了"
        )
        assert f'ENV_FILE="${{ENV_FILE:-{production_env}}}"' in text, (
            f"{script.name} 的默认 ENV_FILE 应为 {production_env}"
        )
        # 找不到 .env 必须显式失败，不能静默退回代码目录
        assert "if [[ ! -f \"$ENV_FILE\" ]]; then" in text, (
            f"{script.name} 缺少 .env 存在性校验"
        )


def test_ops_scripts_normalize_relative_host_data_dir():
    """HOST_DATA_DIR 是相对路径时必须按 .env 所在目录归一化。

    生产 .env 写的是 ``HOST_DATA_DIR=../data``（本意 /opt/justice-office/data），而
    install-backup-timer.sh 生成的 systemd 单元把 WorkingDirectory 设成代码目录
    /opt/judicial_app。不归一化的话 ``../data`` 会解析成 /opt/data —— 又一个错路径。
    """
    for script in (BACKUP, RESTORE):
        text = script.read_text(encoding="utf-8")
        assert 'if [[ "$HOST_DATA_DIR" != /* ]]; then' in text, (
            f"{script.name} 未对相对 HOST_DATA_DIR 做归一化"
        )
        assert 'cd "$(dirname "$ENV_FILE")" && cd "$HOST_DATA_DIR" && pwd' in text, (
            f"{script.name} 的归一化基准应为 .env 所在目录"
        )
        # 归一化后必须校验目录真实存在，避免误建空目录
        assert '[[ -d "$HOST_DATA_DIR" ]]' in text, (
            f"{script.name} 未校验归一化后的 HOST_DATA_DIR 是否存在"
        )
