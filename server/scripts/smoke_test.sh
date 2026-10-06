#!/usr/bin/env bash
# ============================================================================
#  云法智办 · 全功能命令行巡检脚本（无需截图，文本化核查所有功能）
# ============================================================================
#  用法（Git Bash / WSL / Linux 均可）：
#    # 基本（默认连本机 8000，账号 admin）
#    BASE=http://localhost:8000 USERNAME=admin PASSWORD=你的密码 bash smoke_test.sh
#
#    # 指定服务端地址 / 账号，或给格式校验提供样本文件
#    BASE=http://10.x.x.x:8000 USERNAME=admin PASSWORD='xxx' \
#    SAMPLE_DOC=/path/to/sample.docx bash smoke_test.sh
#
#  说明：
#    - 全程只依赖 curl + python（解析 JSON / 抽取 docx 文本），无需 jq。
#    - 每一步都打印原始 JSON，便于你逐项核对。
#    - 写作任务导出 docx 后，自动抽取正文文本并 grep 几个 bug 特征串：
#        ××            （A3：日期占位符未填充）
#        缺少事实依据   （A6：引用标注混进正文）
#        （参考 / [参考 （A6：引用标注）
#      同时检查落款/日期三件套是否齐全。
# ============================================================================
set -uo pipefail

BASE="${BASE:-http://localhost:8000}"
USERNAME="${USERNAME:-admin}"
PASSWORD="${PASSWORD:-请替换为你的管理员密码}"
SAMPLE_DOC="${SAMPLE_DOC:-}"

# 优先用 python3，否则 python
PY="$(command -v python3 || command -v python || echo python)"

echo "============================================================"
echo " 云法智办 全功能巡检  BASE=$BASE   USER=$USERNAME"
echo "============================================================"

# ---------- 1. 登录拿 token ----------
echo
echo "== [1] 登录鉴权 =="
LOGIN_RESP=$(curl -s -X POST "$BASE/api/v1/auth/login" \
  -H "Content-Type: application/json" \
  -d "{\"username\":\"$USERNAME\",\"password\":\"$PASSWORD\"}")
TOKEN=$("$PY" -c 'import sys,json
try:
    d=json.load(sys.stdin)
    print(d.get("access_token",""))
except Exception:
    print("")' <<< "$LOGIN_RESP")
if [ -z "$TOKEN" ]; then
  echo "!! 登录失败，原始响应："; echo "$LOGIN_RESP"; exit 1
fi
echo "token 已获取（前24字符）：${TOKEN:0:24}..."
AUTH="Authorization: Bearer $TOKEN"

# 通用调用 + 美化打印
apij() {
  local method="$1"; local path="$2"; shift 2
  echo "---- $method $path ----"
  curl -s -X "$method" "$BASE$path" -H "$AUTH" "$@" \
    | "$PY" -m json.tool 2>/dev/null || echo "(非 JSON 响应，见上方原始)"
  echo
}

# ---------- 2. 健康检查 + 当前用户 ----------
echo "== [2] 健康检查 / 当前用户 =="
curl -s "$BASE/health"; echo
curl -s "$BASE/ready"; echo
apij GET "/api/v1/auth/me"

# ---------- 3. 模板列表（找「请示」template_id） ----------
echo "== [3] 写作模板列表 =="
TEMPLATES=$(curl -s "$BASE/api/v1/templates/" -H "$AUTH")
echo "$TEMPLATES" | "$PY" -m json.tool 2>/dev/null | head -60
QST_ID="${QST_TEMPLATE_ID:-}"
if [ -z "$QST_ID" ]; then
  QST_ID=$(echo "$TEMPLATES" | "$PY" -c 'import sys,json
try:
    d=json.load(sys.stdin)
except Exception:
    d=[]
items = d.get("items") if isinstance(d,dict) else d
for t in (items or []):
    nm = t.get("name") or ""
    if "请示" in nm:
        print(t.get("id","")); break' 2>/dev/null)
fi
echo "请示模板 ID = ${QST_ID:-<未自动识别，可手动 export QST_TEMPLATE_ID=xxx>}"

# ---------- 4. 用模板创建写作任务（请示） ----------
echo
echo "== [4] 用模板创建写作任务（请示） =="
CREATE_RESP=$(curl -s -X POST "$BASE/api/v1/writing/tasks" \
  -H "$AUTH" -H "Content-Type: application/json" \
  -d "{\"message\":\"帮我写一份关于修缮办公楼顶的请示\",\"template_id\":\"${QST_ID}\",\"planned_context\":{\"title\":\"关于修缮办公楼顶的请示\",\"recipient\":\"广州市白云区司法局\",\"authority\":\"广州市白云区司法局\",\"document_date\":\"2026年10月6日\"}}")
echo "$CREATE_RESP" | "$PY" -m json.tool 2>/dev/null
TASK_ID=$(echo "$CREATE_RESP" | "$PY" -c 'import sys,json
try: d=json.load(sys.stdin)
except Exception: d={}
print(d.get("task_id") or d.get("id") or "")' 2>/dev/null)
echo "TASK_ID = $TASK_ID"

# ---------- 5. 与任务对话（补充要素） ----------
echo
echo "== [5] 任务对话：补充理由/事项 =="
apij POST "/api/v1/writing/tasks/$TASK_ID/chat" \
  -H "Content-Type: application/json" \
  -d '{"message":"理由：楼顶长期漏水影响正常办公。事项：申请专项维修经费。"}'

# ---------- 6. 起草（非流式，直接拿 current_content） ----------
echo "== [6] 起草（非流式） =="
DRAFT_RESP=$(curl -s -X POST "$BASE/api/v1/writing/tasks/$TASK_ID/draft" \
  -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"outline_only":false}')
echo "$DRAFT_RESP" | "$PY" -m json.tool 2>/dev/null | head -80

# 抽取 current_content 做 bug 特征检查（A2/A3/A6）
echo "---- 正文 bug 特征自检（current_content） ----"
printf '%s' "$DRAFT_RESP" > /tmp/draft.json
"$PY" - <<'PYEOF'
import json
try:
    d = json.load(open("/tmp/draft.json", encoding="utf-8"))
except Exception:
    print("无法解析起草响应"); raise SystemExit
body = d.get("current_content") or d.get("content") or ""
print("正文长度:", len(body))
for pat in ["××", "缺少事实依据", "（参考", "[参考", "⚠️", "XXX号"]:
    n = body.count(pat)
    print(f"  含「{pat}」: {n} 次" + ("  <-- 异常，应=0" if n else "  OK"))
# 三件套检查（标题/主送/落款/日期）——注意字段在 task_context 下，不是 context
ctx = d.get("task_context") or d.get("context") or {}
for key in ["title","recipient","authority","document_date"]:
    v = d.get(key) or ctx.get(key) or ""
    print(f"  {key}: {v!r}")
PYEOF

# ---------- 7. 导出 docx 并核查 ----------
echo
echo "== [7] 导出 docx =="
curl -s "$BASE/api/v1/writing/tasks/$TASK_ID/export" -H "$AUTH" -o /tmp/qst_export.docx
if [ -s /tmp/qst_export.docx ]; then
  echo "已保存 /tmp/qst_export.docx ($(wc -c < /tmp/qst_export.docx) 字节)"
  echo "---- docx 正文抽检（抽取文本后 grep 特征串） ----"
  "$PY" - <<'PYEOF'
import sys, re, zipfile, xml.etree.ElementTree as ET
ns="{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
try:
    z=zipfile.ZipFile("/tmp/qst_export.docx")
    xml=z.read("word/document.xml").decode("utf-8", "ignore")
    root=ET.fromstring(xml)
    texts=[t.text or "" for t in root.iter(ns+"t")]
    body="\n".join(texts)
except Exception as e:
    print("docx 解析失败:", e); sys.exit(0)
print("落款/日期三件套是否在文件内：")
for kw in ["广州市白云区司法局","2026年10月6日"]:
    print(f"  含「{kw}」: {body.count(kw)} 次")
for pat in ["××","缺少事实依据","（参考","[参考","⚠️","XXX号"]:
    n=body.count(pat)
    print(f"  含「{pat}」: {n} 次" + ("  <-- 异常，应=0" if n else "  OK"))
PYEOF
else
  echo "!! 导出失败，文件为空"
fi

# ---------- 8. 修订 ----------
echo
echo "== [8] 修订（revise） =="
apij POST "/api/v1/writing/tasks/$TASK_ID/revise" \
  -H "Content-Type: application/json" \
  -d '{"instruction":"把语气改得更正式、更简洁","mode":"revise"}'

# ---------- 9. 格式校验：规则列表 ----------
echo "== [9] 格式校验：规则列表 =="
apij GET "/api/v1/format-check/rules"

# ---------- 10. 规则生成（compile：白话→校验项） ----------
echo "== [10] 规则生成（compile） =="
# target 必须是 VALID_RULE_TARGETS 之一：
#   title / body / heading1 / heading2 / page / signature / date / general / content
apij POST "/api/v1/format-check/rules/compile" \
  -H "Content-Type: application/json" \
  -d '{"target":"heading1","description":"一级标题应使用二号小标宋体，居中排布；正文使用三号仿宋体。"}'

# ---------- 11. 格式校验：上传文件检查（可选） ----------
echo "== [11] 格式校验：上传文件检查 =="
if [ -n "$SAMPLE_DOC" ] && [ -f "$SAMPLE_DOC" ]; then
  apij POST "/api/v1/format-check/check" -F "file=@$SAMPLE_DOC" -F "use_ai=true"
else
  echo "未提供 SAMPLE_DOC，跳过。手动检查命令："
  echo "  curl -X POST \"$BASE/api/v1/format-check/check\" -H \"$AUTH\" -F \"file=@你的文件.docx\" -F \"use_ai=true\""
fi

# ---------- 12. PPT：列出文档 ----------
echo "== [12] PPT：我的文档列表 =="
apij GET "/api/v1/ppt/documents"

# ---------- 13. PPT：新建空白文档 ----------
echo "== [13] PPT：新建空白文档 =="
BLANK=$(curl -s -X POST "$BASE/api/v1/ppt/blank" \
  -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"title":"命令行巡检PPT","subtitle":"自动化验证"}')
echo "$BLANK" | "$PY" -m json.tool 2>/dev/null
DOC_ID=$(echo "$BLANK" | "$PY" -c 'import sys,json
try: d=json.load(sys.stdin)
except Exception: d={}
print(d.get("doc_id") or d.get("id") or "")' 2>/dev/null)
echo "PPT DOC_ID = $DOC_ID"

# ---------- 14. PPT：提交生成任务 ----------
echo
echo "== [14] PPT：提交生成任务 =="
apij POST "/api/v1/ppt/jobs" \
  -H "Content-Type: application/json" \
  -d "{\"doc_id\":\"$DOC_ID\",\"message\":\"生成一份关于社区普法的10页PPT\"}"

# ---------- 15. PPT：轮询状态（最多 30 次，间隔 20s） ----------
echo "== [15] PPT：轮询状态（最长 ~10 分钟） =="
for i in $(seq 1 30); do
  ST=$(curl -s "$BASE/api/v1/ppt/jobs/$DOC_ID/status" -H "$AUTH")
  SHORT=$("$PY" -c 'import sys,json
try:
    d=json.load(sys.stdin)
    print("status=%s phase=%s page=%s/%s renderer=%s elapsed=%ss remain=%s" % (
        d.get("status"), d.get("phase"), d.get("current_page"), d.get("total_pages"),
        d.get("renderer"), d.get("elapsed_seconds"), d.get("estimated_remaining")))
    if d.get("error_msg"): print("   error_msg:", d["error_msg"])
    if d.get("question"): print("   question:", d["question"])
except Exception:
    print("解析失败:", sys.stdin.read()[:120])' <<< "$ST")
  echo "[$i] $SHORT"
  if echo "$ST" | "$PY" -c 'import sys,json
try:
    d=json.load(sys.stdin); s=d.get("status","")
    sys.exit(0 if s in ("finished","failed","error","cancelled") else 1)
except Exception:
    sys.exit(1)' 2>/dev/null; then
    break
  fi
  sleep 20
done

# 轮询结束后给出 renderer 判定（B7：AI 产物是否真的回传）
FINAL=$(curl -s "$BASE/api/v1/ppt/jobs/$DOC_ID/status" -H "$AUTH")
echo "---- 终态判定 ----"
echo "$FINAL" | "$PY" -c 'import sys,json
try:
    d=json.load(sys.stdin)
except Exception:
    print("终态解析失败"); raise SystemExit
st=d.get("status"); rd=(d.get("renderer") or "").strip()
phase=d.get("phase"); cur=d.get("current_page"); tot=d.get("total_pages"); el=d.get("elapsed_seconds")
print("  status=%s  phase=%s  page=%s/%s  elapsed=%ss" % (st, phase, cur, tot, el))
if st in ("finished","succeeded","done"):
    if rd in ("pptagent","pptagent_retry"):
        print("  [OK] 渲染来源 renderer=%s —— 拿到的是 AI 智能设计产物" % rd)
    else:
        print("  [WARN] 渲染来源 renderer=%s —— AI 成品未回传，已回退本地模板渲染（对应 B7）" % (rd or "(空)"))
        print("         客户端现在会显示告警提示；根因见 Design finalize / 双 loop。")
elif st == "failed":
    print("  [FAIL] 任务失败：%s" % d.get("error_msg"))
else:
    print("  [WAIT] 仍在进行/排队（status=%s），未在轮询窗口内收敛" % st)' 2>/dev/null

# ---------- 16. PPT：导出 ----------
echo
echo "== [16] PPT：导出 =="
curl -s "$BASE/api/v1/ppt/documents/$DOC_ID/export" -H "$AUTH" -o /tmp/ppt_export.pptx
if [ -s /tmp/ppt_export.pptx ]; then
  echo "已保存 /tmp/ppt_export.pptx ($(wc -c < /tmp/ppt_export.pptx) 字节)"
else
  echo "导出为空——可能任务尚未 finished 或 PPTAgent 未配置（PPT_AGENT_URL）。"
fi

echo
echo "============================================================"
echo " 巡检完成。写作任务 TASK_ID=$TASK_ID  PPT DOC_ID=$DOC_ID"
echo " 产物：/tmp/qst_export.docx  /tmp/ppt_export.pptx"
echo "============================================================"
