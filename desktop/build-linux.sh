#!/usr/bin/env bash
# ============================================================================
#  云法智办 · Linux（麒麟 / 统信 UOS）打包脚本
# ============================================================================
#  用法（在**目标架构的 Linux 机器**上执行）：
#     bash build-linux.sh              # 自动探测架构，产出 deb + rpm
#     bash build-linux.sh --deb-only   # 只出 deb
#     ARCH=aarch64 bash build-linux.sh # 手动指定架构（交叉编译场景无效，见下）
#
#  ⚠️ 重要：jpackage **不支持交叉编译**。
#     本脚本必须在**与目标包相同架构**的 Linux 机器上运行：
#       x86_64 机器  → 产出 x86_64 的 deb
#       aarch64 机器 → 产出 aarch64 的 deb
#     在 x86 上跑 ARCH=aarch64 **不会**得到 ARM 包，jpackage 会直接报错。
#
#  依赖（内网需先备好离线包，见 deploy/offline）：
#     JDK 17+、Kotlin/Compose 由 Gradle wrapper下载
# ============================================================================
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
cd "$SCRIPT_DIR"

# ---------------------------------------------------------------- 环境自检
step() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
ok()   { printf '\033[1;32m  [ OK ]\033[0m %s\n' "$*"; }
bad()  { printf '\033[1;31m  [FAIL]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[中止] %s\033[0m\n' "$*"; exit 1; }

step "0/5 环境自检"
[[ "$(uname -s)" == "Linux" ]] || die "必须在 Linux 上运行（当前 $(uname -s)）"

MACHINE_ARCH=$(uname -m)
case "$MACHINE_ARCH" in
    x86_64|amd64)  ARCH=x64;   ARCH_LABEL="x86_64" ;;
    aarch64|arm64) ARCH=arm64; ARCH_LABEL="aarch64" ;;
    *) die "不支持的架构：$MACHINE_ARCH（需 x86_64 或 aarch64）" ;;
esac
ok "构建机架构：$ARCH_LABEL（将产出 $ARCH_LABEL 包）"

ARCH_OVERRIDE="${ARCH:-}"
if [[ -n "$ARCH_OVERRIDE" && "$ARCH_OVERRIDE" != "$ARCH" ]]; then
    bad "ARCH=$ARCH_OVERRIDE 与构建机实际架构 ($ARCH) 不符"
    die  "jpackage 不支持交叉编译，请在 ${ARCH_LABEL} 机器上重跑本脚本"
fi

command -v java >/dev/null || die "找不到 java，需 JDK 17+"
JAVA_MAJOR=$(java -version 2>&1 | head -1 | sed -E 's/.*"([0-9]+).*/\1/')
[[ "${JAVA_MAJOR:-0}" -ge 17 ]] && ok "JDK $JAVA_MAJOR" || bad "JDK 版本 $JAVA_MAJOR，建议 17+"

chmod +x ./gradlew 2>/dev/null || true
# gradlew 没有 .sh 后缀，.gitattributes 的 *.sh 规则管不到；从 Windows 复制
# 过来时可能是 CRLF，执行会报「bad interpreter: /bin/sh^M」。统一收敛成 LF。
if grep -q $'\r' ./gradlew 2>/dev/null; then
  sed -i 's/\r$//' ./gradlew
  ok "已把 gradlew 从 CRLF 转为 LF"
fi
[[ -f ./gradlew ]] || die "缺少 gradlew"

# 解析包名与版本（与 build.gradle.kts 保持一致）
PKG_NAME=$(grep -oP '^\s+packageName\s*=\s*"\K[^"]+' build.gradle.kts | head -1)
PKG_VER=$(grep -oP '^\s+packageVersion\s*=\s*"\K[^"]+' build.gradle.kts | head -1)
[[ -f app_logo.png ]] || die "缺少 app_logo.png（deb/rpm 不接受 ico）"
ok "包名 $PKG_NAME / 版本 $PKG_VER / 图标 app_logo.png 齐备"

# ---------------------------------------------------------------- 构建
step "1/5 编译 Kotlin（JVM）"
./gradlew compileKotlinJvm --no-daemon -q

step "2/5 打包原生分发（$ARCH_LABEL）"
if [[ "${1:-}" == "--deb-only" ]]; then
    ./gradlew packageDeb --no-daemon
else
    ./gradlew packageDeb packageRpm --no-daemon
fi

# ---------------------------------------------------------------- 收集产物
step "3/5 收集产物"
OUT_DIR="$SCRIPT_DIR/build/compose/binaries/main/deb"
[[ -d "$OUT_DIR" ]] || OUT_DIR=$(dirname "$(find "$SCRIPT_DIR/build/compose/binaries" -name '*.deb' -print -quit 2>/dev/null)")

DEB=$(find "$SCRIPT_DIR/build/compose/binaries" -name '*.deb' -newermt '-30 minutes' -print -quit 2>/dev/null || true)
[[ -n "$DEB" ]] || die "未找到 .deb 产物（看上方 gradle 输出）"
ok "deb: $DEB ($(du -h "$DEB" | cut -f1))"

# 架构核对：防止在 x86 上误当成arm 包交付
step "4/5 校验包架构"
if command -v dpkg-deb >/dev/null; then
    PKG_ARCH=$(dpkg-deb -f "$DEB" Architecture)
    ok "deb 声明架构：$PKG_ARCH"
    if [[ "$PKG_ARCH" != "$ARCH_LABEL" && "$PKG_ARCH" != "all" ]]; then
        bad "架构不符！期望 $ARCH_LABEL，实际 $PKG_ARCH"
    fi
else
    bad "无 dpkg-deb，跳过架构校验（装之前请手动 dpkg-deb -f xxx.deb Architecture）"
fi

# ---------------------------------------------------------------- 安装说明
step "5/5 安装方式"
cat <<EOF

  # 麒麟/统信安装（推荐，依赖自动处理）
  sudo dpkg -i $(basename "$DEB")

  # 若提示缺依赖，用这句修复（需要本地源或已配内网源）
  sudo apt-get install -f     # 麒麟
  # sudo dnf install -f      # 统信/欧拉

  # 首次启动后，客户端配置文件在（Linux 下 APPDATA 不存在，回退到用户主目录）：
  #   ~/JudicialAIDesktop/server.json     ← 把 baseUrl 改成生产地址
  #   http://10.128.85.133:8000

  ⚠️ 记得改配置里的地址，否则连的是默认 127.0.0.1
EOF
