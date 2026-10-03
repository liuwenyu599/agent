# 生产备份、恢复演练与监控

本流程对应《交付评审报告-20261003》的运维缺口：数据库定期备份、向量索引备份、恢复演练、监控告警。

## 1. 首次上线必须执行

在仓库根目录：

```bash
chmod +x deploy/backup-production.sh deploy/restore-drill.sh deploy/install-backup-timer.sh

# 先做一份真实备份（数据库 + data/vector_index）
./deploy/backup-production.sh

# 恢复到隔离临时目标并校验；不会覆盖生产库
./deploy/restore-drill.sh

# 安装每天 02:30 的 systemd timer（Persistent=true，关机错过后会补跑）
sudo ./deploy/install-backup-timer.sh
```

默认保留 14 天，可通过 `BACKUP_RETENTION_DAYS` 覆盖。备份目录默认是 `${HOST_DATA_DIR}/backups`。

PostgreSQL 环境要求宿主机具备 `pg_dump / pg_restore / createdb / dropdb / psql`；SQLite 环境使用 Python 标准库 online backup API。

每份备份包含：

- `database.dump`（PostgreSQL）或 `database.sqlite3`（SQLite）
- `vector_index.tar.gz`
- `manifest.env`
- `SHA256SUMS`

恢复演练成功后会写 `${HOST_DATA_DIR}/backups/.last-restore-drill`。`postcheck-production.sh` 要求：

- systemd timer 已启用且 active；
- 36 小时内存在一份备份；
- 最新备份 SHA256 完整；
- 包含向量索引归档；
- 最近 30 天内完成过恢复演练。

因此不能只“配置备份但从未验证恢复”。

## 2. 日常检查

```bash
systemctl status judicial-ai-backup.timer
systemctl list-timers judicial-ai-backup.timer
journalctl -u judicial-ai-backup.service --since '7 days ago'

curl -fsS http://127.0.0.1:8000/health
curl -fsS http://127.0.0.1:8000/ready
curl -fsS http://127.0.0.1:8000/metrics | head
```

`/health` 只表示进程存活；`/ready` 额外检查数据库和 FAISS index/meta 文件是否一致。发布流量前应以 `/ready` 为准。

## 3. Prometheus

仓库提供：

- `deploy/prometheus.yml.example`
- `deploy/judicial-ai-alerts.yml`

最少告警项：

1. API 连续 2 分钟无法抓取：critical；
2. 5 分钟窗口 5xx 比例超过 5%：warning；
3. P95 请求延迟连续 10 分钟超过 10 秒：warning。

Prometheus 如果运行在容器中，需要把 `127.0.0.1:8000` 改为实际 API service/container 地址。

## 4. 恢复演练原则

`restore-drill.sh` 的 PostgreSQL 流程会创建临时数据库 `justice_restore_drill_*`，恢复并确认 public schema 有表后删除临时数据库；SQLite 会对备份执行 `PRAGMA integrity_check` 并确认存在 schema object。向量索引归档至少执行 tar 完整性检查和隔离解包。

演练不得直接对生产数据库执行 `pg_restore`。

## 5. 交付签字

执行：

```bash
./deploy/postcheck-production.sh
```

只有脚本最终输出 `POST-CHECK PASSED`，且客户端 2 页 / 10 页 PPT 端到端验收完成，才进入交付签字。代码仓库中存在备份脚本不等于目标机已经具备可恢复能力；目标机必须实际跑过备份和恢复演练。
