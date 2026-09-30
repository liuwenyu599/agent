#!/bin/bash
# /opt/justice-ppt/deploy/rebuild-images.sh
# 从原始镜像重建 deeppresenter-sandbox 和 deeppresenter-host
# 用法：
#   ./rebuild-images.sh sandbox    # 只重建 sandbox
#   ./rebuild-images.sh host       # 只重建 ppt-host
#   ./rebuild-images.sh all        # 两个都重建
#   ./rebuild-images.sh verify     # 只验证当前镜像是否完好
#
# 依赖（必须存在）：
#   /usr/share/fonts/truetype/chinese/
#   /usr/share/fonts/gb-cjk/
#   /opt/justice-ppt/cache/lid.176.bin
#   docker（root）
#
# 关键设计：
#   - 优先用原始（干净）镜像 ID 作基础（SANDBOX_ORIG_ID / PPT_HOST_ORIG_ID）。
#     这两个 ID 是 "docker commit 前" 的干净底包；若被 prune，退回从 :latest 增量补丁。
#   - 重建前自动备份旧 tag 为 backup-<时间戳>。
#   - 每一步幂等（已改则跳过）。
#   - commit 时显式 --change 恢复 entrypoint/cmd，避免 entrypoint 被污染成 sleep。

set -e

# ============ 原始镜像 ID ============
# 如果不小心把这两行也删了，找回方式：
#   docker images | grep deeppresenter-sandbox  →  找到 <none> 且 Created 8 天前的
#   docker images | grep deeppresenter-host     →  同上
SANDBOX_ORIG_ID="${SANDBOX_ORIG_ID:-ed955bc1ff66}"
PPT_HOST_ORIG_ID="${PPT_HOST_ORIG_ID:-6a04e8ab579e}"

SANDBOX_ENTRYPOINT='["docker-entrypoint.sh"]'
SANDBOX_CMD='["node","/usr/src/app/dist/index.js","--no-onboarding"]'

log()  { echo "[$(date '+%H:%M:%S')] $*"; }
err()  { echo "[$(date '+%H:%M:%S')] ERROR: $*" >&2; }
ok()   { echo "[$(date '+%H:%M:%S')] ✅ $*"; }
warn(){ echo "[$(date '+%H:%M:%S')] ⚠️  $*" >&2; }

if [ "$EUID" -ne 0 ]; then
  err "请用 root 运行"
  exit 1
fi

check_deps() {
  local missing=0
  for f in /usr/share/fonts/truetype/chinese /usr/share/fonts/gb-cjk /opt/justice-ppt/cache/lid.176.bin; do
    if [ ! -e "$f" ]; then
      err "缺少依赖：$f"
      missing=1
    fi
  done
  [ "$missing" -eq 0 ] || exit 1
}

# ============ 重建 sandbox ============
rebuild_sandbox() {
  log "========== 重建 deeppresenter-sandbox =========="

  local BASE
  if docker inspect "$SANDBOX_ORIG_ID" >/dev/null 2>&1; then
    BASE="$SANDBOX_ORIG_ID"
    log "基础镜像：原始版 $SANDBOX_ORIG_ID（干净）"
  else
    BASE="deeppresenter-sandbox:latest"
    log "基础镜像：现有 latest（增量打补丁）"
    err "  警告：如果 latest 已被污染，结果可能不可靠"
  fi

  # 备份旧 tag
  local TS
  TS=$(date +%Y%m%d_%H%M%S)
  docker tag deeppresenter-sandbox:latest "deeppresenter-sandbox:backup-$TS" 2>/dev/null || true

  # 起临时容器
  local CID
  CID=$(docker run -d --entrypoint sleep "$BASE" infinity)
  log "临时容器：$CID"
  trap "docker rm -f $CID >/dev/null 2>&1 || true" EXIT

  # ---- 1. schemas.js 补丁（belt-and-suspenders：真实修复在 host 侧 write_file Python 层）----
  if docker exec "$CID" grep -q "rewrite: z.union" /usr/src/app/dist/tools/schemas.js 2>/dev/null; then
    log "schemas.js 已打补丁，跳过"
  else
    docker cp "$CID:/usr/src/app/dist/tools/schemas.js" /tmp/_schemas.js
    python3 - <<'PYEOF'
p = "/tmp/_schemas.js"
src = open(p).read()
old = """    mode: z.enum(['rewrite', 'append']).default('rewrite'),
});"""
new = """    mode: z.enum(['rewrite', 'append']).default('rewrite'),
    rewrite: z.union([z.boolean(), z.string()]).optional(),
});"""
assert old in src, "schemas.js 原结构未匹配"
open(p, "w").write(src.replace(old, new, 1))
print("schemas.js 已生成")
PYEOF
    docker cp /tmp/_schemas.js "$CID:/usr/src/app/dist/tools/schemas.js"
    ok "schemas.js 补丁已应用"
  fi

  # ---- 2. 禁用遥测（offline 部署不需要上报，避免外网访问卡住/报错）----
  local CAP_COUNT
  CAP_COUNT=$(docker exec "$CID" grep -c "offline-patch" /usr/src/app/dist/utils/capture.js 2>/dev/null || echo 0)
  if [ "$CAP_COUNT" -ge 2 ]; then
    log "capture.js 遥测已禁用，跳过"
  else
    docker cp "$CID:/usr/src/app/dist/utils/capture.js" /tmp/_capture.js
    python3 - <<'PYEOF'
import re
p = "/tmp/_capture.js"
src = open(p, encoding="utf-8").read()
for fn in ("capture", "capture_call_tool"):
    pat = re.compile(
        r"export const %s = async \([^)]*\) => \{.*?\n\};" % fn,
        re.DOTALL)
    repl = (
        "export const %s = async (event, properties) => {\n"
        "    // [offline-patch] telemetry disabled for offline deployment\n"
        "    return;\n"
        "};" % fn)
    new_src, n = pat.subn(repl, src, count=1)
    assert n == 1, f"{fn} 未匹配到（匹配数={n}）"
    src = new_src
open(p, "w", encoding="utf-8").write(src)
print("capture.js 已替换 2 处")
PYEOF
    docker cp /tmp/_capture.js "$CID:/usr/src/app/dist/utils/capture.js"
    ok "capture.js 遥测已禁用（offline-patch）"
  fi

  # ---- 3. mmdc wrapper（过滤模型乱传的 --puppeteerConfigFile，强制用我们的 config）----
  if docker exec "$CID" head -1 /usr/local/bin/mmdc 2>/dev/null | grep -q '#!/bin/bash'; then
    log "mmdc wrapper 已存在，跳过"
  else
    cat > /tmp/_mmdc_wrapper <<'WRAPPER_EOF'
#!/bin/bash
# 过滤掉模型/调用方乱传的 --puppeteerConfigFile，强制用我们的 config，
# 避免 PPTAgent 默认 puppeteer 配置把中文字体搞丢或路径错。
args=()
skip=0
for a in "$@"; do
  if [ "$skip" = "1" ]; then
    skip=0
    continue
  fi
  case "$a" in
    --puppeteerConfigFile|--puppeteer-config-file)
      skip=1
      ;;
    *)
      args+=("$a")
      ;;
  esac
done

CLI=""
for p in \
  /usr/local/lib/node_modules/@mermaid-js/mermaid-cli/src/cli.js \
  /usr/local/lib/node_modules/@mermaid-js/mermaid-cli/lib/cli.js ; do
  [ -f "$p" ] && CLI="$p" && break
done

if [ -n "$CLI" ]; then
  exec node "$CLI" -p /root/.puppeteerrc.json "${args[@]}"
else
  exec mmdc -p /root/.puppeteerrc.json "${args[@]}"
fi
WRAPPER_EOF
    docker exec "$CID" rm -f /usr/local/bin/mmdc
    docker cp /tmp/_mmdc_wrapper "$CID:/usr/local/bin/mmdc"
    docker exec "$CID" chmod +x /usr/local/bin/mmdc
    # 配套 puppeteer 配置（让 chromium 渲染中文字体）
    cat > /tmp/_puppeteerrc.json <<'JSON_EOF'
{
  "args": ["--no-sandbox", "--disable-setuid-sandbox", "--font-render-hinting=none"],
  "defaultViewport": {"width": 1600, "height": 900}
}
JSON_EOF
    docker cp /tmp/_puppeteerrc.json "$CID:/root/.puppeteerrc.json"
    ok "mmdc wrapper + puppeteerrc 已写入"
  fi

  # ---- 4. 中文字体 ----
  local ZH_COUNT
  ZH_COUNT=$(docker exec "$CID" sh -c 'fc-list :lang=zh 2>/dev/null | wc -l' || echo 0)
  if [ "$ZH_COUNT" -ge 100 ]; then
    log "中文字体已存在（$ZH_COUNT 个），跳过"
  else
    docker cp /usr/share/fonts/truetype/chinese/. "$CID:/usr/share/fonts/truetype/chinese/"
    docker cp /usr/share/fonts/gb-cjk/. "$CID:/usr/share/fonts/gb-cjk/"
    docker exec "$CID" fc-cache -fv >/dev/null 2>&1
    local NEW_COUNT
    NEW_COUNT=$(docker exec "$CID" sh -c 'fc-list :lang=zh | wc -l')
    ok "中文字体已拷贝（$NEW_COUNT 个）"
  fi

  # ---- 5. matplotlib 配置 ----
  docker exec "$CID" mkdir -p /root/.config/matplotlib
  docker exec "$CID" sh -c 'cat > /root/.config/matplotlib/matplotlibrc <<EOF
font.family: sans-serif
font.sans-serif: FZXiaoBiaoSong-B05S,FangSong_GB2312,SimHei,KaiTi,GB_FS_GB18030,GB_HT_GB18030,Noto Sans CJK SC,WenQuanYi Micro Hei,sans-serif
axes.unicode_minus: False
EOF'
  docker exec "$CID" rm -rf /root/.cache/matplotlib
  ok "matplotlib 配置已写入"

  # ---- 6. commit（恢复 entrypoint）----
  docker stop "$CID" >/dev/null 2>&1 || true
  docker commit \
    --change "ENTRYPOINT $SANDBOX_ENTRYPOINT" \
    --change "CMD $SANDBOX_CMD" \
    "$CID" deeppresenter-sandbox:latest >/dev/null
  docker commit \
    --change "ENTRYPOINT $SANDBOX_ENTRYPOINT" \
    --change "CMD $SANDBOX_CMD" \
    "$CID" docker.1ms.run/forceless/deeppresenter-sandbox:latest >/dev/null
  docker rm -f "$CID" >/dev/null 2>&1 || true
  trap - EXIT

  local ENTRY
  ENTRY=$(docker inspect deeppresenter-sandbox:latest --format '{{json .Config.Entrypoint}}')
  [ "$ENTRY" = "$SANDBOX_ENTRYPOINT" ] || { err "entrypoint 异常：$ENTRY"; exit 1; }
  ok "deeppresenter-sandbox 重建完成"
}

# ============ 重建 ppt-host ============
rebuild_ppt_host() {
  log "========== 重建 deeppresenter-host =========="

  local BASE
  if docker inspect "$PPT_HOST_ORIG_ID" >/dev/null 2>&1; then
    BASE="$PPT_HOST_ORIG_ID"
    log "基础镜像：原始版 $PPT_HOST_ORIG_ID（干净）"
  else
    BASE="deeppresenter-host:latest"
    log "基础镜像：现有 latest（增量）"
  fi

  # 探测原始 entrypoint/cmd（用于 commit --change 还原，避免被污染成 sleep）
  local ORIG_ENTRY ORIG_CMD
  ORIG_ENTRY=$(docker inspect "$BASE" --format '{{json .Config.Entrypoint}}')
  ORIG_CMD=$(docker inspect "$BASE" --format '{{json .Config.Cmd}}')
  log "原始 entrypoint: $ORIG_ENTRY"
  log "原始 cmd:        $ORIG_CMD"

  local TS
  TS=$(date +%Y%m%d_%H%M%S)
  docker tag deeppresenter-host:latest "deeppresenter-host:backup-$TS" 2>/dev/null || true

  local CID
  CID=$(docker run -d --entrypoint sleep "$BASE" infinity)
  log "临时容器：$CID"
  trap "docker rm -f $CID >/dev/null 2>&1 || true" EXIT

  # ---- 0. 【真实修复层】write_file：host 的 FastMCP 工具用 Pydantic 校验入参，
  #        模型幻觉的 rewrite 字段被 'Additional properties are not allowed' 拒绝。
  #        给 write_file 函数签名补一个被忽略的可选 rewrite 参数。
  #        （schemas.js 那层是 sandbox 的 zod 兼容补丁，二者并存互补；本步是必需项。）
  #        仅处理单行签名；多行签名会自动跳过并告警，请手工加 `rewrite: bool = False`。
  local wf_count
  wf_count=$(docker exec "$CID" sh -c "grep -rln 'def write_file' /usr/src /usr/local/lib/python3.13/site-packages 2>/dev/null" | wc -l)
  if [ "$wf_count" -gt 0 ]; then
    docker exec "$CID" sh -c "grep -rln 'def write_file' /usr/src /usr/local/lib/python3.13/site-packages 2>/dev/null" > /tmp/_wf_files
    local applied=0
    while read -r f; do
      [ -z "$f" ] && continue
      docker cp "$CID:$f" /tmp/_wf.orig
      python3 - /tmp/_wf.orig <<'PYEOF'
import sys, re
src = open('/tmp/_wf.orig', encoding='utf-8').read()
m = re.search(r'(def write_file\([^)]*?)\)', src)
if m and 'rewrite' not in m.group(1):
    body = m.group(1).rstrip().rstrip(',')
    open('/tmp/_wf.new','w',encoding='utf-8').write(
        src[:m.start()] + f'({body}, rewrite: bool = False)' + src[m.end():])
    print("OK patched", sys.argv[1])
else:
    print("SKIP (multiline signature or already patched)", sys.argv[1])
PYEOF
      if [ -f /tmp/_wf.new ]; then
        docker cp /tmp/_wf.new "$CID:$f"
        applied=1; rm -f /tmp/_wf.new
      else
        warn "write_file 自动补丁未应用：$f（可能多行签名，请手工加 rewrite: bool = False）"
      fi
    done < /tmp/_wf_files
    [ "$applied" -eq 1 ] && ok "write_file Python 修复已应用" || warn "write_file 自动修复未成功，请手工处理"
  else
    warn "未找到 def write_file，跳过（先 grep 定位）"
  fi

  # ---- 1. LibreOffice + unoconv ----
  if docker exec "$CID" which soffice >/dev/null 2>&1; then
    log "LibreOffice 已安装，跳过"
  else
    log "apt-get install libreoffice ...（约 2-3 分钟）"
    docker exec "$CID" apt-get update >/dev/null
    docker exec "$CID" apt-get install -y --no-install-recommends \
      libreoffice-writer libreoffice-impress unoconv \
      fonts-noto-cjk fonts-wqy-zenhei fonts-wqy-microhei \
      fonts-arphic-uming fonts-arphic-ukai >/dev/null
    ok "LibreOffice 安装完成"
  fi

  # ---- 2. matplotlib 中文字体（图表若在 host 侧渲染也需要；与 sandbox 一致）----
  docker exec "$CID" mkdir -p /root/.config/matplotlib
  docker exec "$CID" sh -c 'cat > /root/.config/matplotlib/matplotlibrc <<EOF
font.family: sans-serif
font.sans-serif: FZXiaoBiaoSong-B05S,FangSong_GB2312,SimHei,KaiTi,GB_FS_GB18030,GB_HT_GB18030,Noto Sans CJK SC,WenQuanYi Micro Hei,sans-serif
axes.unicode_minus: False
EOF'
  docker exec "$CID" rm -rf /root/.cache/matplotlib
  ok "matplotlib 配置已写入（host）"

  # ---- 3. lid.176.bin ----
  if docker exec "$CID" test -f /root/.cache/huggingface/hub/models--julien-c--fasttext-language-id/snapshots/master/lid.176.bin; then
    log "lid.176.bin 已存在，跳过"
  else
    docker exec "$CID" mkdir -p /root/.cache/huggingface/hub/models--julien-c--fasttext-language-id/snapshots/master
    docker cp /opt/justice-ppt/cache/lid.176.bin \
      "$CID:/root/.cache/huggingface/hub/models--julien-c--fasttext-language-id/snapshots/master/lid.176.bin"
    docker exec "$CID" mkdir -p /root/.cache/modelscope/hub/models--forceless--fasttext-language-id/snapshots/master
    docker cp /opt/justice-ppt/cache/lid.176.bin \
      "$CID:/root/.cache/modelscope/hub/models--forceless--fasttext-language-id/snapshots/master/lid.176.bin"
    ok "lid.176.bin 已拷贝（HF + MS 两处）"
  fi

  # ---- 4. commit（保持原 entrypoint，显式 --change 还原）----
  docker stop "$CID" >/dev/null 2>&1 || true
  docker commit --change "ENTRYPOINT=$ORIG_ENTRY" --change "CMD=$ORIG_CMD" \
    "$CID" deeppresenter-host:latest >/dev/null
  docker commit --change "ENTRYPOINT=$ORIG_ENTRY" --change "CMD=$ORIG_CMD" \
    "$CID" docker.1ms.run/forceless/deeppresenter-host:latest >/dev/null
  docker rm -f "$CID" >/dev/null 2>&1 || true
  trap - EXIT

  ok "deeppresenter-host 重建完成"
}

# ============ 验证 ============
do_verify() {
  log "========== 验证当前镜像 =========="

  log "--- sandbox ---"
  docker run --rm --entrypoint sh deeppresenter-sandbox -c '
    echo -n "schemas.js rewrite: "
    grep -c "rewrite: z.union" /usr/src/app/dist/tools/schemas.js 2>/dev/null || echo 0
    echo -n "mmdc 是 wrapper:    "
    head -1 /usr/local/bin/mmdc 2>/dev/null | grep -q "#!/bin/bash" && echo yes || echo no
    echo -n "offline-patch 计数:  "
    grep -c "offline-patch" /usr/src/app/dist/utils/capture.js 2>/dev/null || echo 0
    echo -n "中文字体数:         "
    fc-list :lang=zh 2>/dev/null | wc -l
    echo -n "matplotlibrc 存在:  "
    test -f /root/.config/matplotlib/matplotlibrc && echo yes || echo no
  '

  log "--- ppt-host ---"
  docker run --rm --entrypoint sh deeppresenter-host -c '
    echo -n "soffice:            "
    which soffice >/dev/null 2>&1 && soffice --version 2>/dev/null | head -1 || echo "MISSING"
    echo -n "unoconv:            "
    which unoconv 2>/dev/null || echo "MISSING"
    echo -n "lid.176.bin (HF):   "
    test -f /root/.cache/huggingface/hub/models--julien-c--fasttext-language-id/snapshots/master/lid.176.bin && echo yes || echo no
    echo -n "lid.176.bin (MS):   "
    test -f /root/.cache/modelscope/hub/models--forceless--fasttext-language-id/snapshots/master/lid.176.bin && echo yes || echo no
    echo -n "write_file rewrite: "
    grep -rl "rewrite: bool = False" /usr/src /usr/local/lib/python3.13/site-packages 2>/dev/null | head -1 || echo "NOT-PATCHED"
  '

  log "--- entrypoint ---"
  docker inspect deeppresenter-sandbox:latest --format 'sandbox: Entrypoint={{json .Config.Entrypoint}} Cmd={{json .Config.Cmd}}'
  docker inspect deeppresenter-host:latest    --format 'host:    Entrypoint={{json .Config.Entrypoint}} Cmd={{json .Config.Cmd}}'
}

# ============ 主流程 ============
case "${1:-all}" in
  sandbox) check_deps; rebuild_sandbox ;;
  host)    check_deps; rebuild_ppt_host ;;
  all)     check_deps; rebuild_sandbox; rebuild_ppt_host; do_verify ;;
  verify)  do_verify ;;
  *)
    echo "用法: $0 {all|sandbox|host|verify}"
    exit 1
    ;;
esac

ok "完成：${1:-all}"
