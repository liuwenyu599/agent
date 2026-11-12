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
        self.MODEL_NAME = os.getenv("MODEL_NAME", "Qwen3.6-35B-A3B-W8A8")
        self.MODEL_API_KEY = os.getenv("MODEL_API_KEY", "")
        self.MODEL_TIMEOUT = int(os.getenv("MODEL_TIMEOUT", "300"))
        # 单个网关实例同时在途的模型请求上限。等待在 asyncio.Semaphore 上，不占 FastAPI worker thread。
        self.MODEL_MAX_CONCURRENCY = max(1, int(os.getenv("MODEL_MAX_CONCURRENCY", "4")))
        self.MODEL_USER_MAX_CONCURRENCY = max(1, int(os.getenv("MODEL_USER_MAX_CONCURRENCY", "2")))
        self.MODEL_USER_MAX_PENDING = max(1, int(os.getenv("MODEL_USER_MAX_PENDING", "8")))
        self.MODEL_TEMPERATURE = float(os.getenv("MODEL_TEMPERATURE", "0.4"))
        self.MODEL_MAX_TOKENS = int(os.getenv("MODEL_MAX_TOKENS", "4096"))
        self.MODEL_CTX_LIMIT = int(os.getenv("MODEL_CTX_LIMIT", "16384"))
        self.MODEL_HEALTH_TIMEOUT = int(os.getenv("MODEL_HEALTH_TIMEOUT", "5"))
        self.MODEL_FAILOVER_COOLDOWN = int(os.getenv("MODEL_FAILOVER_COOLDOWN", "15"))
        # 长文生成专用模型（可选）。配置后，写作台「长文正文生成」路由到该模型（如 35B 评估实例），
        # 而规划 / 意图理解 / 工具调用仍走主模型（MODEL_SERVICE_URLS）。留空则长文仍走主模型，
        # 行为与历史完全一致，零侵入。长文网关默认关闭思考（enable_thinking=false），避免 35B 这类
        # 思考模型在正文里输出 CoT，既省 token 又提速。
        self.LONG_FORM_MODEL_URLS = os.getenv("LONG_FORM_MODEL_URLS", "")
        self.LONG_FORM_MODEL_NAME = os.getenv("LONG_FORM_MODEL_NAME", "Qwen3.6-35B-A3B-W8A8")
        self.LONG_FORM_MODEL_TIMEOUT = int(os.getenv("LONG_FORM_MODEL_TIMEOUT", "600"))
        self.VISION_MODEL_URL = os.getenv("VISION_MODEL_URL", "")
        self.VISION_MODEL_NAME = os.getenv("VISION_MODEL_NAME") or self.MODEL_NAME
        self.VISION_MODEL_API_KEY = os.getenv("VISION_MODEL_API_KEY", "")
        self.VISION_MODEL_TIMEOUT = int(os.getenv("VISION_MODEL_TIMEOUT", "180"))
        self.VISION_MAX_IMAGES = int(os.getenv("VISION_MAX_IMAGES", "4"))
        self.AI_PROVIDER = os.getenv("AI_PROVIDER", "auto")

        # PPT 助手专用模型
        self.PPT_MODEL_URL = os.getenv("PPT_MODEL_URL", "")
        self.PPT_MODEL_NAME = os.getenv("PPT_MODEL_NAME", self.MODEL_NAME)
        self.PPT_MODEL_API_KEY = os.getenv("PPT_MODEL_API_KEY", "")
        self.PPT_MODEL_TIMEOUT = int(os.getenv("PPT_MODEL_TIMEOUT", "300"))
        # PPT 长模型请求准入。生产实测（2026-11-12, 35B 单端点 8010）：
        # 2 条 PPT 长构图 + 4 条交互式写作短请求时，短请求 TTFT 从 2.47s
        # 劣化到 9.39s。限制同时在途的 PPT 专用模型调用数，且始终小于
        # MODEL_MAX_CONCURRENCY，为交互式写作至少留 1 个模型名额。
        self.PPT_MODEL_MAX_CONCURRENCY = max(
            1, int(os.getenv("PPT_MODEL_MAX_CONCURRENCY", "2")))
        # 首轮构图批次并行度。默认 1 = 保持串行；实测单端点下并行 2 条构图
        # 几乎无收益（52.1s vs 串行 55.6s），并行 4 条虽省 47s 却会拖慢写作。
        # 只有在给 PPT 起了独立模型副本后才建议灰度调到 2。
        self.PPT_COMPOSITION_PARALLEL = max(
            1, int(os.getenv("PPT_COMPOSITION_PARALLEL", "1")))
        # FIFO 队列上限与排队超时（秒）：50 人同时提交时不无限堆积、不无限等待。
        self.PPT_QUEUE_MAX = max(1, int(os.getenv("PPT_QUEUE_MAX", "50")))
        self.PPT_QUEUE_TIMEOUT = max(0, int(os.getenv("PPT_QUEUE_TIMEOUT", "1800")))
        # 等闸门的最长时间（秒）。防止 50 人同时请求时 HTTP 线程被无限期挂住。
        self.PPT_MODEL_SLOT_TIMEOUT = max(
            1, int(os.getenv("PPT_MODEL_SLOT_TIMEOUT", "300")))
        # FastAPI/AnyIO 默认只有 40 个工作线程；50 人同时等在 PPT 闸门上会
        # 把线程池占满，连交互式写作都排不进来。启动期把配额调大。
        self.WEB_THREADPOOL_TOKENS = max(
            40, int(os.getenv("WEB_THREADPOOL_TOKENS", "120")))
        # PPTAgent 已退出生产链路。只有显式打开兼容开关才读取其地址；默认使用
        # 本地原生 PPTX 渲染器，生成的文本框、形状和表格均可继续编辑。
        self.PPT_AGENT_ENABLED = _bool(os.getenv("PPT_AGENT_ENABLED"), False)
        self.PPT_CLOUD_ALLOWED = _bool(os.getenv("PPT_CLOUD_ALLOWED"), False)
        self.PPT_AGENT_URL = os.getenv("PPT_AGENT_URL", "") if self.PPT_AGENT_ENABLED else ""
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

        # Draw.io MCP（PPT 视觉增强层）
        # 官方镜像 jgraph/drawio-mcp，Streamable HTTP 端点 /mcp，默认容器内端口 3001。
        # 仅作「模型工具调用」后端代理：get_drawio_reference / search_shapes / create_diagram。
        # 留空则 PPT 流程图仍走本地原生渲染，不依赖该服务（零侵入）。
        self.DRAWIO_MCP_URL = os.getenv("DRAWIO_MCP_URL", "")
        self.DRAWIO_MCP_TIMEOUT = int(os.getenv("DRAWIO_MCP_TIMEOUT", "30"))
        # Graphviz dot 可执行文件（或其 bin 目录）。Windows 开发机往往没把
        # Graphviz 加进 PATH，配置后无需改系统环境即可启用 drawio-skill 布局；
        # 容器镜像已内置 graphviz，无需配置。留空则只认 PATH 里的 dot。
        self.GRAPHVIZ_DOT = os.getenv("GRAPHVIZ_DOT", "")

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
        # 单卡默认逐节生成；确认目标机吞吐收益后最多开放两节并发。
        self.WRITING_SECTION_MAX_CONCURRENCY = max(
            1, min(2, int(os.getenv("WRITING_SECTION_MAX_CONCURRENCY", "1"))))
        # 本地 embedding/reranker 不能中断正在执行的 CPU 推理；超过预算后
        # 写作请求返回空资料继续生成，并暂缓再次发起重模型检索。
        self.WRITING_RAG_SOFT_TIMEOUT_SECONDS = max(
            1, int(os.getenv("WRITING_RAG_SOFT_TIMEOUT_SECONDS", "8")))
        self.WRITING_RAG_FAILURE_THRESHOLD = max(
            1, int(os.getenv("WRITING_RAG_FAILURE_THRESHOLD", "3")))
        self.WRITING_RAG_COOLDOWN_SECONDS = max(
            1, int(os.getenv("WRITING_RAG_COOLDOWN_SECONDS", "45")))

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
