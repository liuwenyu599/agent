#!/usr/bin/env bash
#
# test-qwen35b.sh — 35B 评估实例冒烟测试（模型列表 + 流式首 token 时延 + 公文生成质量抽样）
#
# 用法:
#   ./test-qwen35b.sh                                  # 默认 1 次公文生成
#   QWEN35B_N=3 ./test-qwen35b.sh                     # 生成 3 次
#   QWEN35B_PROMPT="自定义提示词" ./test-qwen35b.sh
#   BASE_URL=http://10.128.85.133:8010 ./test-qwen35b.sh
set -euo pipefail

BASE_URL="${QWEN35B_BASE_URL:-http://127.0.0.1:8010}"
MODEL="${QWEN35B_MODEL:-Qwen3.6-35B-A3B-W8A8}"
N="${QWEN35B_N:-1}"
PROMPT="${QWEN35B_PROMPT:-请起草一段关于“加强社区矫正对象教育帮扶”的工作通知开头，要求正式、简洁，200字以内。}"

echo "===== 1) 模型列表探测 ====="
curl -fsS --max-time 10 "$BASE_URL/v1/models" | head -c 400 || { echo "无法连接 $BASE_URL"; exit 1; }
echo; echo

echo "===== 2) 流式首 token 时延探测（已关闭思考）====="
# 用流式输出观察首字节到达时间（不精确计时，仅作直观判断）。
# 裸端点直连需显式传 chat_template_kwargs 关闭思考；后端生产路径已在 qwen.py 请求级默认关闭。
curl -sN -X POST "$BASE_URL/v1/chat/completions" \
  -H 'Content-Type: application/json' \
  -d "{\"model\":\"$MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"你好，请用一句话介绍你自己。\"}],\"stream\":true,\"max_tokens\":64,\"chat_template_kwargs\":{\"enable_thinking\":false}}" \
  --max-time 120 | head -c 200
echo; echo

echo "===== 3) 公文生成抽样（$N 次）====="
if ! command -v python3 >/dev/null 2>&1; then
  echo "ERROR: 需要 python3 做请求与计时（服务端一般已具备）" >&2; exit 1
fi

python3 - "$BASE_URL" "$MODEL" "$N" "$PROMPT" <<'PY'
import sys, time, urllib.request, json
base, model, n, prompt = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4]

def chat():
    # 裸端点直连：显式关闭思考，避免 35B 这类思考模型在正文里输出 CoT。
    # 后端生产路径已在 qwen.py 的 long_form 网关默认带此参数。
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 512,
        "temperature": 0.3,
        "chat_template_kwargs": {"enable_thinking": False},
    }).encode()
    req = urllib.request.Request(
        base + "/v1/chat/completions",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=120) as r:
        t1 = time.time()
        data = json.load(r)
    return data, t1 - t0

for i in range(1, n + 1):
    print(f"---- 请求 {i} ----")
    try:
        data, dt = chat()
        print(f"端到端耗时: {dt:.2f}s")
        msg = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        print(f"输出字数(近似): {len(msg)}   usage={usage}")
        # 思考泄漏检测：若正文混入了 CoT，说明 enable_thinking 没生效
        leak = ("here's a thinking process" in msg.lower()
                or "<think>" in msg.lower() or "思考过程" in msg)
        if leak:
            print("⚠ 警告：检测到思考内容泄漏到正文，enable_thinking=false 未生效，请检查模型/框架版本")
        print(msg)
    except Exception as e:
        print("请求失败:", e)
        sys.exit(1)
    print()
PY

echo "===== 完成 ====="
echo "如需与 14B 对比质量门通过率，把同批公文请求分别打 :8003(14B) 与 :8010(35B) 后人工比对。"
