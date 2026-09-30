#!/usr/bin/env bash
# ============================================================================
# fix_workspace_dir.sh —— 修复司法局后端 .env 并重建 API
#
# 修复两类曾踩过的坑：
#   1) 容器内网络寻址：后端跑在 Docker 容器（bridge 网络），容器里的 127.0.0.1
#      是容器自己，不是宿主机。vLLM/PPTAgent 在宿主机，必须用真实 IP。
#      → 把 MODEL_SERVICE_URL / VISION_MODEL_URL / PPT_MODEL_URL / PPT_AGENT_URL
#        里的 127.0.0.1 统一改成 10.128.85.133。
#   2) 逐页预览路径：PPT_AGENT_WORKSPACE_DIR 必须是【容器内】路径 /data/pptagent，
#      不是宿主机挂载源 /opt/justice-ppt/workspace。
#
# ⚠️ 不自动改 MODEL_CTX_LIMIT：它必须等于 8003 模型实际的 --max-model-len，
#    2026-09-29 核查存在冲突（DeepPresenter-9B@49152 vs Qwen2.5-14B@16384），
#    脚本只打印验证命令，请人确认后再手改，避免设错导致模型报错。
#
# 用法（部署机 /opt/justice-office/deploy，root）：
#   bash fix_workspace_dir.sh            # 改 .env，重启前交互确认（孤儿安全闸）
#   bash fix_workspace_dir.sh --force    # 跳过确认直接重建（仅当确认无在跑 job）
# ============================================================================
set -euo pipefail

DEPLOY_DIR="/opt/justice-office/deploy"
ENV_FILE="$DEPLOY_DIR/.env"
HOST_IP="10.128.85.133"
FORCE=0
[[ "${1:-}" == "--force" ]] && FORCE=1

# --- 0) 安全闸：重建 API 会杀掉进程内后台 async 任务，使在跑的 PPT job 变孤儿 ---
if [[ "$FORCE" -eq 0 ]]; then
  echo "⚠️  重建 API 会终止其进程内的后台生成任务。"
  echo "    若有 PPT job 仍在生成（如 16fad076），重建会让它变成孤儿（DB 永远 running）。"
  echo "    确认已完成 / 可接受后继续；否则按 Ctrl-C 退出。"
  echo "    （也可先执行：find $DEPLOY_DIR/../data/ppt/generated -name '*.pptx' -newermt '2026-09-28 19:30'）"
  read -r -p "确定要重建 API 吗？[y/N] " ans
  [[ "$ans" == "y" || "$ans" == "Y" ]] || { echo "已取消。"; exit 0; }
fi

# --- 1) 修正 .env ---
echo "[1/3] 修正 .env 网络寻址与 workspace 路径"
if [[ ! -f "$ENV_FILE" ]]; then
  echo "ERROR: 找不到 $ENV_FILE，请确认 DEPLOY_DIR 是否正确。" >&2
  exit 1
fi

# 1a) 四个模型/agent URL：127.0.0.1 → 宿主机真实 IP（无论当前是 127.0.0.1 还是其它，统一归一到真实 IP）
for key in MODEL_SERVICE_URL VISION_MODEL_URL PPT_MODEL_URL PPT_AGENT_URL; do
  sed -i -E "s|^(export )?${key}=http://127\.0\.0\.1:|${key}=http://${HOST_IP}:|" "$ENV_FILE"
done

# 1b) workspace 路径：必须是容器内路径
sed -i '/^PPT_AGENT_WORKSPACE_DIR=/d' "$ENV_FILE"
printf 'PPT_AGENT_WORKSPACE_DIR=/data/pptagent\n' >> "$ENV_FILE"

echo "    修正后："
grep -E '^(MODEL_SERVICE_URL|VISION_MODEL_URL|PPT_MODEL_URL|PPT_AGENT_URL|PPT_AGENT_WORKSPACE_DIR)=' "$ENV_FILE"

# 1c) MODEL_CTX_LIMIT：仅提示，不改
echo
echo "[提示] MODEL_CTX_LIMIT 未自动修改。请核对 8003 模型实际 --max-model-len 后手改："
echo "    curl -s http://${HOST_IP}:8003/v1/models"
echo "    （记录冲突：DeepPresenter-9B@49152 vs Qwen2.5-14B@16384；设小仅截断，设大超上限才报错）"
echo "    当前值：$(grep -E '^MODEL_CTX_LIMIT=' "$ENV_FILE" || echo 未设置)"

# --- 2) 重建 API ---
echo "[2/3] 重建 API 容器"
cd "$DEPLOY_DIR"
# 用 compose 服务名重建（不依赖具体 container_name）。
# 若你部署用的是旧命名 justice-api / justice-migrate，请改为：
#   docker rm -f justice-api justice-migrate && docker compose up -d
docker compose up -d --force-recreate api

# --- 3) 健康检查 + 模型端口验证（从宿主机 curl 自身已发布端口）---
echo "[3/3] 等待 40s 并健康检查 + 验证模型端口"
sleep 40
if curl -fsS http://127.0.0.1:8000/health; then
  echo
  echo "✅ API 已重建且 /health 通过。逐页预览 / job_progress_at 应恢复正常。"
else
  echo "❌ /health 未通过，请 docker logs 排查。" >&2
  exit 1
fi

echo "--- 验证模型端口（期望全部 200）---"
for p in 8003 8002 8004; do
  curl -s -o /dev/null -w "$p: %{http_code}\n" "http://${HOST_IP}:$p/v1/models"
done
curl -s -o /dev/null -w "7861: %{http_code}\n" "http://${HOST_IP}:7861/"
