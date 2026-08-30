"""配置层：全部通过环境变量 / .env 覆盖，源码不含任何密钥或生产配置。"""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[2]  # server/
load_dotenv(BASE_DIR / ".env")


def _bool(v: str, default: bool = False) -> bool:
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


class Settings:
    def __init__(self) -> None:
        self.DATA_DIR = Path(os.getenv("DATA_DIR", str(BASE_DIR / "data"))).resolve()
        self.DATABASE_URL = os.getenv(
            "DATABASE_URL", f"sqlite:///{self.DATA_DIR / 'judicial_app.db'}"
        )
        self.SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-insecure-secret-change-me")
        self.ACCESS_TOKEN_EXPIRE_HOURS = int(os.getenv("ACCESS_TOKEN_EXPIRE_HOURS", "24"))

        # Model Service（OpenAI 兼容，vLLM 等）
        self.MODEL_SERVICE_URL = os.getenv("MODEL_SERVICE_URL", "http://127.0.0.1:8001/v1")
        self.MODEL_NAME = os.getenv("MODEL_NAME", "Qwen2.5-14B-Instruct")
        self.MODEL_API_KEY = os.getenv("MODEL_API_KEY", "")
        self.MODEL_TIMEOUT = int(os.getenv("MODEL_TIMEOUT", "300"))
        self.MODEL_MAX_TOKENS = int(os.getenv("MODEL_MAX_TOKENS", "4096"))
        # 模型上下文总长度（与模型服务 max_model_len 一致），用于上下文预算估算
        self.MODEL_CTX_LIMIT = int(os.getenv("MODEL_CTX_LIMIT", "16384"))
        # auto: 有 active 模型走其 provider；mock: 强制 MockProvider（测试）
        self.AI_PROVIDER = os.getenv("AI_PROVIDER", "auto")

        # Embedding / 向量检索
        self.EMBEDDING_PROVIDER = os.getenv("EMBEDDING_PROVIDER", "auto")  # auto|bge|mock
        self.EMBED_MODEL_PATH = os.getenv("EMBED_MODEL_PATH", "/home/lwy/models/BAAI/bge-small-zh-v1.5")
        self.RAG_TOP_K = int(os.getenv("RAG_TOP_K", "5"))
        self.RAG_SCORE_THRESHOLD = float(os.getenv("RAG_SCORE_THRESHOLD", "0.5"))

        # 上传
        self.UPLOAD_MAX_SIZE = int(os.getenv("UPLOAD_MAX_SIZE", str(50 * 1024 * 1024)))
        self.MAX_UPLOAD_SIZE = int(os.getenv("MAX_UPLOAD_SIZE", str(2 * 1024 * 1024 * 1024)))
        self.SUPPORTED_DOC_TYPES = [".pdf", ".doc", ".docx", ".txt", ".md", ".ofd", ".wps"]
        self.CHAT_DOC_TYPES = [".docx", ".doc", ".pdf", ".txt", ".md"]
        self.CHAT_IMAGE_TYPES = [".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"]
        self.CHAT_SUPPORTED_TYPES = self.CHAT_DOC_TYPES + self.CHAT_IMAGE_TYPES
        self.CHAT_MAX_ATTACHMENTS = int(os.getenv("CHAT_MAX_ATTACHMENTS", "5"))
        self.ATTACH_CONTEXT_BUDGET = int(os.getenv("ATTACH_CONTEXT_BUDGET", "4000"))
        self.OCR_ENABLED = _bool(os.getenv("OCR_ENABLED", "false"))
        self.OCR_LANG = os.getenv("OCR_LANG", "chi_sim+eng")
        self.FORMAT_CHECK_MAX_SIZE = int(os.getenv("FORMAT_CHECK_MAX_SIZE", str(20 * 1024 * 1024)))
        self.FORMAT_CHECK_AI_BUDGET = int(os.getenv("FORMAT_CHECK_AI_BUDGET", "1500"))

        self.CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*")
        self.LOG_DIR = Path(os.getenv("LOG_DIR", str(self.DATA_DIR / "logs"))).resolve()
        self.DB_AUTO_MIGRATE = _bool(os.getenv("DB_AUTO_MIGRATE", "true"), True)
        self.HOST = os.getenv("HOST", "0.0.0.0")
        self.PORT = int(os.getenv("PORT", "8000"))

    # ---- 数据目录（生产建议 DATA_DIR=/data/judicial-ai）----
    @property
    def files_dir(self) -> Path:
        return self.DATA_DIR / "files"

    @property
    def uploads_dir(self) -> Path:
        return self.DATA_DIR / "uploads"

    @property
    def ppt_dir(self) -> Path:
        return self.DATA_DIR / "ppt"

    @property
    def templates_dir(self) -> Path:
        return self.DATA_DIR / "templates"

    @property
    def knowledge_base_dir(self) -> Path:
        return self.DATA_DIR / "knowledge-base"

    @property
    def backups_dir(self) -> Path:
        return self.DATA_DIR / "backups"

    @property
    def vector_index_dir(self) -> Path:
        return self.DATA_DIR / "vector_index"

    def ensure_dirs(self) -> None:
        for d in (
            self.DATA_DIR, self.files_dir, self.uploads_dir, self.ppt_dir,
            self.templates_dir, self.knowledge_base_dir, self.backups_dir,
            self.vector_index_dir, self.LOG_DIR,
        ):
            d.mkdir(parents=True, exist_ok=True)


settings = Settings()
