# PPT 助手独立部署（PPTAgent + DeepPresenter-9B）

## 架构

```
司法局 FastAPI :8000
    │  （HTTP，容器网络内 http://justice-ppt-host:7861）
    ▼
justice-ppt-host :7861 ──► justice-ppt-sandbox（仅内部，不对外开端口）
    │  （OpenAI-compatible）
    ▼
justice-deeppresenter-9b 容器内 :8003（宿主机生产端口 :8004，OpenAI 兼容）
```

- 与现有 PostgreSQL、justice-office-server、14B:8003、VL:8002、BGE-M3 隔离；
- 三个 PPT 相关容器都在独立网络 `justice-network`；
- DeepPresenter 容器内仍监听 8003，但生产宿主机发布为 **8004**；PPTAgent Host 为 7861，避免与 14B 的宿主机 8003 冲突。

## 2026-09-28 已验证镜像基线

生产上的 `deeppresenter-sandbox:latest` 与 `deeppresenter-host:latest` 含现场排障后的补丁。
**明日交付前不要重新 pull / rebuild 这两个镜像，也不要用上游 latest 覆盖它们。**

当前仓库没有 2026-09-28 现场补丁的完整原始 diff，因此不能安全地凭记忆重造 Dockerfile。
在原始 patch 被还原并纳入版本控制之前，生产采用“已验证镜像冻结 + 校验 + tar 归档”的方式保证可恢复：

```bash
cd /opt/judicial_app/deploy/pptagent

./verify-patched-images.sh
./archive-patched-images.sh /opt/justice-office/data/delivery-images
```

只有看到：

```text
PPTAGENT IMAGE BASELINE PASSED
```

才允许继续部署。归档会生成：

```text
sandbox.tar
host.tar
pptagent-images.sha256
```

恢复：

```bash
docker load -i /opt/justice-office/data/delivery-images/sandbox.tar
docker load -i /opt/justice-office/data/delivery-images/host.tar
```

这是一条交付安全线，不等价于补丁源码已经完全可复现。后续拿到 9 月 28 日实际 patch diff 后，再补 Dockerfile/overlay 构建；在此之前禁止重建这两个镜像。

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

# 5. 生产后端 .env 使用已确认的宿主机地址：
#    PPT_MODEL_URL=http://10.128.85.133:8004/v1
#    PPT_AGENT_URL=http://10.128.85.133:7861
#    PPT_AGENT_WORKSPACE_DIR=/data/pptagent
```

## 验证

```bash
curl http://localhost:8004/v1/models        # DeepPresenter-9B 在线（生产宿主机端口）
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

PPTAgent 生成完成后，成品落在宿主机文件系统（**真机实测**，job `20260927/f8439174`，
标题「司法局工作汇报」，4 页，耗时约 2 分钟）：

```
/data/pptagent/workspace/20260927/f8439174/
├── .input_request.json                    提交入参（最早的日志：10:22）
├── 司法局工作汇报.md / .pdf / .pptx        ← 都跟着标题走，**文件名随标题动态变化**
├── intermediate_output.json               最后更新（10:24）
├── assets/                                图表素材（problems_analysis.png 等）
├── .history/                              各类日志 + Design/Research history jsonl
├── .slide_images-pdf-司法局工作汇报/        ← 预览图在这（隐藏目录，名字含动态标题）
│   ├── slide_01.jpg  36KB
│   ├── slide_02.jpg  68KB
│   ├── slide_03.jpg  73KB
│   └── slide_04.jpg  31KB
└── slides/
    ├── global.css
    ├── slide_01.html ~ slide_04.html       ← 页数基准
```

三条**已确认**的推断（据此定了后端默认值）：

1. **产物文件名不是固定的 `presentation.pptx`**，而是 `<标题>.pptx`（中文、动态）
   → 后端不再匹配固定名，改为 glob（`PPT_AGENT_RESULT_GLOB`，默认 `*.pptx`），
   在候选里挑"最新且能通过 pptx 合法性校验"的那个，并自动跳过 `~$xxx.pptx`
   之类的 Office 锁文件和小于 8KB 的半成品。
2. **预览图不在 `preview/`、也不是 png**，而是 `.slide_images-pdf-<标题>/slide_NN.jpg`
   → `PPT_AGENT_PREVIEW_GLOB` 默认配置多个候选模式，命中任一即算数：
   `.slide_images-*/*.jpg,.slide_images-*/*.png,preview/*.jpg,preview/*.png`
   （这样换渲染后端或改扩展名都不会让预览整块失效）。
3. `slides/slide_NN.html` 这条**猜对了**，`PPT_AGENT_SLIDE_GLOB=slides/*.html` 不变，
   `current_page` 取它的文件数成立。

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

## 超时，以及两条调用通道的区别（重要）

### ⚠️ 要让 PPTAgent 生成 PPT，必须走异步 job

后端有两条调用 PPTAgent 的通道，**只有异步通道能得到 PPTAgent 的产物**：

| 通道 | 入口 | 产物来源 | 结论 |
|---|---|---|---|
| **异步 job（唯一可用）** | `POST /api/v1/ppt/jobs` → 轮询 `/jobs/{id}/status` → `/jobs/{id}/export` | SSE 出参 `[3]` 的 FileData → 下�� `/gradio_api/file=<path>` | ✅ 走 PPTAgent，成功率高，不依赖共享卷 |
| **同步导出（默认必定回退）** | `/api/v1/ppt/documents/{id}/export` 等老接口 | `render()` 发 REST 请求体 → Gradio 不认 | ❌ 拿不到产物，**回退后端本地 `render_pptx`** |

同步通道回退不是故障：它发的请求体是 REST 形态（`topic`/`content`/…），而 Gradio
命名端点只认 `{"data": [6 个入参]}`，两者在结构上就不可能对齐。后端会在日志里打印
明确诊断（`PPTAgent 契约冲突：…`）。**部署验收请以异步 job 为准。**

### 超时（别调小）

PPTAgent 是聊天式 Agent，实测一次生成 **5~15 分钟**且需排队占 GPU。后端默认
`PPT_AGENT_TOTAL_TIMEOUT=1800`（30 分钟）已留足余量——调小会导致正常任务被判
超时后回退本地渲染，用户白等十几分钟还拿不到 PPTAgent 的产物。
（实测样本：4 页简单任务约 2 分钟；复杂任务仍按 15 分钟量级预留。）

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

### R3：目录结构已确认（job `20260927/f8439174`）

见上面「产物路径」一节的实测树。结论：

| 维度 | 配置项 | 默认值 | 状态 |
|---|---|---|---|
| 产物 pptx | `PPT_AGENT_RESULT_GLOB` | `*.pptx` | ✅ 已按实测改为通配（旧别名 `PPT_AGENT_RESULT_FILENAME` 仍兼容） |
| 预览图 | `PPT_AGENT_PREVIEW_GLOB` | `.slide_images-*/*.jpg,.slide_images-*/*.png,preview/*.jpg,preview/*.png` | ✅ 已按实测改为多候选模式 |
| 页数基准 | `PPT_AGENT_SLIDE_GLOB` | `slides/*.html` | ✅ 原假设成立，无需改动 |

多模式用逗号（或分号）分隔；找不到就降级为「只有总进度、没有逐页预览」，
**不会让 job 失败**。

⚠️ 预览图是 **jpg**，所以 `/ppt/jobs/{id}/preview` 返回的 `url` 可能是
`.../preview/0.jpg` 而不是 `0.png`——取值请以返回的 url 为准。后端同时接受
`0`、`0.png`、`0.jpg` 三种请求形式（同一条路由），老客户端不会被打破。

### 还想读 Pipeline 阶段的话（只读）

`.history/task.log` 与 `intermediate_output.json` 可能比"数文件"更准地反映当前
阶段。若后续要做更精细的 phase 展示，可在 PPTAgent 宿主机执行（**纯只读**，
不触发生成、不占 GPU）：

```bash
cd /data/pptagent/workspace/20260927/f8439174
cat intermediate_output.json
cat .input_request.json
ls -la .history/
tail -80 .history/task.log
```

重点看有没有一个可直接读的 **阶段字段**（Research / Design / Review 之类），
有了它就能替换掉现在"靠文件数推断 phase"的启发式逻辑。

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
