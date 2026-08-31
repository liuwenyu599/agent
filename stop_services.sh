#!/usr/bin/env bash

echo "========================================"
echo " Judicial AI 后端服务停止"
echo "========================================"
echo

# FastAPI
PID=$(lsof -ti TCP:8000 -sTCP:LISTEN 2>/dev/null || true)

if [ -n "$PID" ]; then
    echo "停止 FastAPI: PID=$PID"
    kill "$PID" 2>/dev/null || true
else
    echo "FastAPI 未运行"
fi

# vLLM
PID=$(lsof -ti TCP:8001 -sTCP:LISTEN 2>/dev/null || true)

if [ -n "$PID" ]; then
    echo "停止 vLLM: PID=$PID"
    kill "$PID" 2>/dev/null || true
else
    echo "vLLM 未运行"
fi

sleep 3

echo
echo "当前端口："

if ss -lnt 2>/dev/null | grep -q ":8000 "; then
    echo "8000: 仍在运行"
else
    echo "8000: 已释放"
fi

if ss -lnt 2>/dev/null | grep -q ":8001 "; then
    echo "8001: 仍在运行"
else
    echo "8001: 已释放"
fi

echo
echo "完成。"
