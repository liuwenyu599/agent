#!/usr/bin/env bash
set -euo pipefail

fail() { echo "[FAIL] $*" >&2; exit 1; }
ok() { echo "[ OK ] $*"; }
warn() { echo "[WARN] $*" >&2; }

curl -fsS --max-time 10 http://127.0.0.1:8000/health >/tmp/justice-health.json ||
  fail "API /health 失败"
cat /tmp/justice-health.json
ok "API health"

curl -fsS --max-time 10 http://127.0.0.1:8000/ready >/tmp/justice-ready.json ||
  fail "API /ready 失败（数据库或向量索引状态异常）"
cat /tmp/justice-ready.json
ok "API readiness"

curl -fsS --max-time 10 http://127.0.0.1:8000/metrics >/tmp/justice-metrics.txt ||
  fail "API /metrics 失败"
grep -q 'judicial_ai_http_requests_total' /tmp/justice-metrics.txt ||
  fail "Prometheus 指标缺少 judicial_ai_http_requests_total"
ok "Prometheus metrics"

# ---------- 备份/恢复交付闸门 ----------
# 从 API 容器 /data 挂载反查宿主机真实数据目录，避免依赖 shell source .env。
host_data_dir="$(docker inspect justice-api --format '{{range .Mounts}}{{if eq .Destination "/data/justice"}}{{.Source}}{{end}}{{end}}' 2>/dev/null || true)"
[ -n "$host_data_dir" ] || fail "无法确定 justice-api 的 /data 宿主机挂载目录"
backup_dir="$host_data_dir/backups"
[ -d "$backup_dir" ] || fail "备份目录不存在: $backup_dir"

systemctl is-enabled judicial-ai-backup.timer >/dev/null 2>&1 ||
  fail "judicial-ai-backup.timer 未启用"
systemctl is-active judicial-ai-backup.timer >/dev/null 2>&1 ||
  fail "judicial-ai-backup.timer 未运行"
ok "每日备份 timer 已启用"

latest_backup="$(find "$backup_dir" -mindepth 1 -maxdepth 1 -type d -name '20??????-??????' -mmin -2160 | sort | tail -n 1)"
[ -n "$latest_backup" ] || fail "36 小时内没有数据库+向量索引备份"
(
  cd "$latest_backup"
  sha256sum -c SHA256SUMS >/dev/null
) || fail "最新备份 SHA256 校验失败: $latest_backup"
[ -f "$latest_backup/vector_index.tar.gz" ] || fail "最新备份缺少 vector_index.tar.gz"
ok "最新备份完整: $latest_backup"

restore_marker="$backup_dir/.last-restore-drill"
[ -f "$restore_marker" ] || fail "尚未完成真实恢复演练（缺少 .last-restore-drill）"
find "$restore_marker" -mmin -43200 -print -quit | grep -q . ||
  fail "最近一次恢复演练已超过 30 天，请重新执行 deploy/restore-drill.sh"
ok "恢复演练记录有效: $(cat "$restore_marker")"

# ---------- 模型池：以 API 容器实际生效环境为准逐节点探活 ----------
probe_pool() {
  local pool_key="$1" single_key="$2" label="$3" values url
  values="$(docker exec justice-api printenv "$pool_key" 2>/dev/null || true)"
  if [ -z "$values" ]; then
    values="$(docker exec justice-api printenv "$single_key" 2>/dev/null || true)"
  fi
  [ -n "$values" ] || fail "$label 未配置（$pool_key / $single_key 均为空）"

  local count=0
  IFS=',' read -ra urls <<< "$values"
  for url in "${urls[@]}"; do
    url="$(echo "$url" | xargs)"
    [ -n "$url" ] || continue
    count=$((count + 1))
    curl -fsS --max-time 10 "${url%/}/models" >/dev/null ||
      fail "$label endpoint 不可用: $url"
    echo "[ OK ] $label endpoint $url"
  done
  [ "$count" -gt 0 ] || fail "$label endpoint 池为空"
  ok "$label endpoint_count=$count"
}

vision_url="$(docker exec justice-api printenv VISION_MODEL_URL 2>/dev/null || true)"
if [ -n "$vision_url" ]; then
  curl -fsS --max-time 10 "${vision_url%/}/models" >/dev/null ||
    fail "视觉模型不可用: $vision_url"
  ok "视觉模型 $vision_url"
fi
probe_pool MODEL_SERVICE_URLS MODEL_SERVICE_URL "主文本模型池"
probe_pool PPT_MODEL_URLS PPT_MODEL_URL "PPT 模型池"

code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 10 http://127.0.0.1:7861/ || true)"
[ -n "$code" ] && [ "$code" != "000" ] && [ "${code:0:1}" != "5" ] ||
  fail "PPTAgent 不可用，HTTP=$code"
ok "PPTAgent"

docker exec justice-api python3 -c '
from pathlib import Path
from app.core.config import settings
p = settings.PPT_AGENT_WORKSPACE_DIR
assert p == "/data/pptagent", f"实际: {p!r}"
assert Path(p).is_dir(), f"{p} 不存在"
print("OK")
' || fail "API 容器 PPTAgent workspace 配置错误"
ok "API workspace"

font_count="$(docker exec justice-api sh -c 'fc-list :lang=zh | wc -l' | tr -d '[:space:]')"
[ "${font_count:-0}" -gt 0 ] || fail "API 容器没有中文字体"
ok "中文字体 count=$font_count"

users="$(docker exec justice-db psql -U justice -d justice -Atc 'SELECT count(*) FROM users;' | tr -d '[:space:]')"
[ "${users:-0}" -gt 0 ] || fail "数据库 users 表为空"
ok "数据库 users=$users"

image="$(docker inspect justice-api --format '{{.Config.Image}}')"
echo "API_IMAGE=$image"

# ---------- sandbox / host 镜像补丁二次确认 ----------
if ! docker image inspect deeppresenter-sandbox:latest >/dev/null 2>&1; then
  warn "sandbox 镜像不存在；如有异常请从 /opt/justice-office/data/delivery-images/sandbox.tar 恢复"
elif ! docker run --rm --entrypoint sh deeppresenter-sandbox:latest -c '
  set -eu
  capture=/usr/src/app/dist/utils/capture.js
  schemas=/usr/src/app/dist/tools/schemas.js
  [ -n "$capture" ] && [ "$(grep -o "offline-patch" "$capture" | wc -l | tr -d " ")" = "2" ]
  [ -n "$schemas" ] && grep -q "rewrite: z.union" "$schemas"
  [ ! -L /usr/local/bin/mmdc ] && [ "$(head -n 1 /usr/local/bin/mmdc)" = "#!/bin/bash" ]
  [ "$(fc-list :lang=zh | wc -l | tr -d " ")" -ge 100 ]
'; then
  warn "sandbox 镜像补丁不完整；请从 /opt/justice-office/data/delivery-images/sandbox.tar 恢复"
else
  ok "sandbox 镜像补丁完整"
fi

if ! docker image inspect deeppresenter-host:latest >/dev/null 2>&1; then
  warn "host 镜像不存在；如有异常请从 /opt/justice-office/data/delivery-images/host.tar 恢复"
elif ! docker run --rm --entrypoint sh deeppresenter-host:latest -c '
  set -eu
  grep -q "禁止 apt install" /usr/src/pptagent/deeppresenter/roles/Research.yaml
  which soffice >/dev/null
  which unoconv >/dev/null
  test -f /root/.cache/huggingface/hub/models--julien-c--fasttext-language-id/snapshots/master/lid.176.bin
'; then
  warn "host 镜像补丁不完整；请从 /opt/justice-office/data/delivery-images/host.tar 恢复"
else
  ok "host 镜像补丁完整"
fi

# ---------- 8001 的 3B 容器必须停用 ----------
if docker ps --format '{{.Names}}' | grep -qx justice-qwen; then
  fail "8001 的 3B 容器仍在运行，请按文档停用"
fi
if ss -tlnp 2>/dev/null | grep -q ':8001 '; then
  fail "端口 8001 仍被占用"
fi
ok "8001 旧 3B 服务已停用"

# ---------- API 容器到 PPTAgent 真实连通 ----------
docker exec justice-api sh -c '
  code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 http://10.128.85.133:7861/ || true)
  [ -n "$code" ] && [ "$code" != "000" ] && [ "${code#5}" = "$code" ]
' || fail "API 容器连不到 PPTAgent"
ok "API 容器到 PPTAgent 连通"

echo
echo "POST-CHECK PASSED"
echo "已验证 readiness、Prometheus、36h 内备份、30 天内恢复演练记录。"
echo "若启用了 MODEL_SERVICE_URLS/PPT_MODEL_URLS，仍需按 MODEL_POOL_DEPLOYMENT.md 做负载分散与单节点故障切换验收。"
echo "仍必须由客户端完成 2 页 PPT + 10 页 PPT 两次端到端验收，才能签字。"
