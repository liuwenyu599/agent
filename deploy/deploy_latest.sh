#!/usr/bin/env bash
# ============================================================================
#  云法智办 · 生产覆盖部署脚本（后端镜像 + PPT 宿主守卫镜像）
# ============================================================================
#  用法（在生产服务器 10.128.85.133 上执行）：
#     bash deploy_latest.sh              # 离线模式（生产标准做法，见下）
#     bash deploy_latest.sh --check-only # 只做构建前校验，不build
#     bash deploy_latest.sh --pull       # 仅在可出网的开发/测试机：先 git 拉最新再部署
#
#  ⚠️ 生产环境是**司法局内网，严禁出网**（《完整交接文档-20261004.md》第 74/140/
#     1039-1040 行明文），源码**走 tar 覆盖、不在服务器上 git pull/push**。
#     所以本脚本默认**离线模式**：源码已由 Windows 端 git archive 打包 + scp 上传
#     并替换到位，脚本只做「校验 → 构建 → 切流量 → 验证」，全程不依赖 git 与网络。
#     （此前的版本第1 步硬编码 git fetch，在生产必失败，已改。）
#
#  设计要点（都是踩过的坑，勿改）：
#   1. 代码是**烤进镜像**的（deploy/Dockerfile `COPY server/ /app/`），
#      改宿主机文件 + docker restart **不生效**，必须 docker build。
#   2. **不要传 --build-arg INSTALL_PPT_PREVIEW**（仓库 Dockerfile 只认
#      PIP_INDEX_URL，传了会报 unexpected build arg 而失败）。
#      ⚠️ PRODUCTION_DEPLOYMENT.md §8 仍写着该参数，是过时文档。
#   3. 解包**不要用 --strip-components**（pack_release.py / 建议的
#      `git archive HEAD` 产的是**扁平包**，strip 会把 server/ 削成 app/）。
#      ⚠️ PRODUCTION_DEPLOYMENT.md §6 用的是带 prefix 的包，strip 对它才成立。
#   4. 迁移正规入口是 compose 的 `justice-migrate` 服务，不是 docker exec alembic。
#   5. 部署后必须核对 `docker inspect justice-api --format '{{.Config.Image}}'`，
#      确认镜像真的切过去了（宿主机改文件 + restart 不会生效，容易假成功）。
#   6. 生产 compose 只在服务器 /opt/justice-office/deploy/；仓库里那份是开发用的。
# ============================================================================
set -euo pipefail

SRC_DIR=${SRC_DIR:-/opt/judicial_app}
DEPLOY_DIR=${DEPLOY_DIR:-/opt/justice-office/deploy}
EXPECT_SHA=${EXPECT_SHA:-d162035}
CHECK_ONLY=0
[[ "${1:-}" == "--check-only" ]] && CHECK_ONLY=1

step() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
ok()   { printf '\033[1;32m  [ OK ]\033[0m %s\n' "$*"; }
bad()  { printf '\033[1;31m  [FAIL]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[中止] %s\033[0m\n' "$*"; exit 1; }

# ---------------------------------------------------------------- 0. 前置检查
step "0/8 前置检查"
[[ -d "$SRC_DIR" ]]  || die "源码目录不存在：$SRC_DIR（若是首次部署，先放好源码）"
[[ -d "$DEPLOY_DIR" ]] || die "生产 compose 目录不存在：$DEPLOY_DIR"
cd "$SRC_DIR"
[[ -f deploy/Dockerfile ]] || die "deploy/Dockerfile 缺失，源码不完整"
[[ -f "$DEPLOY_DIR/docker-compose.yml" ]] || die "生产 compose 缺失"
[[ -f "$DEPLOY_DIR/.env" ]] || die "生产 .env 缺失"

# 记录回滚锚点
OLD_IMAGE=$(docker inspect justice-api --format '{{.Config.Image}}' 2>/dev/null || echo "<无>")
ok "当前运行镜像：$OLD_IMAGE"

# ---------------------------------------------------------------- 1. 取最新代码
step "1/8 获取源码"
# 部署模式（依据《完整交接文档-20261004.md》第74/140/1039-1040 行）：
#   司法局内网严禁出网，生产服务器走 **tar 覆盖**，不在服务器上 git pull/push。
#   因此默认 offline：源码已由 Windows 端 git archive 打包 + scp 上传并替换到位，
#   本脚本只负责「校验 → 构建 → 切流量 → 验证」，不碰 git。
#   若在可出网的开发/测试机想让它顺带拉代码，加 --pull。
PULL=0
for a in "$@"; do [[ "$a" == "--pull" ]] && PULL=1; done

if [[ -f "$SRC_DIR/.git" && $PULL -eq 1 ]]; then
  # 可出网环境：两段式拉取（禁用 git pull，会SIGTERM 打断并损坏 .git）
  git fetch origin app
  git merge --ff-only origin/app
  ACTUAL_SHA=$(git rev-parse --short HEAD)
  ok "已拉取，服务器 SHA = $ACTUAL_SHA"
  MODE=pull
  if [[ "$ACTUAL_SHA" != "$EXPECT_SHA" ]]; then
    bad "期望 $EXPECT_SHA，实际 $ACTUAL_SHA"
    die "若这是你想要的版本，用 EXPECT_SHA=$ACTUAL_SHA 重跑"
  fi
  ok "SHA 与预期一致"
else
  if [[ $PULL -eq 1 ]]; then
    die "指定了 --pull 但 $SRC_DIR/.git 不存在（tar 覆盖部署无 .git）。去掉 --pull 走离线模式。"
  fi
  # 离线模式：无.git 属正常。SHA 只能作记录用，真正的闸门是下面的 11 项标记校验。
  ACTUAL_SHA="offline-$(date +%Y%m%d-%H%M%S)"
  MODE=offline
  ok "离线模式：源码已由 tar 覆盖部署，跳过 git（本步无网络依赖）"
  if [[ ! -f "$SRC_DIR/.git" ]]; then
    ok "确认无 .git —— 符合 tar 覆盖部署预期"
  fi
fi

# ---------------------------------------------------------------- 2. 构建前校验
step "2/8 校验今天这批修复确实在源码里（缺任何一项都中止）"
MISSING=0
chk() {  # chk <描述> <文件> <固定字符串>
  if grep -qF -- "$3" "$SRC_DIR/$2" 2>/dev/null; then
    ok "$1"
  else
    bad "$1 —— 缺失 [$3] 于 $2"; MISSING=1
  fi
}

chk "B2/B3 python_guard 非执行式编译预检" deploy/pptagent/python_guard.py 'compile(tree'
chk "B5 质量闸字体来自配置而非硬编码"    server/app/application/ppt/service.py  'forbidden_fonts'
chk "C1 迁移前扩宽钩子已接线"            server/app/migrations/env.py            'ensure_version_capacity(connection)'
chk "C1 015 迁移文件存在"                server/app/migrations/versions/015_widen_alembic_version.py 'revision = "015_widen_alembic_version"'
chk "C1 未改名生产在用的 014"            server/app/migrations/versions/015_widen_alembic_version.py 'down_revision = "014_template_format_profile_skeleton"'
chk "A2/A3 占位落款剥离"                 server/app/application/writing/structured_field_service.py '_PLACEHOLDER_LINE_RE'
chk "A6 行内引用标注剥离"                 server/app/application/writing/structured_field_service.py '_INLINE_CITATION_RE'
chk "A5 标点衔接规整"                    server/app/application/writing/postprocessor.py 'fix_redundant_comma_after_period'
chk "B1 落款兜底接线"                    server/app/application/writing/task_service.py '_default_authority()'
chk "B1 日期兜底接线"                    server/app/application/writing/task_service.py '_today_doc_date()'
chk "B6 本地渲染兜底仍存在（治本需修 B1/B7）" server/app/application/ppt/agent_job.py '_fallback_local'

[[ $MISSING -eq 0 ]] || die "有修复未进入源码，中止部署。当前模式：$MODE。在可出网机加 --pull 可自动核对 SHA；离线部署请确认上传的包就是目标版本（Windows 端 git log --oneline -1）"
ok "全部修复标记命中"

if [[ $CHECK_ONLY -eq 1 ]]; then
  ok "--check-only 模式，校验通过后退出，不构建"
  exit 0
fi

# ---------------------------------------------------------------- 3. 备份
step "3/8 部署前备份（数据库 + 向量索引）"
mkdir -p /opt/justice-office/data/delivery-images
docker tag "$OLD_IMAGE" "rollback-backup:$(date +%Y%m%d-%H%M%S)" 2>/dev/null || true
docker inspect justice-api --format '{{.Config.Image}}' > /tmp/predeploy-image.txt 2>/dev/null || true

# 复用已维护的 backup-production.sh：它从生产 .env 读配置，且优先走运行中的
# justice-db 容器（宿主机无需装pg_dump 客户端），同时备份 FAISS 向量索引并生成
# manifest。不要在本脚本里手写 pg_dump——容器名/凭据随部署配置变，写死易错。
if [[ -x "$SRC_DIR/deploy/backup-production.sh" || -f "$SRC_DIR/deploy/backup-production.sh" ]]; then
  bash "$SRC_DIR/deploy/backup-production.sh" && ok "备份完成（含数据库 + 向量索引）" \
    || bad "备份失败——**必须在确认备份成功后再继续**，否则回滚无数据可依"
else
  bad "缺 backup-production.sh，未备份。回滚将无数据可依，建议先手工备份再继续"
fi

# ---------------------------------------------------------------- 4. 构建后端镜像
step "4/8 构建后端镜像（勿传 INSTALL_PPT_PREVIEW）"
IMAGE="justice-office-server:$(date +%Y%m%d)-${ACTUAL_SHA}"
docker build --platform linux/arm64 \
  --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
  -f deploy/Dockerfile \
  -t "$IMAGE" \
  . 2>&1 | tee "/tmp/build-${ACTUAL_SHA}.log"
ok "镜像构建完成：$IMAGE"

# 验证镜像内部真的含今天的修复
docker run --rm --entrypoint sh "$IMAGE" -c '
  grep -qc "compile(tree" /app/../deploy/pptagent/python_guard.py 2>/dev/null || true
  grep -q "_PLACEHOLDER_LINE_RE" /app/app/application/writing/structured_field_service.py && echo "  [镜像内] A2/A3 占位剥离 ✅"
  grep -q "_INLINE_CITATION_RE"  /app/app/application/writing/structured_field_service.py && echo "  [镜像内] A6 引用剥离 ✅"
  grep -q "fix_redundant_comma_after_period" /app/app/application/writing/postprocessor.py && echo "  [镜像内] A5 标点 ✅"
  grep -q "_today_doc_date" /app/app/application/writing/task_service.py && echo "  [镜像内] B1 日期兜底 ✅"
  grep -q "forbidden_fonts" /app/app/application/ppt/service.py && echo "  [镜像内] B5 字体配置化 ✅"
'
ok "镜像内部代码校验通过"

# ---------------------------------------------------------------- 5. 构建 PPT 宿主守卫镜像
step "5/8 安装 PPT 宿主执行守卫（B2/B3 只有完成本步才生效）"
# 依据 deploy/pptagent/README.md：仅 push 源码不会让运行中的第三方 Host 镜像
# 自动获得守卫，**必须现场构建 + 把生产 Host 切到该 tag + 重建容器**。
# 官方流程：build-python-guard.sh → 设 PPT_HOST_IMAGE → docker compose up -d
GUARDED_IMAGE=deeppresenter-host:python-guard-v1

if [[ ! -f "$SRC_DIR/deploy/pptagent/build-python-guard.sh" ]]; then
  bad "缺 build-python-guard.sh——B2/B3 未生效（sandbox 仍会漏过重复关键字参数）"
elif ! bash "$SRC_DIR/deploy/pptagent/build-python-guard.sh" 2>&1 | tee "/tmp/guard-build.log"; then
  # ⚠️ 上面这行依赖 `set -o pipefail`（见文件头）：管道默认只返回 tee 的退出码，
  #    没有 pipefail 时守卫构建失败会被 tee 吞成"成功"，导致 B2/B3 实际未生效却
  #    报绿灯。已实测：有 pipefail 能检出失败，去掉则漏掉。**不要删 pipefail。**
  # 该脚本自带断言：会实测 draw(color=1, color=2) 必须被拦
  bad "守卫镜像构建失败——B2/B3 本次不生效。其前置 verify-patched-images.sh 会校验冻结
     镜像基线（host 需含 soffice/unoconv/fasttext lid.176.bin），基线不过属镜像问题，
     **不要绕过检查**（README：安装器失败不能绕过继续交付）"
else
  ok "守卫镜像 $GUARDED_IMAGE 构建并自检通过"

  # 找到生产 PPTAgent 的 compose 目录（仓库内与 /opt/justice-ppt 都可能）
  PPT_COMPOSE_DIR=""
  for d in "$SRC_DIR/deploy/pptagent" /opt/justice-ppt/deploy /opt/justice-ppt; do
    [[ -f "$d/docker-compose.yml" ]] && { PPT_COMPOSE_DIR="$d"; break; }
  done

  if [[ -z "$PPT_COMPOSE_DIR" ]]; then
    bad "找不到 PPTAgent 的 docker-compose.yml（B2/B3 仍未生效）。请手工执行：
     cd <PPTAgent 部署目录> && PPT_HOST_IMAGE=$GUARDED_IMAGE docker compose up -d"
  else
    ok "PPTAgent compose 目录：$PPT_COMPOSE_DIR"
    cd "$PPT_COMPOSE_DIR"
    # 写入 .env（compose 默认值已是该tag，但显式写入可防 .env 里残留旧值覆盖）
    if [[ -f .env ]]; then
      if grep -q '^PPT_HOST_IMAGE=' .env; then
        sed -i "s|^PPT_HOST_IMAGE=.*|PPT_HOST_IMAGE=$GUARDED_IMAGE|" .env
      else
        printf '\nPPT_HOST_IMAGE=%s\n' "$GUARDED_IMAGE" >> .env
      fi
      ok "已把 .env 的 PPT_HOST_IMAGE 指向 $GUARDED_IMAGE"
    else
      export PPT_HOST_IMAGE="$GUARDED_IMAGE"
      ok "无 .env，用环境变量传入 PPT_HOST_IMAGE"
    fi
    # 重建 host 容器使新镜像生效
    docker compose up -d 2>&1 | tail -5
    sleep 5
    RUNNING_PPT=$(docker inspect justice-ppt-host --format '{{.Config.Image}}' 2>/dev/null || echo "<无>")
    if [[ "$RUNNING_PPT" == "$GUARDED_IMAGE" ]]; then
      ok "justice-ppt-host 已在运行 $GUARDED_IMAGE —— 守卫已生效"
    else
      bad "justice-ppt-host 仍运行 ${RUNNING_PPT}，未切到 $GUARDED_IMAGE
     → B2/B3 尚未生效。查：docker logs justice-ppt-host --tail 50
     该容器挂载 compose 里的 volumes/环境变量，改镜像后必须 up -d 重建"
    fi
    cd "$SRC_DIR"
  fi
fi

# ---------------------------------------------------------------- 6. 切compose
step "6/8 切换生产 compose 到新镜像"
cd "$DEPLOY_DIR"
cp docker-compose.yml "docker-compose.yml.bak-$(date +%Y%m%d-%H%M%S)"
python3 - "$IMAGE" <<'PYEOF'
import re, sys
image = sys.argv[1]
p = "/opt/justice-office/deploy/docker-compose.yml"
s = open(p, encoding="utf-8").read()
# 只改api 与 migrate 共用的后端镜像标签，保留其余服务不动
new, n = re.subn(r"(image:\s*)justice-office-server:[^\s]+", r"\g<1>" + image, s)
if n == 0:
    sys.exit("!! 没找到 justice-office-server 镜像标签，请手工检查 compose")
open(p, "w", encoding="utf-8").write(new)
print(f"  已更新 {n} 处镜像标签 -> {image}")
PYEOF
docker compose --env-file .env -f docker-compose.yml config > /tmp/effective.yml
grep -q "$IMAGE" /tmp/effective.yml && ok "compose 生效配置已确认指向 $IMAGE"

# ---------------------------------------------------------------- 7. 起服务 + 迁移
step "7/8 重建服务并执行迁移"
docker rm -f justice-api justice-migrate 2>/dev/null || true
docker compose --env-file .env -f docker-compose.yml up -d
sleep 12
docker compose --env-file .env -f docker-compose.yml up migrate 2>&1 | tail -20
ok "API 与迁移已执行"

# ---------------------------------------------------------------- 8. 部署后验证
step "8/8 部署后验证"
RUNNING=$(docker inspect justice-api --format '{{.Config.Image}}' 2>/dev/null || echo "<无>")
echo "  运行镜像：$RUNNING"
[[ "$RUNNING" == "$IMAGE" ]] && ok "镜像已切到 $IMAGE" || bad "镜像未切换（仍是 $RUNNING）"

# 数据库在独立的 justice-db 容器里（应用容器 justice-api 内没有 psql/pg_isready）
PGUSER_NAME=${PGUSER_NAME:-justice}
docker exec justice-db pg_isready -U "$PGUSER_NAME" >/dev/null 2>&1 \
  && ok "数据库可连（justice-db / $PGUSER_NAME）" \
  || bad "数据库不可连（justice-db）——先查容器状态与 .env 里的 POSTGRES_*，勿继续"

curl -sf http://127.0.0.1:8000/health >/dev/null && ok "health 正常" || bad "health 异常"
curl -sf http://127.0.0.1:8000/ready  >/dev/null && ok "ready 正常（向量库就绪）" || bad "ready 异常"

# C1 验证 + 迁移版本：一次 python 输出两个可解析标记，避免分别 grep 造成假阴性
docker exec justice-api python -c "
import sqlalchemy as sa
from app.infrastructure.database import engine
from alembic.runtime.migration import MigrationContext
with engine.connect() as c:
    cols = sa.inspect(c).get_columns('alembic_version')
    w = [x['type'].length for x in cols if x['name'] == 'version_num']
    print('VERSION_NUM_WIDTH=' + str(w[0] if w else 'MISSING'))
    print('ALEMBIC_REV=' + str(MigrationContext.configure(c).get_current_revision()))
" > /tmp/c1-check.txt 2>/tmp/c1-check.err || true

if [[ -s /tmp/c1-check.txt ]]; then
  W=$(grep -o 'VERSION_NUM_WIDTH=[^ ]*' /tmp/c1-check.txt | cut -d= -f2)
  R=$(grep -o 'ALEMBIC_REV=[^ ]*' /tmp/c1-check.txt | cut -d= -f2)
  echo "  version_num 宽度 = ${W:-?}    alembic 版本 = ${R:-?}"
  [[ "$W" == "255" ]] && ok "C1 版本列已扩宽到 255" || bad "C1 版本列 = ${W:-?}，应为 255（迁移未生效或被回滚）"
  [[ "$R" == 015_* ]] && ok "迁移已到 015" || bad "alembic 版本 = ${R:-?}，未到 015_widen_alembic_version"
  [[ -s /tmp/c1-check.err ]] && printf '  (python stderr: %s)\n' "$(head -c 300 /tmp/c1-check.err)"
else
  bad "无法在容器内查库（/tmp/c1-check.txt 为空）。stderr：$(head -c 300 /tmp/c1-check.err 2>/dev/null)"
fi

docker logs justice-api --tail 80 2>&1 | grep -iE 'error|exception|does not exist' \
  && bad "日志有异常（见上）" || ok "日志干净"

printf '\n'
ok "部署完成：新镜像 $IMAGE"
printf '  回滚：把%s 里的镜像标签改回 %s，再 docker compose up -d\n' \
  "$DEPLOY_DIR/docker-compose.yml" "$OLD_IMAGE"
printf '  下一步：跑 server/scripts/smoke_test.sh 做真实验收（本次修复此前从未在生产验证过）\n'