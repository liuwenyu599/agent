#!/usr/bin/env bash
set -euo pipefail

fail() { echo "[FAIL] $*" >&2; exit 1; }
ok() { echo "[ OK ] $*"; }

curl -fsS --max-time 10 http://127.0.0.1:8000/health >/tmp/justice-health.json ||
  fail "API /health 失败"
cat /tmp/justice-health.json
ok "API health"

for p in 8002 8003 8004; do
  curl -fsS --max-time 10 "http://127.0.0.1:$p/v1/models" >/dev/null ||
    fail "模型端口 $p 不可用"
done
ok "三个模型"

code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 10 http://127.0.0.1:7861/ || true)"
[ -n "$code" ] && [ "$code" != "000" ] && [ "${code:0:1}" != "5" ] ||
  fail "PPTAgent 不可用，HTTP=$code"
ok "PPTAgent"

docker exec justice-api sh -c '
  set -e
  test "$PPT_AGENT_WORKSPACE_DIR" = "/data/pptagent"
  test -d /data/pptagent
' || fail "API 容器 PPTAgent workspace 配置错误"
ok "API workspace"

font_count="$(docker exec justice-api sh -c 'fc-list :lang=zh | wc -l' | tr -d '[:space:]')"
[ "${font_count:-0}" -gt 0 ] || fail "API 容器没有中文字体"
ok "中文字体 count=$font_count"

users="$(docker exec justice-db psql -U justice -d justice -Atc 'SELECT count(*) FROM users;' | tr -d '[:space:]')"
[ "${users:-0}" -gt 0 ] || fail "数据库 users 表为空"
ok "数据库 users=$users"

image="$(docker inspect justice-api --format '{{.Config.Image}}')"
echo "API_IMAGE=$image"

echo
echo "POST-CHECK PASSED"
echo "仍必须由客户端完成 2 页 PPT + 10 页 PPT 两次端到端验收，才能签字。"
