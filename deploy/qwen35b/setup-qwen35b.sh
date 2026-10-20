#!/usr/bin/env bash
#
# setup-qwen35b.sh — 在昇腾 310P 上拉起 Qwen3.6-35B-A3B-W8A8 评估实例（不替换生产 14B）
#
# 场景：私有化部署，政务内网离网。作为独立评估实例验证 35B MoE 在 310P 上的质量/速度。
#
# 用法（在 310P 生产服务器上执行）:
#   ./setup-qwen35b.sh                                   # 自动探测 4 张空闲卡并启动
#   QWEN35B_DEVICES=2,4,6,7 ./setup-qwen35b.sh          # 手动指定 4 张卡（仍会校验未被生产占用）
#   DRY_RUN=1 ./setup-qwen35b.sh                         # 只打印将要执行的命令，不真正启动
#
# ⚠ 前置:
#   1) 权重已在 $MODEL_DIR_HOST/$MODEL_SUBDIR（见 runbook 第 1 节离线搬运）
#   2) 镜像 vllm-ascend:v0.23.0-310p 已 docker load（见 runbook 第 2 节，离线搬运）
#
# 关键参数（310P 缺一不可）:
#   --enforce-eager / --mamba-ssm-cache-dtype float16 / --no-enable-prefix-caching
#   TP 默认 4；不指定 --quantization（W8A8 由权重 config.json 自动识别）
#
# ⚠ 关于「思考(Thinking)」关闭：Qwen3.6-35B-A3B 是原生思考模型，若不关闭会在正文中输出
#   CoT（形如 "Here's a thinking process..."），既浪费 token 又拖慢速度。关闭方式：
#   1) 生产路径（后端）：已在 server 的 long_form 网关默认带 chat_template_kwargs:{enable_thinking:false}
#      （见 qwen.py 的 extra_body + ai/__init__.py get_long_form_gateway）。无需改本脚本。
#   2) 裸端点直连（无后端）：用 test-qwen35b.sh 的 curl 已带该参数验证；若要让本容器对所有直连
#      默认关闭思考，可在 vllm serve 加 --chat-template 指向关闭思考的 jinja 模板（默认未启用，
#      以免模板与 Qwen3.6 结构差异导致容器启动失败——这是比「思考没关」更严重的故障）。
#      优先级：优先依赖后端请求级关闭；裸端点关闭属可选增强。
set -euo pipefail

CONTAINER_NAME="${CONTAINER_NAME:-justice-qwen35b-w8a8}"
MODEL_DIR_HOST="${MODEL_DIR_HOST:-/opt/justice-office/models}"
MODEL_SUBDIR="${MODEL_SUBDIR:-qwen35b-a3b-w8a8}"
SERVED_MODEL="${SERVED_MODEL:-Qwen3.6-35B-A3B-W8A8}"
IMAGE="${QWEN35B_IMAGE:-m.daocloud.io/quay.io/ascend/vllm-ascend:v0.23.0-310p}"
PORT="${QWEN35B_PORT:-8010}"
TP_SIZE="${QWEN35B_TP:-4}"
MAX_MODEL_LEN="${QWEN35B_MAX_LEN:-8192}"
MAX_NUM_SEQS="${QWEN35B_MAX_SEQS:-8}"
GPU_MEM_UTIL="${QWEN35B_GPU_UTIL:-0.92}"
DRY_RUN="${DRY_RUN:-0}"

# 从 npu-smi 进程表解析“忙”的芯片号（被某进程占用的卡）
# 注意：进程表“Process information”标题后紧跟一条 +=== 分隔线，
# 不能在此时重置状态，否则会跳过真实数据行；用 seen 计数只在已读到数据行后才结束。
busy_from_npu() {
  npu-smi info 2>/dev/null | awk '
    /Process information/ { p=1; next }
    p && /^[-+]/ { if (seen > 0) p=0; next }
    p && $0 ~ /^[|][ \t]*[0-9]+[ \t]*\|/ {
      split($0, a, "|")
      d=a[2]; gsub(/[ \t]/, "", d)
      if (d ~ /^[0-9]+$/) { print d; seen++ }
    }'
}

# 从其它运行中容器解析已挂载的 davinci 芯片号（避免与生产实例争卡）
busy_from_docker() {
  docker ps -q 2>/dev/null | while read -r c; do
    [ -n "$c" ] || continue
    docker inspect -f '{{range .HostConfig.Devices}}{{.PathOnHost}} {{end}}' "$c" 2>/dev/null
  done | grep -oE 'davinci[0-9]+' | sed 's/davinci//' | sort -u
}

all_chips() {
  # 8×310P3 主机，芯片号 0..7；如主机拓扑不同请用 QWEN35B_DEVICES 显式指定
  local i
  for i in 0 1 2 3 4 5 6 7; do echo "$i"; done
}

# 自动挑 tp 张空闲卡；不足则 abort 并提示
detect_free_chips() {
  local tp=${1:-4}
  local busy
  busy="$( { busy_from_npu; busy_from_docker; } | sort -u | grep -E '^[0-9]+$' )"
  local free=() c
  for c in $(all_chips); do
    if ! echo "$busy" | grep -qx "$c"; then free+=("$c"); fi
  done
  if [ "${#free[@]}" -lt "$tp" ]; then
    echo "ERROR: 空闲芯片不足，需要 $tp 张，仅空闲: ${free[*]:-无}" >&2
    echo "       生产 14B / DeepPresenter 占用的卡（勿动）: $(echo "$busy" | tr '\n' ' ')" >&2
    echo "       可暂停非必要副本释放卡后再试（second-14b 占 0,1 / ppt-replica 占 5,6）" >&2
    return 1
  fi
  printf '%s\n' "${free[@]:0:tp}" | paste -sd, -
}

# 解析最终使用哪 4 张卡（手动指定需校验空闲）
resolve_chips() {
  if [ -n "${QWEN35B_DEVICES:-}" ]; then
    local busy
    busy="$( { busy_from_npu; busy_from_docker; } | sort -u | grep -E '^[0-9]+$' )"
    local c
    for c in $(echo "$QWEN35B_DEVICES" | tr ',' ' '); do
      if echo "$busy" | grep -qx "$c"; then
        echo "ERROR: 指定卡 $c 当前被占用（生产服务），请改选空闲卡或先停对应服务" >&2
        return 1
      fi
    done
    echo "$QWEN35B_DEVICES"
  else
    detect_free_chips "$TP_SIZE"
  fi
}

main() {
  echo "== 1/5 预检权重 =="
  local model_path="$MODEL_DIR_HOST/$MODEL_SUBDIR"
  [ -d "$model_path" ] || {
    echo "ERROR: 权重目录不存在: $model_path" >&2
    echo "       请先用 runbook 第 1 节把 qwen35b-a3b-w8a8 离线搬运到该路径" >&2
    exit 1
  }
  echo "   权重 OK: $model_path"

  echo "== 2/5 预检镜像 =="
  if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
    echo "   镜像未加载，尝试从离线 tar 恢复..."
    if [ -f /opt/justice-office/vllm-ascend-310p.tar ]; then
      docker load -i /opt/justice-office/vllm-ascend-310p.tar
    else
      echo "ERROR: 镜像 $IMAGE 不存在，且离线 tar 未找到 /opt/justice-office/vllm-ascend-310p.tar" >&2
      echo "       请在能联网的机器按 runbook 第 2 节 docker save 后离线搬运" >&2
      exit 1
    fi
  fi
  echo "   镜像 OK: $IMAGE"

  echo "== 3/5 探测空闲卡（避开生产 14B / DeepPresenter）=="
  local CHIPS
  CHIPS="$(resolve_chips)" || exit 1
  echo "   将使用芯片: $CHIPS (TP=$TP_SIZE)"

  echo "== 4/5 端口与容器冲突检查 =="
  if docker ps -a --format '{{.Names}}' | grep -qx "$CONTAINER_NAME"; then
    echo "   已存在同名容器，先停止并移除: $CONTAINER_NAME"
    docker rm -f "$CONTAINER_NAME" >/dev/null
  fi
  if command -v ss >/dev/null 2>&1 && ss -tln 2>/dev/null | grep -Eq ":$PORT[[:space:]]"; then
    echo "ERROR: 端口 $PORT 已被占用" >&2; exit 1
  fi
  echo "   端口 $PORT 空闲"

  echo "   将占用芯片: $CHIPS (TP=$TP_SIZE)，端口 :$PORT"
  if [ "${AUTO_YES:-0}" != "1" ] && [ "${DRY_RUN:-0}" != "1" ]; then
    read -r -p "确认启动 35B 评估实例？(y/N) " ans
    case "$ans" in
      y|Y) ;;
      *) echo "已取消"; exit 0 ;;
    esac
  fi

  echo "== 5/5 启动容器 =="
  local device_flags=() c
  for c in $(echo "$CHIPS" | tr ',' ' '); do
    device_flags+=(--device "/dev/davinci$c")
  done

  local RUN_CMD=(docker run -d --name "$CONTAINER_NAME"
    --restart unless-stopped --shm-size=8g
    "${device_flags[@]}"
    --device /dev/davinci_manager --device /dev/devmm_svm --device /dev/hisi_hdc
    -v /usr/local/dcmi:/usr/local/dcmi
    -v /usr/local/bin/npu-smi:/usr/local/bin/npu-smi
    -v /usr/local/Ascend/driver/lib64:/usr/local/Ascend/driver/lib64
    -v /usr/local/Ascend/driver/version.info:/usr/local/Ascend/driver/version.info
    -v /etc/ascend_install.info:/etc/ascend_install.info
    -v "$MODEL_DIR_HOST:/models:ro"
    -e "ASCEND_RT_VISIBLE_DEVICES=$CHIPS"
    -e VLLM_USE_MODELSCOPE=False
    -p "$PORT:$PORT"
    "$IMAGE"
    vllm serve "/models/$MODEL_SUBDIR"
      --host 0.0.0.0 --port "$PORT"
      --served-model-name "$SERVED_MODEL"
      --tensor-parallel-size "$TP_SIZE"
      --dtype float16
      --mamba-ssm-cache-dtype float16
      --max-model-len "$MAX_MODEL_LEN"
      --max-num-seqs "$MAX_NUM_SEQS"
      --gpu-memory-utilization "$GPU_MEM_UTIL"
      --enforce-eager
      --no-enable-prefix-caching
      --trust-remote-code)

  if [ "$DRY_RUN" = "1" ]; then
    echo "DRY_RUN: 以下命令未执行:"
    printf '%q ' "${RUN_CMD[@]}"; echo
    return 0
  fi

  "${RUN_CMD[@]}"
  echo "   容器已启动: $CONTAINER_NAME"

  echo "== 等待模型就绪（轮询 /v1/models，最多 20 分钟）=="
  local i=0
  until curl -fsS --max-time 10 "http://127.0.0.1:$PORT/v1/models" 2>/dev/null | grep -q "$SERVED_MODEL"; do
    i=$((i+1))
    if [ "$i" -gt 120 ]; then
      echo "ERROR: 20 分钟内模型未就绪，查看日志: docker logs $CONTAINER_NAME" >&2
      exit 1
    fi
    sleep 10
  done
  echo "   模型已就绪: $SERVED_MODEL @ :$PORT"
  echo "完成。验收: ./check-qwen35b.sh   冒烟测试: ./test-qwen35b.sh"
  echo "回滚: docker rm -f $CONTAINER_NAME （生产 14B 不受影响）"
}

if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  main "$@"
fi
