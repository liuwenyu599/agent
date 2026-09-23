# syntax=docker/dockerfile:1
# ============================================================
# judicial-ai 后端镜像（FastAPI + RAG 向量检索）
# 构建上下文是仓库根目录：docker compose 在 deploy/ 下已配置 context: ..
# 手工构建：docker build -f deploy/Dockerfile -t judicial-ai-server:latest .
# ============================================================
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

ARG PIP_INDEX_URL=https://pypi.org/simple

WORKDIR /app

# 系统依赖：
#   antiword            解析 .doc
#   libreoffice-writer  .doc/.docx 转换（PPT 预览等链路）
#   libreoffice-impress .ppt/.pptx 转换
#   fonts-noto-cjk      LibreOffice 转换时中文字体渲染
#   curl                健康检查
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       antiword curl \
       libreoffice-writer libreoffice-impress fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

# 先装 CPU 版 torch（sentence-transformers 的依赖，避免拉入几个 GB 的 CUDA 版）
RUN pip install --index-url https://download.pytorch.org/whl/cpu torch

COPY server/requirements-server.txt /tmp/requirements.txt
RUN pip install --index-url ${PIP_INDEX_URL} -r /tmp/requirements.txt

COPY server/ /app/

# 数据（SQLite / 向量索引 / 上传文件）统一挂 /data；模型目录挂 /models（只读）
ENV DATA_DIR=/data
VOLUME ["/data"]

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s \
    CMD curl -fsS http://127.0.0.1:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
