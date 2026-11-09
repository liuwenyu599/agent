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

# ---------- 模型链路：按 .env 实际值校验，不再硬编码已退役端口 ----------
# 旧布局 14B(:8003) / VL-7B(:8002) / DP9B(:8004) / PPTAgent(:7861) 已停用；
# 文本 / 视觉 / 长文 / PPT 大纲现统一走 35B(:8010)，或留空回退主文本模型。
expect MODEL_CTX_LIMIT "16384"

require_url() {
  local key="$1" actual
  actual="$(getenvv "$key")"
  [[ "$actual" =~ ^https?://[^/]+/v1/?$ ]] ||
    fail "$key 必须是 http(s)://host:port/v1，实际为 '$actual'"
  ok "$key = $actual"
}
require_url MODEL_SERVICE_URL
# 视觉模型可选：留空不报错，但上传图片不会有自动 caption。
if [ -n "$(getenvv VISION_MODEL_URL)" ]; then
  require_url VISION_MODEL_URL
else
  echo "[WARN] VISION_MODEL_URL 为空：图片描述/视觉复检会降级，需人工补写 caption"
fi

if [ -n "$(getenvv PPT_MODEL_URL)" ]; then
  require_url PPT_MODEL_URL
  [ -n "$(getenvv PPT_MODEL_NAME)" ] ||
    fail "PPT_MODEL_URL 非空时必须同时配置 PPT_MODEL_NAME"
  ok "PPT 大纲使用独立模型"
else
  ok "PPT_MODEL_URL 为空：大纲回退主文本模型（35B）"
fi

case "$(getenvv PPT_AGENT_ENABLED)" in
  true|TRUE|1|yes|YES) agent_enabled=true ;;
  *) agent_enabled=false ;;
esac
agent_url="$(getenvv PPT_AGENT_URL)"
if $agent_enabled; then
  [ -n "$agent_url" ] || fail "PPT_AGENT_ENABLED=true 但 PPT_AGENT_URL 为空"
  expect PPT_AGENT_SUBMIT_PATH "/gradio_api/call/send_message"
  expect PPT_AGENT_WORKSPACE_DIR "/data/pptagent"
  ok "PPTAgent 已启用：$agent_url"
else
  # config.py 在开关为 false 时强制忽略该 URL，属于配置残留而非部署阻断。
  [ -z "$agent_url" ] ||
    echo "[WARN] PPTAgent 已停用但 PPT_AGENT_URL 仍为 '$agent_url'（运行时会被忽略，建议清理）"
  ok "PPTAgent 已停用：走本地 render_pptx"
fi

# ---------- SECRET_KEY 生产强校验（2026-10-03 排障基线） ----------
secret_key="$(getenvv SECRET_KEY)"
[ -n "$secret_key" ] || fail "SECRET_KEY 未配置（不能为空，否则 JWT 用弱占位密钥签发）"
[ "$secret_key" != "dev-only-insecure-secret-change-me" ] ||
  fail "SECRET_KEY 仍使用默认弱密钥，必须在生产 .env 中替换为强随机值"
ok "SECRET_KEY 已配置且非默认"

# 以下目录/镜像检查只属于已停用的 PPTAgent 独立栈；本地渲染模式下不要求存在。
if $agent_enabled; then
  [ -d /opt/justice-ppt/workspace ] || fail "缺少 PPTAgent workspace"
  [ -f /opt/justice-ppt/deeppresenter/config.yaml ] || fail "缺少 DeepPresenter config.yaml"
  [ -f /opt/justice-ppt/deeppresenter/mcp.json ] || fail "缺少 DeepPresenter mcp.json"
  [ -f /opt/justice-ppt/cache/lid.176.bin ] || fail "缺少 fasttext 离线模型"
  ok "PPTAgent 配置与缓存"

  for d in /home/lcode/DeepPresenter-9B; do
    [ -d "$d" ] || fail "缺少模型目录: $d"
  done
  ok "PPTAgent 模型目录"
else
  ok "跳过 PPTAgent 目录检查（本地渲染）"
fi

free_kb="$(df -Pk / | awk 'NR==2 {print $4}')"
[ "${free_kb:-0}" -ge 20971520 ] || fail "根分区可用空间不足 20GB"
ok "磁盘空间 >= 20GB"

cfg="$(docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" config)"
if $agent_enabled; then
  grep -q '/data/pptagent' <<<"$cfg" || fail "compose 未挂载 /data/pptagent"
  grep -q '/opt/justice-ppt/workspace' <<<"$cfg" || fail "compose 未挂载宿主机 PPTAgent workspace"
  ok "compose PPTAgent 挂载"
else
  ok "compose 配置可解析（本地渲染，不校验 PPTAgent 挂载）"
fi

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

# ---------- 镜像补丁完整性（仅 PPTAgent 启用时，2026-09-28 排障基线） ----------
if $agent_enabled; then
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
else
  ok "跳过 PPTAgent 镜像补丁检查（本地渲染）"
fi

# ---------- 模型端点可达性：按 .env 实际配置动态探测 ----------
# 不再硬编码 8002/8003/8004；从各条 *_URL(S) 里取出实参逐个请求 /v1/models。
model_urls=""
for key in MODEL_SERVICE_URL MODEL_SERVICE_URLS VISION_MODEL_URL \
           LONG_FORM_MODEL_URLS PPT_MODEL_URL; do
  value="$(getenvv "$key")"
  [ -n "$value" ] && model_urls="$model_urls $(printf '%s' "$value" | tr ',' ' ')"
done
for base in $model_urls; do
  endpoint="${base%/}/models"
  curl -fsS --max-time 10 "$endpoint" >/dev/null ||
    fail "模型端点不可用：$endpoint（检查 .env 的 URL 与模型容器状态）"
done
[ -n "$model_urls" ] || fail ".env 中没有任何可用的模型端点"
ok "模型端点可达"

if $agent_enabled; then
  code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 10 \
    "${agent_url%/}/" || true)"
  [ -n "$code" ] && [ "$code" != "000" ] && [ "${code:0:1}" != "5" ] ||
    fail "PPTAgent 不可用，HTTP=$code"
  ok "PPTAgent 可达"
fi

echo
echo "⚠️ 部署前必须在 Windows 端执行以下两条命令，人工确认客户端行为："
echo ' cd D:\Projects\judicial_app\desktop'
echo ' findstr /n /c:"TIMEOUT_STATUS_MS" src\jvmMain\kotlin\com\judicialai\desktop\features\ppt\PptRepository.kt'
echo ' findstr /n /c:"job_status" /c:"job_error" /c:"error_msg" src\jvmMain\kotlin\com\judicialai\desktop\features\ppt\*.kt'
echo " 期望：TIMEOUT_STATUS_MS >= 30000；判断依据是 job_status，不是 job_error。"
echo " 若不满足，先改客户端再继续部署。"

echo
echo "PRE-FLIGHT PASSED"
