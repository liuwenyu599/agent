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
