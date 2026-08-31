#!/usr/bin/env bash

set -u

PROJECT_DIR="$HOME/judicial_app"
DESKTOP_DIR="$PROJECT_DIR/desktop"
SERVER_DIR="$PROJECT_DIR/server"

MODEL_PATH="$HOME/Qwen2.5-14B-Instruct"
MODEL_HOST="127.0.0.1"
MODEL_PORT="8001"

SERVER_HOST="0.0.0.0"
SERVER_PORT="8000"

LOG_DIR="$PROJECT_DIR/logs"
mkdir -p "$LOG_DIR"

echo "========================================"
echo "      Judicial AI 一键启动脚本"
echo "========================================"
echo

# --------------------------------------------------
# 1. 基础检查
# --------------------------------------------------

echo "[1/7] 检查项目目录..."

if [ ! -d "$PROJECT_DIR" ]; then
    echo "错误：项目目录不存在：$PROJECT_DIR"
    exit 1
fi

if [ ! -d "$DESKTOP_DIR" ]; then
    echo "错误：Desktop 目录不存在：$DESKTOP_DIR"
    exit 1
fi

if [ ! -d "$SERVER_DIR" ]; then
    echo "错误：Server 目录不存在：$SERVER_DIR"
    exit 1
fi

if [ ! -d "$MODEL_PATH" ]; then
    echo "错误：模型目录不存在：$MODEL_PATH"
    echo
    echo "当前设置的模型路径："
    echo "$MODEL_PATH"
    exit 1
fi

echo "项目目录：OK"
echo "模型目录：$MODEL_PATH"
echo

# --------------------------------------------------
# 2. 检查图形环境
# --------------------------------------------------

echo "[2/7] 检查图形环境..."

if [ -z "${DISPLAY:-}" ] && [ -z "${WAYLAND_DISPLAY:-}" ]; then
    echo
    echo "警告：当前终端没有 DISPLAY / WAYLAND_DISPLAY。"
    echo
    echo "Desktop 是 Compose GUI 程序。"
    echo "请在 ToDesk 登录服务器 Ubuntu 图形桌面后，"
    echo "从桌面 Terminal 执行这个脚本。"
    echo
    read -r -p "仍然继续启动后端和模型？[y/N] " answer

    if [[ ! "$answer" =~ ^[Yy]$ ]]; then
        echo "已退出。"
        exit 1
    fi
else
    echo "DISPLAY=${DISPLAY:-}"
    echo "WAYLAND_DISPLAY=${WAYLAND_DISPLAY:-}"
fi

echo

# --------------------------------------------------
# 3. 检查 agent 环境
# --------------------------------------------------

echo "[3/7] 检查 Python / vLLM 环境..."

if [ -f "$HOME/miniconda3/etc/profile.d/conda.sh" ]; then
    source "$HOME/miniconda3/etc/profile.d/conda.sh"
elif [ -f "$HOME/anaconda3/etc/profile.d/conda.sh" ]; then
    source "$HOME/anaconda3/etc/profile.d/conda.sh"
fi

if ! command -v conda >/dev/null 2>&1; then
    echo "错误：找不到 conda。"
    exit 1
fi

conda activate agent

echo "Python：$(which python)"
echo "vLLM：$(which vllm)"

VLLM_VERSION=$(vllm --version 2>/dev/null || true)

if [ -z "$VLLM_VERSION" ]; then
    echo "错误：当前 agent 环境找不到 vLLM。"
    exit 1
fi

echo "vLLM：$VLLM_VERSION"

python - <<'PY'
import torch

print("PyTorch:", torch.__version__)
print("CUDA available:", torch.cuda.is_available())

if torch.cuda.is_available():
    print("GPU:", torch.cuda.get_device_name(0))
else:
    print("WARNING: CUDA 不可用")
PY

echo

# --------------------------------------------------
# 4. 停止旧服务
# --------------------------------------------------

echo "[4/7] 检查旧服务..."

if ss -lnt 2>/dev/null | grep -q ":$MODEL_PORT "; then
    echo "端口 $MODEL_PORT 已被占用。"

    PID=$(lsof -ti TCP:$MODEL_PORT -sTCP:LISTEN 2>/dev/null || true)

    if [ -n "$PID" ]; then
        echo "发现旧进程 PID=$PID"
        echo "尝试停止旧模型服务..."

        kill "$PID" 2>/dev/null || true
        sleep 3
    fi
fi

if ss -lnt 2>/dev/null | grep -q ":$SERVER_PORT "; then
    echo "端口 $SERVER_PORT 已被占用。"

    PID=$(lsof -ti TCP:$SERVER_PORT -sTCP:LISTEN 2>/dev/null || true)

    if [ -n "$PID" ]; then
        echo "发现旧后端进程 PID=$PID"
        echo "尝试停止旧后端..."

        kill "$PID" 2>/dev/null || true
        sleep 2
    fi
fi

echo "旧服务检查完成。"
echo

# --------------------------------------------------
# 5. 启动 vLLM
# --------------------------------------------------

echo "[5/7] 启动 Qwen vLLM..."

cd "$PROJECT_DIR"

nohup vllm serve "$MODEL_PATH" \
    --host "$MODEL_HOST" \
    --port "$MODEL_PORT" \
    --dtype half \
    > "$LOG_DIR/vllm.log" 2>&1 &

VLLM_PID=$!

echo "vLLM PID: $VLLM_PID"
echo "日志：$LOG_DIR/vllm.log"

echo
echo "等待模型服务启动..."

MODEL_READY=0

for i in $(seq 1 60); do
    if curl -sf "http://$MODEL_HOST:$MODEL_PORT/v1/models" >/dev/null 2>&1; then
        MODEL_READY=1
        break
    fi

    printf "."
    sleep 2
done

echo

if [ "$MODEL_READY" -ne 1 ]; then
    echo
    echo "错误：Qwen 模型服务启动失败。"
    echo
    echo "最后 80 行 vLLM 日志："
    echo "----------------------------------------"
    tail -80 "$LOG_DIR/vllm.log"
    echo "----------------------------------------"
    echo
    echo "不会继续启动客户端。"
    exit 1
fi

echo "Qwen 模型服务：OK"
echo

curl -s "http://$MODEL_HOST:$MODEL_PORT/v1/models"
echo
echo

# --------------------------------------------------
# 6. 启动 FastAPI Server
# --------------------------------------------------

echo "[6/7] 启动 FastAPI Server..."

cd "$SERVER_DIR"

nohup python -m app.main \
    > "$LOG_DIR/server.log" 2>&1 &

SERVER_PID=$!

echo "Server PID: $SERVER_PID"
echo "日志：$LOG_DIR/server.log"

echo
echo "等待 FastAPI..."

SERVER_READY=0

for i in $(seq 1 30); do
    if curl -sf "http://127.0.0.1:$SERVER_PORT/health" >/dev/null 2>&1; then
        SERVER_READY=1
        break
    fi

    printf "."
    sleep 1
done

echo

if [ "$SERVER_READY" -ne 1 ]; then
    echo
    echo "错误：FastAPI 启动失败。"
    echo
    echo "最后 80 行 Server 日志："
    echo "----------------------------------------"
    tail -80 "$LOG_DIR/server.log"
    echo "----------------------------------------"
    exit 1
fi

echo "FastAPI Server：OK"
echo

curl -s "http://127.0.0.1:$SERVER_PORT/health"
echo
echo

# --------------------------------------------------
# 7. 启动 Desktop
# --------------------------------------------------

echo "[7/7] 启动 Judicial AI Desktop..."

if [ -z "${DISPLAY:-}" ] && [ -z "${WAYLAND_DISPLAY:-}" ]; then
    echo
    echo "后端和模型已经成功启动。"
    echo "当前 SSH/TTY 没有图形显示环境，因此跳过 Desktop。"
    echo
    echo "请进入 ToDesk Ubuntu 图形桌面 Terminal，重新执行："
    echo
    echo "cd ~/judicial_app"
    echo "./start_all.sh"
    echo
    echo "注意：这次脚本会发现 8000/8001 已经运行，"
    echo "当前版本会尝试处理旧进程。"
    echo
    exit 0
fi

cd "$DESKTOP_DIR"

echo
echo "========================================"
echo "所有后端服务已经启动"
echo "========================================"
echo
echo "模型服务："
echo "  http://127.0.0.1:$MODEL_PORT/v1"
echo
echo "FastAPI："
echo "  http://127.0.0.1:$SERVER_PORT"
echo
echo "FastAPI Docs："
echo "  http://127.0.0.1:$SERVER_PORT/docs"
echo
echo "日志目录："
echo "  $LOG_DIR"
echo
echo "启动 Desktop..."
echo

./gradlew run --no-daemon

DESKTOP_EXIT=$?

echo
echo "Desktop 已退出，exit code=$DESKTOP_EXIT"
echo
echo "后台服务仍可能继续运行。"
echo
echo "查看模型日志："
echo "  tail -f $LOG_DIR/vllm.log"
echo
echo "查看 Server 日志："
echo "  tail -f $LOG_DIR/server.log"
echo
