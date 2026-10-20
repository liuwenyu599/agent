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
