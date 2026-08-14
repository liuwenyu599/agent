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
# vLLM 启动参数中的 max_model_len（start.sh 当前为 4096）。
# 用于后端在拼接"对话历史 + 附件材料"时估算可用上下文预算。
LLM_MAX_MODEL_LEN = int(os.getenv("LLM_MAX_MODEL_LEN", "4096"))

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

# ===== 写作对话附件 =====
# 附件保存目录（独立于知识库，按用户隔离）
CHAT_UPLOAD_DIR = Path(os.getenv("CHAT_UPLOAD_DIR", "/home/lwy/judicial-ai/uploads/chat"))
CHAT_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
# 对话附件：单文件大小上限（图片/文档）
CHAT_UPLOAD_MAX_SIZE = int(os.getenv("CHAT_UPLOAD_MAX_SIZE", str(50 * 1024 * 1024)))  # 50MB
# 单次消息最多附件数
CHAT_MAX_ATTACHMENTS = int(os.getenv("CHAT_MAX_ATTACHMENTS", "5"))
# 支持的附件类型（文档类 + 图片类）
CHAT_DOC_TYPES = [".docx", ".doc", ".pdf", ".txt", ".md"]
CHAT_IMAGE_TYPES = [".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"]
CHAT_SUPPORTED_TYPES = CHAT_DOC_TYPES + CHAT_IMAGE_TYPES
# 注入给模型的附件文本总预算（字符数）。
# 注意：start.sh 中 max_model_len=4096，约折合中文 2500~3500 字可用空间，
# 对话历史和 system prompt 也要占用，因此默认 2000，调高 max_model_len 后可同步调大。
ATTACH_CONTEXT_BUDGET = int(os.getenv("ATTACH_CONTEXT_BUDGET", "2000"))

# OCR（图片附件识别）
# 需要系统安装 tesseract 及中文语言包：apt install tesseract-ocr tesseract-ocr-chi-sim
OCR_ENABLED = os.getenv("OCR_ENABLED", "true").lower() == "true"
OCR_LANG = os.getenv("OCR_LANG", "chi_sim+eng")

# ===== 格式校验 =====
FORMAT_CHECK_MAX_SIZE = int(os.getenv("FORMAT_CHECK_MAX_SIZE", str(50 * 1024 * 1024)))  # 50MB
# AI 辅助判断一次送入的正文字符数上限
FORMAT_CHECK_AI_BUDGET = int(os.getenv("FORMAT_CHECK_AI_BUDGET", "1500"))

# 日志
LOG_DIR = Path(os.getenv("LOG_DIR", "/home/lwy/judicial-ai/logs"))
LOG_DIR.mkdir(parents=True, exist_ok=True)
