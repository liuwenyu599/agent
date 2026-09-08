#!/usr/bin/env bash

set -u

PROJECT_DIR="/home/lwy/judicial_app"
SERVER_DIR="$PROJECT_DIR/server"

MODEL_PATH="/home/lwy/Qwen2.5-14B-Instruct"

MODEL_HOST="127.0.0.1"
MODEL_PORT="8001"

SERVER_HOST="0.0.0.0"
SERVER_PORT="8000"

AGENT_PYTHON="/home/lwy/.conda/envs/agent/bin/python"
VLLM="/home/lwy/.conda/envs/agent/bin/vllm"

LOG_DIR="$PROJECT_DIR/logs"

mkdir -p "$LOG_DIR"
# ==================================================
# 0. 清理旧服务进程
# ==================================================

echo "[0/5] 清理旧服务进程..."

for PORT in 8000 8001; do
    PIDS=$(lsof -ti :"$PORT" 2>/dev/null || true)

    if [ -n "$PIDS" ]; then
        echo "清理端口 $PORT 上的旧进程：$PIDS"
        kill $PIDS 2>/dev/null || true
        sleep 1

        # 如果还没退出，强制杀掉
        PIDS=$(lsof -ti :"$PORT" 2>/dev/null || true)
        if [ -n "$PIDS" ]; then
            echo "强制结束端口 $PORT 上的进程：$PIDS"
            kill -9 $PIDS 2>/dev/null || true
        fi
    else
        echo "端口 $PORT：没有旧进程"
    fi
done

echo "旧服务清理完成。"
echo
echo "========================================"
echo " Judicial AI 后端服务启动"
echo "========================================"
echo

echo "[1/4] 检查 Python / CUDA..."

"$AGENT_PYTHON" - <<'PY'
import torch

print("PyTorch:", torch.__version__)
print("CUDA:", torch.version.cuda)
print("CUDA available:", torch.cuda.is_available())

if torch.cuda.is_available():
    for i in range(torch.cuda.device_count()):
        print(f"GPU {i}:", torch.cuda.get_device_name(i))
PY

echo

echo "[2/4] 检查 Qwen vLLM..."

if curl -sf "http://127.0.0.1:$MODEL_PORT/v1/models" >/dev/null 2>&1; then
    echo "Qwen 已经运行。"
else

    if ss -lnt 2>/dev/null | grep -q ":$MODEL_PORT "; then
        echo "错误：8001 已被其他程序占用。"
        echo "执行：lsof -i :8001"
        exit 1
    fi

    echo "启动 Qwen vLLM..."

    nohup "$VLLM" serve "$MODEL_PATH" \
        --served-model-name Qwen2.5-14B-Instruct \
        --host "$MODEL_HOST" \
        --port "$MODEL_PORT" \
        --dtype bfloat16 \
        --tensor-parallel-size 2 \
        --gpu-memory-utilization 0.9 \
        --max-model-len 16384 \
        --max-num-seqs 2 \
        --enforce-eager \
        > "$LOG_DIR/vllm.log" 2>&1 &

    echo "vLLM PID: $!"
    echo "日志：$LOG_DIR/vllm.log"
    echo

    echo "等待 Qwen 加载模型..."

    READY=0

    for i in $(seq 1 300); do
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
        echo "Qwen 启动失败，最近日志："
        echo "----------------------------------------"
        tail -100 "$LOG_DIR/vllm.log"
        echo "----------------------------------------"
        exit 1
    fi

    echo "Qwen 启动成功。"
fi

echo
echo "模型接口："
curl -s "http://127.0.0.1:$MODEL_PORT/v1/models"
echo
echo

echo "[3/4] 检查 FastAPI..."

if curl -sf "http://127.0.0.1:$SERVER_PORT/health" >/dev/null 2>&1; then
    echo "FastAPI 已经运行。"
else

    if ss -lnt 2>/dev/null | grep -q ":$SERVER_PORT "; then
        echo "错误：8000 已被其他程序占用。"
        echo "执行：lsof -i :8000"
        exit 1
    fi

    cd "$SERVER_DIR"

    echo "启动 FastAPI..."

    nohup "$AGENT_PYTHON" -m app.main \
        > "$LOG_DIR/server.log" 2>&1 &

    echo "FastAPI PID: $!"
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
        echo "FastAPI 启动失败，最近日志："
        echo "----------------------------------------"
        tail -100 "$LOG_DIR/server.log"
        echo "----------------------------------------"
        exit 1
    fi

    echo "FastAPI 启动成功。"
fi

echo
echo "[4/4] 最终检查"
echo

echo "Qwen:"
curl -sf "http://127.0.0.1:$MODEL_PORT/v1/models" >/dev/null \
    && echo "  OK - 8001"

echo "FastAPI:"
curl -sf "http://127.0.0.1:$SERVER_PORT/health" >/dev/null \
    && echo "  OK - 8000"

echo
echo "========================================"
echo " Judicial AI 后端服务正常"
echo "========================================"
echo

echo "Qwen:      http://127.0.0.1:8001/v1"
echo "FastAPI:   http://127.0.0.1:8000"
echo "Docs:      http://127.0.0.1:8000/docs"
echo
echo "日志："
echo "  tail -f $LOG_DIR/vllm.log"
echo "  tail -f $LOG_DIR/server.log"
echo
