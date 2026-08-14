#!/bin/bash
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="${SCRIPT_DIR}/logs"
RUN_DIR="${SCRIPT_DIR}/run"
mkdir -p "${LOG_DIR}" "${RUN_DIR}"
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
log_info() { echo -e "${GREEN}[INFO]${NC} $(date '+%H:%M:%S') $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $(date '+%H:%M:%S') $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $(date '+%H:%M:%S') $1"; }

CONDA_ENV="agent"
BACKEND_PORT=8000; FRONTEND_PORT=5173; VLLM_PORT=8001
MODEL_PATH="/home/lwy/Qwen2.5-14B-Instruct"
MODEL_NAME="Qwen2.5-14B-Instruct"
QUANTIZATION=""; DTYPE="bfloat16"
GPU_MEMORY_UTILIZATION="0.65"
MAX_MODEL_LEN="4096"
MAX_NUM_SEQS="2"
export PYTORCH_CUDA_ALLOC_CONF="expandable_segments:True"
export NCCL_P2P_DISABLE=1

check_conda() {
    for path in /opt/anaconda3 /opt/miniconda3 ~/miniconda3 ~/anaconda3; do
        if [ -f "$path/etc/profile.d/conda.sh" ]; then source "$path/etc/profile.d/conda.sh"; return; fi
    done
    log_error "找不到 conda"; exit 1
}
pid_file() { echo "${RUN_DIR}/$1.pid"; }
save_pid() { echo "$2" > "$(pid_file "$1")"; }
get_pid() { if [ -f "$(pid_file "$1")" ]; then cat "$(pid_file "$1")"; fi; }
remove_pid() { rm -f "$(pid_file "$1")"; }
is_pid_running() { local pid="$1"; [ -n "$pid" ] && ps -p "$pid" >/dev/null 2>&1; }

stop_service() {
    NAME="$1"; PID=$(get_pid "$NAME")
    if ! is_pid_running "$PID"; then remove_pid "$NAME"; return; fi
    log_info "停止 ${NAME} (PID=${PID})"; kill "$PID" 2>/dev/null || true
    for i in {1..15}; do sleep 1; if ! ps -p "$PID" >/dev/null 2>&1; then remove_pid "$NAME"; return; fi; done
    log_warn "${NAME} 未正常退出，强制结束"; kill -9 "$PID" 2>/dev/null || true; remove_pid "$NAME"
}

kill_port() {
    local port="$1" name="$2"
    local pid=$(lsof -ti:${port} 2>/dev/null)
    if [ -n "$pid" ]; then log_warn "端口 ${port}(${name}) 被 PID=${pid} 占用，杀掉"; kill -9 "$pid" 2>/dev/null || true; sleep 1; fi
}

cleanup_all() {
    log_info "清理所有残留..."
    stop_service frontend; stop_service backend; stop_service vllm
    kill_port ${VLLM_PORT} "vllm"; kill_port ${BACKEND_PORT} "backend"; kill_port ${FRONTEND_PORT} "frontend"
    local gpu_pids=$(nvidia-smi --query-compute-apps=pid --format=csv,noheader 2>/dev/null | sort -u)
    if [ -n "$gpu_pids" ]; then
        for pid in $gpu_pids; do
            if [ -n "$pid" ] && [ "$pid" != "$$" ]; then
                log_warn "杀掉 GPU 进程 PID=$pid"; kill -9 "$pid" 2>/dev/null || true
            fi
        done
        sleep 2
    fi
    python -c "import torch; torch.cuda.empty_cache()" 2>/dev/null || true
    log_info "端口状态:"
    for port in ${VLLM_PORT} ${BACKEND_PORT} ${FRONTEND_PORT}; do
        if lsof -i:${port} >/dev/null 2>&1; then log_warn "  端口 ${port} 仍被占用: $(lsof -ti:${port})"
        else log_info "  端口 ${port} 已释放"; fi
    done
    log_info "GPU 状态:"; nvidia-smi --query-gpu=index,memory.used,memory.free --format=csv 2>/dev/null || nvidia-smi
}

start_backend() {
    PID=$(get_pid backend)
    if is_pid_running "$PID"; then log_warn "Backend 已运行 (PID=${PID})"; return; fi
    kill_port ${BACKEND_PORT} "backend"
    check_conda; conda activate "${CONDA_ENV}"; cd "${SCRIPT_DIR}"
    log_info "启动 Backend..."
    nohup python -m backend.main > "${LOG_DIR}/backend.log" 2>&1 &
    PID=$!; disown; save_pid backend "$PID"
    for i in {1..60}; do sleep 1; if curl -fs http://127.0.0.1:${BACKEND_PORT}/docs >/dev/null 2>&1; then log_info "Backend 启动成功 (PID=${PID})"; return; fi; done
    log_error "Backend 启动失败"; remove_pid backend
}

start_frontend() {
    PID=$(get_pid frontend)
    if is_pid_running "$PID"; then log_warn "Frontend 已运行 (PID=${PID})"; return; fi
    kill_port ${FRONTEND_PORT} "frontend"
    cd "${SCRIPT_DIR}/frontend/user"
    log_info "启动 Frontend..."
    nohup npm run dev > "${LOG_DIR}/frontend.log" 2>&1 &
    PID=$!; disown; save_pid frontend "$PID"
    for i in {1..30}; do sleep 1; if curl -fs http://127.0.0.1:${FRONTEND_PORT} >/dev/null 2>&1; then log_info "Frontend 启动成功 (PID=${PID})"; return; fi; done
    log_error "Frontend 启动失败"; remove_pid frontend
}

start_vllm() {
    PID=$(get_pid vllm)
    if is_pid_running "$PID"; then log_warn "vLLM 已运行 (PID=${PID})"; return; fi
    kill_port ${VLLM_PORT} "vllm"
    check_conda; conda activate "${CONDA_ENV}"
    GPU_COUNT=$(python -c "import torch; print(torch.cuda.device_count())" 2>/dev/null || echo "1")
    log_info "检测到 ${GPU_COUNT} 张 GPU"
    if [ "$GPU_COUNT" -gt 1 ]; then TP="--tensor-parallel-size ${GPU_COUNT}"; log_info "启用张量并行: ${GPU_COUNT} 张 GPU"; else TP=""; fi
    if [ -n "$QUANTIZATION" ]; then QUANT_ARG="--quantization ${QUANTIZATION}"; else QUANT_ARG=""; fi
    log_info "启动 vLLM..."
    log_info "  模型: ${MODEL_PATH}"
    log_info "  量化: ${QUANTIZATION:-无}"
    log_info "  数据类型: ${DTYPE}"
    log_info "  GPU 利用率: ${GPU_MEMORY_UTILIZATION}"
    log_info "  最大长度: ${MAX_MODEL_LEN}"
    log_info "  最大并发: ${MAX_NUM_SEQS}"
    nohup python -m vllm.entrypoints.openai.api_server \
        --model "${MODEL_PATH}" \
        --served-model-name "${MODEL_NAME}" \
        --host 0.0.0.0 \
        --port ${VLLM_PORT} \
        --dtype ${DTYPE} \
        --gpu-memory-utilization ${GPU_MEMORY_UTILIZATION} \
        --max-model-len ${MAX_MODEL_LEN} \
        --max-num-seqs ${MAX_NUM_SEQS} \
        --enforce-eager \
        ${QUANT_ARG} \
        ${TP} \
        > "${LOG_DIR}/vllm.log" 2>&1 &
    PID=$!; disown; save_pid vllm "$PID"
    for i in {1..120}; do
        sleep 2
        if curl -fs http://127.0.0.1:${VLLM_PORT}/v1/models >/dev/null 2>&1; then log_info "vLLM 启动成功 (PID=${PID})"; return; fi
        if ! is_pid_running "$PID"; then log_error "vLLM 进程已退出，查看日志: ${LOG_DIR}/vllm.log"; remove_pid vllm; return; fi
    done
    log_error "vLLM 启动超时，查看日志: ${LOG_DIR}/vllm.log"; remove_pid vllm
}

status() {
    echo "========== 服务状态 =========="
    for svc in backend frontend vllm; do
        PID=$(get_pid "$svc")
        if is_pid_running "$PID"; then echo -e "${svc}: ${GREEN}运行中${NC} PID=${PID}"
        else echo -e "${svc}: ${RED}未运行${NC}"; fi
    done
    echo "=============================="
}

case "${1:-start}" in
    start) cleanup_all; start_vllm; start_backend; start_frontend; status ;;
    stop) cleanup_all; log_info "所有服务已停止" ;;
    restart) cleanup_all; sleep 2; start_vllm; start_backend; start_frontend; status ;;
    status) status ;;
    backend) kill_port ${BACKEND_PORT} "backend"; start_backend ;;
    frontend) kill_port ${FRONTEND_PORT} "frontend"; start_frontend ;;
    vllm) kill_port ${VLLM_PORT} "vllm"; start_vllm ;;
    *) echo "用法: ./start.sh {start|stop|restart|status|backend|frontend|vllm}"; exit 1 ;;
esac
