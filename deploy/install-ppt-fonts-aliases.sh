#!/usr/bin/env bash
# 给国产系统（麒麟 / 统信）安装成稿字体别名。
#
# 生成的 pptx 里写的是 Windows 原生字体名（Microsoft YaHei / Times New Roman），
# Windows 双击打开即命中；国产系统没有这两款商业字体，需要把名字映射到本机
# 已有的思源黑体 / Liberation Serif，否则 WPS、LibreOffice 预览会退回宋体。
#
# 用法（root）：
#   sudo bash deploy/install-ppt-fonts-aliases.sh
# 校验：
#   fc-match "Microsoft YaHei"      # 应输出 NotoSansCJK-*.ttc
#   fc-match "Times New Roman"      # 应输出 LiberationSerif-*.ttf
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
SRC="$HERE/fonts/51-ppt-fonts.conf"
DEST_DIR="/etc/fonts/conf.d"
DEST="$DEST_DIR/51-ppt-fonts.conf"

if [ "$(id -u)" -ne 0 ]; then
    echo "请用 root 执行：sudo bash $0" >&2
    exit 1
fi
if [ ! -f "$SRC" ]; then
    echo "缺少配置文件：$SRC" >&2
    exit 1
fi

install -D -m 644 "$SRC" "$DEST"
fc-cache -f >/dev/null 2>&1 || true

echo "已安装 $DEST"
for name in "Microsoft YaHei" "Times New Roman"; do
    printf '  %-20s -> ' "$name"
    fc-match -f '%{family[0]}\n' "$name" 2>/dev/null || echo "查询失败"
done
