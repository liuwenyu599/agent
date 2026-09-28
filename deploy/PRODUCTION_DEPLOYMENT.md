# 白云司法局智慧办公平台：生产部署与验收手册

> 适用范围：司法局生产服务器 `10.128.85.133`。  
> 目标：避免“源码已改、容器仍跑旧代码”“配置路径在宿主机正确、容器内不可见”“PPT 后端成功、客户端误判失败”等假完成。  
> 原则：生产环境不从 GitHub 拉代码；使用 Windows 开发机打包后通过 SCP 传入，生产密钥与源码包分离。

## 0. 镜像策略

本次部署**只重建** `justice-office-server`，并使用唯一 tag：

```text
justice-office-server:<日期>-<sha短码>
```

例如：

```text
justice-office-server:20260929-b89af290
```

`deeppresenter-sandbox:latest` 和 `deeppresenter-host:latest` 保持 **2026-09-28 全天排障后的 commit 版本**，本次部署不重建这两个镜像。但它们承载 PPT 链路的关键补丁，部署前必须验证补丁完整性；`preflight-production.sh` 会自动检查，任一补丁缺失都必须先从交付镜像归档恢复。

期望输出：

```text
[ OK ] sandbox 镜像补丁完整
[ OK ] host 镜像补丁完整
```

## 0.1 部署顺序总览

```text
Windows 端人工确认客户端行为
（TIMEOUT_STATUS_MS >= 30000 且判定依据是 job_status）
命令见 preflight 脚本末尾打印的提示
        ↓
Windows 确认 app SHA
        ↓
生成并上传源码包
        ↓
备份数据库 / 配置 / 旧源码
        ↓
归档 sandbox / host / rollback-server 三个交付镜像
        ↓
替换服务器源码
        ↓
preflight-production.sh
        ↓
只重建 justice-office-server:<日期>-<sha短码>
        ↓
切换 compose 并启动
        ↓
postcheck-production.sh
        ↓
客户端 2 页 PPT E2E
        ↓
客户端 10 页 PPT E2E
        ↓
角色权限与核心业务抽测
        ↓
最终签字
```

## 1. 先纠正旧交接中的几个错误判断

1. **不能再复用同一个镜像标签当作新版本。**  
   旧流程反复构建 `justice-office-server:2.6.6`，会造成镜像不可追溯、回滚对象不明确。生产构建必须生成唯一标签，例如：
   `justice-office-server:20260929-e8dcdb2`。旧镜像保留，验证通过后再切 compose。

2. **不能以“宿主机源码已改”判断修复完成。**  
   真正运行的是 `justice-api` 容器中的镜像代码。部署后必须进入镜像/容器 grep 关键修复，再做 API 与端到端验证。

3. **客户端任务成功/失败判定必须在 Windows 端人工确认。**  
   服务器端不能替客户端下结论。部署前按 preflight 脚本末尾打印的 `findstr` 命令检查：任务终态判断依据应为 `job_status`，不能把历史 `job_error` 是否为空作为成功/失败依据。

4. **客户端状态请求等待时间必须人工确认。**  
   部署前在 Windows 端检查 `TIMEOUT_STATUS_MS`，验收要求为 **>= 30000 ms**。部署文档不假设当前源码具体取值；不满足时先修客户端，再继续生产部署。

5. **PPT 页数不能只靠提示词。**  
   当前源码已同时修正：
   - 服务端允许最少 2 页；
   - 提示词要求 slides 数组严格等于用户页数；
   - normalize 层对最终页数做硬约束；
   - 少页时只补“待根据已确认材料补充”的显式占位页，不编造事实。

6. **PPT 预览时间不能依赖宿主机时区。**  
   `job_started_at` 是东八区语义的 naive datetime。当前源码已显式按 `CN_TZ` 转换后再计算 timestamp，避免 UTC Docker 把新预览图误判为旧文件。

7. **生产配置不能跟源码覆盖。**  
   `/opt/justice-office/deploy/.env`、数据库数据目录、PPTAgent 配置与缓存都不得被代码 tar 包覆盖。

## 1.0 交付镜像归档

在执行 preflight 之前，必须先把 2026-09-28 已验证的 sandbox / host 镜像和当前后端镜像保存为可恢复 tar：

```bash
mkdir -p /opt/justice-office/data/delivery-images

docker save deeppresenter-sandbox:latest \
  -o /opt/justice-office/data/delivery-images/sandbox.tar

docker save deeppresenter-host:latest \
  -o /opt/justice-office/data/delivery-images/host.tar

docker tag justice-office-server:2.6.6 justice-office-server:rollback
docker save justice-office-server:rollback \
  -o /opt/justice-office/data/delivery-images/rollback-server.tar

ls -lh /opt/justice-office/data/delivery-images/
```

期望至少看到：

```text
sandbox.tar
host.tar
rollback-server.tar
```

三个 tar **必须全部存在且非空**，才能进入 preflight。缺任何一个都表示交付镜像未归档，无法保证可恢复。

## 1.1 随包自带的两道部署闸门

服务器替换源码后、构建镜像前先执行：

```bash
chmod +x /opt/judicial_app/deploy/preflight-production.sh
/opt/judicial_app/deploy/preflight-production.sh
```

只有看到 `PRE-FLIGHT PASSED` 才继续构建。

新容器启动后执行：

```bash
chmod +x /opt/judicial_app/deploy/postcheck-production.sh
/opt/judicial_app/deploy/postcheck-production.sh
```

只有看到 `POST-CHECK PASSED` 才进入客户端 2 页 / 10 页 PPT 端到端验收。这两个脚本不会读取或打印生产密码，只检查必须的路径、URL、挂载、模型、字体、数据库存活与关键源码修复。

## 2. 本次部署前置条件

以下条件全部满足才开始部署：

- 当前生产服务可用，`justice-db` 数据正常；
- 至少保留 20 GB 根分区可用空间；
- Windows 开发机 `app` 分支已更新到待部署版本，并且 Acceptance Gate 通过；
- 生产服务器已有：
  - `/opt/justice-office/deploy/.env`
  - `/opt/justice-office/deploy/docker-compose.yml`
  - `/opt/justice-ppt/deeppresenter/config.yaml`
  - `/opt/justice-ppt/deeppresenter/mcp.json`
  - `/opt/justice-ppt/workspace`
  - `/opt/justice-ppt/cache/lid.176.bin`
- 模型目录存在：
  - `/home/lcode/Qwen2.5-14B-Instruct`
  - `/home/lcode/Qwen2.5-VL-7B-Instruct`
  - `/home/lcode/DeepPresenter-9B`
  - `/home/lcode/bge-m3`

## 3. Windows：构建部署包

在 PowerShell：

```powershell
cd D:\Projects\judicial_app

git checkout app
git status
git rev-parse --short HEAD
```

必须确认工作区只有你明确要部署的改动。记录 SHA：

```powershell
$SHA = (git rev-parse --short HEAD).Trim()
$PKG = "D:\judicial_app_$SHA.tar.gz"

tar czf $PKG `
  --exclude=".git" --exclude=".idea" --exclude=".gradle" `
  --exclude="build" --exclude="data" --exclude="logs" `
  --exclude="__pycache__" --exclude="*.pyc" `
  --exclude="deploy/offline" --exclude=".workbuddy" --exclude=".pytest_cache" `
  --exclude=".tmp" --exclude="node_modules" --exclude=".venv" `
  --exclude="dist" --exclude="out" --exclude="*.tar.gz" --exclude="*.zip" `
  --exclude="*.env" --exclude="justice-server.env" `
  -C D:\Projects judicial_app

scp $PKG root@10.128.85.133:/tmp/
```

不要把 `.env`、数据库、日志、模型或生产密钥打进代码包。

## 4. 生产服务器：部署前完整备份

SSH 登录后：

```bash
set -euo pipefail

TS=$(date +%Y%m%d_%H%M%S)
mkdir -p /opt/justice-office/data/backups/delivery-$TS

docker exec justice-db pg_dump -U justice -d justice -Fc \
  > /opt/justice-office/data/backups/delivery-$TS/justice.dump

cp -a /opt/justice-office/deploy/.env \
  /opt/justice-office/data/backups/delivery-$TS/justice-office.env
cp -a /opt/justice-office/deploy/docker-compose.yml \
  /opt/justice-office/data/backups/delivery-$TS/docker-compose.yml
cp -a /opt/justice-ppt/deeppresenter/config.yaml \
  /opt/justice-office/data/backups/delivery-$TS/deeppresenter-config.yaml
cp -a /opt/justice-ppt/deeppresenter/mcp.json \
  /opt/justice-office/data/backups/delivery-$TS/deeppresenter-mcp.json

if [ -d /opt/judicial_app ]; then
  tar czf /opt/justice-office/data/backups/delivery-$TS/judicial_app.tar.gz \
    -C /opt judicial_app
fi

docker inspect justice-api --format '{{.Config.Image}}' \
  > /opt/justice-office/data/backups/delivery-$TS/api-image.txt

echo "BACKUP_DIR=/opt/justice-office/data/backups/delivery-$TS"
ls -lh /opt/justice-office/data/backups/delivery-$TS
```

任何一步失败都不要继续。

## 5. 校验生产配置

生产 `.env` 中这几个值必须是：

```env
MODEL_SERVICE_URL=http://10.128.85.133:8003/v1
MODEL_NAME=Qwen2.5-14B-Instruct
MODEL_CTX_LIMIT=16384

VISION_MODEL_URL=http://10.128.85.133:8002/v1
VISION_MODEL_NAME=Qwen2.5-VL-7B-Instruct

PPT_MODEL_URL=http://10.128.85.133:8004/v1
PPT_MODEL_NAME=DeepPresenter-9B

PPT_AGENT_URL=http://10.128.85.133:7861
PPT_AGENT_SUBMIT_PATH=/gradio_api/call/send_message
PPT_AGENT_TOTAL_TIMEOUT=1800
PPT_AGENT_WORKSPACE_DIR=/data/pptagent

OCR_ENABLED=false
```

严禁把 `PPT_AGENT_WORKSPACE_DIR` 写成宿主机路径 `/opt/justice-ppt/workspace`。

Compose 的 API 服务必须有：

```yaml
volumes:
  - ${HOST_DATA_DIR}:/data/justice
  - /opt/justice-ppt/workspace:/data/pptagent:ro
  - /home/lcode/bge-m3:/models/bge-m3:ro
  - /usr/share/fonts/truetype/chinese:/usr/share/fonts/truetype/chinese:ro
  - /usr/share/fonts/gb-cjk:/usr/share/fonts/gb-cjk:ro
```

快速检查：

```bash
cd /opt/justice-office/deploy

grep -E '^(MODEL_SERVICE_URL|MODEL_CTX_LIMIT|VISION_MODEL_URL|PPT_MODEL_URL|PPT_AGENT_URL|PPT_AGENT_WORKSPACE_DIR)=' .env

docker compose --env-file .env -f docker-compose.yml config | \
  grep -E 'data/pptagent|bge-m3|chinese|gb-cjk'
```

## 6. 替换服务器源码

假设上传包是 `/tmp/judicial_app_<SHA>.tar.gz`：

```bash
set -euo pipefail

SHA=<把 Windows git rev-parse 的短 SHA 填这里>
PKG=/tmp/judicial_app_${SHA}.tar.gz

test -s "$PKG"

rm -rf /opt/judicial_app.new
mkdir -p /opt/judicial_app.new
tar xzf "$PKG" -C /opt/judicial_app.new --strip-components=1

test -f /opt/judicial_app.new/server/app/main.py
test -f /opt/judicial_app.new/deploy/Dockerfile

rm -rf /opt/judicial_app.prev
if [ -d /opt/judicial_app ]; then
  mv /opt/judicial_app /opt/judicial_app.prev
fi
mv /opt/judicial_app.new /opt/judicial_app
```

这里不复制任何生产 `.env`。

## 7. 在构建前检查关键修复已经进入源码

```bash
cd /opt/judicial_app

! grep -R 'max(6, min' server/app/application/ppt/service.py
grep -n 'max(2, min' server/app/application/ppt/service.py
grep -n '页数硬约束' server/app/application/ppt/ppt_engine.py
grep -n '不要虚构材料中没有的事实和数据' \
  server/app/application/ppt/ppt_engine.py
grep -n 'replace(tzinfo=CN_TZ)' server/app/application/ppt/agent_job.py
```

其中任何一项没有命中，都停止部署。

## 8. 构建唯一版本后端镜像

不要覆盖旧标签。

```bash
cd /opt/judicial_app

SHA=<同上>
IMAGE=justice-office-server:$(date +%Y%m%d)-${SHA}

docker build --platform linux/arm64 \
  --build-arg INSTALL_PPT_PREVIEW=true \
  --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
  -f deploy/Dockerfile \
  -t "$IMAGE" \
  . 2>&1 | tee /tmp/build-${SHA}.log

echo "$IMAGE"
```

构建后直接验证镜像内部代码：

```bash
docker run --rm --entrypoint sh "$IMAGE" -c '
  grep -n "max(2, min" /app/app/application/ppt/service.py
  grep -n "页数硬约束" /app/app/application/ppt/ppt_engine.py
  grep -n "replace(tzinfo=CN_TZ)" /app/app/application/ppt/agent_job.py
'
```

## 9. 切换生产 compose 到新镜像

```bash
cd /opt/justice-office/deploy
grep -n 'justice-office-server:' docker-compose.yml
```

将 API 服务的 image 改成刚构建的唯一标签，例如：

```yaml
image: justice-office-server:20260929-e8dcdb2
```

不要修改数据库、模型或 PPTAgent 镜像。

确认最终 compose：

```bash
docker compose --env-file .env -f docker-compose.yml config > /tmp/justice-compose.effective.yml
grep -n 'justice-office-server:' /tmp/justice-compose.effective.yml
grep -n '/data/pptagent' /tmp/justice-compose.effective.yml
```

## 10. 重建 API

```bash
cd /opt/justice-office/deploy

docker rm -f justice-api justice-migrate 2>/dev/null || true
docker compose --env-file .env -f docker-compose.yml up -d

sleep 40
docker ps -a --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}' | grep justice
docker logs justice-migrate --tail 100 2>/dev/null || true
```

## 11. 部署后机器级验证

### API

```bash
curl -fsS http://127.0.0.1:8000/health
```

### 三个模型

```bash
for p in 8002 8003 8004; do
  echo "===== $p ====="
  curl -fsS --max-time 10 http://127.0.0.1:$p/v1/models | head -c 300
  echo
done
```

### PPTAgent

```bash
curl -sS -o /dev/null -w 'PPTAgent HTTP=%{http_code}\n' \
  --max-time 10 http://127.0.0.1:7861/
```

### API 容器能访问模型与 PPTAgent

```bash
docker exec justice-api sh -c '
set -e
for p in 8002 8003 8004 7861; do
  code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 http://10.128.85.133:$p/)
  echo "$p -> $code"
  test "$code" != "000"
done
'
```

### 共享工作区

```bash
docker exec justice-api sh -c '
echo "PPT_AGENT_WORKSPACE_DIR=$PPT_AGENT_WORKSPACE_DIR"
test "$PPT_AGENT_WORKSPACE_DIR" = "/data/pptagent"
test -d /data/pptagent
ls -ld /data/pptagent
'
```

### 字体

```bash
docker exec justice-api sh -c 'fc-list :lang=zh | wc -l'
```

### 数据库

```bash
docker exec justice-db psql -U justice -d justice -c 'SELECT count(*) FROM users;'
```

## 12. 客户端编译与启动

Windows：

```powershell
cd D:\Projects\judicial_app\desktop
.\gradlew.bat clean
.\gradlew.bat compileKotlinJvm --console=plain
.\gradlew.bat run --console=plain
```

客户端服务器地址设为：

```text
http://10.128.85.133:8000
```

## 13. 最关键的 2 页 PPT 端到端验收

这一步不过，不能宣布交付成功。

1. 打开 PPT 助手；
2. 输入一个有真实材料依据的主题；
3. 页数填写 **2**；
4. 上传一份短材料；
5. 点击“生成大纲”；
6. 确认大纲必须正好 **2 页**；
7. 点击“确认大纲并生成 PPT”；
8. 生成期间应看到任务状态，已有预览图时应逐页出现；
9. 完成后必须得到真实可打开的 `.pptx`；
10. 文件页数必须与确认大纲一致。

服务器观察：

```bash
docker logs -f justice-api
```

另开终端：

```bash
find /opt/justice-ppt/workspace -type f \
  \( -name 'slide_*.jpg' -o -name 'slide_*.png' -o -name '*.pptx' \) \
  -printf '%TY-%Tm-%Td %TH:%TM:%TS %p\n' | sort | tail -30
```

数据库检查：

```bash
docker exec justice-db psql -U justice -d justice -c "
SELECT id,title,status,slide_count,job_status,job_phase,
       job_current_page,job_total_pages,job_renderer,job_error,
       job_started_at,job_finished_at
FROM ppt_documents
ORDER BY job_started_at DESC NULLS LAST
LIMIT 5;"
```

验收标准：

- `job_status=succeeded`；
- 客户端不能因为历史 `job_error` 残值显示失败；
- 最终 pptx 存在且 PowerPoint/LibreOffice 可正常打开；
- 2 页请求最终就是 2 页；
- 不允许出现模型自行编造的数字、排名、日期；
- 使用材料中的数字时应能在大纲 sources 中追溯来源。

## 14. 快速定位失败层

API：

```bash
docker logs justice-api --tail 200
```

模型：

```bash
docker logs justice-qwen-14b --tail 100
docker logs justice-qwen-7bvl --tail 100
docker logs justice-deeppresenter-9b --tail 100
```

PPTAgent：

```bash
docker logs justice-ppt-host --tail 200
```

看不到预览：

```bash
grep '^PPT_AGENT_WORKSPACE_DIR=' /opt/justice-office/deploy/.env
docker exec justice-api ls -la /data/pptagent | head
```

第一条不是 `/data/pptagent` 或第二条看不到 workspace 内容时，不要改客户端，先修挂载。

## 15. 回滚步骤

如果 `postcheck-production.sh` 失败，或者 2 页 / 10 页 PPT 端到端验收失败，不要在新镜像上继续临时打补丁，直接回滚后端：

```bash
cd /opt/justice-office/deploy

cp docker-compose.yml docker-compose.yml.rollback-$(date +%Y%m%d_%H%M%S)

sed -i 's|justice-office-server:[^ "]*|justice-office-server:rollback|' docker-compose.yml

docker rm -f justice-api justice-migrate
docker compose --env-file .env -f docker-compose.yml up -d

sleep 40
curl -s http://127.0.0.1:8000/health
```

期望：

```text
HTTP 200，health 返回正常状态
```

如本次新版本执行过数据库迁移，且迁移与旧版本不兼容，**必须在回滚 API 前停止业务写入**，再从部署前备份恢复数据库。备份文件位置：

```text
/opt/justice-office/data/backups/delivery-YYYYMMDD/justice.dump
```

实际目录以第 4 节执行备份时输出的 `BACKUP_DIR` 为准。

如还需要回滚服务器源码：

```bash
rm -rf /opt/judicial_app.failed
mv /opt/judicial_app /opt/judicial_app.failed
mv /opt/judicial_app.prev /opt/judicial_app
```

sandbox / host 镜像补丁损坏时分别恢复：

```bash
docker load -i /opt/justice-office/data/delivery-images/sandbox.tar
docker load -i /opt/justice-office/data/delivery-images/host.tar
```

恢复后必须重新执行 preflight，再启动服务。

## 16. 最终交付签字条件

必须同时满足：

- Desktop Compose 编译通过；
- 后端 Acceptance Gate 全量测试通过；
- API、数据库、三个模型、PPTAgent 均可达；
- API 容器内 `PPT_AGENT_WORKSPACE_DIR=/data/pptagent` 且挂载可读；
- 2 页 PPT 端到端成功并得到真实 pptx；
- 10 页常规 PPT 再跑一次成功；
- 普通用户、科室管理员、系统管理员三角色权限各抽测一次；
- 知识库检索、智能写作、格式校验各完成一条主流程；
- 生产数据库和配置已做交付备份；
- 当前镜像标签、源码 SHA、部署时间写入交付记录。

任意一项未满足，状态只能写“待复验”，不能写“已交付”。
