#!/usr/bin/env bash
#
# pack-and-scp.sh — 在 Windows 开发机(Git Bash)打包后端代码并 SCP 到生产服务器
#
# 场景：政务内网严禁出网，不能 git pull；用仓库自带 pack_release.py 产扁平包，再 scp。
# 注意：pack_release.py 产的是扁平包（无 judicial_app/ 顶层目录），
#       服务器解包用 `tar xzf ... -C /opt/judicial_app.new`（不带 --strip-components=1）。
#
# 用法（在仓库根目录执行，如 D:\Projects\judicial_app）:
#   ./deploy/qwen35b/pack-and-scp.sh
#   SCP_TARGET=root@10.128.85.133:/tmp/ ./deploy/qwen35b/pack-and-scp.sh
#
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

SHA=$(git rev-parse --short HEAD)
echo "仓库: $REPO_DIR"
echo "当前分支 SHA: $SHA"

echo "== 1/2 打包（pack_release.py，扁平包）=="
OUT=$(python pack_release.py 2>&1) || { echo "打包失败:"; echo "$OUT"; exit 1; }
echo "$OUT"

PKG=$(echo "$OUT" | grep -Eo 'judicial_app_[0-9a-f]+\.tar\.gz' | head -1)
PKG="${PKG:-$REPO_DIR/judicial_app_$SHA.tar.gz}"
[ -s "$PKG" ] || { echo "未找到产物: $PKG"; exit 1; }
echo "产物: $PKG ($(du -h "$PKG" | cut -f1))"

echo "== 2/2 SCP 到生产服务器 =="
SCP_TARGET="${SCP_TARGET:-root@10.128.85.133:/tmp/}"
echo "目标: $SCP_TARGET"
scp "$PKG" "$SCP_TARGET"

echo "== 完成 =="
echo "服务器端解包（扁平包，不带 --strip-components）:"
echo "  mkdir -p /opt/judicial_app.new && tar xzf $PKG -C /opt/judicial_app.new"
echo "  详细步骤见 deploy/PRODUCTION_DEPLOYMENT.md 第 6 节。"
