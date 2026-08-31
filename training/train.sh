#!/usr/bin/env bash
# 司法AI 模型训练一键脚本
# 用法: ./training/train.sh <prepare|lora|qlora|test>

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# 颜色
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

show_help() {
    echo "司法AI 模型训练脚本"
    echo ""
    echo "用法: $0 <命令> [选项]"
    echo ""
    echo "命令:"
    echo "  prepare   数据预处理"
    echo "  lora      LoRA 训练（7B 推荐）"
    echo "  qlora     QLoRA 训练（14B 推荐）"
    echo "  test      最小训练测试（快速验证环境）"
    echo ""
    echo "示例:"
    echo "  $0 prepare --input training/data/raw/data.jsonl --output-dir training/data/processed"
    echo "  $0 lora --model /home/lwy/Qwen2.5-7B-Instruct --output-dir training/outputs/judicial-lora"
    echo "  $0 qlora --model /home/lwy/Qwen2.5-14B-Instruct --output-dir training/outputs/judicial-qlora"
    echo "  $0 test"
}

log_info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# 检查 Python 依赖
check_deps() {
    local deps="torch transformers peft datasets accelerate bitsandbytes"
    for dep in $deps; do
        if ! python3 -c "import $dep" 2>/dev/null; then
            log_error "缺少依赖: $dep"
            log_info "尝试安装: pip install $dep"
            exit 1
        fi
    done
    log_info "依赖检查通过"
}

# 数据预处理
cmd_prepare() {
    local input_file=""
    local output_dir="$SCRIPT_DIR/data/processed"
    local val_ratio=0.1
    local seed=42

    while [[ $# -gt 0 ]]; do
        case $1 in
            --input) input_file="$2"; shift 2 ;;
            --output-dir) output_dir="$2"; shift 2 ;;
            --val-ratio) val_ratio="$2"; shift 2 ;;
            --seed) seed="$2"; shift 2 ;;
            *) shift ;;
        esac
    done

    if [[ -z "$input_file" ]]; then
        log_error "请指定 --input 参数"
        exit 1
    fi

    log_info "开始数据预处理 ..."
    python3 "$SCRIPT_DIR/scripts/prepare_dataset.py" \
        --input "$input_file" \
        --output-dir "$output_dir" \
        --val-ratio "$val_ratio" \
        --seed "$seed"
}

# LoRA 训练
cmd_lora() {
    local model="/home/lwy/Qwen2.5-7B-Instruct"
    local train_file="$SCRIPT_DIR/data/processed/train.jsonl"
    local val_file="$SCRIPT_DIR/data/processed/val.jsonl"
    local output_dir="$SCRIPT_DIR/outputs/judicial-lora"
    local epochs=3
    local batch_size=1
    local grad_acc=8
    local lr=2e-4
    local max_length=2048
    local lora_r=64
    local lora_alpha=128
    local lora_dropout=0.05
    local adapter_path=""

    while [[ $# -gt 0 ]]; do
        case $1 in
            --model) model="$2"; shift 2 ;;
            --train-file) train_file="$2"; shift 2 ;;
            --val-file) val_file="$2"; shift 2 ;;
            --output-dir) output_dir="$2"; shift 2 ;;
            --adapter-path) adapter_path="$2"; shift 2 ;;
            --epochs) epochs="$2"; shift 2 ;;
            --batch-size) batch_size="$2"; shift 2 ;;
            --gradient-accumulation) grad_acc="$2"; shift 2 ;;
            --learning-rate) lr="$2"; shift 2 ;;
            --max-length) max_length="$2"; shift 2 ;;
            --lora-r) lora_r="$2"; shift 2 ;;
            --lora-alpha) lora_alpha="$2"; shift 2 ;;
            --lora-dropout) lora_dropout="$2"; shift 2 ;;
            *) shift ;;
        esac
    done

    if [[ ! -f "$train_file" ]]; then
        log_error "训练文件不存在: $train_file"
        log_info "请先运行: $0 prepare --input <raw_data.jsonl>"
        exit 1
    fi

    log_info "开始 LoRA 训练 ..."
    log_info "模型: $model"
    log_info "输出: $output_dir"

    local extra_args=()
    if [[ -n "$adapter_path" ]]; then
        extra_args+=(--adapter-path "$adapter_path")
    fi

    python3 "$SCRIPT_DIR/scripts/train_lora.py" \
        --model "$model" \
        --train-file "$train_file" \
        --val-file "$val_file" \
        --output-dir "$output_dir" \
        --epochs "$epochs" \
        --batch-size "$batch_size" \
        --gradient-accumulation "$grad_acc" \
        --learning-rate "$lr" \
        --max-length "$max_length" \
        --lora-r "$lora_r" \
        --lora-alpha "$lora_alpha" \
        --lora-dropout "$lora_dropout" \
        "${extra_args[@]}"
}

# QLoRA 训练
cmd_qlora() {
    local model="/home/lwy/Qwen2.5-14B-Instruct"
    local train_file="$SCRIPT_DIR/data/processed/train.jsonl"
    local val_file="$SCRIPT_DIR/data/processed/val.jsonl"
    local output_dir="$SCRIPT_DIR/outputs/judicial-qlora"
    local epochs=3
    local batch_size=1
    local grad_acc=8
    local lr=1e-4
    local max_length=2048
    local lora_r=64
    local lora_alpha=16
    local lora_dropout=0.05
    local adapter_path=""

    while [[ $# -gt 0 ]]; do
        case $1 in
            --model) model="$2"; shift 2 ;;
            --train-file) train_file="$2"; shift 2 ;;
            --val-file) val_file="$2"; shift 2 ;;
            --output-dir) output_dir="$2"; shift 2 ;;
            --adapter-path) adapter_path="$2"; shift 2 ;;
            --epochs) epochs="$2"; shift 2 ;;
            --batch-size) batch_size="$2"; shift 2 ;;
            --gradient-accumulation) grad_acc="$2"; shift 2 ;;
            --learning-rate) lr="$2"; shift 2 ;;
            --max-length) max_length="$2"; shift 2 ;;
            --lora-r) lora_r="$2"; shift 2 ;;
            --lora-alpha) lora_alpha="$2"; shift 2 ;;
            --lora-dropout) lora_dropout="$2"; shift 2 ;;
            *) shift ;;
        esac
    done

    if [[ ! -f "$train_file" ]]; then
        log_error "训练文件不存在: $train_file"
        exit 1
    fi

    log_info "开始 QLoRA 训练 ..."
    log_info "模型: $model"
    log_info "输出: $output_dir"

    local extra_args=()
    if [[ -n "$adapter_path" ]]; then
        extra_args+=(--adapter-path "$adapter_path")
    fi

    python3 "$SCRIPT_DIR/scripts/train_qlora.py" \
        --model "$model" \
        --train-file "$train_file" \
        --val-file "$val_file" \
        --output-dir "$output_dir" \
        --epochs "$epochs" \
        --batch-size "$batch_size" \
        --gradient-accumulation "$grad_acc" \
        --learning-rate "$lr" \
        --max-length "$max_length" \
        --lora-r "$lora_r" \
        --lora-alpha "$lora_alpha" \
        --lora-dropout "$lora_dropout" \
        "${extra_args[@]}"
}

# 最小测试
cmd_test() {
    log_info "运行最小训练测试（验证环境）..."

    local test_dir="$SCRIPT_DIR/outputs/test-run"
    mkdir -p "$test_dir"

    # 创建 10 条测试数据
    cat > "$test_dir/test_data.jsonl" <<'EOF'
{"messages":[{"role":"user","content":"写一份通知"},{"role":"assistant","content":"通知内容"}]}
{"messages":[{"role":"user","content":"写一份报告"},{"role":"assistant","content":"报告内容"}]}
{"messages":[{"role":"user","content":"写一份请示"},{"role":"assistant","content":"请示内容"}]}
{"messages":[{"role":"user","content":"写一份批复"},{"role":"assistant","content":"批复内容"}]}
{"messages":[{"role":"user","content":"写一份函"},{"role":"assistant","content":"函内容"}]}
{"messages":[{"role":"user","content":"写一份纪要"},{"role":"assistant","content":"纪要内容"}]}
{"messages":[{"role":"user","content":"写一份决定"},{"role":"assistant","content":"决定内容"}]}
{"messages":[{"role":"user","content":"写一份意见"},{"role":"assistant","content":"意见内容"}]}
{"messages":[{"role":"user","content":"写一份方案"},{"role":"assistant","content":"方案内容"}]}
{"messages":[{"role":"user","content":"写一份总结"},{"role":"assistant","content":"总结内容"}]}
EOF

    log_info "测试数据已创建: $test_dir/test_data.jsonl"

    # 这里只是验证脚本能正常启动，不实际运行训练（避免下载大模型）
    log_info "环境验证完成。如需实际测试训练，请运行:"
    log_info "  $0 lora --model <模型路径> --train-file $test_dir/test_data.jsonl --val-file $test_dir/test_data.jsonl --output-dir $test_dir/lora --epochs 1"
}

# 主入口
main() {
    if [[ $# -eq 0 ]]; then
        show_help
        exit 0
    fi

    local cmd="$1"
    shift

    case "$cmd" in
        prepare) cmd_prepare "$@" ;;
        lora) check_deps; cmd_lora "$@" ;;
        qlora) check_deps; cmd_qlora "$@" ;;
        test) cmd_test "$@" ;;
        help|--help|-h) show_help ;;
        *)
            log_error "未知命令: $cmd"
            show_help
            exit 1
            ;;
    esac
}

main "$@"