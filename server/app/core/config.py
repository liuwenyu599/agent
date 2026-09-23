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
        # 采样温度：公文写作建议 0.2~0.5（越低越规范）；闲聊可调高
        self.MODEL_TEMPERATURE = float(os.getenv("MODEL_TEMPERATURE", "0.4"))
        self.MODEL_MAX_TOKENS = int(os.getenv("MODEL_MAX_TOKENS", "4096"))
        # 模型上下文总长度（与模型服务 max_model_len 一致），用于上下文预算估算
        self.MODEL_CTX_LIMIT = int(os.getenv("MODEL_CTX_LIMIT", "16384"))
        # 视觉模型服务（可选，Qwen2.5-VL 等，OpenAI 兼容）：
        # 配置后对话中的图片附件直接送视觉模型；留空则走 OCR 文本通道
        self.VISION_MODEL_URL = os.getenv("VISION_MODEL_URL", "")
        self.VISION_MODEL_NAME = os.getenv("VISION_MODEL_NAME", "Qwen2.5-VL-7B-Instruct")
        self.VISION_MODEL_API_KEY = os.getenv("VISION_MODEL_API_KEY", "")
        self.VISION_MODEL_TIMEOUT = int(os.getenv("VISION_MODEL_TIMEOUT", "180"))
        # 单次对话最多送入视觉模型的图片数
        self.VISION_MAX_IMAGES = int(os.getenv("VISION_MAX_IMAGES", "4"))
        # auto: 有 active 模型走其 provider；mock: 强制 MockProvider（测试）
        self.AI_PROVIDER = os.getenv("AI_PROVIDER", "auto")

        # PPT 助手专用模型（DeepPresenter-9B，OpenAI 兼容，独立容器服务）：
        # 配置后 PPT 的大纲 / 逐页编辑等全部走该服务；留空则回退主文本模型
        self.PPT_MODEL_URL = os.getenv("PPT_MODEL_URL", "")
        self.PPT_MODEL_NAME = os.getenv("PPT_MODEL_NAME", "DeepPresenter-9B")
        self.PPT_MODEL_API_KEY = os.getenv("PPT_MODEL_API_KEY", "")
        self.PPT_MODEL_TIMEOUT = int(os.getenv("PPT_MODEL_TIMEOUT", "300"))
        # PPTAgent Host 地址（自管流程模式：后端编排，预留下行渲染/导出集成；
        # 容器网络内地址，如 http://justice-ppt-host:7861）
        self.PPT_AGENT_URL = os.getenv("PPT_AGENT_URL", "")

        # 智能写作流水线（V1.3 推理层机制服务端化）
        # 生成后自动：后处理（文号/日期程序接管）→ 质量门 → 内容校验
        self.WRITING_AUTO_QA = os.getenv("WRITING_AUTO_QA", "true").lower() == "true"
        # 文号默认代字（无法从落款推导时使用）
        self.DOC_NUMBER_DEFAULT_DAIZI = os.getenv("DOC_NUMBER_DEFAULT_DAIZI", "粤府办")
        # 生成后是否追加一次基于格式规则的 AI 内容检查（消耗一次模型调用）
        self.WRITING_AI_FORMAT_CHECK = os.getenv("WRITING_AI_FORMAT_CHECK", "false").lower() == "true"
        # 质量门 D 级（退化/截断等硬伤）自动重试次数上限
        self.WRITING_RETRY_MAX = int(os.getenv("WRITING_RETRY_MAX", "1"))
        # 写作生成后自动保存草稿到"我的文档"（版本 1）
        self.WRITING_AUTO_SAVE_DRAFT = os.getenv("WRITING_AUTO_SAVE_DRAFT", "true").lower() == "true"

        # Embedding / 向量检索
        self.EMBEDDING_PROVIDER = os.getenv("EMBEDDING_PROVIDER", "auto")  # auto|bge|mock|http
        self.EMBED_MODEL_PATH = os.getenv("EMBED_MODEL_PATH", "/home/lwy/models/BAAI/bge-small-zh-v1.5")
        self.EMBEDDING_HTTP_URL = os.getenv("EMBEDDING_HTTP_URL", "")
        self.EMBEDDING_HTTP_MODEL = os.getenv("EMBEDDING_HTTP_MODEL", "")
        self.EMBEDDING_HTTP_TIMEOUT = int(os.getenv("EMBEDDING_HTTP_TIMEOUT", "30"))
        self.RAG_TOP_K = int(os.getenv("RAG_TOP_K", "5"))
        self.RAG_SCORE_THRESHOLD = float(os.getenv("RAG_SCORE_THRESHOLD", "0.5"))
        # 分块：结构段再按句子边界约束到 MAX_CHARS，块间保留 OVERLAP 重叠，
        # 过短碎块（< MIN_CHARS）并入前一块
        self.RAG_CHUNK_MAX_CHARS = int(os.getenv("RAG_CHUNK_MAX_CHARS", "500"))
        self.RAG_CHUNK_OVERLAP = int(os.getenv("RAG_CHUNK_OVERLAP", "80"))
        self.RAG_CHUNK_MIN_CHARS = int(os.getenv("RAG_CHUNK_MIN_CHARS", "30"))
        # 混合检索：向量 + 关键词双路召回 RRF 融合；单文档最多贡献 PER_DOC_CAP 块
        self.RAG_VECTOR_CANDIDATES = int(os.getenv("RAG_VECTOR_CANDIDATES", "30"))
        self.RAG_RRF_K = int(os.getenv("RAG_RRF_K", "60"))
        self.RAG_PER_DOC_CAP = int(os.getenv("RAG_PER_DOC_CAP", "2"))
        # 命中块上下文扩展：拼接前后相邻块（总长不超 EXPAND_BUDGET）
        self.RAG_NEIGHBOR_EXPAND = _bool(os.getenv("RAG_NEIGHBOR_EXPAND", "true"), True)
        self.RAG_EXPAND_BUDGET = int(os.getenv("RAG_EXPAND_BUDGET", "1500"))

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
