# PPT 助手独立部署（PPTAgent + DeepPresenter-9B）

## 架构

```
司法局 FastAPI :8000
    │  （HTTP，容器网络内 http://justice-ppt-host:7861）
    ▼
justice-ppt-host :7861 ──► justice-ppt-sandbox（仅内部，不对外开端口）
    │  （OpenAI-compatible）
    ▼
justice-deeppresenter-9b :8003（vLLM serve，OpenAI 兼容）
```

- 与现有 PostgreSQL、justice-office-server、Qwen:8001、VL:8002、BGE-M3 完全隔离，互不干扰；
- 三个新容器都在独立网络 `justice-network`；
- 端口只新增 8003（模型）和 7861（PPTAgent Host），避开 8000/8001/8002。

## 部署步骤

```bash
# 1. 准备配置
cd deploy/pptagent
cp .env.example .env && cp config.yaml.example config.yaml
#    按 .env 注释修改模型路径 / 镜像（CUDA 或昇腾）

# 2. 拉取模型权重到 ${HOST_MODEL_DIR}/DeepPresenter-9B
#    （内网环境：在有网机器 modelscope/huggingface 下载后离线拷贝）

# 3. 启动
docker compose up -d

# 4. 让司法局后端能访问 PPTAgent Host（不改动后端容器本身）
docker network connect justice-network justice-office-server

# 5. 后端 .env 增加（供 FastAPI 调 PPTAgent）：
#    PPT_AGENT_URL=http://justice-ppt-host:7861
```

## 验证

```bash
curl http://localhost:8003/v1/models        # DeepPresenter-9B 在线
curl http://localhost:7861/                 # PPTAgent WebUI
# 在后端容器内：
docker exec justice-office-server curl -s http://justice-ppt-host:7861/
```

## 说明

- `config.yaml` 把 research / design / long_context 三个角色全部指向
  DeepPresenter-9B；vision_model 可选，复用现有 VL:8002。
- 离线模式 `PPTAGENT_OFFLINE=true`，不产生任何外网请求。
- 若需本地 PDF 高精度解析（扫描件），可再独立部署 MinerU 并在
  `deeppresenter/mcp.json` 中配置；非必需。

## 产物路径与「共享卷取结果」通道（可选，同机部署时推荐）

PPTAgent 生成完成后，成品落在宿主机文件系统（实测）：

```
/data/pptagent/workspace/<日期>/<job_id>/presentation.pptx
                                         presentation.pdf
                                         preview/*.png
```

后端取结果有两条通道，二选一（由 `PPT_AGENT_WORKSPACE_DIR` 是否为空决定）：

| 通道 | 配置 | 说明 |
|---|---|---|
| HTTP 通道 | `PPT_AGENT_WORKSPACE_DIR` 为空 | 提交 → 轮询 → 取结果，依赖 Gradio 未文档化端点 |
| **共享卷通道**（推荐） | 该值填工作区路径 | 提交后直接扫文件系统取最新产物，**不依赖结果端点，也不用猜对 job_id** |

启用共享卷通道的前提是**后端容器与 PPTAgent 容器在同一台宿主机**，且后端容器以
只读方式挂到同一目录（只读挂载不会影响 PPTAgent 写入）：

```yaml
# justice-office-server 的 compose 中新增（路径与本文 PPT_DATA_DIR 对齐）
volumes:
  - <PPT_DATA_DIR 的绝对路径>/workspace:/mnt/pptagent-workspace:ro
```

```bash
# 后端 .env
PPT_AGENT_WORKSPACE_DIR=/mnt/pptagent-workspace
```

⚠️ 两个坑：

1. 本目录 `.env` 里 `PPT_DATA_DIR` 默认是**相对路径** `./data`；另一个 compose
   解析相对路径的基准目录不同，会挂错。跨 compose 共享时必须改成绝对路径。
2. 若两套服务**不在同一台宿主机**，共享卷通道不成立，`PPT_AGENT_WORKSPACE_DIR`
   必须留空，只能走 HTTP 通道。

## 超时（重要，别调小）

PPTAgent 是聊天式 Agent，实测一次生成 **5~15 分钟**且需排队占 GPU。后端默认
`PPT_AGENT_TOTAL_TIMEOUT=1800`（30 分钟）已留足余量——调小会导致正常任务被判
超时后回退本地渲染，用户白等十几分钟还拿不到 PPTAgent 的产物。

## 契约探查（7861 是 Gradio，不是 REST）

7861 跑的是 **Gradio 聊天式 WebUI**（没有 REST/OpenAPI 文档）。命名端点
`/send_message`（另有同签名的 `/send_message_1`），**`queue=True`**。

**入参 6 个（顺序固定）**

| # | 参数名 | 类型 | 默认 | 说明 |
|---|---|---|---|---|
| 1 | `message` | str | 无（必填） | 用户需求 |
| 2 | `history` | list[Message] | `[]` | 对话历史 |
| 3 | `attachments` | list[FileData] | **无默认（必填）** | 附件材料 |
| 4 | `convert_type_value` | enum | `自由生成 (freeform)` | 另一值 `模版 (templates)` |
| 5 | `template_value` | enum | `auto` | `cip/ucas/hit/beamer/default/thu/auto` |
| 6 | `num_pages_value` | enum | `auto` | `auto` 或 `"1"`~`"30"`（**字符串**） |

**出参 5 个（顺序固定）**

| # | 组件 | 说明 |
|---|---|---|
| 1 | Chatbot | 对话记录 |
| 2 | Textbox | 任务标识等文本 |
| 3 | File | 中间产物列表 |
| 4 | **📥 下载文件** | **最终 pptx 的 FileData** ← 产物在这里 |
| 5 | Markdown | 说明；**信息不足时这里是一段追问** |

调用序列：`POST /gradio_api/call/send_message`（body `{"data":[6 个入参]}`）
→ 返回 `event_id` → `GET /gradio_api/call/send_message/{event_id}` 消费 SSE
→ `event: complete` 的 `data` 就是那 5 个出参。

若部署的是旧版 Gradio（4.x），改为 queue 风格（后端已同时兼容）：
`SUBMIT=/gradio_api/queue/join`、`EVENT=/gradio_api/queue/data?session_hash={session_hash}`。

契约若需复核，在 PPTAgent 宿主机跑（**只读**，不触发生成、不占 GPU）：
`bash probe_gradio_readonly.sh`。

### R1：它可能先追问而不是直接生成

「语义匹配」阶段若信息不足，**会先向用户确认关键细节**，此时 out[4] 为空、
out[5] 是一段提问。后端处理：**不做自动代答**，把 job 置为
`awaiting_clarification` 并把问题透给用户；用户回答后走
`POST /ppt/jobs/{id}/clarify` 带上下文续跑。理由：自动代答等于替用户编需求，
产出的 PPT 会偏离预期——这正是它反问所想要避免的事。

### R2：attachments 跨容器不可用

`attachments` 的 `path` 是 **PPTAgent 容器内**路径，后端在另一个容器，传本地
路径它读不到。当前策略：**默认不传附件**，材料内容内联进 `message`（后端本就会
把素材转成文本）。只有在两边挂了同一个共享卷、且知道容器内挂载点时才启用：
`PPT_AGENT_ATTACHMENT_MAP="<后端可见目录>:<PPTAgent容器内目录>"`。
⚠️ 不要为了传附件去改 PPTAgent 的启动参数或重建它的容器。

### R3：目录结构尚未确认，别假设

用户两份说明不一致（是否真有 `slides/slide_NN.html` 存疑）。后端扫描走配置项
`PPT_AGENT_PREVIEW_GLOB` / `PPT_AGENT_SLIDE_GLOB`，**找不到就降级为「只有总
进度、没有逐页预览」，不会让 job 失败**。

确认真实结构请在 PPTAgent 宿主机执行（**只读**）：

```bash
D=$(ls -1t /data/pptagent/workspace | head -1)          # 最新日期目录
ls -la /data/pptagent/workspace/
ls -la "/data/pptagent/workspace/$D"
J=$(ls -1t "/data/pptagent/workspace/$D" | head -1)     # 最新 job 目录
ls -laR "/data/pptagent/workspace/$D/$J"
```

重点确认三点：① 是否有 `slides/` 目录、里面是不是 `slide_NN.html`；
② `preview/` 下 PNG 的命名规律；③ `presentation.pptx` 是否在 job 目录根下。
把输出发回后据此调整两个 GLOB 配置即可。

## 网络与容器名对齐

| 环境 | 网络 | PPTAgent 容器 | 模型容器 | WebUI |
|---|---|---|---|---|
| 实验室（探查用） | `pptagent-net` | `justice-ppt-host` | `dp9b-llm` | `http://192.168.68.51:7861` |
| 司法局生产（本目录 compose） | `justice-network` | `justice-ppt-host` | `justice-deeppresenter-9b` | `http://<宿主机>:7861` |

两者 **PPTAgent 容器名相同（`justice-ppt-host`），只有网络名不同**，因此后端 `.env`
里的 `PPT_AGENT_URL=http://justice-ppt-host:7861` **不需要改**；切换环境时只需确认
后端容器已接入对应网络：

```bash
docker network connect justice-network justice-office-server   # 司法局
docker network connect pptagent-net   justice-office-server    # 实验室
```
