#!/usr/bin/env bash
#
# check-qwen35b.sh — 检查 35B 评估实例的健康状态（容器 / 端口 / 模型注册 / 卡占用）
#
# 用法: ./check-qwen35b.sh
#   或覆盖: QWEN35B_PORT=8010 BASE_URL=http://127.0.0.1:8010 ./check-qwen35b.sh
set -euo pipefail

CONTAINER_NAME="${CONTAINER_NAME:-justice-qwen35b-w8a8}"
PORT="${QWEN35B_PORT:-8010}"
BASE_URL="${QWEN35B_BASE_URL:-http://127.0.0.1:$PORT}"
SERVED_MODEL="${SERVED_MODEL:-Qwen3.6-35B-A3B-W8A8}"

PASS=0; FAIL=0
check() {
  if [ "$2" = "OK" ]; then echo "[ OK ] $1"; PASS=$((PASS+1));
  else echo "[FAIL] $1 -> $2"; FAIL=$((FAIL+1)); fi
}

echo "===== 容器状态 ====="
STATUS=$(docker ps --filter "name=^${CONTAINER_NAME}$" --format '{{.Status}}' 2>/dev/null || echo "")
if [ -n "$STATUS" ]; then check "容器 $CONTAINER_NAME 运行中" "OK";
else check "容器 $CONTAINER_NAME 运行中" "未运行（docker ps 无匹配）"; fi

echo "===== API 可达性 ====="
if curl -fsS --max-time 5 "$BASE_URL/v1/models" >/dev/null 2>&1; then
  check "API 可达 (:${PORT}/v1/models)" "OK";
else check "API 可达 (:${PORT}/v1/models)" "不可达"; fi

echo "===== 模型注册 ====="
MODELS=$(curl -fsS --max-time 10 "$BASE_URL/v1/models" 2>/dev/null | grep -o '"id":"[^"]*"' | head -5 || echo "")
if echo "$MODELS" | grep -q "$SERVED_MODEL"; then
  check "模型已注册: $SERVED_MODEL" "OK";
else check "模型已注册: $SERVED_MODEL" "未找到 ($MODELS)"; fi

echo "===== 卡占用与利用率 ====="
CHIPS=$(docker inspect -f '{{range .HostConfig.Devices}}{{.PathOnHost}} {{end}}' "$CONTAINER_NAME" 2>/dev/null \
        | grep -oE 'davinci[0-9]+' | sed 's/davinci//' | sort -u | tr '\n' ' ')
echo "   本实例使用芯片: ${CHIPS:-未知}"
if command -v npu-smi >/dev/null 2>&1; then
  echo "   --- npu-smi 相关芯片 ---"
  npu-smi info 2>/dev/null | grep -E "^[|] *(${CHIPS// /|}) " || echo "   (无匹配行，请人工核对 npu-smi)"
fi

echo
echo "汇总: PASS=$PASS  FAIL=$FAIL"
[ "$FAIL" -eq 0 ]
