# 服务端部署（Docker 镜像）

## 一、代码上传服务器

方式 A（推荐，服务器能连 GitHub）：
```bash
git clone -b app git@github.com:liuwenyu599/agent.git
cd agent
```

方式 B（内网不能连 GitHub，本地打包上传）：
```bash
# 本地（Windows PowerShell 用 git bash 或先打成 zip）
git archive --format=tar.gz -o agent.tar.gz app
scp agent.tar.gz user@服务器:/opt/
# 服务器上
cd /opt && tar xzf agent.tar.gz -C judicial-ai --one-top-level || (mkdir -p judicial-ai && tar xzf agent.tar.gz -C judicial-ai)
```

## 二、配置

```bash
cd /opt/judicial-ai/deploy
cp .env.example .env
vim .env
```
必改项：
- `SECRET_KEY`：`openssl rand -hex 32` 生成
- `MODEL_SERVICE_URL` / `MODEL_NAME`：指向推理服务
- `HOST_DATA_DIR`：数据落盘目录（SQLite、向量索引、上传文件都在这里）
- `HOST_MODEL_DIR`：宿主机模型目录（只读挂到容器 /models）
- `EMBED_MODEL_PATH=/models/<模型目录名>`（容器内路径）

## 三、构建并启动

```bash
cd /opt/judicial-ai/deploy
docker compose up -d --build
```

手工构建（不用 compose 时）：
```bash
cd /opt/judicial-ai
docker build -f deploy/Dockerfile -t judicial-ai-server:latest .
docker run -d --name judicial-ai-api \
  -p 8000:8000 --env-file deploy/.env \
  -v /data/justice:/data \
  -v /data/justice/models:/models:ro \
  --restart unless-stopped judicial-ai-server:latest
```

## 四、验证

```bash
curl http://127.0.0.1:8000/health
docker logs -f judicial-ai-api
```

## 五、更新代码

```bash
cd /opt/judicial-ai && git pull
cd deploy && docker compose up -d --build   # 只重建变化的层
```

## 六、换向量模型后（必须）

模型维度变化后旧 FAISS 索引不兼容，重建一次：
```bash
docker exec -it judicial-ai-api python -m scripts.reindex_vectors --dry   # 预览
docker exec -it judicial-ai-api python -m scripts.reindex_vectors         # 重建
```

## 备注

- 镜像内装的是 CPU 版 torch（避免几 GB 的 CUDA 依赖）；embedding 在 CPU 上跑
  Qwen3-Embedding-0.6B 完全够，4B 建议只在有 NPU/GPU 的宿主机上用。
- 大语言模型推理不在本镜像内，由 `MODEL_SERVICE_URL` 指向的 vLLM/MindIE 服务承担。
- PostgreSQL 默认不启用（SQLite 已够用）；要启用见 docker-compose.yml 注释。
