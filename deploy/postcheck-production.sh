#!/usr/bin/env bash
set -euo pipefail

fail() { echo "[FAIL] $*" >&2; exit 1; }
ok() { echo "[ OK ] $*"; }
warn() { echo "[WARN] $*" >&2; }

curl -fsS --max-time 10 http://127.0.0.1:8000/health >/tmp/justice-health.json ||
  fail "API /health 失败"
cat /tmp/justice-health.json
ok "API health"

for p in 8002 8003 8004; do
  curl -fsS --max-time 10 "http://127.0.0.1:$p/v1/models" >/dev/null ||
    fail "模型端口 $p 不可用"
done
ok "三个模型"

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
  fail "8001 的 3B 容器仍在运行，请按文档 §二 停用"
fi
if ss -tlnp 2>/dev/null | grep -q ':8001 '; then
  fail "端口 8001 仍被占用"
fi
ok "8001 旧 3B 服务已停用"

# ---------- API 容器到宿主机模型真实连通 ----------
docker exec justice-api sh -c '
  for u in 8002 8003 8004 7861; do
    curl -sf --max-time 5 -o /dev/null http://10.128.85.133:$u/v1/models \
      || curl -sf --max-time 5 -o /dev/null http://10.128.85.133:$u/ \
      || { echo "FAIL $u"; exit 1; }
  done
' || fail "API 容器连不到宿主机模型"
ok "API 容器到宿主机模型/PPTAgent 连通"

echo
echo "POST-CHECK PASSED"
echo "仍必须由客户端完成 2 页 PPT + 10 页 PPT 两次端到端验收，才能签字。"
