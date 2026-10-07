#!/usr/bin/env bash
set -euo pipefail

fail() { echo "[FAIL] $*" >&2; exit 1; }
ok() { echo "[ OK ] $*"; }

SANDBOX_IMAGE="${SANDBOX_IMAGE:-deeppresenter-sandbox:latest}"
HOST_IMAGE="${HOST_IMAGE:-deeppresenter-host:latest}"

docker image inspect "$SANDBOX_IMAGE" >/dev/null 2>&1 ||
  fail "缺少已验证 sandbox 镜像: $SANDBOX_IMAGE"

docker run --rm --entrypoint sh "$SANDBOX_IMAGE" -c '
  set -eu
  capture=$(find / -type f -name capture.js 2>/dev/null | head -n 1)
  [ -n "$capture" ]
  [ "$(grep -o "offline-patch" "$capture" | wc -l | tr -d " ")" = "2" ]

  # 必须先筛出「含 rewrite: z.union 的那个」schemas.js，不能拿第一个 schemas.js 就断言。
  # 镜像里存在多个 schemas.js 时，旧写法会挑中不含该改动的那个，
  # 导致基线校验恒失败或误判。
  schemas=$(find / -type f -name schemas.js 2>/dev/null | xargs grep -l "rewrite: z.union" 2>/dev/null | head -n 1)
  [ -n "$schemas" ]
  grep -q "rewrite: z.union" "$schemas"

  [ ! -L /usr/local/bin/mmdc ]
  [ "$(head -n 1 /usr/local/bin/mmdc)" = "#!/bin/bash" ]

  [ "$(fc-list :lang=zh | wc -l | tr -d " ")" -ge 100 ]
' || fail "sandbox 镜像未达到 2026-09-28 已验证补丁基线"
ok "sandbox 镜像补丁基线"

docker image inspect "$HOST_IMAGE" >/dev/null 2>&1 ||
  fail "缺少已验证 host 镜像: $HOST_IMAGE"

docker run --rm --entrypoint sh "$HOST_IMAGE" -c '
  set -eu
  grep -q "禁止 apt install" /usr/src/pptagent/deeppresenter/roles/Research.yaml
  which soffice >/dev/null
  which unoconv >/dev/null
  test -f /root/.cache/huggingface/hub/models--julien-c--fasttext-language-id/snapshots/master/lid.176.bin
' || fail "host 镜像未达到 2026-09-28 已验证补丁基线"
ok "host 镜像补丁基线"

echo
echo "PPTAGENT IMAGE BASELINE PASSED"
