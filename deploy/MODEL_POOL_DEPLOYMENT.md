# Ascend 多实例模型池部署与验收

本页只处理第 8 项：在现有单实例模型服务之外，利用已知备用 Ascend 设备增加同模型副本，并由后端 `QwenGateway` 做 endpoint 级负载分配与故障切换。

## 1. 已知条件与安全边界

目标机目前记录的备用设备为：`davinci0`、`davinci1`、`davinci5`、`davinci6`、`davinci7`。

仓库**不假定**现有主 Qwen2.5-14B / DeepPresenter-9B 占用了哪些卡。因此：

- 新实例只能从上述备用集合中显式选择；
- 启动前必须在目标机执行 `npu-smi info`，确认卡确实空闲；
- `deploy/ascend-model-pool.sh` 默认只 dry-run，只有 `APPLY=1` 才真正启动；
- 一个 `*_URLS` 池内必须是同一个模型、同一 API 契约的副本，禁止把 14B 与 DeepPresenter 混池；
- 如果现场 TP、显存或运行时要求与示例不同，用环境变量覆盖，不修改业务代码。

## 2. 推荐拓扑

现有生产地址保持不变：

```text
Qwen2.5-14B-Instruct  primary   :8003
DeepPresenter-9B      primary   :8004
```

新增副本建议：

```text
Qwen2.5-14B-Instruct  replica   :8005   devices 0,1   TP=2
DeepPresenter-9B      replica   :8006   devices 5,6   TP=2
davinci7                        保留，不默认占用
```

这只是默认部署模板，不代表硬件必须如此分配。若只需要第二个 14B，启动 `second-14b` 即可；若当前瓶颈在 PPT，再启动 `ppt-replica`。不要为了“用满卡”而启动无需求实例。

## 3. 启动前检查

```bash
cd /opt/judicial_app

npu-smi info
ss -tlnp | grep -E ':8003|:8004|:8005|:8006' || true

bash deploy/ascend-model-pool.sh plan
bash deploy/ascend-model-pool.sh second-14b
bash deploy/ascend-model-pool.sh ppt-replica
```

最后两条仍是 dry-run，只打印将执行的命令。确认设备、模型路径、vLLM 可执行文件和端口都正确后再实际启动：

```bash
APPLY=1 VLLM_BIN=/path/to/vllm \
  bash deploy/ascend-model-pool.sh second-14b

APPLY=1 VLLM_BIN=/path/to/vllm \
  bash deploy/ascend-model-pool.sh ppt-replica
```

如现场 DeepPresenter 只能单卡运行，可显式覆盖：

```bash
APPLY=1 PPT_REPLICA_DEVICES=5 PPT_TP_SIZE=1 \
  bash deploy/ascend-model-pool.sh ppt-replica
```

## 4. 实例探活后再加入 URL 池

任何副本**只有 `/v1/models` 通过后**才能写入生产 `.env`：

```bash
curl -fsS --max-time 10 http://127.0.0.1:8005/v1/models
curl -fsS --max-time 10 http://127.0.0.1:8006/v1/models
```

确认模型名与主实例一致后，生产配置改为：

```env
MODEL_SERVICE_URL=http://10.128.85.133:8003/v1
MODEL_SERVICE_URLS=http://10.128.85.133:8003/v1,http://10.128.85.133:8005/v1
MODEL_NAME=Qwen2.5-14B-Instruct

PPT_MODEL_URL=http://10.128.85.133:8004/v1
PPT_MODEL_URLS=http://10.128.85.133:8004/v1,http://10.128.85.133:8006/v1
PPT_MODEL_NAME=DeepPresenter-9B

MODEL_HEALTH_TIMEOUT=5
MODEL_FAILOVER_COOLDOWN=15
MODEL_MAX_CONCURRENCY=4
```

若只部署其中一个副本，只给对应池增加第二个 URL。未启动的端口禁止提前写入池。

修改 `.env` 后重启 API，使进程级 gateway 重新读取 endpoint 列表。

## 5. 后端分配策略

`QwenGateway` 的池内策略是：

1. 优先健康 endpoint；
2. 选择当前在途请求最少的 endpoint；
3. 在并列节点间 round-robin 打散；
4. `ConnectError`、timeout、HTTP 429、HTTP 5xx 会临时熔断该 endpoint 并切下一副本；
5. 普通 HTTP 4xx 视为请求本身错误，不换节点重复发送；
6. 全部 endpoint 都失败后才向业务层返回 `AIServiceError`。

`MODEL_MAX_CONCURRENCY` 是单 API 进程发向模型池的总并发上限，不是每个 endpoint 的独立上限。

当前 API 使用一个 worker。网关按登录用户轮转发放模型位，交互请求优先于后台任务；
后台任务最多占 `max(1, MODEL_MAX_CONCURRENCY-1)` 个位。
`MODEL_USER_MAX_CONCURRENCY` 限制同一用户的在途请求（默认 2），
`MODEL_USER_MAX_PENDING` 限制同一用户在队列中的请求（默认 8）。
这些是**进程内**额度；增加 API worker 前必须在模型服务或共享调度层增加跨进程总限流。
实际承载量还受模型实例的 token/s、提示词长度和生成长度限制；上线时用并发人数、
首 token 延迟、排队时长和 429 比例压测确定 `MODEL_MAX_CONCURRENCY`，不能仅按用户数估算。

## 6. 部署后验收

先运行标准 postcheck：

```bash
cd /opt/judicial_app
bash deploy/postcheck-production.sh
```

postcheck 会从 `justice-api` 容器当前环境读取 `MODEL_SERVICE_URLS` / `PPT_MODEL_URLS`，逐个访问 `/models`。任意已声明副本不可达都必须判失败。

再做负载/故障切换检查：

```bash
# 1. 连续发多次短请求，观察 8003/8005 两边访问日志都有请求。
# 2. 临时停止一个“副本”而不是唯一主实例，再发请求；业务应继续成功。
# 3. 恢复副本，等待 MODEL_FAILOVER_COOLDOWN 后再次观察其重新承接请求。
```

不得用“API health 200”代替模型池验收。至少要确认：

- 每个声明 endpoint 的 `/v1/models` 可达；
- 同池模型名一致；
- 正常请求能够分散到多个副本；
- 单个副本故障时请求可切到同池其他节点；
- 恢复后可重新进入池。

## 7. 回滚

如果新副本不稳定，最小回滚不是停整个 AI 服务，而是先从 `.env` 的对应 `*_URLS` 中移除新 URL，重启 API：

```env
MODEL_SERVICE_URLS=http://10.128.85.133:8003/v1
PPT_MODEL_URLS=http://10.128.85.133:8004/v1
```

确认业务恢复后再停止新增模型进程。保留 `MODEL_SERVICE_URL` / `PPT_MODEL_URL` 单实例变量是为了兼容这种快速回滚。
