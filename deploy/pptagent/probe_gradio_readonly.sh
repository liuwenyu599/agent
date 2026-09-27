#!/usr/bin/env bash
# =============================================================================
# PPTAgent Gradio 契约「只读」探查脚本
#
# 用途：后端无法直接访问 7861 时，由运维在 **PPTAgent 宿主机** 上执行本脚本，
#       把输出的 gradio_api_probe.txt 发回给开发，用于校准后端客户端配置。
#
# ⚠️ 安全声明（重要）
#   本脚本**全部为只读操作**：GET 请求 + ls + docker ps/inspect/logs。
#   - 不 POST 任何端点，因此**不会触发任何生成任务**（一次生成 5~15 分钟且占 GPU，
#     会影响同服务器其他人）；
#   - 不 start/stop/rm/restart 任何容器，不写任何业务文件（只在 /tmp 下写结果）。
#   请勿自行追加 curl -X POST 去"试试看能不能生成"。
#
# 用法：
#   bash probe_gradio_readonly.sh                 # 在 PPTAgent 宿主机上执行
#   bash probe_gradio_readonly.sh 192.168.68.51   # 或指定别的地址
# =============================================================================
set -u

HOST="${1:-127.0.0.1}"
PORT="${2:-7861}"
BASE="http://${HOST}:${PORT}"
OUT="/tmp/gradio_api_probe.txt"

: > "$OUT"

log() { echo "$*" | tee -a "$OUT"; }
hr()  { echo "------------------------------------------------------------" | tee -a "$OUT"; }

log "PPTAgent Gradio 契约只读探查"
log "时间: $(date)"
log "目标: ${BASE}"
log ""

# ---------------------------------------------------------------- 1. 容器状态
hr
log "[1] 容器与网络（只读）"
log ""
docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}' 2>&1 | tee -a "$OUT"
log ""
log "-- justice-ppt-host 的挂载（判断产物落在宿主机哪个目录）--"
docker inspect -f '{{range .Mounts}}{{.Source}} => {{.Destination}} ({{.Mode}})
{{end}}' justice-ppt-host 2>&1 | tee -a "$OUT"
log ""
log "-- 网络 --"
docker network ls 2>&1 | tee -a "$OUT"
log ""

# ---------------------------------------------------------------- 2. 根页面
hr
log "[2] GET / （Gradio 根页面，读 window.gradio_config）"
ROOT_HTTP=$(curl -s -m 20 -o /tmp/gradio_root.html -w "%{http_code}" "${BASE}/")
log "HTTP ${ROOT_HTTP}  大小: $(wc -c < /tmp/gradio_root.html 2>/dev/null) 字节"
log ""

# ------------------------------------------------- 3. 可能存在的 API 描述端点
hr
log "[3] 尝试 Gradio/FastAPI 的自描述端点（全部为 GET，安全）"
for P in "/gradio_api/info" "/info" "/openapi.json" "/gradio_api/openapi.json" "/docs" "/gradio_api/schema"; do
    CODE=$(curl -s -m 15 -o "/tmp/probe$(echo "$P" | tr '/' '_')" -w "%{http_code}" "${BASE}${P}")
    SIZE=$(wc -c < "/tmp/probe$(echo "$P" | tr '/' '_')" 2>/dev/null)
    log "  ${P} -> HTTP ${CODE} (${SIZE} 字节)"
done
log ""
log "-- /gradio_api/info 前 2000 字符（若上面是 200）--"
head -c 2000 /tmp/probe_gradio_api_info 2>/dev/null | tee -a "$OUT"
log ""

# ------------------------------------------------------- 4. 解析依赖（最关键）
hr
log "[4] 函数入口（api_name / 入参 / 出参 / 是否 queue）—— 后端最需要这一段"
python3 - <<'PY' 2>&1 | tee -a /tmp/gradio_api_probe.txt
import json, re, sys

try:
    html = open('/tmp/gradio_root.html', encoding='utf-8', errors='replace').read()
except Exception as e:
    print("无法读取根页面:", e)
    sys.exit(0)

m = re.search(r'window\.gradio_config\s*=\s*(\{.*?\})\s*;?\s*(?:</script>|$)', html, re.S)
if not m:
    print("未在页面中找到 window.gradio_config")
    print("（可能是新版 Gradio 改为异步加载，请手工在浏览器 DevTools 里搜 gradio_config）")
    sys.exit(0)

try:
    cfg = json.loads(m.group(1))
except Exception as e:
    print("gradio_config 解析失败:", e)
    sys.exit(0)

print("root:", cfg.get('root'))
print("version:", cfg.get('version'))
deps = cfg.get('dependencies') or []
print("dependencies 数量:", len(deps))
print()
for i, d in enumerate(deps):
    ins = d.get('inputs') or []
    outs = d.get('outputs') or []
    print(f"--- [{i}] api_name={d.get('api_name')!r}  id={d.get('id')!r}")
    print(f"      queue={d.get('queue')!r}  show_progress={d.get('show_progress')!r} "
          f"batch={d.get('batch')!r}  cancels={d.get('cancels')!r}")
    print(f"      inputs ({len(ins)}): {[x.get('id') for x in ins]}")
    print(f"      outputs({len(outs)}): "
          f"{[(x.get('id'), (x.get('type') or {}).get('type')) for x in outs]}")
    print(f"      targets: {d.get('targets')}")
print()
print("提示：后端需要的是「接收需求文本 + 返回文件」的那个入口的 api_name，")
print("      以及它是否 queue=True（queue=True 就要走 /gradio_api/queue/join）。")
PY
log ""

# ------------------------------------------------------------ 5. 产物目录结构
hr
log "[5] 产物目录结构（只读 ls，用于确认 workspace 布局与文件名）"
WS_DEFAULT="/data/pptagent/workspace"
if [ -d "$WS_DEFAULT" ]; then
    log "工作区: ${WS_DEFAULT}"
    ls -la "$WS_DEFAULT" 2>&1 | tee -a "$OUT"
    log ""
    LAST=$(ls -1t "$WS_DEFAULT" 2>/dev/null | head -1)
    if [ -n "$LAST" ]; then
        log "最新日期目录: ${LAST}"
        ls -la "${WS_DEFAULT}/${LAST}" 2>&1 | tee -a "$OUT"
        JOB=$(ls -1t "${WS_DEFAULT}/${LAST}" 2>/dev/null | head -1)
        if [ -n "$JOB" ]; then
            log "最新 job 目录: ${JOB}"
            ls -laR "${WS_DEFAULT}/${LAST}/${JOB}" 2>&1 | head -60 | tee -a "$OUT"
        fi
    fi
else
    log "默认工作区 ${WS_DEFAULT} 不存在，搜索产物目录（文件名随标题动态变化，用 *.pptx）："
    timeout 60 find /data -maxdepth 7 -name '*.pptx' -printf '%p  %s字节  %TY-%Tm-%Td %TH:%TM\n' 2>/dev/null | head -20 | tee -a "$OUT"
fi
log ""

# ------------------------------------------------------------ 6. 容器日志尾巴
hr
log "[6] justice-ppt-host 最近日志（只读，找 API 路径与产物路径线索）"
docker logs --tail 60 justice-ppt-host 2>&1 | tee -a "$OUT"
log ""

hr
log "完成。请把本文件发给开发： ${OUT}"
log "（若担心敏感信息，可先手工删掉 [6] 段与 IP 相关行）"
