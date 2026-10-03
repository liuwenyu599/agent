#!/usr/bin/env bash
set -euo pipefail

# Install a daily systemd timer for backup-production.sh.
# Usage: sudo ./deploy/install-backup-timer.sh

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
  echo "run as root (sudo)" >&2
  exit 2
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_SCRIPT="$ROOT_DIR/deploy/backup-production.sh"
[[ -f "$BACKUP_SCRIPT" ]] || { echo "backup script missing: $BACKUP_SCRIPT" >&2; exit 2; }
chmod +x "$BACKUP_SCRIPT"

cat > /etc/systemd/system/judicial-ai-backup.service <<EOF
[Unit]
Description=Judicial AI database and vector index backup
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
WorkingDirectory=$ROOT_DIR
Environment=ENV_FILE=$ROOT_DIR/deploy/.env
ExecStart=$BACKUP_SCRIPT
Nice=10
IOSchedulingClass=best-effort
IOSchedulingPriority=7
EOF

cat > /etc/systemd/system/judicial-ai-backup.timer <<'EOF'
[Unit]
Description=Run Judicial AI backup daily

[Timer]
OnCalendar=*-*-* 02:30:00
Persistent=true
RandomizedDelaySec=900
Unit=judicial-ai-backup.service

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable --now judicial-ai-backup.timer
systemctl list-timers judicial-ai-backup.timer --no-pager

echo "installed: judicial-ai-backup.timer"
