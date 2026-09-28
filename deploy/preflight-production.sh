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

for p in 8002 8003 8004; do
  curl -fsS --max-time 10 "http://127.0.0.1:$p/v1/models" >/dev/null ||
    fail "模型端口 $p 不可用"
done
code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 10 http://127.0.0.1:7861/ || true)"
[ -n "$code" ] && [ "$code" != "000" ] && [ "${code:0:1}" != "5" ] ||
  fail "PPTAgent 7861 不可用，HTTP=$code"
ok "模型与 PPTAgent"

echo
echo "PRE-FLIGHT PASSED"
