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
        # PPTAgent Host 地址（渲染下行集成；容器网络内地址，如
        # http://justice-ppt-host:7861）。留空 → 完全走本地 render_pptx，
        # 行为与接入前一致；非空 → 优先走 PPTAgent，失败自动回退本地渲染。
        self.PPT_AGENT_URL = os.getenv("PPT_AGENT_URL", "")
        # ---- PPTAgent 接口契约（第三方镜像 forceless/deeppresenter-host，
        # HTTP 契约尚未真机验证，故路径 / 字段名全部可覆盖）----------------
        # ⚠️ 下列默认值均为"最合理的 REST 形式"假设，**待真机联调确认**：
        # 挂上服务后先看 http://<host>:7861/docs 的 OpenAPI，再据此改这几项。
        # 支持 {task_id} 占位符；不写占位符时自动退化为 ?task_id=xxx 查询参数。
        self.PPT_AGENT_SUBMIT_PATH = os.getenv("PPT_AGENT_SUBMIT_PATH", "/api/ppt/generate")
        self.PPT_AGENT_STATUS_PATH = os.getenv("PPT_AGENT_STATUS_PATH", "/api/ppt/status/{task_id}")
        self.PPT_AGENT_RESULT_PATH = os.getenv("PPT_AGENT_RESULT_PATH", "/api/ppt/result/{task_id}")
        # 健康探测路径（判定"能否连上"，200/307/404 均算在线，5xx 才判不可用）。
        # PPTAgent Host 的 7861 是 Gradio WebUI，根路径 "/" 一定在，故用它做探针。
        self.PPT_AGENT_HEALTH_PATH = os.getenv("PPT_AGENT_HEALTH_PATH", "/")
        # 提交响应的任务 ID 字段名；留空则按常见候选自动探测（task_id/id/job_id...）
        self.PPT_AGENT_TASK_ID_FIELD = os.getenv("PPT_AGENT_TASK_ID_FIELD", "")
        # 轮询状态视为"完成"/"失败"的字面量（逗号分隔，大小写不敏感）
        self.PPT_AGENT_DONE_VALUES = os.getenv(
            "PPT_AGENT_DONE_VALUES", "succeeded,success,completed,complete,done,finished")
        self.PPT_AGENT_FAIL_VALUES = os.getenv(
            "PPT_AGENT_FAIL_VALUES", "failed,failure,error,cancelled,canceled,aborted,timeout")
        # 可选鉴权（GET/POST 都会带 Authorization 与 X-API-Key 头）
        self.PPT_AGENT_API_KEY = os.getenv("PPT_AGENT_API_KEY", "")
        # 超时（秒）：按真机实测的生成耗时设定——PPTAgent 是**聊天式 Agent**，
        # 一次生成实测 5~15 分钟（300~900s），且需排队占 GPU。默认务必留足余量，
        # 宁可让用户多等，也不能把正常任务判超时后回退成本地渲染（白等十分钟）。
        # 提交：Gradio 若走 queue（/gradio_api/queue/join），入队本身也可能阻塞
        self.PPT_AGENT_SUBMIT_TIMEOUT = int(os.getenv("PPT_AGENT_SUBMIT_TIMEOUT", "60"))
        # 单次取结果/下载：pptx + pdf 一起落盘，磁盘慢时也要够
        self.PPT_AGENT_RESULT_TIMEOUT = int(os.getenv("PPT_AGENT_RESULT_TIMEOUT", "300"))
        # 整体预算（秒）：从提交到取回 pptx 的总上限 = 1800s（30 分钟），
        # 覆盖 15 分钟生成 + 排队等待；超时才回退本地渲染
        self.PPT_AGENT_TOTAL_TIMEOUT = int(os.getenv("PPT_AGENT_TOTAL_TIMEOUT", "1800"))
        # 轮询间隔（秒）：长任务不需要秒级轮询，10s 兼顾及时性与日志量
        self.PPT_AGENT_POLL_INTERVAL = int(os.getenv("PPT_AGENT_POLL_INTERVAL", "10"))

        # ---- 取结果的**备用主通道**：直接读共享卷里的产物文件 ----------------
        # PPTAgent 会把成品写到 <workspace>/<日期>/<job_id>/presentation.pptx。
        # 若后端容器能以只读方式挂到同一目录，则无需猜 Gradio 的结果端点，
        # 直接扫文件系统取最新产物，可靠性远高于未文档化的 HTTP 契约。
        # 留空 = 走 HTTP 通道（submit → 轮询 → 取结果）；非空 = 走文件系统通道。
        self.PPT_AGENT_WORKSPACE_DIR = os.getenv("PPT_AGENT_WORKSPACE_DIR", "")
        # 产物文件名（PPTAgent 固定输出 presentation.pptx）
        self.PPT_AGENT_RESULT_FILENAME = os.getenv("PPT_AGENT_RESULT_FILENAME", "presentation.pptx")
        # 产物"新鲜度"判定：只认提交任务之后落盘的文件（秒，容错时钟偏差）
        self.PPT_AGENT_WORKSPACE_FRESH_TOLERANCE = int(
            os.getenv("PPT_AGENT_WORKSPACE_FRESH_TOLERANCE", "120"))

        # ---- Gradio 真实契约（已在真机探查确认，见 deploy/pptagent/README.md）----
        # 命名端点 /send_message：6 个入参（message, history, attachments,
        # convert_type_value, template_value, num_pages_value），5 个出参，
        # 其中第 4 个（0-based index 3）「📥 下载文件」是最终 pptx 的 FileData。
        # 两个端点 queue=True → 提交返回 event_id，再消费 SSE 事件流取结果。
        # Gradio 5 命名端点风格（默认）：
        self.PPT_AGENT_SUBMIT_PATH = os.getenv(
            "PPT_AGENT_SUBMIT_PATH", "/gradio_api/call/send_message")
        self.PPT_AGENT_EVENT_PATH = os.getenv(
            "PPT_AGENT_EVENT_PATH", "/gradio_api/call/send_message/{event_id}")
        # 旧版 Gradio（4.x）queue 风格，可整体切换为：
        #   SUBMIT=/gradio_api/queue/join
        #   EVENT =/gradio_api/queue/data?session_hash={session_hash}
        # 事件流句柄字段名；留空则自动探测 event_id / task_id / id
        self.PPT_AGENT_EVENT_ID_FIELD = os.getenv("PPT_AGENT_EVENT_ID_FIELD", "")
        # queue/join 需要的 fn_index（命名端点风格不需要，留空不下发）
        self.PPT_AGENT_FN_INDEX = os.getenv("PPT_AGENT_FN_INDEX", "")
        # queue/data 需要的 session_hash；留空时自动生成随机串
        self.PPT_AGENT_SESSION_HASH = os.getenv("PPT_AGENT_SESSION_HASH", "")
        # 出参索引（0-based）：3=📥 下载文件（pptx FileData）、4=Markdown（追问/说明）
        self.PPT_AGENT_RESULT_OUTPUT_INDEX = int(
            os.getenv("PPT_AGENT_RESULT_OUTPUT_INDEX", "3"))
        self.PPT_AGENT_QUESTION_OUTPUT_INDEX = int(
            os.getenv("PPT_AGENT_QUESTION_OUTPUT_INDEX", "4"))
        # 入参 4/5/6 的固定取值（契约内的枚举字面量）
        self.PPT_AGENT_CONVERT_TYPE = os.getenv(
            "PPT_AGENT_CONVERT_TYPE", "自由生成 (freeform)")
        self.PPT_AGENT_TEMPLATE = os.getenv("PPT_AGENT_TEMPLATE", "auto")
        # 单条 message 的最大字符数（超出截断，避免请求体过大）
        self.PPT_AGENT_MESSAGE_MAX_CHARS = int(
            os.getenv("PPT_AGENT_MESSAGE_MAX_CHARS", "24000"))
        # 附件目录映射（R2）："后端可见目录:PPTAgent容器内目录"，留空=不传附件。
        # attachments 的 path 必须是 **PPTAgent 容器内** 的路径，跨容器传本地路径
        # 它读不到；只有在两边挂了同一个共享卷、且知道容器内挂载点时才可启用。
        self.PPT_AGENT_ATTACHMENT_MAP = os.getenv("PPT_AGENT_ATTACHMENT_MAP", "")

        # ---- 目录扫描（仅用于实时进度；目录结构待真机核实，故全部可配置）----
        # ⚠️ 用户给过的两份说明对目录结构说法不一致（是否有 slides/slide_NN.html
        # 存疑），因此这里不写死，找不到就降级为"只有总进度、没有逐页预览"。
        self.PPT_AGENT_PREVIEW_GLOB = os.getenv("PPT_AGENT_PREVIEW_GLOB", "preview/*.png")
        self.PPT_AGENT_SLIDE_GLOB = os.getenv("PPT_AGENT_SLIDE_GLOB", "slides/*.html")
        # 无进展判定（秒）：超过这个时长目录和事件流都没动静就判失败
        self.PPT_AGENT_STALL_TIMEOUT = int(os.getenv("PPT_AGENT_STALL_TIMEOUT", "1800"))
        # 进度扫描间隔（秒）
        self.PPT_AGENT_PROGRESS_INTERVAL = int(os.getenv("PPT_AGENT_PROGRESS_INTERVAL", "5"))

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
