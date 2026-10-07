"""PPTAgent Host 渲染客户端（HTTP / 同步）。

部署契约见 ``deploy/pptagent/README.md``：

    司法局 FastAPI :8000
      → PPTAgent Host :7861（容器名 justice-ppt-host）
          → 内部 Sandbox → OpenAI 兼容 → DeepPresenter-9B :8003

⚠️ API 契约状态（务必先读）
    ``forceless/deeppresenter-host`` 是第三方镜像。公开资料显示它的 7861 端口跑的
    是 **Gradio WebUI**（容器内 ``python webui.py 0.0.0.0``），而不是文档化的 REST
    服务。同时它的定位是"喂主题/材料，Agent 全权生成整套 PPT"，而非"渲染现成大纲"。
    因此本客户端遵循两条原则：

    1. **不臆造**：所有路径、任务 ID 字段名、状态字面量、结果字段名全部做成
       配置项，默认值只取"最合理的 REST 形式"占位，并在
       ``deploy/.env.example`` 中标注"待真机联调确认"。Gradio 若只能走
       ``/gradio_api/...``，改 ``PPT_AGENT_SUBMIT_PATH`` 即可；
       若提交一次即返回结果文件，客户端会自动识别并跳过轮询。
    2. **不硬撑**：调用方（PPTService._render_and_store）必须在拿不到**合法
       pptx** 时回退本地 ``render_pptx``。绝不把打不开的文件交给用户。

已知（公开资料，非真机实测）：
    - deeppresenter-host 容器内运行 Gradio UI + Agent Loop + MCP Server；
    - deeppresenter-sandbox 由 host 通过 docker socket 按需拉起，不常驻、不开端口；
    - PPTAgent 的内部三大工具链：any2markdown（材料转 MD）、task（任务编排）、
      search（联网检索），HTML → PPTX 由 Node/Playwright 完成。

待真机确认（拿到 7861 后第一步就是看它自己吐出来的 API 定义）：
    1. Gradio 根路径 ``/`` 是否可匿名访问（健康探测依赖它）；
    2. Gradio 的函数入口名（``/gradio_api/run/<fn>`` 或 ``/run/<fn>``）与入参结构；
    3. 是"提交→轮询"两步，还是"一次请求等到出结果"；后者客户端已自动兼容；
    4. 结果形态：Gradio FileData（``{"url"/"path", "orig_name": "x.pptx"}``）、
       二进制直返、或 JSON 里的下载链接 / BASE64，三种本客户端均已处理。
详见 deploy/.env.example 中 PPT_AGENT_* 段落注释。
"""
import base64
import json as _json
import re
import time
import uuid
import zipfile
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin

import httpx

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_PPTX_MIME_HINTS = (
    "presentationml",
    "vnd.ms-powerpoint",
    "application/zip",
    "application/octet-stream",
)

# 任务 ID 候选字段名（按命中概率排序）—— 待真机确认后可由 PPT_AGENT_TASK_ID_FIELD 覆盖
_TASK_ID_FIELDS = ("task_id", "taskId", "job_id", "jobId", "id", "session_id",
                   "sessionId", "run_id", "runId", "task", "result_id")

# 状态值候选字段名
_STATUS_FIELDS = ("status", "state", "stage", "phase")

# 结果 URL 候选字段名
_URL_FIELDS = ("download_url", "downloadUrl", "file_url", "fileUrl", "result_url",
               "resultUrl", "pptx_url", "pptxUrl", "url", "path", "file", "link",
               "output", "output_url")

# 结果 base64 候选字段名
_B64_FIELDS = ("file_base64", "fileBase64", "pptx_base64", "pptxBase64", "content",
               "data_base64", "base64", "file_content")

# 事件流句柄候选字段名（Gradio 5 命名端点 / Gradio 4 queue 风格）
_EVENT_ID_FIELDS = ("event_id", "eventId", "task_id", "taskId", "job_id", "run_id", "id")

# Office / LibreOffice 打开文档时产生的锁文件与临时副本，扫描产物时必须跳过，
# 否则会拿到 0 字节或一个读写中的半成品。
_TEMP_FILE_PREFIXES = ("~$", ".~")

# 小于此字节数的 .pptx 一定不是成品（真实的 pptx 至少几十 KB），
# 用于挡住 PPTAgent 刚创建、尚未写入完成的空壳文件。
_MIN_PPTX_SIZE = 8 * 1024


def gradio_contract_conflict(submit_path: str) -> str:
    """诊断「同步 REST 通道被指向 Gradio 端点」这种必失败配置。

    ``render()`` 发的是 REST 请求体（``topic``/``content``/...），Gradio 命名端点
    只认 ``{"data": [6 个入参]}``，两者不可能同时对得上：请求一定会拿到 4xx/5xx，
    然后在调用方静默回退本地渲染。这本是部署策略问题（要不要让同步导出也走
    PPTAgent），不宜由客户端擅自拦死，所以这里**只返回说明文本**供日志提示，
    不改变任何调用行为。

    Args:
        submit_path: 提交地址（``PPT_AGENT_SUBMIT_PATH`` 的当前值）。

    Returns:
        冲突说明；无冲突时返回空串。
    """
    if "/gradio_api/" not in (submit_path or ""):
        return ""
    return (
        f"PPT_AGENT_SUBMIT_PATH={submit_path} 是 Gradio 命名端点，"
        "但同步 render 通道只能发 REST 请求体，本次请求必然失败并回退本地渲染。"
        "若希望导出也用 PPTAgent，请走异步链路 POST /ppt/jobs"
        "（agent_job 内部走 submit_message + SSE 事件流）；"
        "若希望同步通道保持可用，请把该项改回非 Gradio 的 REST 地址。"
    )


def split_patterns(raw: str) -> Tuple[str, ...]:
    """把配置项里的 glob 模式拆成元组，支持逗号或分号分隔的多个候选模式。

    预览图目录名与产物文件名都**随 PPT 标题动态变化**（例如真实 job 目录里的
    ``.slide_images-pdf-司法局工作汇报/slide_01.jpg``），单个模式一旦对不上就整块
    失效，因此允许配置多个候选、命中任一即算数。

    Args:
        raw: 原始配置值，如 ``".slide_images-*/*.jpg,preview/*.png"``。

    Returns:
        去空去重后的模式元组；输入为空时返回空元组。
    """
    parts = (raw or "").replace(";", ",").split(",")
    seen: List[str] = []
    for p in parts:
        p = p.strip()
        if p and p not in seen:
            seen.append(p)
    return tuple(seen)


def collect_files(root: Path, patterns: Tuple[str, ...], threshold: float,
                  min_size: int = 0) -> List[Path]:
    """按多个 glob 模式递归搜集文件：**去重后按路径字典序排序**。

    ``rglob`` 会对每个模式各 walking 一次，多个模式可能命中同一文件，所以这里用
    绝对路径做键去重。排序保证 ``slide_01..slide_NN`` 的页序稳定可预测（文件名是
    零填充的两位数，字典序 == 页序）。

    Args:
        root: 扫描根目录（共享卷挂载的工作区）。
        patterns: :func:`split_patterns` 得到的模式元组。
        threshold: mtime 下限（Unix 秒），用于只认本次任务之后落盘的文件。
        min_size: 最小字节数，用于过滤尚未写完的空壳文件。

    Returns:
        命中的文件路径列表；任何 OSError 都被吞掉并降级为空列表——远端目录
        随时在变，扫描失败绝不能影响主流程。
    """
    found: Dict[str, Path] = {}
    for pattern in patterns:
        try:
            for p in root.rglob(pattern):
                if p.name.startswith(_TEMP_FILE_PREFIXES):
                    continue
                try:
                    st = p.stat()
                except OSError:
                    continue
                if not p.is_file() or st.st_mtime < threshold or st.st_size < min_size:
                    continue
                found[str(p)] = p
        except OSError as e:  # noqa: BLE001 - 扫描失败只降级
            logger.debug("扫描模式 %s 失败（已跳过）：%s", pattern, e)
            continue
    return [found[k] for k in sorted(found)]


# Gradio FileData 自身的字段；用于判断某个 dict "是不是 FileData 本体"
# ——只有确认不是本体时，才允许继续往下剥包装，避免把 FileData 的字段误拆。
_FILEDATA_KEYS = frozenset(
    {"path", "url", "orig_name", "meta", "tmp_url", "is_stream", "size", "mime_type"}
)

# Gradio 组件更新会把值包进 {"value": X, "__type__": "update"}，多个组件的出参
# 组成 data 数组时，**每个元素都带这层壳**。少解这层就等于产物摆在眼前取不回来。
_VALUE_WRAPPER_KEYS = ("value", "data", "result", "result_data", "output", "payload")

_MAX_UNWRAP_DEPTH = 6

# ---- OUT[4] Markdown 末尾的运行统计：必须整段丢掉，不能当追问弹给用户 ------
# ⚠️ 真机样本（20260927）是**中文、无 emoji**的整块统计，形如：
#     ## Token 使用统计
#     **Research Agent** (Model: `DeepPresenter-9B`)
#     - 输入: 33,320 tokens
#     - 输出: 2,609 tokens
#     ...
#     **总计**  - 输入: 316,242 tokens
# 只靠"含 marker 且带数字"的逐行过滤是拦不住的：标题行 `## Token 使用统计`、
# Agent 名行、**总计** 行都**不带数字**，过滤完照样拼成一段"看起来像追问"的文本。
# 所以主防线必须是**整块判定**：认出统计块的起始标题行，从那一行起整段丢弃。

# 统计块的起始标题行判定：该行同时出现 token 与统计/用量语义词。
_TOKEN_KEYWORD_RE = re.compile(r"\btokens?\b", re.I)
_TOKEN_STATS_WORD_RE = re.compile(r"统计|用量|使用量|消耗|概况|usage|statistics", re.I)

# 逐行兜底：命中这些 marker **且同行带数字**的行才丢掉。
# 要求带数字是为了不误伤正文里提到"成本控制""统计工作"的普通句子。
_TOKEN_STAT_LINE_RE = re.compile(r"(🔤|💰|💵|⏱|\btokens?\b|\bcost\b)", re.I)
# 无数字的短状态语也不是追问；真机偶发返回“暂无 token 数据”。
_NO_TOKEN_DATA_RE = re.compile(r"^\s*(?:暂无|没有|无)\s*tokens?\s*(?:数据|信息|统计)?\s*[。.!！]?$|^\s*no\s+token\s+data\s*[.!]?$", re.I)
_DIGIT_RE = re.compile(r"\d")


def unwrap_value(obj: Any, _depth: int = 0) -> Any:
    """剥掉 Gradio 组件的更新包装，拿到真正的值。

    真机一次 ``event: complete`` 的 data 形如（每个元素一层壳）::

        [ Chatbot, Textbox, File,
          {"value": {"path": "/tmp/x.pptx",
                     "url": "/gradio_api/file=/tmp/x.pptx",
                     "orig_name": "x.pptx",
                     "meta": {"_type": "gradio.FileData"}}, "__type__": "update"},
          {"value": "## 请确认汇报对象…", "__type__": "update"} ]

    早期实现只认 data/result/output 三种 wrapper，**漏了 value**，于是每个出参都
    被当成"没字段的字典"跳过，产物永远取不到。这里改成通用解包：
    只要 dict 带 value/data/... 且自身不是 FileData，就继续往下剥，直到稳定。

    Args:
        obj: 可能是包装层、FileData、也可能是普通值。
        _depth: 递归深度保护，防止异常结构导致无限递归。

    Returns:
        解包后的对象；无法再剥时原样返回。
    """
    if _depth >= _MAX_UNWRAP_DEPTH:
        return obj
    if isinstance(obj, dict):
        # 命中 FileData 本体就停手，绝不把它的内部字段拆出来
        if obj.keys() & _FILEDATA_KEYS:
            return obj
        for key in _VALUE_WRAPPER_KEYS:
            if key in obj:
                inner = obj[key]
                # File 组件常见 {"value": None, "__type__": "update"} —— 必须把
                # None 原样解出来（而不是把整个包装层返回去），否则下游会把它当成一个
                # "没有 url 的 dict"反复尝试，语义上完全错位。
                if isinstance(inner, (dict, list)):
                    return unwrap_value(inner, _depth + 1)
                return inner
    return obj


def find_token_stats_block(text: str) -> int:
    """定位 Markdown 里「Token 使用统计」块的起始位置（行首下标），没有则返回 -1。

    Args:
        text: Markdown 原始文本。

    Returns:
        统计块标题行的行首下标；未命中返回 -1。
    """
    pos = 0
    for line in (text or "").splitlines(keepends=True):
        if _TOKEN_KEYWORD_RE.search(line) and _TOKEN_STATS_WORD_RE.search(line):
            return pos
        pos += len(line)
    return -1


def strip_token_stats(text: str) -> str:
    """去掉 Markdown 出参里的 token 统计块，留下真正要说的话。

    PPTAgent 成功生成后，会在 Markdown 出参（OUT[4]）里写一段**运行统计**：

        ## Token 使用统计
        **Research Agent** (Model: `DeepPresenter-9B`)
        - 输入: 33,320 tokens  ·  - 输出: 2,609 tokens
        ...
        **总计** - 输入: 316,242 tokens

    它既不是追问、也不是给用户看的内容，若当成 question 弹出去，用户会对着一屏
    数字不知所措。过滤分两级：

    1. **整块判定（主防线）**：认出统计块的标题行，**从那一行起整段丢弃**。
       这一步必须有——真机是中文无 emoji 的块，标题行/Agent 名行/总计行都不带
       数字，只靠逐行过滤拦不住。
    2. **逐行剔除（兜底）**：没有成块标题时（比如只散落几行 ``🔤 Tokens: 123``），
       再按行剔除。要求"命中 marker 且同行带数字"，避免误伤正文里提到
       "成本控制""统计工作"的普通句子。

    Args:
        text: 原始 Markdown 文本。

    Returns:
        剔除统计后的文本；全是统计时返回空串（调用方据此判定"没有追问"）。
    """
    raw = text or ""
    # ① 整块判定：统计块是追加在末尾的，命中就把它连同之后的内容全部切掉
    pos = find_token_stats_block(raw)
    if pos >= 0:
        return raw[:pos].strip()
    # ② 逐行兜底
    kept: List[str] = []
    for line in raw.splitlines():
        if _NO_TOKEN_DATA_RE.match(line):
            continue
        if _TOKEN_STAT_LINE_RE.search(line) and _DIGIT_RE.search(line):
            continue
        kept.append(line)
    return "\n".join(kept).strip()


class PPTAgentError(RuntimeError):
    """PPTAgent 调用失败（网络 / 协议 / 返回非法文件），调用方应回退本地渲染。"""


@dataclass
class PPTAgentOutcome:
    """一次 PPTAgent 交互的结果（异步 job 用）。

    Attributes:
        pptx: 成品 pptx 字节；拿到即为成功产物。
        question: PPTAgent 的**追问**文本（R1：信息不足时它会先提问而不是生成）。
        outputs: 原始出参列表（5 项），便于排障与后续扩展。
        event_id: 事件流句柄，用于日志串联。
        pending: True 表示既没拿到产物也没拿到追问（仍在进行/异常）。
    """
    pptx: Optional[bytes] = None
    question: str = ""
    outputs: List[Any] = field(default_factory=list)
    event_id: str = ""

    @property
    def pending(self) -> bool:
        """既无产物也无追问 —— 视为仍在进行中。"""
        return self.pptx is None and not self.question.strip()


def looks_like_pptx(data: Optional[bytes]) -> Tuple[bool, str]:
    """校验字节流是否为可打开的 pptx。

    pptx 本质是 OPC 包（zip），且必须含 ``ppt/presentation.xml``；这里只做
    ``content_types`` 级别的廉价校验，足以挡住 HTML 错误页 / JSON / 空文件。

    Args:
        data: 待校验的字节流。

    Returns:
        (是否合法, 原因说明)
    """
    if not data:
        return False, "返回内容为空"
    if len(data) < 1024:
        return False, f"返回内容过小（{len(data)} 字节），疑似错误页"
    try:
        if not zipfile.is_zipfile(BytesIO(data)):
            return False, "返回内容不是 zip 包（pptx 应为 OPC zip 包）"
        with zipfile.ZipFile(BytesIO(data)) as zf:
            names = set(zf.namelist())
            if "ppt/presentation.xml" not in names:
                return False, "zip 包内缺少 ppt/presentation.xml，不是有效 pptx"
    except Exception as e:  # noqa: BLE001 - 校验不应抛出，转为一律判定非法
        return False, f"校验异常：{type(e).__name__}: {e}"
    return True, "ok"


def _dig(obj: Any, fields: Tuple[str, ...]) -> Optional[Any]:
    """从响应体里按候选字段名取值，支持一层 data/result 包裹。

    Gradio 的响应里 ``data`` 是**数组**（元素可能自带文件对象），故这里额外遍历
    数组元素；这样对接 Gradio 原生端点时无需改代码。
    """
    if not isinstance(obj, dict):
        return None
    # Gradio 出参带 {"value": ...} 壳，先剥掉再按候选字段名取值
    obj = unwrap_value(obj)
    if not isinstance(obj, dict):
        return None
    for f in fields:
        if f in obj and obj[f] not in (None, ""):
            return obj[f]
    for wrapper in _VALUE_WRAPPER_KEYS:
        sub = obj.get(wrapper)
        if isinstance(sub, dict):
            for f in fields:
                if f in sub and sub[f] not in (None, ""):
                    return sub[f]
        elif isinstance(sub, list):
            # Gradio: {"data": [{"url": "...", "orig_name": "x.pptx", ...}, ...]}
            for item in sub:
                if not isinstance(item, dict):
                    continue
                for f in fields:
                    if f in item and item[f] not in (None, ""):
                        return item[f]
    return None


def _gradio_file_url(obj: Any) -> str:
    """提取 Gradio FileData 里的文件地址：优先 url，退化到 path。

    Gradio FileData 形如 ``{"path": "/tmp/gradio/x.pptx", "url":
    "/gradio_api/file=/tmp/gradio/x.pptx", "orig_name": "x.pptx",
    "meta": {"_type": "gradio.FileData"}}``。``path`` 多为容器内绝对路径，
    所以只在没有 ``url`` 时才用它（拼成绝对 URL 后多半 404，届时正常回退本地）。
    """
    if not isinstance(obj, dict):
        return ""
    # 先剥一层 {"value": FileData, "__type__": "update"}；少这一步就取不到产物
    obj = unwrap_value(obj)
    if isinstance(obj, list):
        for item in obj:
            got = _gradio_file_url(item)
            if got:
                return got
        return ""
    if not isinstance(obj, dict):
        return ""
    for key in ("url", "path", "tmp_url"):
        v = obj.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    for wrapper in _VALUE_WRAPPER_KEYS:
        sub = obj.get(wrapper)
        if isinstance(sub, (dict, list)):
            got = _gradio_file_url(sub)
            if got:
                return got
    return ""


def _abs_url(base: str, maybe_url: str) -> str:
    """把可能的结果 URL 拼成绝对地址。"""
    maybe_url = (maybe_url or "").strip()
    if not maybe_url:
        return ""
    if maybe_url.startswith(("http://", "https://")):
        return maybe_url
    return urljoin(base.rstrip("/") + "/", maybe_url.lstrip("/"))


class PPTAgentClient:
    """PPTAgent Host 的同步 HTTP 客户端：提交 / 轮询 / 取结果。

    路径支持 ``{task_id}`` 占位符；未写占位符时自动退化为 query 参数
    ``?task_id=xxx``（部分服务是这种风格）。

    所有网络异常统一抛 ``PPTAgentError``，调用方捕获后回退本地渲染即可。
    """

    def __init__(
        self,
        base_url: str,
        *,
        submit_path: str = "/api/ppt/generate",
        status_path: str = "/api/ppt/status/{task_id}",
        result_path: str = "/api/ppt/result/{task_id}",
        health_path: str = "/",
        api_key: str = "",
        submit_timeout: int = 30,
        poll_interval: int = 5,
        total_timeout: int = 600,
        task_id_field: str = "",
        done_values: str = "succeeded,success,completed,complete,done,finished",
        fail_values: str = "failed,failure,error,cancelled,canceled,aborted,timeout",
        workspace_dir: str = "",
        result_glob: str = "",
        fresh_tolerance: int = 120,
        event_path: str = "/gradio_api/call/send_message/{event_id}",
        event_id_field: str = "",
        fn_index: str = "",
        session_hash: str = "",
        result_output_index: int = 3,
        question_output_index: int = 4,
        convert_type: str = "自由生成 (freeform)",
        template_value: str = "auto",
        message_max_chars: int = 24000,
        preview_glob: str = ".slide_images-*/*.jpg,.slide_images-*/*.png,"
                             "preview/*.jpg,preview/*.png",
        slide_glob: str = "slides/*.html",
        attachment_map: str = "",
        transport: Optional[Any] = None,
    ) -> None:
        self.base_url = (base_url or "").rstrip("/")
        self.submit_path = submit_path or "/api/ppt/generate"
        self.status_path = status_path or "/api/ppt/status/{task_id}"
        self.result_path = result_path or "/api/ppt/result/{task_id}"
        self.health_path = health_path or "/docs"
        self.api_key = (api_key or "").strip()
        self.submit_timeout = max(1, int(submit_timeout))
        self.poll_interval = max(1, int(poll_interval))
        self.total_timeout = max(self.submit_timeout, int(total_timeout))
        self.task_id_field = (task_id_field or "").strip()
        self.done_values = {v.strip().lower() for v in done_values.split(",") if v.strip()}
        self.fail_values = {v.strip().lower() for v in fail_values.split(",") if v.strip()}
        # 共享卷取产物通道（留空则走 HTTP 三步流程）
        self.workspace_dir = (workspace_dir or "").strip()
        # 产物匹配模式（glob，支持多模式；默认为 *.pptx —— 产物名随标题动态变化）
        self.result_glob = (
            (result_glob or "").strip() or getattr(settings, "PPT_AGENT_RESULT_GLOB", "*.pptx")
            or "*.pptx")
        self.fresh_tolerance = max(0, int(fresh_tolerance))
        # ---- Gradio 真实契约相关 ----
        self.event_path = event_path or "/gradio_api/call/send_message/{event_id}"
        self.event_id_field = (event_id_field or "").strip()
        self.fn_index = (fn_index or "").strip()
        self.session_hash = (session_hash or "").strip() or uuid.uuid4().hex
        self.result_output_index = max(0, int(result_output_index))
        self.question_output_index = max(0, int(question_output_index))
        self.convert_type = convert_type or "自由生成 (freeform)"
        self.template_value = template_value or "auto"
        self.message_max_chars = max(500, int(message_max_chars))
        self.preview_glob = preview_glob or ".slide_images-*/*.jpg"
        self.slide_glob = slide_glob or "slides/*.html"
        self.attachment_map = (attachment_map or "").strip()
        self._transport = transport

    # ---------------- 构造 ----------------

    @classmethod
    def from_settings(cls, transport: Optional[Any] = None) -> "PPTAgentClient":
        """按全局配置构造客户端（测试可注入 transport / monkeypatch 配置）。"""
        return cls(
            base_url=settings.PPT_AGENT_URL,
            submit_path=settings.PPT_AGENT_SUBMIT_PATH,
            status_path=settings.PPT_AGENT_STATUS_PATH,
            result_path=settings.PPT_AGENT_RESULT_PATH,
            health_path=settings.PPT_AGENT_HEALTH_PATH,
            api_key=settings.PPT_AGENT_API_KEY,
            submit_timeout=settings.PPT_AGENT_SUBMIT_TIMEOUT,
            poll_interval=settings.PPT_AGENT_POLL_INTERVAL,
            total_timeout=settings.PPT_AGENT_TOTAL_TIMEOUT,
            task_id_field=settings.PPT_AGENT_TASK_ID_FIELD,
            done_values=settings.PPT_AGENT_DONE_VALUES,
            fail_values=settings.PPT_AGENT_FAIL_VALUES,
            workspace_dir=settings.PPT_AGENT_WORKSPACE_DIR,
            result_glob=settings.PPT_AGENT_RESULT_GLOB,
            fresh_tolerance=settings.PPT_AGENT_WORKSPACE_FRESH_TOLERANCE,
            event_path=settings.PPT_AGENT_EVENT_PATH,
            event_id_field=settings.PPT_AGENT_EVENT_ID_FIELD,
            fn_index=settings.PPT_AGENT_FN_INDEX,
            session_hash=settings.PPT_AGENT_SESSION_HASH,
            result_output_index=settings.PPT_AGENT_RESULT_OUTPUT_INDEX,
            question_output_index=settings.PPT_AGENT_QUESTION_OUTPUT_INDEX,
            convert_type=settings.PPT_AGENT_CONVERT_TYPE,
            template_value=settings.PPT_AGENT_TEMPLATE,
            message_max_chars=settings.PPT_AGENT_MESSAGE_MAX_CHARS,
            preview_glob=settings.PPT_AGENT_PREVIEW_GLOB,
            slide_glob=settings.PPT_AGENT_SLIDE_GLOB,
            attachment_map=settings.PPT_AGENT_ATTACHMENT_MAP,
            transport=transport,
        )

    @staticmethod
    def is_enabled() -> bool:
        """是否启用了 PPTAgent（URL 非空即启用）。"""
        return bool((getattr(settings, "PPT_AGENT_URL", "") or "").strip())

    # ---------------- 扫描模式（多候选，抗目录结构漂移） ----------------

    def preview_patterns(self) -> Tuple[str, ...]:
        """预览图的 glob 模式元组（如 ``.slide_images-*/*.jpg``）。"""
        return split_patterns(self.preview_glob)

    def slide_patterns(self) -> Tuple[str, ...]:
        """HTML 稿的 glob 模式元组（页数基准，默认 ``slides/*.html``）。"""
        return split_patterns(self.slide_glob)

    def result_patterns(self) -> Tuple[str, ...]:
        """产物 pptx 的 glob 模式元组（默认 ``*.pptx``）。"""
        return split_patterns(self.result_glob)

    # ---------------- 基础设施 ----------------

    def _headers(self, *, json_body: bool = True) -> Dict[str, str]:
        h: Dict[str, str] = {"Accept": "application/json, */*"}
        if json_body:
            h["Content-Type"] = "application/json"
        if self.api_key:
            # 不打印 key 本体，只在使用时附加
            h["Authorization"] = f"Bearer {self.api_key}"
            h["X-API-Key"] = self.api_key
        return h

    def _client(self, timeout: int) -> httpx.Client:
        kwargs: Dict[str, Any] = {"timeout": timeout, "follow_redirects": True}
        if self._transport is not None:
            kwargs["transport"] = self._transport
        return httpx.Client(**kwargs)

    def _url(self, path_tpl: str, task_id: str = "") -> str:
        """拼路径：支持 {task_id} 占位符；无占位符时退化为 query 参数。"""
        path = (path_tpl or "").strip()
        if not path.startswith("/"):
            path = "/" + path
        if "{task_id}" in path:
            path = path.replace("{task_id}", task_id)
            return self.base_url + path
        if task_id:
            sep = "&" if "?" in path else "?"
            path = f"{path}{sep}task_id={task_id}"
        return self.base_url + path

    # ---------------- 健康探测 ----------------

    def health_check(self) -> Tuple[bool, str]:
        """健康探测：确认服务在线，返回 (是否健康, 原因)。

        成功条件放宽为"能连上且非 5xx"——第三方服务的根路径可能是 WebUI HTML，
        200/307/404 都算在线，只有连接失败 / 5xx 才判定不可用。
        """
        if not self.base_url:
            return False, "未配置 PPT_AGENT_URL"
        url = self._url(self.health_path)
        try:
            with httpx.Client(timeout=settings.PPT_AGENT_SUBMIT_TIMEOUT,
                              follow_redirects=True,
                              transport=self._transport) as c:
                r = c.get(url)
        except Exception as e:  # noqa: BLE001
            return False, f"无法连接（{type(e).__name__}: {e}）"
        if r.status_code >= 500:
            return False, f"服务返回 {r.status_code}"
        return True, f"HTTP {r.status_code}"

    # ---------------- 三步：提交 / 轮询 / 取结果 ----------------

    def submit(self, payload: Dict[str, Any]) -> Tuple[str, Optional[bytes]]:
        """提交生成任务，返回 (任务 ID, 已内嵌的结果字节)。失败抛 PPTAgentError。

        Gradio 端点是同步阻塞的：一次 POST 可能直接把成品文件带回响应体里。
        这种情况下自动跳过轮询（任务 ID 返回空串），避免猜错轮询路径导致假失败。
        """
        url = self._url(self.submit_path)
        logger.info("PPTAgent 提交任务：POST %s（超时 %ss）", url, self.submit_timeout)
        try:
            with self._client(self.submit_timeout) as c:
                r = c.post(url, json=payload, headers=self._headers())
        except Exception as e:  # noqa: BLE001
            raise PPTAgentError(f"提交失败：{type(e).__name__}: {e}") from e
        if r.status_code >= 400:
            raise PPTAgentError(
                f"提交失败：HTTP {r.status_code}，响应摘要 {self._snippet(r)}")
        embedded = self._try_extract_pptx(r)
        if embedded is not None:
            ok, why = looks_like_pptx(embedded)
            if ok:
                logger.info("PPTAgent 提交即返回结果文件（%d 字节），跳过轮询", len(embedded))
                return "", embedded
            logger.warning("提交响应内含疑似文件但非法（%s），继续按任务 ID 流程处理", why)
        task_id = self._parse_task_id(r)
        if not task_id:
            raise PPTAgentError(
                "提交成功但未取到任务 ID：响应缺少已知字段，"
                f"请设置 PPT_AGENT_TASK_ID_FIELD。响应摘要 {self._snippet(r)}")
        logger.info("PPTAgent 任务已受理：task_id=%s", task_id)
        return task_id, None

    def _parse_task_id(self, r: httpx.Response) -> str:
        """从提交响应里取任务 ID（先看 X-Task-Id 头，再看候选字段 / 自定义字段）。"""
        for hk in ("X-Task-Id", "X-Job-Id", "X-Request-Id"):
            v = r.headers.get(hk)
            if v:
                return v.strip()
        try:
            body = r.json()
        except Exception:  # noqa: BLE001
            body = r.text
        if not isinstance(body, (dict, list)):
            if isinstance(body, str) and body.strip():
                return body.strip()
            return ""
        fields: Tuple[str, ...] = ((self.task_id_field,) if self.task_id_field
                                   else tuple()) + _TASK_ID_FIELDS
        raw = _dig(body, fields) if isinstance(body, dict) else None
        if isinstance(raw, str):
            return raw.strip()
        if isinstance(raw, (int, float)):
            return str(raw)
        if isinstance(body, str):
            return body.strip()
        return ""

    def poll_status(self, task_id: str, deadline: float) -> Tuple[bool, Optional[bytes]]:
        """轮询状态直到完成/失败/超时。

        Returns:
            (是否成功完成, 若状态响应里已带 pptx 则一并返回)
        """
        url = self._url(self.status_path, task_id)
        logger.info("PPTAgent 轮询状态：GET %s（间隔 %ss）", url, self.poll_interval)
        while True:
            if time.monotonic() >= deadline:
                raise PPTAgentError(f"轮询超时：超过 {self.total_timeout}s 未完成")
            with self._client(max(5, self.submit_timeout)) as c:
                r = c.get(url, headers=self._headers())
            if r.status_code >= 400:
                raise PPTAgentError(
                    f"轮询失败：HTTP {r.status_code}，摘要 {self._snippet(r)}")
            embedded = self._try_extract_pptx(r)
            if embedded is not None:
                ok, why = looks_like_pptx(embedded)
                if ok:
                    logger.info("PPTAgent 状态响应直接携带 pptx（%d 字节）", len(embedded))
                    return True, embedded
                logger.warning("PPTAgent 状态响应含疑似文件但非法：%s", why)
            status = self._parse_status(r)
            if status:
                sval = str(status).strip().lower()
                if sval in self.fail_values:
                    raise PPTAgentError(
                        f"任务失败：status={status}，详情 {self._snippet(r)}")
                if sval in self.done_values:
                    logger.info("PPTAgent 任务完成：status=%s", status)
                    return True, None
                logger.debug("PPTAgent 任务进行中：status=%s", status)
            else:
                # 状态字段缺失：服务可能直接返回结果体，交给上层按成功处理
                logger.debug("PPTAgent 轮询响应未识别到状态字段，摘要 %s",
                             self._snippet(r))
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise PPTAgentError(f"轮询超时：超过 {self.total_timeout}s 未完成")
            time.sleep(min(self.poll_interval, remaining))

    def _parse_status(self, r: httpx.Response) -> Optional[str]:
        try:
            body = r.json()
        except Exception:  # noqa: BLE001
            return None
        raw = _dig(body, _STATUS_FIELDS)
        return str(raw).strip().lower() if raw is not None else None

    def fetch_result(self, task_id: str) -> bytes:
        """取回结果 pptx 字节；非法直接抛 PPTAgentError。"""
        url = self._url(self.result_path, task_id)
        logger.info("PPTAgent 取结果：GET %s", url)
        with self._client(settings.PPT_AGENT_RESULT_TIMEOUT) as c:
            r = c.get(url, headers=self._headers())
        if r.status_code >= 400:
            raise PPTAgentError(
                f"取结果失败：HTTP {r.status_code}，摘要 {self._snippet(r)}")
        data = self._try_extract_pptx(r)
        if data is None:
            raise PPTAgentError(
                f"取结果失败：响应未见二进制/下载链接/BASE64，摘要 {self._snippet(r)}")
        ok, why = looks_like_pptx(data)
        if not ok:
            raise PPTAgentError(f"取到的文件不是合法 pptx：{why}")
        logger.info("PPTAgent 结果已取回：%d 字节", len(data))
        return data

    # ============================================================
    # 真实契约：命名端点 /send_message（6 入参 / 5 出参 / queue + SSE）
    # 契约来源：真机探查（见 deploy/pptagent/README.md「Gradio 契约」一节）。
    # 入参顺序：message, history, attachments, convert_type_value,
    #          template_value, num_pages_value
    # 出参顺序：Chatbot / Textbox / File(list) / 📥下载文件(pptx) / Markdown
    # ============================================================

    def build_message_payload(self, message: str, history: Optional[List[Any]] = None,
                              attachments: Optional[List[Any]] = None,
                              num_pages: Optional[int] = None) -> Dict[str, Any]:
        """组装 Gradio 请求体 ``{"data": [6 个入参]}``（顺序与契约严格一致）。"""
        text = (message or "").strip()[:self.message_max_chars]
        num_pages_value = "auto"
        if num_pages and int(num_pages) > 0:
            num_pages_value = str(int(num_pages))
        body: Dict[str, Any] = {
            "data": [
                text,                       # 1 message
                history or [],              # 2 history
                attachments or [],          # 3 attachments（R2：默认不传）
                self.convert_type,          # 4 convert_type_value
                self.template_value,        # 5 template_value
                num_pages_value,            # 6 num_pages_value（字符串）
            ]
        }
        # 仅 Gradio 4 的 queue/join 风格需要这两个字段；命名端点风格下发会被忽略
        if self.fn_index:
            body["fn_index"] = int(self.fn_index) if self.fn_index.isdigit() else self.fn_index
        if "session_hash" in (self.event_path or "") or "queue/join" in (self.submit_path or ""):
            body["session_hash"] = self.session_hash
        return body

    def submit_message(self, message: str, history: Optional[List[Any]] = None,
                       attachments: Optional[List[Any]] = None,
                       num_pages: Optional[int] = None) -> str:
        """提交生成请求，返回事件流句柄 event_id。失败抛 PPTAgentError。"""
        payload = self.build_message_payload(message, history, attachments, num_pages)
        url = self._url(self.submit_path)
        logger.info("PPTAgent 提交生成请求：POST %s（message %d 字符）", url, len(message or ""))
        try:
            with self._client(self.submit_timeout) as c:
                r = c.post(url, json=payload, headers=self._headers())
        except Exception as e:  # noqa: BLE001
            raise PPTAgentError(f"提交失败：{type(e).__name__}: {e}") from e
        if r.status_code >= 400:
            raise PPTAgentError(
                f"提交失败：HTTP {r.status_code}，摘要 {self._snippet(r)}")
        event_id = self._extract_event_id(r)
        if not event_id:
            raise PPTAgentError(
                "提交成功但未取到事件流句柄：响应缺少 event_id/task_id，"
                f"请设置 PPT_AGENT_EVENT_ID_FIELD。摘要 {self._snippet(r)}")
        logger.info("PPTAgent 任务已受理：event_id=%s", event_id)
        return event_id

    def _extract_event_id(self, r: httpx.Response) -> str:
        """从提交响应里取事件流句柄（先看响应头，再看候选字段）。"""
        for hk in ("X-Event-Id", "X-Task-Id", "X-Job-Id"):
            v = r.headers.get(hk)
            if v:
                return v.strip()
        try:
            body = r.json()
        except Exception:  # noqa: BLE001
            body = r.text
        if isinstance(body, str) and body.strip():
            return body.strip()
        if not isinstance(body, dict):
            return ""
        fields: Tuple[str, ...] = ((self.event_id_field,) if self.event_id_field
                                   else tuple()) + _EVENT_ID_FIELDS
        raw = _dig(body, fields)
        if raw is None and self.event_id_field:
            raw = body.get(self.event_id_field)
        return str(raw).strip() if raw is not None else ""

    def _event_url(self, event_id: str) -> str:
        """拼事件流地址，支持 {event_id} / {session_hash} 占位符。"""
        path = (self.event_path or "").replace("{event_id}", event_id) \
                                      .replace("{session_hash}", self.session_hash)
        if not path.startswith("/"):
            path = "/" + path
        return self.base_url + path

    @staticmethod
    def _data_from_event(obj: Any) -> Optional[List[Any]]:
        """从一条 SSE 载荷里取出参数组（兼容 Gradio 5 与 4 两种形态）。"""
        # Gradio 5：event: complete 后 data 直接是入/出参数组
        if isinstance(obj, list):
            return obj
        if isinstance(obj, dict):
            out = obj.get("output")
            if isinstance(out, dict) and isinstance(out.get("data"), list):
                return out["data"]
            if isinstance(obj.get("data"), list):
                return obj["data"]
        return None

    @staticmethod
    def _is_terminal_event(obj: Any, event_name: str) -> bool:
        """该事件是否意味着流程结束（成功或失败都算结束）。"""
        if event_name in ("complete", "close_stream"):
            return True
        if isinstance(obj, dict):
            return obj.get("msg") in ("process_completed", "close_stream")
        return False

    def consume_event_stream(self, event_id: str, deadline: float,
                             on_event=None) -> Optional[List[Any]]:
        """消费 SSE 事件流直到终态，返回出参数组；超时/失败抛 PPTAgentError。

        Args:
            event_id: :meth:`submit_message` 返回的句柄。
            deadline: ``time.monotonic()`` 形式的截止时间。
            on_event: 可选回调，每收到一条事件就调用一次（用于进度日志）。
        """
        url = self._event_url(event_id)
        logger.info("PPTAgent 消费事件流：GET %s", url)
        final: Optional[List[Any]] = None
        # 读超时=剩余预算：流一直空闲时由 httpx 到点抛错，避免线程无限挂住
        remaining = max(1.0, deadline - time.monotonic())
        read_timeout = max(1.0, min(remaining, float(self.total_timeout)))
        try:
            with self._client(read_timeout) as c:
                with c.stream("GET", url, headers=self._headers()) as r:
                    if r.status_code >= 400:
                        raise PPTAgentError(f"事件流 HTTP {r.status_code}")
                    event_name = ""
                    for raw_line in r.iter_lines():
                        if time.monotonic() >= deadline:
                            raise PPTAgentError("事件流超时：超过整体预算仍未结束")
                        line = (raw_line or "").strip()
                        if not line:
                            continue
                        if line.startswith("event:"):
                            event_name = line[len("event:"):].strip()
                            continue
                        if not line.startswith("data:"):
                            continue
                        payload = line[len("data:"):].strip()
                        if not payload:
                            continue
                        if "PPT_PYTHON_GUARD_ABORT" in payload:
                            raise PPTAgentError(
                                "PPT 生成脚本出现相同执行错误两次，任务已中止。"
                                "请检查字符串字面量中的转义后重新生成。")
                        if event_name == "error":
                            reason = payload[:300] if payload.lower() != "null" else "上游服务未提供具体原因"
                            raise PPTAgentError(f"PPTAgent 处理失败：{reason}")
                        try:
                            obj = _json.loads(payload)
                        except Exception:  # noqa: BLE001 - 非 JSON 行（心跳等）直接跳过
                            continue
                        if on_event:
                            on_event(obj)
                        if isinstance(obj, dict) and obj.get("success") is False:
                            raise PPTAgentError(f"PPTAgent 处理失败：{str(obj)[:300]}")
                        if isinstance(obj, dict) and obj.get("msg") in (
                                "process_failed", "queue_full"):
                            raise PPTAgentError(
                                f"PPTAgent 处理失败：{str(obj)[:300]}")
                        got = self._data_from_event(obj)
                        if got is not None:
                            final = got
                        if self._is_terminal_event(obj, event_name):
                            logger.info("PPTAgent 事件流结束：event=%s", event_name or "-")
                            return final
        except PPTAgentError:
            raise
        except Exception as e:  # noqa: BLE001
            # 空闲到点的读超时也算超时，措辞统一，便于上层识别"该回退了"
            if "imeout" in type(e).__name__:
                raise PPTAgentError(
                    f"事件流超时：{self.total_timeout}s 内未收到终态事件") from e
            raise PPTAgentError(f"事件流读取失败：{type(e).__name__}: {e}") from e
        # 流正常结束但没等到终态：到点了同样按超时处理
        if time.monotonic() >= deadline:
            raise PPTAgentError(f"事件流超时：{self.total_timeout}s 内未收到终态事件")
        return final

    @staticmethod
    def _at(outputs: List[Any], index: int) -> Any:
        """按下标取出参，越界返回 None（契约变化时不能抛异常）。"""
        if isinstance(outputs, list) and 0 <= index < len(outputs):
            return outputs[index]
        return None

    def _bytes_from_filedata(self, item: Any) -> Optional[bytes]:
        """把出参里的 FileData 转成字节；取不到或非法都返回 None（由调用方回退）。

        入参可能已经是裸 FileData，也可能是被 ``{"value": ..., "__type__": "update"}``
        包过的组件更新，还可能是一组文件（list）——三种都要能穿透。
        """
        candidates: List[Any] = []
        for candidate in (item, unwrap_value(item)):
            if isinstance(candidate, dict):
                candidates.append(candidate)
            elif isinstance(candidate, list):
                candidates.extend([x for x in candidate if isinstance(x, dict)])
                # list 里的元素自己还可能带着 value 壳（File 组件常见）
                candidates.extend([unwrap_value(x) for x in candidate
                                   if isinstance(x, dict)])
        for fd in candidates:
            url = _gradio_file_url(fd)
            if not url:
                continue
            data = self._download(_abs_url(self.base_url, url))
            if not data:
                continue
            ok, why = looks_like_pptx(data)
            if ok:
                return data
            logger.warning("下载到的文件不是合法 pptx：%s（%s）", why, url)
        return None

    def _question_from(self, raw: Any) -> str:
        """从 Markdown 出参里提取**真正的追问**文本。

        两个坑：
        1. 出参带 ``{"value": ...}`` 壳，不解包会得到 dict 而非字符串；
        2. Markdown 出参末尾常附带 ``🔤 Tokens: 12,345 · 💰 Cost: $0.012`` 这类
           运行统计——它不是追问，直接弹给用户只会让人对着数字发愣，必须先剔除，
           剔除后如果什么都不剩，就当作"没有追问"（而不是把统计原文丢出去）。
        """
        text = raw
        if not isinstance(text, str):
            if isinstance(text, dict) and isinstance(text.get("value"), str):
                text = text["value"]
            else:
                return ""
        cleaned = strip_token_stats(text)
        return cleaned[:2000]

    def parse_outputs(self, outputs: List[Any], event_id: str = "") -> PPTAgentOutcome:
        """按契约索引解析出参 → 产物或追问（R1）。

        ⚠️ 真机出参的**每个元素**都被 Gradio 包成 ``{"value": X, "__type__":
        "update"}``。直接在 row 上找 ``url`` / ``path`` 必然一无所获（早期版本踩过：
        产物明明生成了却判定 pending），所以每一步取值前都要先 :func:`unwrap_value`。

        产物优先级：契约指定索引（第 4 项 📥 下载文件）→ 其余项全量扫描。
        拿不到产物时，取 Markdown 项作为**追问**文本返回给前端（已剔除运行统计）。
        """
        out = PPTAgentOutcome(outputs=list(outputs or []), event_id=event_id)
        if not isinstance(outputs, list) or not outputs:
            return out
        pptx = self._bytes_from_filedata(self._at(outputs, self.result_output_index))
        if pptx is None:
            # 索引对不上时退化为全量扫描，避免一次契约微调就完全拿不到产物
            for item in outputs:
                pptx = self._bytes_from_filedata(item)
                if pptx is not None:
                    logger.warning("产物不在约定索引 %s 上，已通过全量扫描兜底",
                                   self.result_output_index)
                    break
        if pptx is not None:
            out.pptx = pptx
            return out
        # 没有产物 → 极可能是 PPTAgent 在先确认需求（R1）
        # ⚠️ 只认约定索引，不做"扫到任意字符串就当追问"的兜底：真机出参里还有
        # Textbox 的 job id（"job-18da4fbb"）这类纯标识串，自由扫描会把它们当作
        # 追问弹给用户，用户对着一串 id 完全不知道该怎么回答。契约已经规定了
        # Markdown 出参的下标（可用 PPT_AGENT_QUESTION_OUTPUT_INDEX 覆盖），
        # 这一个位置没有内容就是没有追问，宁可按 pending 处理回退本地渲染。
        question = self._question_from(self._at(outputs, self.question_output_index))
        if question.strip():
            out.question = question.strip()
            return out
        if not isinstance(self._at(outputs, self.question_output_index), (str, dict)):
            logger.warning(
                "PPTAgent 出参缺第 %s 项（Markdown/追问），无可判定的追问内容，"
                "本次按 pending 处理并回退本地渲染", self.question_output_index)
        return out

    def generate_deck(self, message: str, *, history: Optional[List[Any]] = None,
                      attachments: Optional[List[Any]] = None,
                      num_pages: Optional[int] = None,
                      deadline: Optional[float] = None,
                      on_event=None) -> PPTAgentOutcome:
        """一步到位：健康检查 → 提交 → 消费事件流 → 解析产物/追问。

        不阻塞调用方语义之外：本方法本身是同步长调用，**只应在后台线程里调用**
        （异步 job 由 PPTAgentJobRunner 负责起线程）。
        """
        ok, why = self.health_check()
        if not ok:
            raise PPTAgentError(f"健康探测未通过：{why}")
        logger.info("PPTAgent 健康探测通过（%s）", why)
        event_id = self.submit_message(message, history=history,
                                       attachments=attachments, num_pages=num_pages)
        dl = deadline if deadline is not None else time.monotonic() + self.total_timeout
        outputs = self.consume_event_stream(event_id, dl, on_event=on_event)
        if outputs is None:
            return PPTAgentOutcome(outputs=[], event_id=event_id)
        return self.parse_outputs(outputs, event_id=event_id)

    # ============================================================
    # 目录扫描：仅用于实时进度与产物兜底（目录结构待真机核实 → 全部可配置）
    # ============================================================

    def scan_progress(self, since_ts: float, workspace: str = "") -> Dict[str, Any]:
        """扫描共享卷里的进度产物，用于逐页实时预览。

        真机结构（已核实，见 ``deploy/pptagent/README.md``）::

            <ws>/<日期>/<job_id>/
              ├─ .slide_images-pdf-<标题>/slide_01.jpg   ← 预览图（目录名动态）
              ├─ slides/slide_01.html                    ← 页数基准
              └─ <标题>.pptx                             ← 成品（文件名动态）

        因为目录名/文件名都随标题变化，这里**全部走通配多模式匹配**：
        - 每个维度可配多个候选模式，命中任一即算数；
        - 找不到/扫描失败就返回零值，**绝不抛异常**，上层据此降级为"只有总进度"。

        Args:
            since_ts: 本次任务提交的 Unix 时间戳（秒），用于判定"是不是本次产物"。
            workspace: 覆盖默认工作区目录（测试用）。

        Returns:
            ``{"slides": int, "previews": int, "has_pptx": bool,
               "preview_files": List[str]}``
        """
        info: Dict[str, Any] = {"slides": 0, "previews": 0, "has_pptx": False,
                                "preview_files": []}
        root_str = (workspace or self.workspace_dir or "").strip()
        if not root_str:
            return info
        root = Path(root_str)
        if not root.is_dir():
            return info
        threshold = since_ts - self.fresh_tolerance
        try:
            pngs = collect_files(root, self.preview_patterns(), threshold)
            htmls = collect_files(root, self.slide_patterns(), threshold)
            # 产物加 min_size：过滤刚创建还没写内容（<8KB）的空壳 pptx
            pptxs = collect_files(root, self.result_patterns(), threshold,
                                  min_size=_MIN_PPTX_SIZE)
        except OSError as e:  # noqa: BLE001 - 扫描失败只降级，不影响 job
            logger.debug("进度扫描失败（降级为无逐页预览）：%s", e)
            return info
        info["slides"] = len(htmls)
        info["previews"] = len(pngs)
        info["has_pptx"] = bool(pptxs)
        info["preview_files"] = [str(p) for p in pngs]
        return info

    def wait_for_workspace_result(self, since_ts: float, deadline: float) -> bytes:
        """共享卷通道：等产物文件落盘并校验，取结果**不依赖**未文档化的 HTTP 端点。

        产物文件名**随标题动态变化**（真机实测为 ``<标题>.pptx``，如
        ``司法局工作汇报.pptx``），所以这里按 glob 模式搜集候选，再从中挑
        "最新且能通过 pptx 合法性校验"的那个，而不是认死一个文件名。

        Args:
            since_ts: 提交任务时的 Unix 时间戳（秒），用于判定产物是否本次生成。
            deadline: ``time.monotonic()`` 形式的截止时间。

        Raises:
            PPTAgentError: 目录不可读，或到截止时间仍未出现合法的 pptx。
        """
        root = Path(self.workspace_dir)
        if not self.workspace_dir:
            raise PPTAgentError("未配置工作区目录（PPT_AGENT_WORKSPACE_DIR）")
        if not root.is_dir():
            raise PPTAgentError(f"工作区目录不存在或不可读：{root}")
        patterns = self.result_patterns()
        logger.info("PPTAgent 走共享卷通道：扫描 %s 下的 %s（只认 %s 之后落盘的文件）",
                    root, " / ".join(patterns) or "<无匹配模式>",
                    time.strftime("%H:%M:%S", time.localtime(since_ts)))
        # 容忍两端时钟偏差，避免产物因"看起来更旧"被漏掉
        threshold = since_ts - self.fresh_tolerance
        warned_half_written = False
        while True:
            candidates = collect_files(root, patterns, threshold,
                                       min_size=_MIN_PPTX_SIZE)
            # 按修改时间倒序：优先取最新产物；若它还没写完就顺位看次新的
            candidates.sort(key=lambda x: x.stat().st_mtime, reverse=True)
            for p in candidates:
                try:
                    data = p.read_bytes()
                except OSError as e:  # noqa: BLE001 - 文件可能正被删除/重写
                    logger.debug("读取产物候选失败，跳过：%s（%s）", p, e)
                    continue
                ok, why = looks_like_pptx(data)
                if ok:
                    logger.info("共享卷取到产物：%s（%d 字节）", p, len(data))
                    return data
                # 文件可能正在写入中（半包），换个候选或下一轮再看
                if not warned_half_written:
                    logger.warning("产物已出现但尚不完整（%s），继续等待", why)
                    warned_half_written = True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise PPTAgentError(
                    f"等待产物超时：{self.total_timeout}s 内 {root} 下未出现合法的 "
                    f"{' / '.join(patterns) or '<无匹配模式>'}")
            time.sleep(min(self.poll_interval, remaining))

    def _try_extract_pptx(self, r: httpx.Response) -> Optional[bytes]:
        """从响应中提取 pptx 字节：二进制直返 / JSON 内 URL / BASE64。

        Returns:
            bytes 表示已提取到疑似文件；None 表示没识别出来（由调用方决定后续）。
        """
        ctype = (r.headers.get("content-type") or "").lower()
        looks_binary = any(h in ctype for h in _PPTX_MIME_HINTS) or (
            "json" not in ctype and "html" not in ctype and "xml" not in ctype)
        if looks_binary and r.content:
            return r.content
        body: Any = None
        try:
            body = r.json()
        except Exception:  # noqa: BLE001
            return None
        if not isinstance(body, dict):
            return None
        # Gradio FileData 优先（它的字段名藏在 data 数组里，通用 _dig 命中率低于此）
        gradio_url = _gradio_file_url(body)
        if gradio_url:
            return self._download(_abs_url(self.base_url, gradio_url))
        maybe_url = _dig(body, _URL_FIELDS)
        if isinstance(maybe_url, str) and maybe_url.strip():
            return self._download(_abs_url(self.base_url, maybe_url))
        maybe_b64 = _dig(body, _B64_FIELDS)
        if isinstance(maybe_b64, str) and maybe_b64.strip():
            raw = maybe_b64.strip()
            if "," in raw and raw.split(",")[0].endswith("base64"):
                raw = raw.split(",", 1)[1]
            try:
                return base64.b64decode(raw)
            except Exception as e:  # noqa: BLE001
                logger.warning("BASE64 解码失败：%s", e)
                return None
        return None

    def _download(self, url: str) -> Optional[bytes]:
        """按下载链接取字节；失败只记日志并返回 None，由上层决定是否回退。"""
        logger.info("PPTAgent 结果内含下载链接：%s", url)
        try:
            with self._client(settings.PPT_AGENT_RESULT_TIMEOUT) as c:
                sub = c.get(url, headers=self._headers())
        except Exception as e:  # noqa: BLE001
            logger.warning("下载链接请求失败：%s: %s", type(e).__name__, e)
            return None
        if sub.status_code >= 400 or not sub.content:
            logger.warning("下载链接返回 HTTP %s（%d 字节）", sub.status_code, len(sub.content))
            return None
        return sub.content

    @staticmethod
    def _snippet(r: httpx.Response, limit: int = 300) -> str:
        """响应摘要（截断），用于排障日志；不含任何凭据。"""
        try:
            text = r.text or ""
        except Exception:  # noqa: BLE001
            text = "<binary>"
        text = " ".join(text.split())
        if len(text) > limit:
            text = text[:limit] + "..."
        return f"[{r.status_code}] {text}"

    # ---------------- 对外主入口 ----------------

    def render(self, *, topic: str, content_markdown: str, slide_count: int,
               template_hint: str = "", language: str = "zh-CN") -> bytes:
        """三步走完并取回合法 pptx 字节；任何失败都抛 PPTAgentError。

        Args:
            topic: PPT 主题 / 标题。
            content_markdown: 大纲正文（Markdown 文本），后端已完成 outline 编排。
            slide_count: 期望页数。
            template_hint: 模板/主题风格提示，供 PPTAgent 参考排版。
            language: 输出语言。

        Raises:
            PPTAgentError: 提交/轮询/取结果任一环节失败，或结果不是合法 pptx。
        """
        payload: Dict[str, Any] = {
            "topic": topic,
            "title": topic,
            "prompt": content_markdown,
            "content": content_markdown,
            "markdown": content_markdown,
            "outline": content_markdown,
            "slide_count": slide_count,
            "num_slides": slide_count,
            "language": language,
            "template": template_hint,
            "theme": template_hint,
            "format": "pptx",
            "return_format": "pptx",
        }
        logger.debug("PPTAgent 生效配置：base_url=%s submit=%s status=%s result=%s",
                     self.base_url, self.submit_path, self.status_path,
                     self.result_path)
        # 契约冲突诊断（**只提示、不阻断**）：同步 render 通道发的是 REST 请求体，
        # 而 Gradio 命名端点只认 {"data":[6 个入参]}，两者不可能同时成立。既然默认
        # SUBMIT_PATH 就是 Gradio 路径，不提示的话排障的人会把"必然失败"当成
        # "PPTAgent 偶发抽风"。是否让同步导出也走 PPTAgent 属于部署策略，交给上层
        # 决定（上层会正常兜底本地渲染），这里只负责把原因讲清楚。
        conflict = gradio_contract_conflict(self.submit_path)
        if conflict:
            logger.warning("PPTAgent 契约冲突：%s", conflict)
        ok, why = self.health_check()
        if not ok:
            raise PPTAgentError(f"健康探测未通过：{why}")
        logger.info("PPTAgent 健康探测通过（%s）", why)

        started_at = time.time()
        deadline = time.monotonic() + self.total_timeout
        task_id, embedded = self.submit(payload)
        if embedded is not None:
            # 一次请求就拿到结果（Gradio 同步端点常见），无需轮询状体
            return embedded
        # 共享卷通道优先：产物路径稳定已知，不必依赖未文档化的结果端点
        if self.workspace_dir:
            return self.wait_for_workspace_result(started_at, deadline)
        done, embedded = self.poll_status(task_id, deadline)
        if not done:
            raise PPTAgentError("任务未完成即退出轮询")
        if embedded:
            ok, why = looks_like_pptx(embedded)
            if not ok:
                raise PPTAgentError(f"状态响应内的文件非法：{why}")
            return embedded
        return self.fetch_result(task_id)


def build_outline_markdown(outline: dict) -> str:
    """把内部 outline 结构序列化为 PPTAgent 易读的 Markdown 文本。

    保持与 PPTAgent「喂材料 / 主题，由它全权排版」的输入习惯一致：既有结构化
    标题层级，也保留每页要点与备注。

    Args:
        outline: ``{"title","subtitle","slides":[{"title","points","notes",...}]}``

    Returns:
        Markdown 文本（UTF-8）。
    """
    title = (outline or {}).get("title") or "未命名演示文稿"
    subtitle = (outline or {}).get("subtitle") or ""
    lines: List[str] = [f"# {title}"]
    if subtitle:
        lines.append(f"> {subtitle}")
    lines.append("")
    slides: List[Dict[str, Any]] = (outline or {}).get("slides") or []
    for i, s in enumerate(slides, start=1):
        stitle = (s or {}).get("title") or f"第 {i} 页"
        lines.append(f"## 第 {i} 页：{stitle}")
        for p in (s or {}).get("points") or []:
            text = p if isinstance(p, str) else str((p or {}).get("text") or p)
            if text:
                lines.append(f"- {text}")
        for sub_k in ("subtitle", "summary"):
            v = (s or {}).get(sub_k)
            if v:
                lines.append(f"- {v}")
        if (s or {}).get("notes"):
            lines.append(f"（备注：{s['notes']}）")
        lines.append("")
    return "\n".join(lines).strip() + "\n"
