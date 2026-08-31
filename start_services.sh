#!/usr/bin/env bash

set -u

PROJECT_DIR="$HOME/judicial_app"
SERVER_DIR="$PROJECT_DIR/server"

MODEL_PATH="$HOME/Qwen2.5-14B-Instruct"

MODEL_HOST="127.0.0.1"
MODEL_PORT="8001"

SERVER_HOST="0.0.0.0"
SERVER_PORT="8000"

AGENT_PYTHON="$HOME/.conda/envs/agent/bin/python"
VLLM="$HOME/.conda/envs/agent/bin/vllm"

LOG_DIR="$PROJECT_DIR/logs"

mkdir -p "$LOG_DIR"

echo "========================================"
echo " Judicial AI 后端服务启动"
echo "========================================"
echo

# ==================================================
# 1. 检查环境
# ==================================================

echo "[1/5] 检查 Python / vLLM..."

if [ ! -x "$AGENT_PYTHON" ]; then
    echo "错误：找不到 agent Python："
    echo "$AGENT_PYTHON"
    exit 1
fi

if [ ! -x "$VLLM" ]; then
    echo "错误：找不到 vLLM："
    echo "$VLLM"
    exit 1
fi

echo "Python:"
echo "  $AGENT_PYTHON"

echo "vLLM:"
echo "  $VLLM"

"$AGENT_PYTHON" - <<'PY'
import torch

print("PyTorch:", torch.__version__)
print("CUDA:", torch.cuda.is_available())

if torch.cuda.is_available():
    print("GPU:", torch.cuda.get_device_name(0))
PY

echo

# ==================================================
# 2. 检查模型
# ==================================================

echo "[2/5] 检查 Qwen 模型..."

if [ ! -d "$MODEL_PATH" ]; then
    echo
    echo "错误：找不到模型："
    echo "$MODEL_PATH"
    echo
    exit 1
fi

echo "模型：$MODEL_PATH"
echo

# ==================================================
# 3. 检查 8001
# ==================================================

echo "[3/5] 检查 Qwen 服务..."

if curl -sf "http://127.0.0.1:$MODEL_PORT/v1/models" >/dev/null 2>&1; then

    echo "Qwen 已经运行。"

else

    if ss -lnt 2>/dev/null | grep -q ":$MODEL_PORT "; then
        echo
        echo "错误：8001 已被其他程序占用。"
        echo
        echo "执行："
        echo "lsof -i :8001"
        echo
        exit 1
    fi

    echo "启动 Qwen vLLM..."

    nohup "$VLLM" serve "$MODEL_PATH" \
        --host "$MODEL_HOST" \
        --port "$MODEL_PORT" \
        --dtype bfloat16 \
        --gpu-memory-utilization 0.9 \
        --max-model-len 16384 \
        --max-num-seqs 2 \
        --enforce-eager \
        > "$LOG_DIR/vllm.log" 2>&1 &
    VLLM_PID=$!

    echo "vLLM PID: $VLLM_PID"
    echo "日志：$LOG_DIR/vllm.log"

    echo
    echo "等待 Qwen 加载模型..."

    READY=0

    for i in $(seq 1 600); do

        if curl -sf "http://127.0.0.1:$MODEL_PORT/v1/models" >/dev/null 2>&1; then
            READY=1
            break
        fi

        printf "."
        sleep 2

    done

    echo

    if [ "$READY" -ne 1 ]; then

        echo
        echo "========================================"
        echo " Qwen 启动失败"
        echo "========================================"
        echo

        echo "最近 100 行日志："
        echo "----------------------------------------"

        tail -100 "$LOG_DIR/vllm.log"

        echo "----------------------------------------"
        echo

        exit 1
    fi

    echo "Qwen 启动成功。"

fi

echo
echo "模型接口："
curl -s "http://127.0.0.1:$MODEL_PORT/v1/models"
echo
echo

# ==================================================
# 4. 检查 8000
# ==================================================

echo "[4/5] 检查 FastAPI..."

if curl -sf "http://127.0.0.1:$SERVER_PORT/health" >/dev/null 2>&1; then

    echo "FastAPI 已经运行。"

else

    if ss -lnt 2>/dev/null | grep -q ":$SERVER_PORT "; then

        echo
        echo "错误：8000 已被占用，但健康检查失败。"
        echo
        echo "执行："
        echo "lsof -i :8000"
        echo

        exit 1
    fi

    echo "启动 FastAPI..."

    cd "$SERVER_DIR"

    nohup "$AGENT_PYTHON" -m app.main \
        > "$LOG_DIR/server.log" 2>&1 &

    SERVER_PID=$!

    echo "FastAPI PID: $SERVER_PID"
    echo "日志：$LOG_DIR/server.log"

    echo
    echo "等待 FastAPI..."

    READY=0

    for i in $(seq 1 30); do

        if curl -sf "http://127.0.0.1:$SERVER_PORT/health" >/dev/null 2>&1; then
            READY=1
            break
        fi

        printf "."
        sleep 1

    done

    echo

    if [ "$READY" -ne 1 ]; then

        echo
        echo "========================================"
        echo " FastAPI 启动失败"
        echo "========================================"
        echo

        echo "最近 100 行日志："
        echo "----------------------------------------"

        tail -100 "$LOG_DIR/server.log"

        echo "----------------------------------------"
        echo

        exit 1
    fi

    echo "FastAPI 启动成功。"

fi

# ==================================================
# 5. 最终状态
# ==================================================

echo
echo "[5/5] 服务检查完成"
echo

echo "========================================"
echo " Judicial AI 后端服务正常"
echo "========================================"
echo

echo "Qwen:"
echo "  http://127.0.0.1:8001/v1"

echo
echo "FastAPI:"
echo "  http://127.0.0.1:8000"

echo
echo "FastAPI Docs:"
echo "  http://127.0.0.1:8000/docs"

echo
echo "日志目录:"
echo "  $LOG_DIR"

echo
echo "查看 Qwen 日志:"
echo "  tail -f $LOG_DIR/vllm.log"

echo
echo "查看 FastAPI 日志:"
echo "  tail -f $LOG_DIR/server.log"

echo
