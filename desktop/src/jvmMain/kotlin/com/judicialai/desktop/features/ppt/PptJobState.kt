package com.judicialai.desktop.features.ppt

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import com.judicialai.desktop.app.AppState
import com.judicialai.desktop.core.logging.ClientLog
import com.judicialai.desktop.core.network.ApiResult
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import java.io.File

/**
 * PPT 异步生成的界面状态机：
 * IDLE（填需求）→ SUBMITTED（提交任务）→ GENERATING（轮询，逐页出图）
 * → CLARIFYING（PPTAgent 追问，等用户回答 → 回到 GENERATING）
 * → DONE（缩略图 + 大图 + 下载）/ FAILED（错误 + 重试）/ CANCELLED（回 IDLE）。
 */
enum class PptJobStatus {
    IDLE, SUBMITTED, GENERATING, CLARIFYING, DONE, FAILED, CANCELLED,
}

/** 服务端 `status` 字段：pending|running|awaiting_clarification|succeeded|failed|cancelled */
private val TERMINAL_JOB_STATUSES = setOf("succeeded", "failed", "cancelled")

/** 提交 / 追问接口返回的结构：{job_id, status, phase, message} */
data class PptJobSubmit(
    val jobId: String,
    /** pending / running / failed（未配置 PPT_AGENT_URL 时后端直接给 failed） */
    val status: String,
    /** 后端附带的说明，如「已有进行中的任务」「未配置 PPT_AGENT_URL」 */
    val hint: String,
)

/** 服务端 `phase` 字段 */
enum class PptJobPhase(val key: String) {
    SUBMITTING("submitting"),
    RESEARCHING("researching"),
    OUTLINING("outlining"),
    DESIGNING("designing"),
    FINALIZING("finalizing"),
    SUCCEEDED("succeeded"),
    FAILED("failed"),
    UNKNOWN(""),
    ;

    companion object {
        fun of(key: String): PptJobPhase =
            entries.firstOrNull { it.key.equals(key, ignoreCase = true) } ?: UNKNOWN
    }
}

/**
 * GET /ppt/jobs/{id}/preview 的一页。
 * 后端只列已生成的文件，所以列出的页一律是「已出图」。
 */
data class PptJobPage(
    /** 展示用的页序，从 1 开始 */
    val n: Int,
    /** 后端索引，从 0 开始（拼预览图 URL 用） */
    val index: Int,
    val pngReady: Boolean,
    val pngUrl: String,
)

/** GET /ppt/jobs/{id}/status 的解析结果（字段缺失一律给安全默认值，不崩） */
data class PptJobStatusSnapshot(
    val status: String,
    val totalPages: Int,
    val currentPage: Int,
    val phase: String,
    val elapsedSeconds: Int,
    val estimatedRemaining: Int?,
    val errorMsg: String?,
    /** PPTAgent 的追问文本，非空即等待用户回答 */
    val question: String?,
    /** 产物来源：pptagent / local */
    val renderer: String?,
) {
    val isTerminal: Boolean get() = status in TERMINAL_JOB_STATUSES
}

/**
 * 一次生成任务的进度（**全局可见**：挂在 [PptJobEngine] 上，不随页面销毁）。
 * 字段全部是 Compose State，界面直接读即可自动重组。
 */
class PptJobProgress {
    var jobId by mutableStateOf("")
    var docId by mutableStateOf<String?>(null)
    /** 提交时用户填的补充需求，「重试」时复用 */
    var message by mutableStateOf("")
    /** 用户预先选好的 pptx 保存位置（离开页面再回来也还记得） */
    var targetFile: File? = null

    var status by mutableStateOf(PptJobStatus.SUBMITTED)
    /** 服务端原始 status / phase，便于排障 */
    var statusRaw by mutableStateOf("")
    var rawPhase by mutableStateOf("")
    var phase by mutableStateOf(PptJobPhase.UNKNOWN)
    /** 给用户看的当前阶段文案 */
    var stageText by mutableStateOf("正在提交生成任务…")

    var totalPages by mutableStateOf(0)
    var currentPage by mutableStateOf(0)
    var elapsedSeconds by mutableStateOf(0)
    var estimatedRemaining by mutableStateOf<Int?>(null)
    var pages by mutableStateOf(listOf<PptJobPage>())
    var selectedPage by mutableStateOf(1)

    /** PPTAgent 的追问文本（status=awaiting_clarification 时有值） */
    var question by mutableStateOf<String?>(null)
    /** 提交回答中（防重复点击） */
    var answering by mutableStateOf(false)
    /** 回答提交失败的原因（展示在追问框里） */
    var answerError by mutableStateOf<String?>(null)
    /** 产物来源：pptagent / local */
    var renderer by mutableStateOf<String?>(null)

    /** 失败原因（服务端 error_msg 或本地原因） */
    var errorMsg by mutableStateOf<String?>(null)
    /** 网络抖动等可恢复错误：不终止任务，只在界面上提示「正在重试」 */
    var transientError by mutableStateOf<String?>(null)
    /** 提交被拒（例如服务端未配置 PPT_AGENT_URL / 还没部署 /ppt/jobs） */
    var submitRejected by mutableStateOf(false)

    var exporting by mutableStateOf(false)
    var exportedPath by mutableStateOf<String?>(null)
    var exportError by mutableStateOf<String?>(null)

    /** 生成中（不含追问等待：那一段是等用户，不是等服务端） */
    val isActive: Boolean
        get() = status == PptJobStatus.SUBMITTED || status == PptJobStatus.GENERATING

    /** 已出图的页数（用于「已生成 N 页」） */
    val donePages: Int get() = pages.count { it.pngReady }

    /**
     * 服务端明确给出的总页数；**跨机部署（共享卷没挂）时恒为 0**，
     * 这时返回 null，界面改用阶段文案，绝不显示「第 0 / 0 页」。
     */
    val knownTotal: Int? get() = totalPages.takeIf { it > 0 }

    /** 左栏占位块数量：服务端没给总页数时按本地大纲页数铺占位，避免只有一两个灰块 */
    fun displayTotal(fallback: Int): Int =
        knownTotal ?: maxOf(pages.size, fallback).coerceAtLeast(1)

    fun pageOf(n: Int): PptJobPage? = pages.firstOrNull { it.n == n }
}

/**
 * PPT 异步生成任务引擎（全局单例）。
 *
 * 为什么放在全局而不是 ViewModel：
 * - 本项目的 ViewModel 是 `remember { XxxViewModel() }`，切走页面 remember 会重建、本地状态清零，
 *   用户中途切走再切回会看到空白。任务句柄（[AppState.pendingPptJobId] + 这里的 [current]）
 *   必须活过页面销毁——与既有 `pendingPptDocId / pptOutlineGenerating / pptExporting` 同一套做法。
 * - 轮询协程在这里起、也在这里收：任务终态 / 用户取消 / 退出登录 / 超过 30 分钟兜底都会停，
 *   另外页面离开时由界面显式调用 [stopPolling]（回到页面再 [resumeIfNeeded] 续上），不会泄漏。
 */
object PptJobEngine {

    private const val FIRST_DELAY_MS = 2_000L
    private const val INTERVAL_MS = 3_000L
    private const val MAX_INTERVAL_MS = 30_000L
    /** 连续失败达到这个次数后才开始指数退避（前几次抖动按正常节奏重试） */
    private const val BACKOFF_AFTER_FAILS = 5
    /** 兜底：极端情况下不让轮询无限跑下去 */
    private const val MAX_TOTAL_MS = 30 * 60 * 1_000L

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private var repo: PptRepository? = null
    private var pollJob: Job? = null
    private var exportJob: Job? = null

    var current by mutableStateOf<PptJobProgress?>(null)
        private set

    // ---------------- 提交 ----------------

    /**
     * 提交生成任务（30 秒超时：接口是秒回的，只登记任务、不等渲染）。
     *
     * @param message 用户补充需求（后端会追加到给 PPTAgent 的需求末尾）。
     *                大纲走服务端已存的 doc.outline，**调用前必须先保存草稿**。
     *
     * 返回结构里 status=failed 表示后端直接拒绝了（如未配置 PPT_AGENT_URL），
     * 此时 [PptJobProgress.submitRejected] = true，由调用方回退同步导出。
     */
    suspend fun submit(
        repository: PptRepository, docId: String, message: String, target: File,
    ): ApiResult<PptJobSubmit> {
        stopPolling()
        exportJob?.cancel()
        exportJob = null
        repo = repository

        val p = PptJobProgress()
        p.docId = docId.ifBlank { null }
        p.message = message
        p.targetFile = target
        p.status = PptJobStatus.SUBMITTED
        p.stageText = "正在提交生成任务…"
        current = p
        AppState.pendingPptJobId = null
        AppState.pptJobActive = false
        AppState.pptLastError = null

        val r = repository.submitJob(docId, message)
        when (r) {
            is ApiResult.Ok -> {
                val s = r.data
                p.jobId = s.jobId
                p.statusRaw = s.status
                if (s.status == "failed") {
                    // 后端明确拒绝（未配置 PPT_AGENT_URL 等）：HTTP 仍是 200，只有 status 能看出来
                    p.submitRejected = true
                    p.status = PptJobStatus.FAILED
                    p.errorMsg = s.hint.ifBlank { "服务端未启用 PPTAgent 异步生成" }
                    AppState.pptLastError = p.errorMsg
                    ClientLog.warn("PPT 生成任务被服务端拒绝：" + p.errorMsg)
                } else {
                    p.status = PptJobStatus.GENERATING
                    p.stageText = "任务已提交，正在排队…"
                    // 跨页面恢复句柄：切走再切回时据此重新挂上任务
                    AppState.pendingPptJobId = s.jobId
                    AppState.pptJobActive = true
                    ClientLog.info("PPT 生成任务已提交 job=" + s.jobId + " status=" + s.status)
                    startPolling()
                }
            }
            is ApiResult.Err -> {
                p.submitRejected = true
                p.status = PptJobStatus.FAILED
                p.errorMsg = r.message
                AppState.pptLastError = r.message
                ClientLog.warn("PPT 生成任务提交失败：" + r.message)
            }
        }
        return r
    }

    // ---------------- 轮询 ----------------

    private fun startPolling() {
        val p = current ?: return
        val r = repo ?: return
        if (p.jobId.isBlank()) return
        pollJob?.cancel()
        pollJob = scope.launch {
            val startedAt = System.currentTimeMillis()
            var first = true
            var fails = 0
            while (isActive) {
                // 提交后首次 2 秒，之后每 3 秒一次
                delay(if (first) FIRST_DELAY_MS else nextDelay(fails))
                first = false

                // 退出登录（换账号）后不再替上一个账号拉任务
                if (!AppState.loggedIn) {
                    p.status = PptJobStatus.CANCELLED
                    p.stageText = "已退出登录，本次生成已停止"
                    AppState.pendingPptJobId = null
                    AppState.pptJobActive = false
                    return@launch
                }
                if (System.currentTimeMillis() - startedAt > MAX_TOTAL_MS) {
                    p.status = PptJobStatus.FAILED
                    p.errorMsg = "生成超时（超过 30 分钟仍未完成），请重试或联系管理员"
                    AppState.pptLastError = p.errorMsg
                    AppState.pendingPptJobId = null
                    AppState.pptJobActive = false
                    return@launch
                }

                when (val s = r.jobStatus(p.jobId)) {
                    is ApiResult.Ok -> {
                        fails = 0
                        p.transientError = null
                        applyStatus(p, s.data)
                        fetchPreview(r, p)
                        if (s.data.isTerminal) {
                            finish(p, s.data)
                            return@launch
                        }
                        // PPTAgent 在信息不足时会先反问：停下来等用户回答，
                        // 继续轮询没有意义（服务端状态不会自己变），回答后由 clarify() 重启轮询
                        if (p.status == PptJobStatus.CLARIFYING) return@launch
                    }
                    is ApiResult.Err -> {
                        // 任务不存在（服务端重启 / 任务已过期）或登录已过期：重试多少次都不会好，
                        // 直接判终态，否则会一直退避到 30 秒一轮空转到兜底超时
                        if (s.status == 404 || s.status == 401) {
                            p.status = PptJobStatus.FAILED
                            p.errorMsg = if (s.status == 401) "登录已过期，请重新登录后再生成"
                            else "任务已失效（服务端找不到该任务），请重新生成"
                            AppState.pptLastError = p.errorMsg
                            AppState.pendingPptJobId = null
                            AppState.pptJobActive = false
                            return@launch
                        }
                        fails++
                        p.transientError = if (fails >= BACKOFF_AFTER_FAILS)
                            "网络不稳定，正在放慢速度重试（${s.message}）" else s.message
                        ClientLog.warn("PPT 任务状态查询失败（$fails 次）：" + s.message)
                    }
                }
            }
        }
    }

    /** 指数退避：3s → 6s → 12s → 24s → 30s（封顶） */
    private fun nextDelay(fails: Int): Long {
        if (fails < BACKOFF_AFTER_FAILS) return INTERVAL_MS
        val step = fails - BACKOFF_AFTER_FAILS + 1
        val backoff = INTERVAL_MS * (1L shl step.coerceAtMost(4))
        return backoff.coerceAtMost(MAX_INTERVAL_MS)
    }

    private fun applyStatus(p: PptJobProgress, s: PptJobStatusSnapshot) {
        p.statusRaw = s.status
        p.rawPhase = s.phase
        p.phase = PptJobPhase.of(s.phase)
        p.totalPages = s.totalPages
        p.currentPage = s.currentPage
        p.elapsedSeconds = s.elapsedSeconds
        p.estimatedRemaining = s.estimatedRemaining
        if (!s.errorMsg.isNullOrBlank()) p.errorMsg = s.errorMsg
        if (!s.renderer.isNullOrBlank()) p.renderer = s.renderer
        p.status = when (s.status) {
            "pending" -> PptJobStatus.SUBMITTED
            "running" -> PptJobStatus.GENERATING
            "awaiting_clarification" -> PptJobStatus.CLARIFYING
            "succeeded" -> PptJobStatus.DONE
            "failed" -> PptJobStatus.FAILED
            "cancelled" -> PptJobStatus.CANCELLED
            else -> PptJobStatus.GENERATING
        }
        p.question = if (p.status == PptJobStatus.CLARIFYING) s.question else null
        p.stageText = stageTextOf(p)
    }

    /** 阶段 → 中文文案；页数只有共享卷可用时才准，为 0 时只说阶段，不出现「第 0/0 页」 */
    private fun stageTextOf(p: PptJobProgress): String = when (p.phase) {
        PptJobPhase.SUBMITTING -> "正在提交生成任务…"
        PptJobPhase.RESEARCHING -> "正在理解需求…"
        PptJobPhase.OUTLINING -> "正在生成大纲…"
        PptJobPhase.DESIGNING ->
            if (p.totalPages > 0) "正在生成第 ${p.currentPage.coerceAtLeast(1)}/${p.totalPages} 页"
            else "正在生成页面…"
        PptJobPhase.FINALIZING -> "正在合成 PPT…"
        PptJobPhase.SUCCEEDED -> "生成完成"
        PptJobPhase.FAILED -> "生成失败"
        PptJobPhase.UNKNOWN -> when (p.status) {
            PptJobStatus.SUBMITTED -> "任务已提交，正在排队…"
            PptJobStatus.CLARIFYING -> "AI 需要你补充一点信息"
            PptJobStatus.DONE -> "生成完成"
            else -> "正在生成…"
        }
    }

    /** 只拉已生成页的清单（PNG 本身由界面懒加载）；后端降级返回空列表时保留上一次结果 */
    private suspend fun fetchPreview(r: PptRepository, p: PptJobProgress) {
        when (val v = r.jobPreview(p.jobId)) {
            is ApiResult.Ok -> if (v.data.isNotEmpty()) p.pages = v.data
            is ApiResult.Err -> Unit // 预览拉取失败不影响主流程，下一次轮询再试
        }
    }

    private fun finish(p: PptJobProgress, s: PptJobStatusSnapshot) {
        stopPolling()
        when (p.status) {
            PptJobStatus.DONE -> {
                // 生成阶段已成功：全局"正在生成"标记必须立刻复位，否则切到别的页面后
                // 会一直挂着「PPT 正在生成」的提示。
                // pendingPptJobId 先留着——落盘是在 autoExport 里异步做的，
                // 万一落盘失败还要靠这个句柄回到页面补一次导出；落盘成功后才清。
                AppState.pptJobActive = false
                autoExport(p)
            }
            PptJobStatus.FAILED -> {
                p.errorMsg = s.errorMsg?.takeIf { it.isNotBlank() } ?: "生成失败，请重试"
                AppState.pptLastError = p.errorMsg
                AppState.pendingPptJobId = null
                AppState.pptJobActive = false
            }
            PptJobStatus.CANCELLED -> {
                p.errorMsg = null
                AppState.pendingPptJobId = null
                AppState.pptJobActive = false
            }
            else -> Unit
        }
    }

    // ---------------- 追问（PPTAgent 反问 → 用户回答 → 续跑同一任务） ----------------

    /**
     * 回答 PPTAgent 的追问：POST /ppt/jobs/{id}/clarify {answer}，
     * 后端带着「它问了什么 / 用户答了什么」的上下文**续跑同一个任务**。
     * 后端刻意不自动代答（自动代答等于替用户编需求），所以这一步必须落到用户头上。
     */
    fun clarify(answer: String) {
        val p = current ?: return
        val r = repo ?: return
        if (p.jobId.isBlank() || p.answering) return
        p.answering = true
        p.answerError = null
        scope.launch {
            when (val s = r.clarifyJob(p.jobId, answer)) {
                is ApiResult.Ok -> {
                    p.question = null
                    p.status = if (s.data.status == "failed") PptJobStatus.FAILED
                    else PptJobStatus.GENERATING
                    if (p.status == PptJobStatus.FAILED) {
                        p.errorMsg = s.data.hint.ifBlank { "补充信息后仍无法生成，请重试" }
                        AppState.pptLastError = p.errorMsg
                        AppState.pendingPptJobId = null
                        AppState.pptJobActive = false
                    } else {
                        p.statusRaw = s.data.status
                        p.errorMsg = null
                        p.stageText = "已补充信息，正在继续生成…"
                        startPolling()
                    }
                }
                is ApiResult.Err -> p.answerError = s.message
            }
            p.answering = false
        }
    }

    // ---------------- 导出 ----------------

    /** 成功后自动把 pptx 写到用户先前选好的位置（20 分钟超时） */
    private fun autoExport(p: PptJobProgress) {
        val r = repo ?: return
        val target = p.targetFile ?: return
        if (p.exporting) return
        p.exporting = true
        p.exportError = null
        p.stageText = "生成完成，正在写入文件…"
        exportJob = scope.launch {
            try {
                var d = r.exportJob(p.jobId, target)
                // 后端在产物落盘前返回 404「任务尚未完成」，不是下载失败：等 3 秒再取一次
                if (d is ApiResult.Err && d.status == 404) {
                    delay(3_000)
                    d = r.exportJob(p.jobId, target)
                }
                when (d) {
                    is ApiResult.Ok -> {
                        p.exportedPath = target.absolutePath
                        p.exportError = null
                        p.stageText = "已保存：" + target.absolutePath
                        ClientLog.info("PPT 生成完成并已保存 " + target.name)
                    }
                    is ApiResult.Err -> {
                        p.exportError = d.message
                        p.stageText = "生成完成，但保存失败"
                        AppState.pptLastError = d.message
                        ClientLog.warn("PPT 落盘失败：" + d.message)
                    }
                }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                p.exportError = "保存失败：" + (e.message ?: "未知错误")
            } finally {
                p.exporting = false
                // 落盘成功才收尾：清掉全局失败痕迹与恢复句柄。
                // 不清的话，任务早已 succeeded，回到 PPT 页时
                // （ViewModel 重建后 docId 为 null）顶部会一直挂着上一次的红横幅，
                // 并且还会拿这个已结束的任务号去发起恢复。
                if (p.exportedPath != null) {
                    AppState.pptLastError = null
                    AppState.pendingPptJobId = null
                    AppState.pptJobActive = false
                }
            }
        }
    }

    /**
     * DONE 状态下的「下载 PPTX」：没有保存位置时返回 false，
     * 由界面用 pickSaveFile 重新要一个位置。
     */
    fun download(target: File?): Boolean {
        val p = current ?: return false
        if (p.jobId.isBlank()) return false
        if (target != null) p.targetFile = target
        if (p.targetFile == null) return false
        autoExport(p)
        return true
    }

    // ---------------- 取消 / 重置 / 恢复 ----------------

    /**
     * 取消：语义是**停止等待**，不是终止生成——PPTAgent 侧已启动的任务无法远程终止，
     * 会在服务端跑完（产物无人取）。所以文案一律说「已停止等待」，不说「已终止生成」。
     */
    fun cancel() {
        val p = current ?: return
        val r = repo
        stopPolling()
        exportJob?.cancel()
        exportJob = null
        if (r != null && p.jobId.isNotBlank()) {
            scope.launch { r.cancelJob(p.jobId) } // 服务端取消失败也不影响本地回到已取消态
        }
        p.status = PptJobStatus.CANCELLED
        p.stageText = "已停止等待"
        p.exporting = false
        AppState.pendingPptJobId = null
        AppState.pptJobActive = false
    }

    /** 回到 IDLE（清掉任务句柄，界面回到编辑工作台） */
    fun reset() {
        stopPolling()
        exportJob?.cancel()
        exportJob = null
        current = null
        AppState.pendingPptJobId = null
        AppState.pptJobActive = false
    }

    /**
     * 页面离开时调用：只停轮询协程（任务状态与目标文件都在服务端/全局对象里，不丢）。
     * 不这样处理的话，每个页面都会留下一条永远跑着的轮询协程。
     */
    fun stopPolling() {
        pollJob?.cancel()
        pollJob = null
    }

    /**
     * 回到页面时调用：任务还在跑就续上轮询；
     * 任务已在离开期间跑完但还没落盘（用户没在页面上，finish 没机会执行导出）就补一次导出。
     * 追问等待中（CLARIFYING）**不续轮询**——这一段是等用户，不是等服务端。
     */
    fun resumeIfNeeded(repository: PptRepository) {
        val p = current ?: return
        repo = repository
        if (p.isActive) {
            if (pollJob?.isActive != true) startPolling()
            return
        }
        stopPolling()
        if (p.status == PptJobStatus.DONE && !p.exporting &&
            p.exportedPath == null && p.targetFile != null
        ) {
            autoExport(p)
        }
    }
}

/**
 * 生成任务页图的绝对地址。
 *
 * 后端 `/preview` 给的 `url` 是**以 /api/v1 开头的服务器绝对路径**
 * （如 `/api/v1/ppt/jobs/{id}/preview/0.jpg`，见 interfaces/ppt.py），
 * 扩展名按 PPTAgent 实际产出走（实测是 jpg），客户端不自己拼扩展名；
 * 必须拼在 **origin**（scheme://host:port）后面，不能拼在 baseUrl 后面——
 * 一旦用户在设置里把 baseUrl 配成带路径前缀的地址，就会拼出 `/api/v1/.../api/v1/...` 而 404。
 * 未出图的页返回 null，界面显示占位、**不发请求**。
 */
fun pptJobImageUrl(jobId: String, page: PptJobPage?): String? {
    if (page == null || !page.pngReady) return null
    if (page.pngUrl.isNotBlank()) {
        val raw = page.pngUrl
        if (raw.startsWith("http", ignoreCase = true)) return raw
        val path = if (raw.startsWith("/")) raw else "/$raw"
        return originOf(AppState.serverConfig.baseUrl) + path
    }
    // 兜底：后端没给 url 时按 apiBase 自行拼出绝对地址（不在这里硬编码 /api/v1）
    return AppState.serverConfig.apiBase +
        com.judicialai.desktop.core.network.Endpoints.Ppt.Jobs.previewPage(jobId, page.index)
}

/** 取 origin（scheme://host:port）；解析失败时退回原样去尾斜杠 */
private fun originOf(baseUrl: String): String {
    val u = runCatching { java.net.URL(baseUrl) }.getOrNull()
        ?: return baseUrl.trimEnd('/')
    return u.protocol + "://" + u.authority
}

/** 秒 → 「5分20秒」 */
fun formatJobDuration(seconds: Int): String {
    val s = seconds.coerceAtLeast(0)
    val m = s / 60
    val rest = s % 60
    return if (m <= 0) "${rest}秒" else "${m}分${rest.toString().padStart(2, '0')}秒"
}

/** 产物来源说明：回退本地渲染是有意行为（宁可给能打开的文件），要明确告诉用户 */
fun pptRendererNote(renderer: String?): String? = when (renderer?.lowercase()) {
    "local" -> "本次由本地引擎生成（PPTAgent 未产出可用文件，已自动回退；排版与预览可能略有差异，文件可正常打开）"
    "pptagent" -> null
    else -> null
}
