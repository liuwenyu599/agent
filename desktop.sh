#!/usr/bin/env bash

set -u

PROJECT_DIR="$HOME/judicial_app"
DESKTOP_DIR="$PROJECT_DIR/desktop"

echo "========================================"
echo " Judicial AI Desktop"
echo "========================================"
echo

# 必须有 GUI
if [ -z "${DISPLAY:-}" ] && [ -z "${WAYLAND_DISPLAY:-}" ]; then
    echo "错误：当前终端没有图形显示环境。"
    echo
    echo "请通过 ToDesk 登录 Ubuntu 图形桌面，"
    echo "然后在服务器桌面的 Terminal 中运行："
    echo
    echo "cd ~/judicial_app"
    echo "./desktop.sh"
    echo
    exit 1
fi

echo "DISPLAY=${DISPLAY:-}"
echo "XDG_SESSION_TYPE=${XDG_SESSION_TYPE:-}"
echo

# 检查后端
echo "检查 FastAPI..."

if curl -sf http://127.0.0.1:8000/health >/dev/null 2>&1; then
    echo "FastAPI: OK"
else
    echo "警告：FastAPI 当前不可用。"
    echo "请先在 SSH 中执行："
    echo
    echo "cd ~/judicial_app"
    echo "./start_services.sh"
    echo
    read -r -p "仍然启动 Desktop？[y/N] " answer

    if [[ ! "$answer" =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# 检查模型
echo "检查 Qwen..."

if curl -sf http://127.0.0.1:8001/v1/models >/dev/null 2>&1; then
    echo "Qwen: OK"
else
    echo "警告：Qwen 模型服务当前不可用。"
    echo "请先在 SSH 中执行："
    echo
    echo "cd ~/judicial_app"
    echo "./start_services.sh"
    echo
    read -r -p "仍然启动 Desktop？[y/N] " answer

    if [[ ! "$answer" =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

echo
echo "启动 Compose Desktop..."
echo

cd "$DESKTOP_DIR"

./gradlew run --no-daemon

EXIT_CODE=$?

echo
echo "Desktop 已退出。"
echo "Exit code: $EXIT_CODE"
