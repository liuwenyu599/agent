#!/usr/bin/env bash
# ============================================================================
#  云法智办 · Docker 方式打包 Linux(x64) 客户端
# ============================================================================
#  用途：在**只有 Windows + Docker Desktop**的机器上产出麒麟/统信用的 deb。
#  为什么不用 WSL：WSL 首次初始化（OOBE）在部分环境失败，而 Docker Desktop
#  已经就绪，容器环境可复现、不受代理/NAT 影响、产物直接挂到 Windows 盘。
#
#  用法（Git Bash 里跑，Docker Desktop 需已启动）：
#     bash build-linux-docker.sh              # 用清华镜像源（国内快）
#     bash build-linux-docker.sh --no-mirror  # 用官方源
#     bash build-linux-docker.sh --proxy 7890  # 额外走代理
# ============================================================================
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
OUT_DIR="${OUT_DIR:-$REPO_ROOT/build/linux-out}"

USE_MIRROR=1
PROXY_PORT=""
for a in "$@"; do
  case "$a" in
    --no-mirror) USE_MIRROR=0 ;;
    --proxy) shift; PROXY_PORT="${1:-}" ;;
  esac
done

step() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
ok()   { printf '\033[1;32m  [ OK ]\033[0m %s\n' "$*"; }
bad()  { printf '\033[1;31m  [FAIL]\033[0m %*s\n' "$*"; }
die()  { printf '\033[1;31m[中止] %s\033[0m\n' "$*"; exit 1; }

# ------------------------------------------------------------ Docker 路径转换
# Git Bash 里 /d/... 需要转成 Docker 能识别的 D:/...
d2w() {
  local p="$1"
  if [[ "$p" =~ ^/([a-zA-Z])/(.*)$ ]]; then
    printf '%s:/%s' "$(echo "${BASH_REMATCH[1]}" | tr '[:lower:]' '[:upper:]')" "${BASH_REMATCH[2]}"
  else
    printf '%s' "$p"
  fi
}

step "0/5 环境自检"
# Docker Desktop 常见安装位置；PATH 里常常没有 docker，需要主动探测。
# 注意：**不要依赖 $USER** —— Git Bash 下该变量可能未定义，set -u 会直接报错
# （实测报 line 52: USER: unbound variable）。改用 LOCALAPPDATA + cygpath 转换。
DOCKER_BIN="${DOCKER_BIN:-}"
if [[ -z "$DOCKER_BIN" ]]; then
  if command -v docker >/dev/null 2>&1; then
    DOCKER_BIN="$(command -v docker)"
  else
    for cand in \
      "/c/Program Files/Docker/Docker/resources/bin/docker.exe" \
      "/c/Program Files/Docker/Docker/resources/bin/docker" \
      "/c/ProgramData/DockerDesktop/resources/bin/docker.exe"
    do
      [[ -f "$cand" ]] && { DOCKER_BIN="$cand"; break; }
    done
    # 用户级安装目录（默认位置），用 cygpath 把 Windows 路径转成 POSIX 路径，
    # 这样即使用户名含中文/空格（%USERNAME% 非 ASCII）也能正确定位。
    if [[ -z "$DOCKER_BIN" && -n "${LOCALAPPDATA:-}" ]]; then
      win_cand="${LOCALAPPDATA}\\DockerDesktop\\resources\\bin\\docker.exe"
      [[ -f "$win_cand" ]] && DOCKER_BIN="$(cygpath -u "$win_cand")"
    fi
    # 最后兜底：逐个遍历 /c/Users/*（跳过非 ASCII 用户目录会漏，但成本极低）
    if [[ -z "$DOCKER_BIN" ]]; then
      for u in /c/Users/*; do
        cand="$u/AppData/Local/Programs/DockerDesktop/resources/bin/docker.exe"
        [[ -f "$cand" ]] && { DOCKER_BIN="$cand"; break; }
      done
    fi
  fi
fi
[[ -n "$DOCKER_BIN" ]] || die "找不到 docker 可执行文件。若 Docker Desktop 装在别处，用 DOCKER_BIN=/path/to/docker.exe 指定"
ok "docker 路径：$DOCKER_BIN"

# Docker Desktop 必须已启动，否则 daemon 连不上
if ! "$DOCKER_BIN" info >/dev/null 2>&1; then
  bad "Docker daemon 未运行"
  die  "请先在开始菜单启动 Docker Desktop，等右下角图标不再转圈后再跑本脚本"
fi
ok "daemon 可用：$("$DOCKER_BIN" --version 2>/dev/null | head -1)"

# Docker Desktop 的 WSL 集成可能未挂载 /mnt/c，用 docker 自己探测宿主盘
HOST_ROOT=$(d2w "$REPO_ROOT")
[[ -f "$REPO_ROOT/desktop/build.gradle.kts" ]] || HOST_ROOT="D:/Projects/judicial_app"
ok "仓库映射：$HOST_ROOT/desktop"

[[ -f "$REPO_ROOT/desktop/app_logo.png" ]] || die "缺少 app_logo.png（deb 不接受 ico）"
ok "Linux 图标齐备"

# 架构：只做 x64。ARM64 已确认不需要（目标机是兆芯 KX-7000，x86_64 兼容）
DOCKER_HOST_ARCH=$("$DOCKER_BIN" run --rm -v /var/run/docker.sock:/var/run/docker.sock \
  alpine uname -m 2>/dev/null || echo unknown)
if [[ "$DOCKER_HOST_ARCH" == "aarch64" ]]; then
  ok "宿主是aarch64，产出 arm64 包"
else
  ok "宿主是 x86_64，产出 amd64 包（目标机为兆芯 KX-7000/x86_64）"
fi

mkdir -p "$OUT_DIR"
GRADLE_CACHE="$REPO_ROOT/.gradle-docker"
mkdir -p "$GRADLE_CACHE"

# ------------------------------------------------------------ 镜像与源
if [[ $USE_MIRROR -eq 1 ]]; then
  APT_MIRROR='sed -i "s@//.*deb.debian.org@//mirrors.tuna.tsinghua.edu.cn@g; s@//.*security.debian.org@//mirrors.tuna.tsinghua.edu.cn@g" /etc/apt/sources.list; sed -i "s@//.*archive.ubuntu.com@//mirrors.tuna.tsinghua.edu.cn@g; s@//.*security.ubuntu.com@//mirrors.tuna.tsinghua.edu.cn@g" /etc/apt/sources.list'
  GRADLE_INIT='mkdir -p ~/.gradle && cat > ~/.gradle/init.gradle <<EOF
allprojects {
    repositories {
        maven { url "https://maven.tuna.tsinghua.edu.cn/repository/public" }
        maven { url "https://maven.aliyun.com/repository/public" }
        mavenCentral()
    }
    buildscript {
        repositories {
            maven { url "https://maven.tuna.tsinghua.edu.cn/repository/public" }
            maven { url "https://maven.aliyun.com/repository/public" }
            mavenCentral()
        }
    }
}
settingsEvaluated { settings ->
    settings.pluginManagement {
        repositories {
            maven { url "https://maven.tuna.tsinghua.edu.cn/repository/public" }
            gradlePluginPortal()
        }
    }
}
EOF'
  ok "使用清华镜像源（apt + gradle）"
else
  APT_MIRROR=':'
  GRADLE_INIT=':'
  ok "使用官方源"
fi

# 代理参数
PROXY_ENV=''
if [[ -n "$PROXY_PORT" ]]; then
  PROXY_ENV="-e http_proxy=http://host.docker.internal:$PROXY_PORT -e https_proxy=http://host.docker.internal:$PROXY_PORT"
  ok "走代理 host.docker.internal:$PROXY_PORT"
fi

# ------------------------------------------------------------ 构建
step "1/5 拉取构建镜像"
"$DOCKER_BIN" pull eclipse-temurin:17-jdk
ok "eclipse-temurin:17-jdk 就绪"

step "2/5 容器内编译 + 打包 deb（首次需下载依赖，较慢）"
# shellcheck disable=SC2086
"$DOCKER_BIN" run --rm \
  -v "$HOST_ROOT:/src" \
  -v "$GRADLE_CACHE:/g" \
  -v "$(d2w "$OUT_DIR"):/out" \
  -e GRADLE_USER_HOME=/g \
  $PROXY_ENV \
  eclipse-temurin:17-jdk \
  bash -c "
    set -e
    echo '--- 换镜像源 ---'
    $APT_MIRROR || true
    echo '--- 装打包依赖 ---'
    apt-get update -qq
    apt-get install -y -qq fakeroot dpkg-dev > /dev/null
    which fakeroot && echo 'fakeroot OK'
    echo '--- 配置 Gradle 镜像 ---'
    $GRADLE_INIT
    echo '--- 开始打包（首次会下载依赖，请耐心等待）---'
    cd /src/desktop
    chmod +x gradlew
    ./gradlew packageDeb --no-daemon --stacktrace
    echo '--- 收集产物 ---'
    mkdir -p /out
    find /src/desktop/build/compose/binaries -name '*.deb' -exec cp {} /out/ \;
    ls -lh /out/
  " 2>&1 | tail -60

step "3/5 校验产物"
DEB=$(find "$OUT_DIR" -name '*.deb' -newermt '-30 minutes' -print -quit 2>/dev/null || true)
if [[ -z "$DEB" ]]; then
  bad "未找到 .deb 产物"
  echo "  构建日志在上面的输出里；常见原因见下"
  echo "  · fakeroot 没装上→ 换用官方源试（--no-mirror）"
  echo "  · 依赖下载失败     → 加代理：--proxy 7890"
  echo "  · Gradle 卡住       → 首次拉依赖慢，再等几分钟"
  exit 1
fi
ok "产物：$DEB ($(du -h "$DEB" | cut -f1))"

step "4/5 包内架构核对"
if command -v dpkg-deb >/dev/null; then
  dpkg-deb -f "$DEB" Architecture Package Version 2>/dev/null || echo "  （本机无 dpkg-deb，跳过）"
fi

step "5/5 交付"
cat <<EOF
  deb 已就绪：
    $(cygpath -w "$DEB" 2>/dev/null || echo "$DEB")

  拷到麒麟机器后安装：
    sudo dpkg -i $(basename "$DEB")
    sudo apt-get install -f        # 缺依赖时修复
    # 统信/欧拉用：sudo dnf install -f

  装完改配置（Linux 下 APPDATA 不存在，落在用户主目录）：
    nano ~/JudicialAIDesktop/server.json
    → "baseUrl": "http://10.128.85.133:8000"

  连通验证：
    curl -o /dev/null -s -w '%{http_code}\\n' http://10.128.85.133:8000/docs
EOF
