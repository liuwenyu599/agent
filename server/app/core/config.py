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
        # 单个网关实例同时在途的模型请求上限。等待在 asyncio.Semaphore 上，不占 FastAPI worker thread。
        self.MODEL_MAX_CONCURRENCY = max(1, int(os.getenv("MODEL_MAX_CONCURRENCY", "4")))
        self.MODEL_TEMPERATURE = float(os.getenv("MODEL_TEMPERATURE", "0.4"))
        self.MODEL_MAX_TOKENS = int(os.getenv("MODEL_MAX_TOKENS", "4096"))
        self.MODEL_CTX_LIMIT = int(os.getenv("MODEL_CTX_LIMIT", "16384"))
        self.MODEL_HEALTH_TIMEOUT = int(os.getenv("MODEL_HEALTH_TIMEOUT", "5"))
        self.MODEL_FAILOVER_COOLDOWN = int(os.getenv("MODEL_FAILOVER_COOLDOWN", "15"))
        self.VISION_MODEL_URL = os.getenv("VISION_MODEL_URL", "")
        self.VISION_MODEL_NAME = os.getenv("VISION_MODEL_NAME", "Qwen2.5-VL-7B-Instruct")
        self.VISION_MODEL_API_KEY = os.getenv("VISION_MODEL_API_KEY", "")
        self.VISION_MODEL_TIMEOUT = int(os.getenv("VISION_MODEL_TIMEOUT", "180"))
        self.VISION_MAX_IMAGES = int(os.getenv("VISION_MAX_IMAGES", "4"))
        self.AI_PROVIDER = os.getenv("AI_PROVIDER", "auto")

        # PPT 助手专用模型
        self.PPT_MODEL_URL = os.getenv("PPT_MODEL_URL", "")
        self.PPT_MODEL_NAME = os.getenv("PPT_MODEL_NAME", "DeepPresenter-9B")
        self.PPT_MODEL_API_KEY = os.getenv("PPT_MODEL_API_KEY", "")
        self.PPT_MODEL_TIMEOUT = int(os.getenv("PPT_MODEL_TIMEOUT", "300"))
        self.PPT_AGENT_URL = os.getenv("PPT_AGENT_URL", "")
        self.PPT_AGENT_HEALTH_PATH = os.getenv("PPT_AGENT_HEALTH_PATH", "/")
        self.PPT_AGENT_API_KEY = os.getenv("PPT_AGENT_API_KEY", "")
        self.PPT_AGENT_STATUS_PATH = os.getenv("PPT_AGENT_STATUS_PATH", "/api/ppt/status/{task_id}")
        self.PPT_AGENT_RESULT_PATH = os.getenv("PPT_AGENT_RESULT_PATH", "/api/ppt/result/{task_id}")
        self.PPT_AGENT_TASK_ID_FIELD = os.getenv("PPT_AGENT_TASK_ID_FIELD", "")
        self.PPT_AGENT_DONE_VALUES = os.getenv(
            "PPT_AGENT_DONE_VALUES", "succeeded,success,completed,complete,done,finished")
        self.PPT_AGENT_FAIL_VALUES = os.getenv(
            "PPT_AGENT_FAIL_VALUES", "failed,failure,error,cancelled,canceled,aborted,timeout")
        self.PPT_AGENT_SUBMIT_TIMEOUT = int(os.getenv("PPT_AGENT_SUBMIT_TIMEOUT", "60"))
        self.PPT_AGENT_RESULT_TIMEOUT = int(os.getenv("PPT_AGENT_RESULT_TIMEOUT", "300"))
        self.PPT_AGENT_TOTAL_TIMEOUT = int(os.getenv("PPT_AGENT_TOTAL_TIMEOUT", "1800"))
        self.PPT_AGENT_POLL_INTERVAL = int(os.getenv("PPT_AGENT_POLL_INTERVAL", "10"))
        self.PPT_AGENT_WORKSPACE_DIR = os.getenv("PPT_AGENT_WORKSPACE_DIR", "")
        self.PPT_AGENT_RESULT_GLOB = (
            os.getenv("PPT_AGENT_RESULT_GLOB")
            or os.getenv("PPT_AGENT_RESULT_FILENAME")
            or "*.pptx")
        self.PPT_AGENT_WORKSPACE_FRESH_TOLERANCE = int(
            os.getenv("PPT_AGENT_WORKSPACE_FRESH_TOLERANCE", "120"))
        self.PPT_AGENT_SUBMIT_PATH = os.getenv(
            "PPT_AGENT_SUBMIT_PATH", "/gradio_api/call/send_message")
        self.PPT_AGENT_EVENT_PATH = os.getenv(
            "PPT_AGENT_EVENT_PATH", "/gradio_api/call/send_message/{event_id}")
        self.PPT_AGENT_EVENT_ID_FIELD = os.getenv("PPT_AGENT_EVENT_ID_FIELD", "")
        self.PPT_AGENT_FN_INDEX = os.getenv("PPT_AGENT_FN_INDEX", "")
        self.PPT_AGENT_SESSION_HASH = os.getenv("PPT_AGENT_SESSION_HASH", "")
        self.PPT_AGENT_RESULT_OUTPUT_INDEX = int(
            os.getenv("PPT_AGENT_RESULT_OUTPUT_INDEX", "3"))
        self.PPT_AGENT_QUESTION_OUTPUT_INDEX = int(
            os.getenv("PPT_AGENT_QUESTION_OUTPUT_INDEX", "4"))
        self.PPT_AGENT_CONVERT_TYPE = os.getenv(
            "PPT_AGENT_CONVERT_TYPE", "自由生成 (freeform)")
        self.PPT_AGENT_TEMPLATE = os.getenv("PPT_AGENT_TEMPLATE", "auto")
        self.PPT_AGENT_MESSAGE_MAX_CHARS = int(
            os.getenv("PPT_AGENT_MESSAGE_MAX_CHARS", "24000"))
        self.PPT_AGENT_ATTACHMENT_MAP = os.getenv("PPT_AGENT_ATTACHMENT_MAP", "")
        self.PPT_AGENT_PREVIEW_GLOB = os.getenv(
            "PPT_AGENT_PREVIEW_GLOB",
            ".slide_images-*/*.jpg,.slide_images-*/*.png,preview/*.jpg,preview/*.png")
        self.PPT_AGENT_SLIDE_GLOB = os.getenv("PPT_AGENT_SLIDE_GLOB", "slides/*.html")
        self.PPT_AGENT_STALL_TIMEOUT = int(os.getenv("PPT_AGENT_STALL_TIMEOUT", "1800"))
        self.PPT_AGENT_PROGRESS_INTERVAL = int(os.getenv("PPT_AGENT_PROGRESS_INTERVAL", "5"))

        # 智能写作流水线
        self.WRITING_AUTO_QA = os.getenv("WRITING_AUTO_QA", "true").lower() == "true"
        self.DOC_NUMBER_DEFAULT_DAIZI = os.getenv("DOC_NUMBER_DEFAULT_DAIZI", "粤府办")
        self.WRITING_AI_FORMAT_CHECK = os.getenv("WRITING_AI_FORMAT_CHECK", "false").lower() == "true"
        self.WRITING_RETRY_MAX = int(os.getenv("WRITING_RETRY_MAX", "1"))
        self.WRITING_AUTO_SAVE_DRAFT = os.getenv("WRITING_AUTO_SAVE_DRAFT", "true").lower() == "true"
        self.WRITING_AGENT_GRAPH_ENABLED = _bool(
            os.getenv("WRITING_AGENT_GRAPH_ENABLED"), False)
        self.WRITING_AGENT_GRAPH_COMPLEX_ONLY = _bool(
            os.getenv("WRITING_AGENT_GRAPH_COMPLEX_ONLY"), True)
        self.WRITING_AGENT_MAX_TOOL_ROUNDS = max(
            1, int(os.getenv("WRITING_AGENT_MAX_TOOL_ROUNDS", "4")))
        self.WRITING_AGENT_MAX_REPAIR_ROUNDS = max(
            0, int(os.getenv("WRITING_AGENT_MAX_REPAIR_ROUNDS", "2")))
        self.WRITING_AGENT_RUN_TIMEOUT_SECONDS = max(
            30, int(os.getenv("WRITING_AGENT_RUN_TIMEOUT_SECONDS", "300")))
        self.WRITING_AGENT_ROLLOUT_PERCENT = max(
            0, min(100, int(os.getenv("WRITING_AGENT_ROLLOUT_PERCENT", "0"))))
        self.WRITING_AGENT_TRACE_RETENTION_DAYS = max(
            1, int(os.getenv("WRITING_AGENT_TRACE_RETENTION_DAYS", "180")))

        # Embedding / 向量检索。生产基线使用 bge-m3(1024d)，避免默认 512d 模型与既有索引静默错配。
        self.EMBEDDING_PROVIDER = os.getenv("EMBEDDING_PROVIDER", "auto")  # auto|bge|mock|http
        self.EMBED_MODEL_PATH = os.getenv("EMBED_MODEL_PATH", "/home/lcode/bge-m3")
        self.EMBEDDING_HTTP_URL = os.getenv("EMBEDDING_HTTP_URL", "")
        self.EMBEDDING_HTTP_MODEL = os.getenv("EMBEDDING_HTTP_MODEL", "")
        self.EMBEDDING_HTTP_TIMEOUT = int(os.getenv("EMBEDDING_HTTP_TIMEOUT", "30"))
        self.RAG_TOP_K = int(os.getenv("RAG_TOP_K", "3"))
        # 政务事实问答宁可少召回，也不把低相关内容交给模型补全。
        self.RAG_SCORE_THRESHOLD = float(os.getenv("RAG_SCORE_THRESHOLD", "0.7"))
        # CrossEncoder 二阶段重排；模型需随离线部署资产一起提供。
        self.RAG_RERANK_ENABLED = _bool(os.getenv("RAG_RERANK_ENABLED", "true"), True)
        self.RAG_RERANK_MODEL_PATH = os.getenv(
            "RAG_RERANK_MODEL_PATH", "/home/lcode/bge-reranker-v2-m3")
        self.RAG_RERANK_TOP_K = int(os.getenv("RAG_RERANK_TOP_K", "3"))
        self.RAG_CHUNK_MAX_CHARS = int(os.getenv("RAG_CHUNK_MAX_CHARS", "500"))
        self.RAG_CHUNK_OVERLAP = int(os.getenv("RAG_CHUNK_OVERLAP", "80"))
        self.RAG_CHUNK_MIN_CHARS = int(os.getenv("RAG_CHUNK_MIN_CHARS", "30"))
        self.RAG_VECTOR_CANDIDATES = int(os.getenv("RAG_VECTOR_CANDIDATES", "30"))
        self.RAG_RRF_K = int(os.getenv("RAG_RRF_K", "60"))
        self.RAG_PER_DOC_CAP = int(os.getenv("RAG_PER_DOC_CAP", "2"))
        self.RAG_NEIGHBOR_EXPAND = _bool(os.getenv("RAG_NEIGHBOR_EXPAND", "true"), True)
        self.RAG_EXPAND_BUDGET = int(os.getenv("RAG_EXPAND_BUDGET", "800"))

        # 上传与 OCR。知识库支持文本型 OFD；PDF/图片以及扫描型 OFD 在视觉模型可用时走 OCR。
        self.UPLOAD_MAX_SIZE = int(os.getenv("UPLOAD_MAX_SIZE", str(50 * 1024 * 1024)))
        self.MAX_UPLOAD_SIZE = int(os.getenv("MAX_UPLOAD_SIZE", str(2 * 1024 * 1024 * 1024)))
        self.SUPPORTED_DOC_TYPES = [
            ".pdf", ".doc", ".docx", ".txt", ".md", ".wps", ".xlsx", ".ofd",
            ".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff",
        ]
        self.CHAT_DOC_TYPES = [".docx", ".doc", ".pdf", ".txt", ".md", ".xlsx"]
        self.CHAT_IMAGE_TYPES = [".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"]
        self.CHAT_SUPPORTED_TYPES = self.CHAT_DOC_TYPES + self.CHAT_IMAGE_TYPES
        self.CHAT_MAX_ATTACHMENTS = int(os.getenv("CHAT_MAX_ATTACHMENTS", "5"))
        self.ATTACH_CONTEXT_BUDGET = int(os.getenv("ATTACH_CONTEXT_BUDGET", "4000"))
        self.OCR_ENABLED = _bool(os.getenv("OCR_ENABLED", "true"), True)
        self.OCR_LANG = os.getenv("OCR_LANG", "chi_sim+eng")  # legacy/local OCR compatibility knob
        self.OCR_MAX_PAGES = max(1, int(os.getenv("OCR_MAX_PAGES", "20")))
        self.OCR_MIN_TEXT_CHARS = max(1, int(os.getenv("OCR_MIN_TEXT_CHARS", "80")))
        self.OCR_MAX_TOKENS = max(256, int(os.getenv("OCR_MAX_TOKENS", "4096")))
        self.FORMAT_CHECK_MAX_SIZE = int(os.getenv("FORMAT_CHECK_MAX_SIZE", str(20 * 1024 * 1024)))
        self.FORMAT_CHECK_AI_BUDGET = int(os.getenv("FORMAT_CHECK_AI_BUDGET", "1500"))
        self.FORMAT_CHECK_SENSITIVE_WORDS = [
            x.strip() for x in os.getenv("FORMAT_CHECK_SENSITIVE_WORDS", "").split(",") if x.strip()
        ]
        self.FORMAT_CHECK_FORBIDDEN_WORDS = [
            x.strip() for x in os.getenv("FORMAT_CHECK_FORBIDDEN_WORDS", "").split(",") if x.strip()
        ]

        self.CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*")
        self.LOG_DIR = Path(os.getenv("LOG_DIR", str(self.DATA_DIR / "logs"))).resolve()
        self.DB_AUTO_MIGRATE = _bool(os.getenv("DB_AUTO_MIGRATE", "true"), True)
        self.HOST = os.getenv("HOST", "0.0.0.0")
        self.PORT = int(os.getenv("PORT", "8000"))

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
