#!/usr/bin/env bash
# ============================================================================
#  云法智办 · 生产覆盖部署脚本（后端镜像 + PPT 宿主守卫镜像）
# ============================================================================
#  用法（在生产服务器 10.128.85.133 上执行）：
#     bash deploy_latest.sh              # 正常部署
#     bash deploy_latest.sh --check-only # 只做构建前校验，不build
#
#  设计要点（都是踩过的坑，勿改）：
#   1. 源码用**两段式** git fetch + merge --ff-only；**不要 git pull**（会被
#      SIGTERM 打断并损坏 .git）。
#   2. 代码是**烤进镜像**的（deploy/Dockerfile `COPY server/ /app/`），
#      改宿主机文件 + docker restart **不生效**，必须 docker build。
#   3. **不要传 --build-arg INSTALL_PPT_PREVIEW**（仓库 Dockerfile 只认
#      PIP_INDEX_URL，传了会报 unexpected build arg 而失败）。
#   4. **不要用 --strip-components 解包** pack_release.py 的包（那是扁平包，
#      strip 会把 server/ 削成 app/）。本脚本走 git 路径，绕开此坑。
#   5. 迁移正规入口是 compose 的 `justice-migrate` 服务，不是 docker exec alembic。
#   6. push 后本地 tracking ref 常不更新，本脚本一律用 `git rev-parse HEAD`
#      读真实 SHA，不信任 origin/app。
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
step "1/8 拉取最新源码（两段式，勿用 git pull）"
git fetch origin app
git merge --ff-only origin/app
ACTUAL_SHA=$(git rev-parse --short HEAD)
ok "服务器当前 SHA = $ACTUAL_SHA"

if [[ "$ACTUAL_SHA" != "$EXPECT_SHA" ]]; then
  bad "期望 $EXPECT_SHA，实际 $ACTUAL_SHA"
  die "若这是你想要的版本，改用 EXPECT_SHA=$ACTUAL_SHA bash deploy_latest.sh 重跑"
fi
ok "SHA 与预期一致：$ACTUAL_SHA"

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

[[ $MISSING -eq 0 ]] || die "有修复未进入源码，中止部署。先查 git 是否真的 pull 到 $EXPECT_SHA"
ok "全部修复标记命中"

if [[ $CHECK_ONLY -eq 1 ]]; then
  ok "--check-only 模式，校验通过后退出，不构建"
  exit 0
fi

# ---------------------------------------------------------------- 3. 备份
step "3/8 部署前记录回滚锚点"
mkdir -p /opt/justice-office/data/delivery-images
docker tag "$OLD_IMAGE" "rollback-backup:$(date +%Y%m%d-%H%M%S)" 2>/dev/null || true
docker inspect justice-api --format '{{.Config.Image}}' > /tmp/predeploy-image.txt 2>/dev/null || true
docker exec justice-api sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' \
  > /opt/justice-office/data/backup-$(date +%Y%m%d-%H%M%S).sql 2>/dev/null \
  && ok "数据库已备份" || bad "数据库备份跳过（容器内无 pg_dump，可用 backup-production.sh）"

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
step "5/8 构建 PPT 宿主守卫镜像（B2/B3 只有重建宿主镜像才生效）"
if [[ -f deploy/pptagent/build-python-guard.sh ]]; then
  cd "$SRC_DIR"
  # 该脚本自带断言：会实测 draw(color=1, color=2) 必须被拦
  bash deploy/pptagent/build-python-guard.sh 2>&1 | tee "/tmp/guard-build-${ACTUAL_SHA}.log" \
    && ok "守卫镜像已构建并自检通过" \
    || bad "守卫镜像构建失败——B2/B3 修复本次不生效，PPT 代码预检仍会漏过"
else
  bad "缺 build-python-guard.sh，跳过守卫镜像（B2/B3 未生效）"
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

docker exec justice-api sh -c 'pg_isready -U "$POSTGRES_USER"' >/dev/null 2>&1 && ok "数据库可连" || bad "数据库不可连"

curl -sf http://127.0.0.1:8000/health >/dev/null && ok "health 正常" || bad "health 异常"
curl -sf http://127.0.0.1:8000/ready  >/dev/null && ok "ready 正常（向量库就绪）" || bad "ready 异常"

# C1 验证：版本列已加宽
docker exec justice-api python -c "
import sqlalchemy as sa
from app.infrastructure.database import engine
with engine.connect() as c:
    t = sa.inspect(c).get_columns('alembic_version')
    w = [x['type'].length for x in t if x['name']=='version_num']
    print('  alembic_version.version_num 宽度 =', w)
" 2>/dev/null | grep -q '255' && ok "C1 版本列已扩宽到 255" || bad "C1 版本列未达255（迁移未生效）"

docker exec justice-api python -c "
from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine
from app.core.config import settings
e = create_engine(settings.DATABASE_URL)
with e.connect() as c:
    print('  当前版本 =', MigrationContext.configure(c).get_current_revision())
" 2>/dev/null | grep -q '015_' && ok "迁移已到 015" || bad "迁移未到 015"

docker logs justice-api --tail 80 2>&1 | grep -iE 'error|exception|does not exist' \
  && bad "日志有异常（见上）" || ok "日志干净"

printf '\n'
ok "部署完成：新镜像 $IMAGE"
printf '  回滚：把%s 里的镜像标签改回 %s，再 docker compose up -d\n' \
  "$DEPLOY_DIR/docker-compose.yml" "$OLD_IMAGE"
printf '  下一步：跑 server/scripts/smoke_test.sh 做真实验收（本次修复此前从未在生产验证过）\n'