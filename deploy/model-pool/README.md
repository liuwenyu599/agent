# 模型池 Compose（deploy/model-pool）

把原来靠 shell 脚本裸进程管理的模型服务，统一成 Docker Compose。
本目录只管**模型推理服务**；后端 API（`deploy/docker-compose.yml`）和 PPT 栈
（`deploy/pptagent/docker-compose.yml`）各自独立，互不影响。

## 1. 拓扑（8×昇腾 310P3，davinci0~7）

| 芯片 | 服务 | 端口 | 模型 | 启动方式 |
|---|---|---|---|---|
| 0,1 | `qwen35b-main` | 8010 | Qwen3.6-35B-A3B-W8A8（W8A8，多模态 MoE） | `docker compose up -d` |
| 2,3 | `qwen38-27b-trial` | 8011 | 新一代 27B 多模态（待下载） | `--profile trial` |
| 4 | `qwen-flash-next-trial` | 8012 | 轻量多模态（待下载） | `--profile trial` |
| 5,6 | DeepPresenter-9B | 8004 | DeepPresenter-9B | `deploy/pptagent` 栈（不变） |
| 7 | `qwen14b-rollback` | 8003 | Qwen2.5-14B-Instruct | `--profile rollback` 应急才起 |

试用模型来自外部建议（2026-10-20）：27B 与 flash-next 都是较新的多模态，
先下载试跑、用同一套 compare 脚本对比后再决定是否扶正；flash-next 若响应快，
可后续承接意图理解/问答等高频短任务给 35B 分流。权重到位后：
`.env` 填 `QWEN38_27B_MODEL_PATH` / `QWEN_FLASH_MODEL_PATH` →
`docker compose --profile trial up -d <服务名>`。**W8A8 量化版才加
`--quantization ascend`（用 `*_EXTRA_ARGS` 传），BF16 版严禁加。**
| 2,3,4 | 空闲预留 | - | - | 第三副本/紧急扩容 |

**一套 35B 接管原来三个模型的活**：
- 文本（原 `MODEL_*` → 14B:8003）：写作、问答、意图理解
- 视觉（原 `VISION_*` → Qwen2.5-VL-7B:8002）：图片附件理解、文档 OCR——35B 本身多模态，**VL-7B 退役**
- 长文（`LONG_FORM_*`，后端已预留该网关）：带 `enable_thinking:false` 请求级双保险

后端零代码改动，全部靠 `.env` 切换（见第 4 节）。

## 2. 快速启动

```bash
cd deploy/model-pool
cp .env.example .env          # 按注释确认 HOST_MODEL_DIR
npu-smi info                  # ⚠ 确认 davinci0/1 空闲（旧 14B 裸进程占着就先停）
docker compose up -d          # 起 35B；权重加载约 5~15 分钟
docker compose logs -f qwen35b-main
curl -s http://127.0.0.1:8010/v1/models      # 探活：应返回 Qwen3.6-35B-A3B-W8A8
```

## 3. 生产上线顺序（重要）

35B 要 davinci0,1，而现网旧 14B 主实例占 davinci0，直接 up 会撞卡。按序执行：

1. **停旧模型裸进程**（compose 化之前它们是 nohup 起来的，不受 compose 管）：
   ```bash
   lsof -ti:8003 | xargs -r kill        # 旧 14B 主（确认 PID 确实是 vllm 再杀）
   lsof -ti:8002 | xargs -r kill        # 旧 VL-7B（确认后杀，此模型退役）
   ```
2. `npu-smi info` 确认 0,1 已释放。
3. `docker compose up -d` 起 35B，探活 `/v1/models`。
4. **改后端 `.env`**（`/opt/justice-office/deploy/.env`，见第 4 节）。
5. 重建后端使新 `.env` 生效：`cd /opt/justice-office/deploy && docker compose up -d`
   （后端镜像是代码烤进的，`.env` 走 compose env_file，重建容器即生效）。
6. 验收：`BASE=http://127.0.0.1:8000 bash server/scripts/smoke_test.sh`
   （写作任务全流程 + PPT；观察回复质量与耗时）。
7. 观察期建议 ≥1 天。35B 是 MoE（激活约 3B），速度不差；质量按公文写作场景抽查。

## 4. 后端 .env 需要改的段（`deploy/.env.example` 已同步为相同结构）

```bash
# 文本主模型 → 35B
MODEL_SERVICE_URL=http://10.128.85.133:8010/v1
MODEL_SERVICE_URLS=http://10.128.85.133:8010/v1
MODEL_NAME=Qwen3.6-35B-A3B-W8A8

# 视觉 → 同一个 35B（多模态，模型名相同；留空则图片退回 OCR 文本通道）
VISION_MODEL_URL=http://10.128.85.133:8010/v1
VISION_MODEL_NAME=Qwen3.6-35B-A3B-W8A8

# 长文 → 35B（后端会自带 chat_template_kwargs enable_thinking:false）
LONG_FORM_MODEL_URLS=http://10.128.85.133:8010/v1
LONG_FORM_MODEL_NAME=Qwen3.6-35B-A3B-W8A8
LONG_FORM_MODEL_TIMEOUT=600
```

PPT 段（`PPT_*`，指向 DeepPresenter-9B:8004）**不用动**。

注意：
- 35B 的 `--max-model-len 16384` 与 `MODEL_CTX_LIMIT=16384` 一致，保持即可；
- 容器级已带 `--default-chat-template-kwargs '{"enable_thinking": false}'`，
  长文网关的请求级参数是双保险，两者不冲突；
- 一个 URL 池内只能是**同一个模型**——不要把 14B 和 35B 混进 `MODEL_SERVICE_URLS`。

## 5. 回滚（35B 有问题时切回 14B）

```bash
# 1) 起 14B 回滚实例（davinci7，:8003）
docker compose --profile rollback up -d
curl -s http://127.0.0.1:8003/v1/models

# 2) 后端 .env 改回：
#    MODEL_SERVICE_URL(S)=http://10.128.85.133:8003/v1
#    MODEL_NAME=Qwen2.5-14B-Instruct
#    VISION_* 按需恢复 VL-7B（如仍有该裸进程）；LONG_FORM_MODEL_URLS 清空
# 3) 重建 justice-api
```

停 35B：`docker compose down`（只停模型服务，不动数据库和后端）。
停 14B 回滚实例：`docker compose --profile rollback down`。

## 6. 35B 关键 flag 说明（真机验证版，勿随意改）

| flag | 作用 |
|---|---|
| `--tensor-parallel-size 2` | 双卡 TP；W8A8 权重约 35GB，双卡 86GB 余量充足 |
| `--quantization ascend` | 昇腾 W8A8 量化路径（此版本需要显式指定才能走 ascend kernel） |
| `--additional-config ...enable_npugraph_ex:false` + `--compilation-config cudagraph_mode:FULL_DECODE_ONLY` | 310P 图捕获死锁的规避组合，替代早期 `--enforce-eager`（保速度） |
| `--default-chat-template-kwargs '{"enable_thinking": false}'` | 容器级默认关闭思考，防 CoT 漏进正文（裸端点直连也生效） |
| `--max-num-seqs 8` / `--gpu-memory-utilization 0.90` | 并发与显存水位 |
| `--dtype float16` / `--trust-remote-code` | 精度与自定义代码 |

> 与仓库旧文档的分歧（以真机验证版为准）：早期 `setup-qwen35b.sh` 的
> `--enforce-eager --mamba-ssm-cache-dtype float16 --no-enable-prefix-caching`、
> TP=4、不加 `--quantization` 的结论**已被本版本取代**；旧脚本已标 deprecated，
> 保留仅作历史参考。

## 7. 与其它栈的共存关系

- **PPT 栈**（`deploy/pptagent`）：DeepPresenter-9B 是 PPT 生成专用模型，
  独立 compose、独立网络 `justice-network`，不并入本目录。占卡见其 `.env`。
- **后端栈**（`deploy/docker-compose.yml`）：通过宿主机 IP:8010 调 35B，
  无需加挂设备；把后端容器接入 `justice-network` 才能调 PPT Host(:7861)。
- 旧脚本 `deploy/ascend-model-pool.sh`、`deploy/qwen35b/setup-qwen35b.sh`
  已 deprecated，功能由本 compose 取代；`check-qwen35b.sh` / `test-qwen35b.sh`
  仍可用来验收本 compose 起的实例（改一下端口变量即可）。

## 8. 模型对比验收脚本

`deploy/qwen35b/compare_14b_vs_35b.py`：同一批公文任务（通知/请示/讲话稿）
分别打两个模型，对比结构合规（落款三件套）、占位符、思考泄漏、tok/s，
输出报告与切换建议。仅依赖 python3 标准库：

```bash
# 生产服务器（35B 与 14B 都在时）
python3 deploy/qwen35b/compare_14b_vs_35b.py
# 对比 27B 试用实例时把 35B 列换成它
URL35B=http://127.0.0.1:8011/v1 MODEL35B=Qwen3.8-27B \
    python3 deploy/qwen35b/compare_14b_vs_35b.py
```

## 9. 后续方向（外部建议，未排期）

- **PPT 试 drawio MCP + 本地模型调用**：当前 PPT 链路是 DeepPresenter-9B +
  PPTAgent（Gradio）出 pptx。可尝试让本地模型（35B/flash-next）通过 drawio
  MCP 直接画图表型 PPT 页，作为渲染通道的备选/补充。属架构级改动，
  需先做技术验证（MCP 客户端接在哪、drawio 文件如何转 pptx/pdf），
  验证通过再排期，勿影响现有 PPTAgent 链路。

## 10. 多 35B 副本：按用途隔离（2026-11-12 生产实测后新增）

### 10.1 为什么要副本，而不是「加大并发」

在单端点 `10.128.85.133:8010`（35B，TP=2，`--max-num-seqs 8`，
`--gpu-memory-utilization 0.90`）上实测：

| 场景 | 墙钟 | 交互式写作短请求 TTFT |
|---|---|---|
| 单条 PPT 长构图 | 27.8s | — |
| 2 条构图并行 | 52.1s（串行约 55.6s，几乎无收益） | — |
| 4 条构图并行 | 64.0s（串行约 111s，省 47s） | — |
| **2×PPT 长构图 + 4×写作** | 54.2s | **9.39s** |
| 4×写作基线 | 5.0s | 2.47s |

瓶颈是**单端点 decode 吞吐 + vLLM continuous batching 把长短请求合批**。
应用层只能约束「发出去几个请求」，管不了端点内部的 batch 调度。
因此：加应用并发、放开 `--max-num-seqs` 都不解决问题，
**只有把 PPT/VISION 长请求与写作短请求分到不同端点**才是根治。

⚠ **不要把新副本加进 `MODEL_SERVICE_URLS` 做全局负载均衡**：那会让长短请求
重新混进同一个池，隔离失效。正确做法是**按业务路由隔离，池内才做负载均衡**。

⚠ **不要放开 `--max-num-seqs 8`**：后端 `MODEL_MAX_CONCURRENCY=4`、PPT 闸门 2，
端点本来就没跑满 8；且 `--compilation-config cudagraph_capture_sizes [1,8]`
只捕获了 batch 1/8，超过后走非图路径可能更慢；KV cache 固定水位下更多 seq
还会挤占长构图的上下文（几千 prompt + 2400 输出）触发重算。

### 10.2 卡位账本（8×310P3，单卡 43GB HBM）

| 卡 | 现状 | 说明 |
|---|---|---|
| 0,1 | `qwen35b-main` :8010 | 主 35B，TP=2，**保留给写作/长文** |
| 2,3 | 27B 试用 :8011 | TP=2，试用实例；可停以腾卡（需人工确认） |
| 4 | bge-m3 :8001（裸进程） | 1 卡，向量服务必须保留；实际卡位待 root 核实 |
| 5,6 | 空闲 | 原 DeepPresenter-9B / pptagent 栈已停 |
| 7 | 空闲 | 原 14B 回滚实例已停 |

每套 35B TP=2 必须**独占 2 张卡**：W8A8 权重约 35GB → 约 17.5GB/卡，
`0.90 × 43GB ≈ 38.7GB` 可用，余约 21GB/卡给 KV cache，无法与第二实例共享。
因此：

- **阶段 1（推荐先做，零停服）**：用 5,6 起 **1 个** 35B 副本（:8020），
  `PPT_MODEL_URL` + `VISION_MODEL_URL` 指向它，主 8010 专供写作/长文。
  这一步就能消除写作 TTFT 劣化。
- **阶段 2（可选）**：确认卡位后停掉 27B 试用腾出 2,3，再起第 2 个副本
  （:8021），`PPT_MODEL_URLS` 填两个地址，网关按「最少在途 + 轮询」分流。
  **「再起 2 个副本」在当前卡位下大概率差 1 张卡，必须先核实再动手。**

### 10.3 资源影响（实测 + 估算）

- **主机 RAM 不会飙升**：`free -h` = 253Gi total / 61Gi used / 155Gi available
  （161Gi buff/cache 里已有权重 page cache）。单个 35B 实例进程组 RSS 约
  21GB（主 4.4 + EngineCore 4.5 + Worker_TP0 5.8 + Worker_TP1 6.2）。
  加 2 个副本约 +42GB → used 约 103Gi，仍有 >100Gi 可用。
- **NPU HBM 才是硬约束**，见 10.2；与主机 RAM 无关，别看 `free -h` 就以为能起。
- **加载时间会明显变长，但属一次性启动成本**：第 2 节已注明单实例权重加载
  约 5~15 分钟（含 CANN 图编译 `FULL_DECODE_ONLY`）。两个副本建议**串行启动**
  约 10~30 分钟；并行启动会争抢 CPU/磁盘/编译，常常更慢。
  期间该副本不可用，须 `/v1/models` 探活就绪后再切流量。
- **磁盘无压力**：根分区 1.7T / 49% used / 890G 可用；权重只读复用同一路径，
  无需复制 35GB；图编译缓存每实例几 GB 量级。

### 10.4 root 只读核查命令（AI 不越权，请人工执行并回传输出）

```bash
npu-smi info                                  # 确认 davinci0~7 实际占用
ps -eo pid,user,rss,etime,args | grep -E 'vllm serve' | grep -v grep
ss -ltnp | grep -E ':802[01]'                 # 确认示例端口未被占用
docker logs --since 24h justice-api 2>&1 \
  | grep -E '\[PPT 任务耗时\]|\[PPT 构图耗时\]|排队=' | tail -120
```

### 10.5 启动与切换命令模板（均为高危操作，仅打印，由人工确认执行）

```bash
# 1) 单个副本：复制现有 35B 服务定义，只改容器名 / 端口 / 可见卡
#    ASCEND_RT_VISIBLE_DEVICES=5,6 ；端口 8020；其余 flag 与 qwen35b-main 完全一致
#    （--tensor-parallel-size 2 --quantization ascend --max-num-seqs 8
#      --gpu-memory-utilization 0.90 --max-model-len 16384 ...）
cd /opt/justice-office/deploy
docker compose up -d <新副本服务名>
curl -s http://127.0.0.1:8020/v1/models       # 探活，确认模型名一致

# 2) 改后端 .env（600 root），按用途隔离，勿动 MODEL_SERVICE_URLS
#    PPT_MODEL_URL=http://10.128.85.133:8020/v1
#    PPT_MODEL_NAME=Qwen3.6-35B-A3B-W8A8
#    VISION_MODEL_URL=http://10.128.85.133:8020/v1
#    PPT_MODEL_MAX_CONCURRENCY=4
#    PPT_COMPOSITION_PARALLEL=2
# 3) 让 .env 生效（重建后端容器，非目录挂载）
docker compose up -d justice-api

# 4) 验收：隔离前后用同一把尺子，先看写作 TTFT 倍率是否回落到 ~1.0
#    隔离前（基线，长短请求都打 8010）
python3 deploy/probe_ppt_concurrency.py
#    隔离后：PPT 长请求打副本，交互式写作打主端点
PPT_PROBE_BASE=http://10.128.85.133:8010 \
PPT_PROBE_PPT_BASE=http://10.128.85.133:8020 \
    python3 deploy/probe_ppt_concurrency.py
```

脚本会分别采样两个端点的 `vllm:num_requests_running/waiting` 峰值，
并在结尾打印「混合场景写作 TTFT / 纯写作基线」倍率：隔离成功应接近 1.0，
仍 >2 说明流量没真正分开（检查 `.env` 是否还指向主端点）。

后端会自动识别 `PPT_MODEL_URL(S)` 与主端点不重叠
（`server/app/application/ppt/ppt_admission.py::dedicated_ppt_pool`），
准入闸门不再套「给写作留 1 个主池名额」的约束，副本算力才用得满。
**灰度顺序**：先只切 `PPT_MODEL_URL`（不动并行度）→ 压测 →
再开 `PPT_COMPOSITION_PARALLEL=2` → 再压测。任一步写作 TTFT 明显劣化即回退。
