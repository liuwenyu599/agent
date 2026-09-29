#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="${ENV_FILE:-/opt/justice-office/deploy/.env}"
COMPOSE_FILE="${COMPOSE_FILE:-/opt/justice-office/deploy/docker-compose.yml}"
SOURCE_DIR="${SOURCE_DIR:-/opt/judicial_app}"

fail() { echo "[FAIL] $*" >&2; exit 1; }
ok() { echo "[ OK ] $*"; }

[ -f "$ENV_FILE" ] || fail "缺少生产 .env: $ENV_FILE"
[ -f "$COMPOSE_FILE" ] || fail "缺少生产 compose: $COMPOSE_FILE"
[ -d "$SOURCE_DIR" ] || fail "缺少源码目录: $SOURCE_DIR"
command -v docker >/dev/null || fail "docker 不存在"
command -v curl >/dev/null || fail "curl 不存在"

getenvv() {
  local key="$1"
  sed -n "s/^${key}=//p" "$ENV_FILE" | tail -n 1 | tr -d '\r'
}
expect() {
  local key="$1" expected="$2" actual
  actual="$(getenvv "$key")"
  [ "$actual" = "$expected" ] || fail "$key 应为 '$expected'，实际为 '$actual'"
  ok "$key"
}

expect MODEL_SERVICE_URL "http://10.128.85.133:8003/v1"
expect MODEL_CTX_LIMIT "16384"
expect VISION_MODEL_URL "http://10.128.85.133:8002/v1"
expect PPT_MODEL_URL "http://10.128.85.133:8004/v1"
expect PPT_AGENT_URL "http://10.128.85.133:7861"
expect PPT_AGENT_SUBMIT_PATH "/gradio_api/call/send_message"
expect PPT_AGENT_WORKSPACE_DIR "/data/pptagent"

[ -d /opt/justice-ppt/workspace ] || fail "缺少 PPTAgent workspace"
[ -f /opt/justice-ppt/deeppresenter/config.yaml ] || fail "缺少 DeepPresenter config.yaml"
[ -f /opt/justice-ppt/deeppresenter/mcp.json ] || fail "缺少 DeepPresenter mcp.json"
[ -f /opt/justice-ppt/cache/lid.176.bin ] || fail "缺少 fasttext 离线模型"
ok "PPTAgent 配置与缓存"

for d in   /home/lcode/Qwen2.5-14B-Instruct   /home/lcode/Qwen2.5-VL-7B-Instruct   /home/lcode/DeepPresenter-9B   /home/lcode/bge-m3
do
  [ -d "$d" ] || fail "缺少模型目录: $d"
done
ok "模型目录"

free_kb="$(df -Pk / | awk 'NR==2 {print $4}')"
[ "${free_kb:-0}" -ge 20971520 ] || fail "根分区可用空间不足 20GB"
ok "磁盘空间 >= 20GB"

cfg="$(docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" config)"
grep -q '/data/pptagent' <<<"$cfg" || fail "compose 未挂载 /data/pptagent"
grep -q '/opt/justice-ppt/workspace' <<<"$cfg" || fail "compose 未挂载宿主机 PPTAgent workspace"
ok "compose PPTAgent 挂载"

grep -q 'max(2, min' "$SOURCE_DIR/server/app/application/ppt/service.py" ||
  fail "源码缺少 2 页下限修复"
! grep -q 'max(6, min' "$SOURCE_DIR/server/app/application/ppt/service.py" ||
  fail "源码仍含 6 页下限"
grep -q '页数硬约束' "$SOURCE_DIR/server/app/application/ppt/ppt_engine.py" ||
  fail "源码缺少页数硬约束"
grep -q '不要虚构材料中没有的事实和数据' "$SOURCE_DIR/server/app/application/ppt/ppt_engine.py" ||
  fail "源码缺少事实约束"
grep -q 'replace(tzinfo=CN_TZ)' "$SOURCE_DIR/server/app/application/ppt/agent_job.py" ||
  fail "源码缺少 PPT 预览时区修复"
ok "关键源码修复"

# ---------- 镜像补丁完整性（2026-09-28 排障基线） ----------
DELIVERY_IMAGE_DIR="/opt/justice-office/data/delivery-images"
SANDBOX_IMAGE="deeppresenter-sandbox:latest"
HOST_IMAGE="deeppresenter-host:latest"
SANDBOX_RESTORE="$DELIVERY_IMAGE_DIR/sandbox.tar"
HOST_RESTORE="$DELIVERY_IMAGE_DIR/host.tar"

for tar_file in \
  "$DELIVERY_IMAGE_DIR/sandbox.tar" \
  "$DELIVERY_IMAGE_DIR/host.tar" \
  "$DELIVERY_IMAGE_DIR/rollback-server.tar"
do
  [ -s "$tar_file" ] || fail "交付镜像未归档，无法保证可恢复：缺少 $tar_file"
done
ok "交付镜像归档"

docker image inspect "$SANDBOX_IMAGE" >/dev/null 2>&1 ||
  fail "sandbox 镜像补丁丢失，请从 /opt/justice-office/data/delivery-images/sandbox.tar 恢复"

docker run --rm --entrypoint sh "$SANDBOX_IMAGE" -c '
  set -eu
  capture=/usr/src/app/dist/utils/capture.js
  [ -n "$capture" ]
  [ "$(grep -o "offline-patch" "$capture" | wc -l | tr -d " ")" = "2" ]
  schemas=/usr/src/app/dist/tools/schemas.js
  [ -n "$schemas" ]
  grep -q "rewrite: z.union" "$schemas"
  [ ! -L /usr/local/bin/mmdc ]
  [ "$(head -n 1 /usr/local/bin/mmdc)" = "#!/bin/bash" ]
  [ "$(fc-list :lang=zh | wc -l | tr -d " ")" -ge 100 ]
' || fail "sandbox 镜像补丁丢失，请从 /opt/justice-office/data/delivery-images/sandbox.tar 恢复"
ok "sandbox 镜像补丁完整"

docker image inspect "$HOST_IMAGE" >/dev/null 2>&1 ||
  fail "host 镜像补丁丢失，请从 /opt/justice-office/data/delivery-images/host.tar 恢复"

docker run --rm --entrypoint sh "$HOST_IMAGE" -c '
  set -eu
  grep -q "禁止 apt install" /usr/src/pptagent/deeppresenter/roles/Research.yaml
  python3 -c "import yaml; yaml.safe_load(open(\"/usr/src/pptagent/deeppresenter/roles/Research.yaml\", encoding=\"utf-8\"))"
  which soffice >/dev/null
  which unoconv >/dev/null
  test -f /root/.cache/huggingface/hub/models--julien-c--fasttext-language-id/snapshots/master/lid.176.bin
' || fail "host 镜像补丁丢失，请从 /opt/justice-office/data/delivery-images/host.tar 恢复"
ok "host 镜像补丁完整"

for p in 8002 8003 8004; do
  curl -fsS --max-time 10 "http://127.0.0.1:$p/v1/models" >/dev/null ||
    fail "模型端口 $p 不可用"
done
code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 10 http://127.0.0.1:7861/ || true)"
[ -n "$code" ] && [ "$code" != "000" ] && [ "${code:0:1}" != "5" ] ||
  fail "PPTAgent 7861 不可用，HTTP=$code"
ok "模型与 PPTAgent"

echo
echo "⚠️ 部署前必须在 Windows 端执行以下两条命令，人工确认客户端行为："
echo ' cd D:\Projects\judicial_app\desktop'
echo ' findstr /n /c:"TIMEOUT_STATUS_MS" src\jvmMain\kotlin\com\judicialai\desktop\features\ppt\PptRepository.kt'
echo ' findstr /n /c:"job_status" /c:"job_error" /c:"error_msg" src\jvmMain\kotlin\com\judicialai\desktop\features\ppt\*.kt'
echo " 期望：TIMEOUT_STATUS_MS >= 30000；判断依据是 job_status，不是 job_error。"
echo " 若不满足，先改客户端再继续部署。"

echo
echo "PRE-FLIGHT PASSED"
