import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# 临时用 SQLite
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR}/judicial_ai.db")

# Redis
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# Milvus
MILVUS_HOST = os.getenv("MILVUS_HOST", "localhost")
MILVUS_PORT = int(os.getenv("MILVUS_PORT", "19530"))
MILVUS_COLLECTION = os.getenv("MILVUS_COLLECTION", "judicial_kb")

# Elasticsearch
ES_HOST = os.getenv("ES_HOST", "localhost")
ES_PORT = int(os.getenv("ES_PORT", "9200"))
ES_INDEX = os.getenv("ES_INDEX", "judicial_docs")

# LLM
VLLM_URL = os.getenv("VLLM_URL", "http://localhost:8001/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "Qwen2.5-14B-Instruct")

# Embedding
EMBED_MODEL_PATH = os.getenv("EMBED_MODEL_PATH", "/home/lwy/models/BAAI/bge-small-zh-v1.5")

# Reranker
RERANKER_MODEL_PATH = os.getenv("RERANKER_MODEL_PATH", "/home/lwy/models/BAAI/bge-reranker-v2-m3")

# 安全
SECRET_KEY = os.getenv("SECRET_KEY", "judicial-ai-secret-key-2026")
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24

# 文件存储
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "localhost:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin")
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "judicial-docs")

# 知识库
MAX_UPLOAD_SIZE = 2 * 1024 * 1024 * 1024
SUPPORTED_DOC_TYPES = [".pdf", ".doc", ".docx", ".txt", ".md", ".ofd", ".wps"]

# 日志
LOG_DIR = Path(os.getenv("LOG_DIR", "/home/lwy/judicial-ai/logs"))
LOG_DIR.mkdir(parents=True, exist_ok=True)
