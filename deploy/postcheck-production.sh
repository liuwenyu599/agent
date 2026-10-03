#!/usr/bin/env bash
set -euo pipefail

fail() { echo "[FAIL] $*" >&2; exit 1; }
ok() { echo "[ OK ] $*"; }
warn() { echo "[WARN] $*" >&2; }

curl -fsS --max-time 10 http://127.0.0.1:8000/health >/tmp/justice-health.json ||
  fail "API /health 失败"
cat /tmp/justice-health.json
ok "API health"

# ---------- 模型池：以 API 容器实际生效环境为准逐节点探活 ----------
# URLS 未配置时回退单 endpoint 变量，保持老部署兼容。已声明的副本任何一个
# /models 不可达都必须失败，避免“配置看起来有双实例，实际只有一个活着”的假完成。
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

# 视觉模型仍是单 endpoint；主文本与 PPT 模型按实际 URL 池逐个检查。
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
echo "若启用了 MODEL_SERVICE_URLS/PPT_MODEL_URLS，仍需按 MODEL_POOL_DEPLOYMENT.md 做负载分散与单节点故障切换验收。"
echo "仍必须由客户端完成 2 页 PPT + 10 页 PPT 两次端到端验收，才能签字。"
