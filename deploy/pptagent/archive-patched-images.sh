#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT_DIR="${1:-/opt/justice-office/data/delivery-images}"
SANDBOX_IMAGE="${SANDBOX_IMAGE:-deeppresenter-sandbox:latest}"
HOST_IMAGE="${HOST_IMAGE:-deeppresenter-host:latest}"

"$SCRIPT_DIR/verify-patched-images.sh"

mkdir -p "$OUT_DIR"

docker save "$SANDBOX_IMAGE" -o "$OUT_DIR/sandbox.tar"
docker save "$HOST_IMAGE" -o "$OUT_DIR/host.tar"

test -s "$OUT_DIR/sandbox.tar"
test -s "$OUT_DIR/host.tar"

sha256sum "$OUT_DIR/sandbox.tar" "$OUT_DIR/host.tar"   | tee "$OUT_DIR/pptagent-images.sha256"

echo
echo "已归档经过补丁校验的 PPTAgent 镜像："
ls -lh "$OUT_DIR/sandbox.tar" "$OUT_DIR/host.tar" "$OUT_DIR/pptagent-images.sha256"
echo
echo "恢复命令："
echo "  docker load -i $OUT_DIR/sandbox.tar"
echo "  docker load -i $OUT_DIR/host.tar"
