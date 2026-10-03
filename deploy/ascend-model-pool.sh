#!/usr/bin/env bash
set -euo pipefail

# Ascend multi-instance launcher for backlog item 8.
#
# Known spare devices for the target host: 0,1,5,6,7.  We deliberately do NOT
# guess which devices the already-running primary 14B / DeepPresenter services
# occupy.  This helper only uses the spare set and is dry-run by default.
#
# Examples:
#   ./deploy/ascend-model-pool.sh second-14b
#   APPLY=1 VLLM_BIN=/opt/venv/bin/vllm ./deploy/ascend-model-pool.sh second-14b
#   APPLY=1 ./deploy/ascend-model-pool.sh ppt-replica
#
# Override every path/port/device assignment through env when the production
# topology differs.  A profile never mixes different model names in one URL pool.

PROFILE=${1:-plan}
APPLY=${APPLY:-0}
VLLM_BIN=${VLLM_BIN:-vllm}
LOG_DIR=${MODEL_POOL_LOG_DIR:-/opt/justice-office/data/model-logs}

TEXT_MODEL_PATH=${TEXT_MODEL_PATH:-/home/lcode/Qwen2.5-14B-Instruct}
TEXT_MODEL_NAME=${TEXT_MODEL_NAME:-Qwen2.5-14B-Instruct}
TEXT_REPLICA_DEVICES=${TEXT_REPLICA_DEVICES:-0,1}
TEXT_REPLICA_PORT=${TEXT_REPLICA_PORT:-8005}
TEXT_TP_SIZE=${TEXT_TP_SIZE:-2}
TEXT_MAX_MODEL_LEN=${TEXT_MAX_MODEL_LEN:-16384}

PPT_MODEL_PATH=${PPT_MODEL_PATH:-/home/lcode/DeepPresenter-9B}
PPT_MODEL_NAME=${PPT_MODEL_NAME:-DeepPresenter-9B}
PPT_REPLICA_DEVICES=${PPT_REPLICA_DEVICES:-5,6}
PPT_REPLICA_PORT=${PPT_REPLICA_PORT:-8006}
PPT_TP_SIZE=${PPT_TP_SIZE:-2}
PPT_MAX_MODEL_LEN=${PPT_MAX_MODEL_LEN:-16384}

# Device 7 is intentionally left available by the defaults for a vision model,
# a third replica, or emergency capacity.  It may be assigned explicitly by
# overriding *_DEVICES after checking npu-smi on the target host.
KNOWN_SPARE_DEVICES=${KNOWN_SPARE_DEVICES:-0,1,5,6,7}

contains_only_spares() {
  local csv=$1 item
  IFS=',' read -ra parts <<< "$csv"
  IFS=',' read -ra spare <<< "$KNOWN_SPARE_DEVICES"
  for item in "${parts[@]}"; do
    local ok=0 s
    for s in "${spare[@]}"; do
      if [[ "$item" == "$s" ]]; then ok=1; break; fi
    done
    if [[ $ok -ne 1 ]]; then
      echo "ERROR: device $item is outside KNOWN_SPARE_DEVICES=$KNOWN_SPARE_DEVICES" >&2
      return 1
    fi
  done
}

check_port_free() {
  local port=$1
  if command -v ss >/dev/null 2>&1 && ss -tln 2>/dev/null | grep -Eq ":${port}[[:space:]]"; then
    echo "ERROR: port $port is already listening; refusing to start" >&2
    return 1
  fi
}

print_pool_env() {
  cat <<EOF
# Put these values in the backend production .env only after /v1/models probes pass.
MODEL_SERVICE_URLS=http://10.128.85.133:8003/v1,http://10.128.85.133:${TEXT_REPLICA_PORT}/v1
PPT_MODEL_URLS=http://10.128.85.133:8004/v1,http://10.128.85.133:${PPT_REPLICA_PORT}/v1
EOF
}

launch() {
  local label=$1 devices=$2 port=$3 tp=$4 model_path=$5 model_name=$6 max_len=$7
  contains_only_spares "$devices"
  check_port_free "$port"
  local cmd=("$VLLM_BIN" serve "$model_path"
    --served-model-name "$model_name"
    --host 0.0.0.0
    --port "$port"
    --tensor-parallel-size "$tp"
    --max-model-len "$max_len")

  echo "[$label] devices=$devices port=$port tp=$tp model=$model_path"
  printf 'ASCEND_RT_VISIBLE_DEVICES=%q ' "$devices"
  printf '%q ' "${cmd[@]}"
  echo

  if [[ "$APPLY" != "1" ]]; then
    echo "DRY-RUN: set APPLY=1 after npu-smi/port checks to start this replica."
    return 0
  fi
  mkdir -p "$LOG_DIR"
  local logfile="$LOG_DIR/${label}-${port}.log"
  echo "Starting $label; log=$logfile"
  nohup env ASCEND_RT_VISIBLE_DEVICES="$devices" "${cmd[@]}" >"$logfile" 2>&1 &
  echo $! >"$LOG_DIR/${label}-${port}.pid"
}

case "$PROFILE" in
  plan)
    echo "Known spare Ascend devices: $KNOWN_SPARE_DEVICES"
    echo "Default second-14B allocation: devices=$TEXT_REPLICA_DEVICES port=$TEXT_REPLICA_PORT"
    echo "Default DeepPresenter replica allocation: devices=$PPT_REPLICA_DEVICES port=$PPT_REPLICA_PORT"
    echo "Device 7 remains unassigned by default."
    print_pool_env
    ;;
  second-14b)
    launch second-14b "$TEXT_REPLICA_DEVICES" "$TEXT_REPLICA_PORT" "$TEXT_TP_SIZE" \
      "$TEXT_MODEL_PATH" "$TEXT_MODEL_NAME" "$TEXT_MAX_MODEL_LEN"
    ;;
  ppt-replica)
    launch ppt-replica "$PPT_REPLICA_DEVICES" "$PPT_REPLICA_PORT" "$PPT_TP_SIZE" \
      "$PPT_MODEL_PATH" "$PPT_MODEL_NAME" "$PPT_MAX_MODEL_LEN"
    ;;
  both)
    launch second-14b "$TEXT_REPLICA_DEVICES" "$TEXT_REPLICA_PORT" "$TEXT_TP_SIZE" \
      "$TEXT_MODEL_PATH" "$TEXT_MODEL_NAME" "$TEXT_MAX_MODEL_LEN"
    launch ppt-replica "$PPT_REPLICA_DEVICES" "$PPT_REPLICA_PORT" "$PPT_TP_SIZE" \
      "$PPT_MODEL_PATH" "$PPT_MODEL_NAME" "$PPT_MAX_MODEL_LEN"
    ;;
  env)
    print_pool_env
    ;;
  *)
    echo "usage: $0 {plan|second-14b|ppt-replica|both|env}" >&2
    exit 2
    ;;
esac
