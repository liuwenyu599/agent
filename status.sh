#!/usr/bin/env bash

echo "========================================"
echo " Judicial AI 服务状态"
echo "========================================"
echo

echo "[Qwen / vLLM]"

if curl -sf http://127.0.0.1:8001/v1/models >/tmp/judicial_models.json 2>/dev/null; then
    echo "状态：运行正常"
    echo "地址：http://127.0.0.1:8001/v1"
    echo
    cat /tmp/judicial_models.json
else
    echo "状态：未运行 / 异常"
fi

echo
echo "----------------------------------------"
echo

echo "[FastAPI]"

if curl -sf http://127.0.0.1:8000/health >/tmp/judicial_health.json 2>/dev/null; then
    echo "状态：运行正常"
    echo "地址：http://127.0.0.1:8000"
    echo
    cat /tmp/judicial_health.json
else
    echo "状态：未运行 / 异常"
fi

echo
echo "----------------------------------------"
echo

echo "[端口]"

ss -lntp 2>/dev/null | grep -E ":8000 |:8001 " || echo "8000 / 8001 均未监听"

echo
echo "----------------------------------------"
echo

echo "[进程]"

ps aux | grep -E "vllm|app.main" | grep -v grep || echo "未发现服务进程"

echo
