package com.judicialai.desktop.features.writing

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import com.judicialai.desktop.app.AppScreen
import com.judicialai.desktop.app.AppState
import com.judicialai.desktop.app.PendingTemplateWrite
import com.judicialai.desktop.core.network.ApiResult
import com.judicialai.desktop.core.utils.arr
import com.judicialai.desktop.core.utils.bool
import com.judicialai.desktop.core.utils.int
import com.judicialai.desktop.core.utils.obj
import com.judicialai.desktop.core.utils.str
import com.judicialai.desktop.features.chat.model.ChatAttachment
import com.judicialai.desktop.features.knowledge.KnowledgeRepository
import com.judicialai.desktop.features.templates.TemplatesRepository
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.serialization.json.JsonObject
import java.io.File
import java.security.MessageDigest
import java.util.logging.Logger

private val writingTimeline = Logger.getLogger("WritingTimeline")
private fun requestDigest(text: String): String = MessageDigest.getInstance("SHA-256")
    .digest(text.toByteArray(Charsets.UTF_8)).take(6)
    .joinToString("") { "%02x".format(it.toInt() and 0xff) }

/** 工作台对话消息 */
data class TaskChatMessage(val role: String, val content: String, val revisionSummary: String = "")
data class WritingReference(val title: String, val documentId: String,
                            val attachmentId: String = "", val matchText: String = "")
data class WritingTextStyle(
    val fontName: String? = null,
    val fontSizePt: Float? = null,
    val bold: Boolean? = null,
    val alignment: String? = null,
    val indentChars: Float? = null,
) {
    fun toRequest(): Map<String, Any> = buildMap {
        fontName?.let { put("font_name", it) }
        fontSizePt?.let { put("font_size_pt", it) }
        bold?.let { put("bold", it) }
        alignment?.let { put("alignment", it) }
    }
}

/** 图片识别结果（写作台「上传图片识别」，服务端视觉模型 Qwen2.5-VL 识别） */
data class RecognizedImage(
    val filename: String,
    val text: String,
    val note: String,
    val ok: Boolean,
)

/**
 * 写作任务状态（对应后端 task_context）。
 * 所有字段的权威来源是后端返回；前端字段可编辑，编辑后 PATCH 同步回后端。
 */
data class WritingTaskState(
    val taskId: String? = null,
    val documentType: String = "",
    val title: String = "",
    val topic: String = "",
    val purpose: String = "",
    val timeRange: String = "",
    val recipient: String = "",
    val authority: String = "",
    val keyFacts: List<String> = emptyList(),
    val requirements: String = "",
    val tone: String = "",
    val wordCountTarget: Int = 0,
    val documentNumberEnabled: Boolean = false,
    val documentNumber: String = "",
    val documentDate: String = "",
    val missingFields: List<String> = emptyList(),
)

class WritingViewModel(
    private val repo: WritingRepository,
    private val knowledgeRepo: KnowledgeRepository? = null,
    private val templatesRepo: TemplatesRepository? = null,
) {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)

    /**
     * 模板中心的可选模板（供「本次写作」左栏下拉）。
     * 刻意保持**可选**：默认空表示不套模板，模型按自身判断组织文种与结构；
     * 强套模板会让 14B 变得死板（曾经把讲话稿套成报告四段式就是这个后果）。
     */
    private val _templateOptions = MutableStateFlow<List<SpecOption>>(emptyList())
    val templateOptions: StateFlow<List<SpecOption>> = _templateOptions.asStateFlow()

    /** 当前选中的模板 id；空串 = 不使用模板。 */
    private val _chosenTemplateId = MutableStateFlow("")
    val chosenTemplateId: StateFlow<String> = _chosenTemplateId.asStateFlow()

    /** 拉取模板中心的启用模板，供下拉使用。失败时静默降级为「无模板可选」。 */
    fun loadTemplateOptions() {
        val tpl = templatesRepo ?: return
        scope.launch {
            val items = tpl.list()
            val opts = (items as? List<*>)?.mapNotNull { it as? kotlinx.serialization.json.JsonObject }
                ?.filter { (it["is_active"] as? kotlinx.serialization.json.JsonPrimitive)?.content != "false" }
                ?.map { o ->
                    SpecOption(
                        id = (o["id"] as? kotlinx.serialization.json.JsonPrimitive)?.content.orEmpty(),
                        label = (o["name"] as? kotlinx.serialization.json.JsonPrimitive)?.content.orEmpty(),
                        selected = false,
                    )
                }
                ?.filter { it.id.isNotBlank() && it.label.isNotBlank() }
                .orEmpty()
            _templateOptions.value = opts
        }
    }

    /** 切换选中的模板；传空串表示不使用模板（恢复14B 自由生成）。 */
    fun chooseTemplate(id: String) {
        _chosenTemplateId.value = id
        _templateOptions.value = _templateOptions.value.map {
            it.copy(selected = it.id == id)
        }
    }

    /** 当前正在执行的生成类任务（创建/规划/起草/对话/改写），用于「取消生成」 */
    private var activeJob: Job? = null
    private var writingClickAtNanos: Long = 0
    private var draftPreviousContent: String? = null
    private var currentAgentRunId: String? = null

    /**
     * 跨页面恢复任务（切回本页时按 [AppState.pendingWritingTaskId] 拉回任务上下文）的协程句柄。
     *
     * **必须与 [activeJob] 分开**：恢复不是"生成"，如果共用句柄，用户点「取消生成」
     * 会取消这次恢复（界面上的 busy 状态还卡着），而真正跑着的生成反而没人能取消。
     */
    private var restoreJob: Job? = null

    var task by mutableStateOf(WritingTaskState())
        private set
    var renderProfile by mutableStateOf<JsonObject?>(null)
        private set
    var titleFormatting by mutableStateOf(WritingTextStyle())
        private set
    var paragraphFormatting by mutableStateOf(mapOf<Int, WritingTextStyle>())
        private set
    var formatDirty by mutableStateOf(false)
    var formatIssues by mutableStateOf<List<JsonObject>>(emptyList())
        private set

    fun setParagraphFormatting(index: Int, style: WritingTextStyle) {
        paragraphFormatting = paragraphFormatting + (index to style)
        formatDirty = true
        formatIssues = emptyList()
    }

    fun replaceParagraphContent(index: Int, replacement: String) {
        val lines = content.split('\n').toMutableList()
        if (index !in lines.indices) return
        lines.removeAt(index)
        val inserted = if (replacement.isBlank()) emptyList() else replacement.split('\n')
        lines.addAll(index, inserted)
        val shift = inserted.size - 1
        paragraphFormatting = paragraphFormatting.mapNotNull { (line, style) ->
            when {
                line < index -> line to style
                line == index && inserted.isNotEmpty() -> index to style
                line > index -> line + shift to style
                else -> null
            }
        }.toMap()
        content = lines.joinToString("\n")
        formatIssues = emptyList()
    }

    fun replaceSourceContent(value: String) {
        if (value != content) {
            paragraphFormatting = emptyMap()
            formatDirty = true
        }
        content = value
        formatIssues = emptyList()
    }

    fun updateTitleFormatting(style: WritingTextStyle) {
        titleFormatting = style
        formatDirty = true
        formatIssues = emptyList()
    }

    private fun formattingRequest(): Map<String, Any> = mapOf(
        "title" to titleFormatting.toRequest(),
        "paragraphs" to paragraphFormatting.mapKeys { it.key.toString() }
            .mapValues { it.value.toRequest() },
    )

    private fun parseStyle(o: JsonObject?): WritingTextStyle = WritingTextStyle(
        fontName = o?.get("font_name").str().ifBlank { null },
        fontSizePt = o?.get("font_size_pt").str().toFloatOrNull(),
        bold = o?.get("bold")?.let { it.bool() },
        alignment = o?.get("alignment").str().ifBlank { null },
    )
    var content by mutableStateOf("")
    var versionNo by mutableStateOf(0)
        private set
    var status by mutableStateOf<String?>(null)
    var agentProgress by mutableStateOf<String?>(null)
        private set
    var taskStatus by mutableStateOf("collecting")
        private set

    var messages by mutableStateOf(listOf<TaskChatMessage>())
        private set
    var chatInput by mutableStateOf("")
    var materials by mutableStateOf(listOf<ChatAttachment>())
        private set
    var entryMaterials by mutableStateOf(listOf<File>())
        private set
    var references by mutableStateOf(listOf<String>())
        private set
    var contentIssues by mutableStateOf(listOf<JsonObject>())
        private set
    var checkingContent by mutableStateOf(false)
        private set
    var referenceItems by mutableStateOf(listOf<WritingReference>())
        private set
    var openedReference by mutableStateOf<WritingReference?>(null)
        private set
    var openedReferenceDocument by mutableStateOf<JsonObject?>(null)
        private set
    var referenceLoading by mutableStateOf(false)
        private set
    var referenceError by mutableStateOf<String?>(null)
        private set

    fun openReference(reference: WritingReference) {
        openedReference = reference
        openedReferenceDocument = null
        referenceError = if (reference.documentId.isBlank() && reference.attachmentId.isBlank())
            "本条资料暂无可查看的原文" else null
        if (referenceError != null) return
        referenceLoading = true
        scope.launch {
            val result = if (reference.attachmentId.isNotBlank())
                repo.getAttachment(reference.attachmentId)
            else knowledgeRepo?.getDocument(reference.documentId)
            when (result) {
                is ApiResult.Ok -> openedReferenceDocument = result.data
                is ApiResult.Err -> referenceError = result.message
                null -> referenceError = "知识库暂不可用"
            }
            referenceLoading = false
        }
    }

    fun closeReference() {
        openedReference = null
        openedReferenceDocument = null
        referenceError = null
        referenceLoading = false
    }

    fun checkContent() {
        val id = task.taskId ?: return
        if (checkingContent || !hasDraft) return
        checkingContent = true
        scope.launch {
            when (val result = repo.checkContent(id)) {
                is ApiResult.Ok -> {
                    contentIssues = result.data?.get("issues").arr().mapNotNull { it.obj() }
                    status = if (result.data?.get("ai_used").bool())
                        "内容校验完成：发现 ${contentIssues.size} 项需核对"
                        else "语义模型暂不可用；已返回可完成的证据核验结果"
                }
                is ApiResult.Err -> status = result.message
            }
            checkingContent = false
        }
    }
    var versions by mutableStateOf(listOf<JsonObject>())
        private set
    var busy by mutableStateOf(false)
        private set

    /**
     * 正在按全局 taskId 恢复上一次的写作任务（切到别的页面再切回时触发）。
     *
     * 与 [busy] 分开的意义：恢复是**正常的无感动作**，不是失败。
     * 之前恢复进度写进 [status]，而界面把 status 一律按红色错误框渲染，
     * 用户每切一次页面就看见一次红字，正是"切换就报错"的观感来源。
     */
    var restoring by mutableStateOf(false)
        private set

    /**
     * 轻提示（如「取消生成成功」）：居中浮层短暂展示后自动消失。
     * 与 [status] 的区别：status 会驻留直到下一次操作覆盖，轻提示只闪一下，
     * 用于「用户刚做的动作生效了」这类即时反馈，不打断后续操作。
     */
    var toast by mutableStateOf<String?>(null)
        private set
    private var toastJob: Job? = null

    /** 弹一个轻提示，[durationMs] 后自动消失（默认 0.5 秒） */
    fun showToast(msg: String, durationMs: Long = 500) {
        toastJob?.cancel()
        toast = msg
        toastJob = scope.launch {
            delay(durationMs)
            toast = null
        }
    }

    /** 历史版本预览弹窗（查看 + 回退） */
    var versionPreview by mutableStateOf<JsonObject?>(null)
        private set

    /** 参考材料（知识库文档）查看/编辑弹窗 */
    var docDialogId by mutableStateOf<String?>(null)
        private set
    var docDialogTitle by mutableStateOf("")
    var docDialogDocType by mutableStateOf("")
    var docDialogContent by mutableStateOf("")
    var docDialogBusy by mutableStateOf(false)
        private set

    /** 零门槛入口输入 */
    var entryInput by mutableStateOf("")

    /** AI 规划出的本次写作工作台配置；为空表示尚未规划或后端不支持 */
    var spec by mutableStateOf<WorkspaceSpec?>(null)
        private set

    /** 规划中（AI 理解任务 → 生成 WorkspaceSpec） */
    var planning by mutableStateOf(false)
        private set

    /** 规划失败原因（后端不支持 / 模型不可用时的真实提示） */
    var planError by mutableStateOf<String?>(null)
        private set

    /** 图片识别（视觉模型）：进行中标记与最近一批识别结果 */
    var recognizingImages by mutableStateOf(false)
        private set
    var imageResults by mutableStateOf(listOf<RecognizedImage>())
        private set

    val hasTask: Boolean get() = task.taskId != null
    val hasDraft: Boolean get() = content.isNotBlank()

    /**
     * 最近一次由服务端下发的正文快照。
     * 与 [content] 相等说明用户没有手改过编辑器内容，此时才允许用服务端新内容覆盖
     * （用于「离开页面之后生成才跑完」的自动刷新，避免把用户手改的字冲掉）。
     */
    private var serverContent: String = ""

    /** Server-backed line anchors; only the selected line is ever offered to the model. */
    var paragraphs by mutableStateOf(listOf<JsonObject>())
        private set
    var selectedLineIndex by mutableStateOf<Int?>(null)
        private set
    var selectedSuggestion by mutableStateOf<JsonObject?>(null)
        private set
    var suggestionText by mutableStateOf("")
    var suggestionInstruction by mutableStateOf("")
    var suggestionBusy by mutableStateOf(false)
        private set
    var paragraphEditing by mutableStateOf(false)
        private set
    private var suggestionOperation = 0
    fun markParagraphEditing(editing: Boolean) { paragraphEditing = editing }
    val selectedParagraph: JsonObject?
        get() = paragraphs.firstOrNull { it["line_index"].int() == selectedLineIndex }
    val suggestionReady: Boolean
        get() = selectedParagraph != null && content == serverContent &&
            !busy && !suggestionBusy && !paragraphEditing

    private suspend fun loadParagraphs(id: String): Boolean {
        val expectedContent = serverContent
        val expectedVersion = versionNo
        when (val r = repo.paragraphs(id)) {
            is ApiResult.Ok -> {
                if (task.taskId != id || serverContent != expectedContent ||
                    versionNo != expectedVersion || r.data?.get("version_no").int() != versionNo) {
                    return false
                }
                paragraphs = r.data?.get("items").arr().mapNotNull { it.obj() }.orEmpty()
                val previousSuggestion = selectedSuggestion
                val editedText = suggestionText
                val nextSuggestion = selectedParagraph?.get("suggestion").obj()
                val preserveEdit = previousSuggestion?.get("id").str() ==
                    nextSuggestion?.get("id").str() &&
                    nextSuggestion?.get("status").str() == "pending" &&
                    editedText != previousSuggestion?.get("proposed_content").str()
                selectedSuggestion = nextSuggestion
                if (!preserveEdit) suggestionText = nextSuggestion?.get("proposed_content").str()
                return true
            }
            is ApiResult.Err -> if (r.status != 404) status = r.message
        }
        return false
    }

    fun refreshParagraphs() {
        val id = task.taskId ?: return
        scope.launch { loadParagraphs(id) }
    }

    fun selectParagraph(index: Int) {
        selectedLineIndex = index
        selectedSuggestion = selectedParagraph?.get("suggestion").obj()
        suggestionText = selectedSuggestion?.get("proposed_content").str()
        suggestionInstruction = ""
        if (selectedParagraph == null) {
            val id = task.taskId ?: return
            scope.launch {
                if (!loadParagraphs(id) && selectedLineIndex == index) {
                    status = "暂时无法定位该段，请刷新任务后重试"
                }
            }
        }
    }

    fun suggestParagraph(regenerate: Boolean = false) {
        val id = task.taskId ?: return
        val requestedLineIndex = selectedLineIndex
        val pid = selectedParagraph?.get("id").str()
        if (pid.isNullOrBlank()) {
            status = "该段定位尚未加载，请稍后再点 AI 优化"
            refreshParagraphs()
            return
        }
        if (!suggestionReady) {
            status = "请先保存当前手工修改，再获取该段建议"
            return
        }
        suggestionBusy = true
        val operation = ++suggestionOperation
        scope.launch {
            when (val r = repo.suggestParagraph(id, pid, suggestionInstruction, regenerate)) {
                is ApiResult.Ok -> {
                    if (suggestionOperation == operation && task.taskId == id &&
                        selectedLineIndex == requestedLineIndex &&
                        selectedParagraph?.get("id").str() == pid) {
                        selectedSuggestion = r.data
                        suggestionText = r.data?.get("proposed_content").str()
                    }
                    if (suggestionOperation == operation && task.taskId == id) refreshParagraphs()
                }
                is ApiResult.Err -> if (suggestionOperation == operation && task.taskId == id)
                    status = r.message
            }
            if (suggestionOperation == operation) suggestionBusy = false
        }
    }

    fun acceptSuggestion() {
        val id = task.taskId ?: return
        val suggestionId = selectedSuggestion?.get("id").str()
        if (suggestionId.isNullOrBlank() || !suggestionReady) return
        val expectedContent = content
        val expectedServerContent = serverContent
        val expectedVersion = versionNo
        suggestionBusy = true
        val operation = ++suggestionOperation
        scope.launch {
            when (val r = repo.acceptSuggestion(id, suggestionId, suggestionText)) {
                is ApiResult.Ok -> {
                    if (suggestionOperation == operation && task.taskId == id) {
                        if (content == expectedContent && serverContent == expectedServerContent &&
                            versionNo == expectedVersion) {
                            r.data?.let { applyResponse(it) }
                            status = if (r.data?.get("content_changed").bool())
                                "已只替换选中段，其他正文保持不变"
                            else "原文无需修改，已记录采纳"
                            if (!r.data?.get("content_changed").bool()) refreshParagraphs()
                        } else {
                            status = "建议已在服务器采纳；本地有新编辑，请先处理本地内容再刷新任务"
                        }
                    }
                }
                is ApiResult.Err -> if (suggestionOperation == operation && task.taskId == id)
                    status = r.message
            }
            if (suggestionOperation == operation) suggestionBusy = false
        }
    }

    fun rejectSuggestion() {
        val id = task.taskId ?: return
        val suggestionId = selectedSuggestion?.get("id").str()
        if (suggestionId.isNullOrBlank() || !suggestionReady) return
        val requestedLineIndex = selectedLineIndex
        suggestionBusy = true
        val operation = ++suggestionOperation
        scope.launch {
            when (val r = repo.rejectSuggestion(id, suggestionId)) {
                is ApiResult.Ok -> {
                    if (suggestionOperation == operation && task.taskId == id) {
                        if (selectedLineIndex == requestedLineIndex) {
                            selectedSuggestion = r.data?.get("suggestion").obj()
                        }
                        status = "已拒绝建议，原文未更改"
                        refreshParagraphs()
                    }
                }
                is ApiResult.Err -> if (suggestionOperation == operation && task.taskId == id)
                    status = r.message
            }
            if (suggestionOperation == operation) suggestionBusy = false
        }
    }

    // ---------------- 状态装载 ----------------

    private fun applyResponse(d: JsonObject) {
        val id = d["task_id"].str().ifBlank { task.taskId }
        val previousTaskId = task.taskId
        // 记录到全局：切到别的页面再切回时（ViewModel 重建、状态清零）
        // 按此 id 调 GET /writing/tasks/{id} 恢复任务
        if (!id.isNullOrBlank()) AppState.pendingWritingTaskId = id
        val ctx = d["task_context"].obj() ?: return
        task = WritingTaskState(
            taskId = id,
            documentType = ctx["document_type"].str(),
            title = ctx["title"].str(),
            topic = ctx["topic"].str(),
            purpose = ctx["purpose"].str(),
            timeRange = ctx["time_range"].str(),
            recipient = ctx["recipient"].str(),
            authority = ctx["authority"].str(),
            keyFacts = ctx["key_facts"].arr().map { it.str() }.filter { it.isNotBlank() },
            requirements = ctx["requirements"].str(),
            tone = ctx["tone"].str(),
            wordCountTarget = ctx["word_count_target"].int(),
            documentNumberEnabled = ctx["document_number_enabled"].bool(),
            documentNumber = ctx["document_number"].str(),
            documentDate = ctx["document_date"].str(),
            missingFields = ctx["missing_fields"].arr().map { it.str() }.filter { it.isNotBlank() },
        )
        if (id != previousTaskId && !id.isNullOrBlank()) {
            renderProfile = null
            scope.launch {
                val profile = repo.renderProfile(id)
                if (task.taskId == id && profile is ApiResult.Ok) {
                    renderProfile = profile.data
                }
            }
        }
        if (messages.isEmpty()) {
            messages = ctx["history"].arr().mapNotNull { item ->
                val entry = item.obj() ?: return@mapNotNull null
                val role = entry["role"].str()
                val text = entry["content"].str()
                if (role.isBlank() || text.isBlank()) null else TaskChatMessage(role, text)
            }
        }
        val nextVersion = d["version_no"].int()
        d["current_content"].str().takeIf { it.isNotBlank() }?.let {
            val shouldRefresh = it != serverContent || nextVersion != versionNo || id != previousTaskId
            content = it
            serverContent = it
            versionNo = nextVersion
            if (shouldRefresh) {
                paragraphs = emptyList()
                selectedSuggestion = null
                suggestionText = ""
                refreshParagraphs()
            }
        }
        versionNo = nextVersion
        d["formatting"].obj()?.let { format ->
            titleFormatting = parseStyle(format["title"].obj())
            paragraphFormatting = format["paragraphs"].obj()?.mapNotNull { (key, value) ->
                key.toIntOrNull()?.let { it to parseStyle(value.obj()) }
            }?.toMap().orEmpty()
            formatDirty = false
        }
        taskStatus = d["status"].str().ifBlank { taskStatus }
        d["references"].arr().map { it.str() }.filter { it.isNotBlank() }
            .takeIf { it.isNotEmpty() }?.let { references = it }
        referenceItems = d["reference_items"].arr().mapNotNull { element ->
            val item = element.obj() ?: return@mapNotNull null
            item["title"].str().takeIf { it.isNotBlank() }?.let {
                title -> WritingReference(title, item["doc_id"].str(),
                    item["attachment_id"].str(), item["match_text"].str())
            }
        }
        if (d["content_changed"].bool()) refreshVersions()
    }

    private fun fail(msg: String) {
        agentProgress = null
        status = msg
        busy = false
        AppState.writingGenerating = false
        // 记到全局：切走再切回时本地 status 会随 ViewModel 一起丢失，
        // 用户只会看到空工作台，不知道这次其实失败了
        AppState.writingLastError = msg
    }

    // ---------------- 取消生成 / 返回模板 ----------------

    /**
     * 取消本次生成：立即结束本地等待，并通知服务端终止对应智能体运行。
     *
     * 注意：这里**不写 [status]**。取消是用户主动操作、不是失败，
     * 写 status 会被按提示条/错误框渲染；协程取消后 ApiClient 会上抛
     * CancellationException 正常收尾，不会再走 fail()。
     */
    fun cancelGeneration() {
        val taskId = task.taskId
        val runId = currentAgentRunId
        activeJob?.cancel()
        activeJob = null
        currentAgentRunId = null
        agentProgress = null
        if (taskId != null && !runId.isNullOrBlank()) {
            scope.launch { repo.cancelAgentRun(taskId, runId) }
        }
        draftPreviousContent?.let { content = it }
        draftPreviousContent = null
        busy = false
        planning = false
        AppState.writingGenerating = false
    }

    /**
     * 「取消生成」按钮语义：停止等待 → 轻提示「取消生成成功」（约 0.5 秒自动消失）
     * → 回到任务入口初始状态。
     */
    fun cancelAndReset() {
        cancelGeneration()
        newTask()
        spec = null
        planError = null
        showToast("取消生成成功")
    }

    // ---------------- 跨页面恢复 ----------------

    /**
     * 按 taskId 重新装载任务（切到别的页面再切回时 ViewModel 被重建、状态清零，
     * 但生成协程不会被取消，任务在服务端仍然存在）。
     * 复用 applyResponse 填充任务上下文 / 正文 / 版本号，并补拉版本链。
     *
     * 关于"切回页面就报错"：本方法过去把进度文案写进 [status]，而界面把 status
     * 一律按红色错误框渲染；失败时还把服务端 detail 原样拼成
     * 「恢复上次写作任务失败：xxx」。现在改为——
     * - 进度走 [restoring]，不进 status，不染红；
     * - 任务在服务端已不存在（HTTP 404）属于**无害的正常收尾**：静默回到入口页，
     *   不再弹红字；
     * - 其余错误给一句用户能照做的中文提示，不透传服务端原文。
     */
    fun openTask(id: String) {
        if (id.isBlank() || busy || restoring) return
        busy = true
        restoring = true
        status = null
        restoreJob = scope.launch {
            try {
                when (val r = repo.getTask(id)) {
                    is ApiResult.Ok -> {
                        // 护栏：取回结果期间用户可能已点「新建任务」或切走，
                        // 此时 pendingWritingTaskId 已不再是本任务 id，绝不可把旧内容写回
                        // 当前（全新）任务，否则串台。
                        if (AppState.pendingWritingTaskId != id) {
                            return@launch
                        }
                        val d = r.data
                        if (d != null) {
                            applyResponse(d)
                            // 服务端正文可能为空（还没起草完）：这里无条件对齐，避免残留别的内容
                            content = d["current_content"].str()
                            serverContent = content
                            refreshVersions()
                            status = null
                            // 服务端已经有正文，说明上次生成其实成功了：
                            // 「上次生成未完成」那条提示再挂着就是误导，这里清掉
                            if (content.isNotBlank()) AppState.writingLastError = null
                        } else {
                            // 任务已被清理：静默回到入口页即可，不是错误
                            AppState.pendingWritingTaskId = null
                            AppState.writingLastError = null
                        }
                    }
                    is ApiResult.Err -> {
                        // 取不到就别再记着，避免每次切回页面都重试一次失败的请求
                        AppState.pendingWritingTaskId = null
                        // 404 = 任务在服务端已不存在（删除 / 换账号 / 服务端清理），是无害情况
                        if (r.status == 404) {
                            AppState.writingLastError = null
                        } else {
                            val tip = "暂时没能取回上次的写作任务，已回到任务入口，可重新描述需求"
                            status = tip
                            AppState.writingLastError = tip
                        }
                    }
                }
            } finally {
                // 无论成败都要放掉，否则界面会永久卡在"恢复中"、按钮全灰
                busy = false
                restoring = false
            }
        }
    }

    /**
     * 用服务端最新状态刷新当前任务。
     * 仅在用户没有手改过正文（[content] 与 [serverContent] 一致）时才覆盖，
     * 用于「离开页面之后生成才跑完」的场景：那时本地拿到的还是生成前的内容。
     */
    fun refreshTask() {
        val id = task.taskId ?: return
        if (content != serverContent) return
        scope.launch {
            when (val r = repo.getTask(id)) {
                is ApiResult.Ok -> r.data?.let { applyResponse(it) }
                is ApiResult.Err -> Unit
            }
        }
    }

    /**
     * 模板中心来的任务：取消当前生成并销毁本次任务，
     * 回到模板中心重新填写要素（已填要素由 AppState 暂存回填）。
     */
    fun returnToTemplate() {
        val templateId = spec?.templateId ?: return
        cancelGeneration()
        newTask()
        spec = null
        planError = null
        AppState.pendingTemplateUseId = templateId
        AppState.navigate(AppScreen.TEMPLATES)
    }

    // ---------------- 入口 ----------------

    /**
     * 开新任务前的隔离动作：作废旧任务的跨页恢复标记、清掉残留的一次性跳转参数。
     * 不做这一步，「创建期间切走再切回」会把上一个任务（连同它的工作内容）
     * 恢复到本次新任务的工作台里，表现为上下文串话。
     */
    private fun isolateNewTask() {
        AppState.pendingWritingTaskId = null
        AppState.pendingWritingIntent = null
        AppState.pendingWritingTemplate = null
    }

    /** 一句话启动任务 */
    fun startFromIntent() {
        val text = entryInput.trim()
        if (text.isBlank() || busy) return
        isolateNewTask()
        busy = true
        AppState.writingGenerating = true
        AppState.writingLastError = null
        status = null
        agentProgress = null
        messages = messages + TaskChatMessage("user", text)
        activeJob = scope.launch {
            when (val r = repo.createTask(text)) {
                is ApiResult.Ok -> {
                    r.data?.let { d ->
                        applyResponse(d)
                    }
                    entryInput = ""
                    busy = false
                    AppState.writingGenerating = false
                    if (hasTask) draft()
                    return@launch
                }
                is ApiResult.Err -> fail(r.message)
            }
            busy = false
            AppState.writingGenerating = false
        }
    }

    // ---------------- AI 任务规划 → WorkspaceSpec ----------------

    /**
     * 一句话指令 → AI 规划工作台 → 创建任务。
     * 先规划（决定文种/材料/知识范围/模板），再带着规划结果建任务，
     * 因此左栏不是固定字段，而是本次任务真正需要的参数。
     */
    fun planAndStart() {
        val text = entryInput.trim()
        if (text.isBlank() || busy) return
        writingClickAtNanos = System.nanoTime()
        val requestId = requestDigest(text)
        isolateNewTask()
        busy = true
        AppState.writingGenerating = true
        AppState.writingLastError = null
        planning = true
        status = null
        agentProgress = "正在理解需求并规划写作…"
        planError = null
        messages = messages + TaskChatMessage("user", text)
        activeJob = scope.launch {
            val planned = runCatching { repo.plan(text) }.getOrNull()
            writingTimeline.info("request=$requestId plan_ms=${(System.nanoTime() - writingClickAtNanos) / 1_000_000}")
            val specResult = when (planned) {
                is ApiResult.Ok -> planned.data?.let { parseSpec(it) }
                is ApiResult.Err -> {
                    planError = planned.message
                    null
                }
                else -> null
            }
            spec = specResult
            planning = false
            agentProgress = "正在创建写作任务…"
            // 无论是否规划成功，都按用户的原话创建任务（不阻断写作）
            when (val r = repo.createTask(text, specResult)) {
                is ApiResult.Ok -> {
                    writingTimeline.info("request=$requestId create_ms=${(System.nanoTime() - writingClickAtNanos) / 1_000_000}")
                    val task = r.data ?: run {
                        fail("创建写作任务失败：服务端未返回任务")
                        return@launch
                    }
                    applyResponse(task)
                    entryInput = ""
                    val pending = entryMaterials
                    if (pending.isNotEmpty()) {
                        agentProgress = "正在读取上传材料并识别图片…"
                        when (val uploaded = repo.uploadTaskMaterials(this@WritingViewModel.task.taskId!!, pending)) {
                            is ApiResult.Ok -> {
                                materials = materials + uploaded.data.map {
                                    ChatAttachment(it["id"].str(), it["filename"].str(),
                                        it["kind"].str().ifBlank { "doc" },
                                        it["parse_status"].str() == "failed")
                                }
                                entryMaterials = emptyList()
                                val failedCount = uploaded.data.count {
                                    it["parse_status"].str() == "failed" || it["text"].str().isBlank()
                                }
                                if (failedCount == uploaded.data.size) {
                                    fail("材料均未识别出可用文字；请检查图片清晰度或 OCR 配置后重传")
                                    busy = false
                                    AppState.writingGenerating = false
                                    return@launch
                                }
                                if (failedCount > 0) messages = messages + TaskChatMessage(
                                    "assistant", "$failedCount 份材料未识别出文字，其余已加入写作上下文")
                            }
                            is ApiResult.Err -> {
                                fail("材料上传失败：${uploaded.message}；任务已创建，请重试上传后再起草")
                                busy = false
                                AppState.writingGenerating = false
                                return@launch
                            }
                        }
                    }
                    busy = false
                    AppState.writingGenerating = false
                    if (hasTask) draft()
                    return@launch
                }
                is ApiResult.Err -> fail(r.message)
            }
            busy = false
            AppState.writingGenerating = false
        }
    }

    /**
     * 模板中心「使用模板」直达：模板要素已在模板中心内联填好，
     * 这里直接创建绑定该模板的写作任务（template_id 随任务落库），
     * 成功后自动起草初稿——与智能写作工作台同一套对话/版本/导出能力。
     *
     * 注意：这是「开新任务」语义。即便当前已恢复出旧任务（例如页面未被销毁、
     * hasTask 仍为 true），也必须先清场再建任务，否则旧任务的工作内容
     * 会混进本次模板任务（上下文串话）。
     */
    fun startFromTemplate(p: PendingTemplateWrite) {
        if (busy) return
        isolateNewTask()
        newTask()
        busy = true
        AppState.writingGenerating = true
        AppState.writingLastError = null
        status = "正在按模板「${p.templateName}」创建写作任务…"
        agentProgress = "正在准备模板写作任务…"
        messages = messages + TaskChatMessage("user", p.message)
        activeJob = scope.launch {
            val planned = WorkspaceSpec(
                docType = p.docType,
                title = p.title,
                source = "template",
                templateId = p.templateId,
                templateName = p.templateName,
                plannedContext = p.plannedContext,
            )
            spec = planned
            when (val r = repo.createTask(p.message, planned)) {
                is ApiResult.Ok -> {
                    r.data?.let { d ->
                        applyResponse(d)
                    }
                    busy = false
                    status = null
                    // 创建阶段结束；紧接着的 draft() 会自己把标记重新置起
                    AppState.writingGenerating = false
                    if (hasTask) draft()
                    return@launch
                }
                is ApiResult.Err -> fail(r.message)
            }
        }
    }

    /** 未规划直接进入（后端不支持规划接口时的降级路径） */
    fun startWithoutPlan() {
        planError = null
        startFromIntent()
    }

    /** 返回任务入口（重新描述任务） */
    fun backToEntry() {
        cancelGeneration()
        newTask()
        spec = null
        planError = null
    }

    private fun parseSpec(d: JsonObject): WorkspaceSpec {
        val scopeArr = d["scopes"].arr().map { it.str() }.filter { it.isNotBlank() }
        return WorkspaceSpec(
            docType = d["doc_type"].str(),
            target = d["target"].str(),
            audience = d["audience"].str(),
            department = d["department"].str(),
            agent = d["agent"].str(),
            title = d["title"].str(),
            source = d["source"].str(),
            plannedContext = d["planned_context"].obj(),
            fields = d["fields"].arr().mapNotNull { it.obj() }.map { f ->
                SpecField(label = f["label"].str(), value = f["value"].str())
            },
            materials = d["materials"].arr().mapNotNull { it.obj() }.map { o ->
                SpecOption(id = o["id"].str(), label = o["label"].str(),
                    selected = o["selected"].bool(), note = o["note"].str())
            },
            knowledge = d["knowledge"].arr().mapNotNull { it.obj() }.map { o ->
                SpecOption(id = o["id"].str(), label = o["label"].str(),
                    selected = o["selected"].bool(), note = o["note"].str())
            },
            // 后端 plan 可能带一个推荐模板，但**不自动选中**：模板是可选增强，
            // 自动勾上等于把模型锁死成某文种的固定骨架（曾导致讲话稿被套成报告体例）。
            // 只有用户在下拉里显式选过才带上 templateId。
            templateId = _chosenTemplateId.value,
            templateName = if (_chosenTemplateId.value.isBlank()) ""
                           else _templateOptions.value.firstOrNull { it.id == _chosenTemplateId.value }?.label.orEmpty(),
            scopes = scopeArr,
            kbIds = d["kb_ids"].arr().map { it.str() }.filter { it.isNotBlank() },
            aiActions = d["ai_actions"].arr().map { it.str() }.filter { it.isNotBlank() },
        )
    }

    /** 切换知识来源：影响后续检索范围（写入任务上下文） */
    fun toggleKnowledge(opt: SpecOption) {
        val s = spec ?: return
        spec = s.copy(knowledge = s.knowledge.map {
            if (it.id == opt.id) it.copy(selected = !it.selected) else it
        })
        val id = task.taskId ?: return
        scope.launch {
            repo.patchContext(id, mapOf(
                "kb_ids" to spec!!.knowledge.filter { it.selected }.map { it.id },
            ))
        }
    }

    /** 勾选 / 取消参考材料 */
    fun toggleMaterial(opt: SpecOption) {
        val s = spec ?: return
        spec = s.copy(materials = s.materials.map {
            if (it.id == opt.id) it.copy(selected = !it.selected) else it
        })
    }

    /**
     * 左栏 AI 规划参数人工修订：对生成结果不满意时直接改参数，
     * 改后同步 spec 展示并 PATCH 回任务上下文，下次「继续生成」按新参数起草。
     */
    fun patchSpecField(label: String, value: String) {
        val s = spec ?: return
        when (label) {
            "文种" -> spec = s.copy(docType = value)
            "报送对象" -> spec = s.copy(audience = value)
            "写作目标" -> spec = s.copy(target = value)
            else -> spec = s.copy(fields = s.fields.map {
                if (it.label == label) it.copy(value = value) else it
            })
        }
        val key = SPEC_FIELD_KEYS[label] ?: return
        patchContext(mapOf(key to value.ifBlank { null }))
    }

    // ---------------- 任务内对话 ----------------

    /** 用户在工作台持续对话（补要素 / 起草 / 自然语言修改都由后端决策） */
    fun sendChat() {
        val text = chatInput.trim()
        val id = task.taskId
        if (text.isBlank() || busy || id == null) return
        busy = true
        agentProgress = "正在理解修改要求并检查当前文稿…"
        AppState.writingGenerating = true
        AppState.writingLastError = null
        messages = messages + TaskChatMessage("user", text)
        chatInput = ""
        activeJob = scope.launch {
            try {
                when (val r = repo.chatStream(id, text) { progress ->
                    agentProgress = progress
                }) {
                    is ApiResult.Ok -> {
                        r.data?.let { d ->
                            applyResponse(d)
                            d["reply"].str().takeIf { it.isNotBlank() }
                                ?.let { messages = messages + TaskChatMessage(
                                    "assistant", it, d["revision_summary"].str()) }
                        }
                    }
                    is ApiResult.Err -> fail(r.message)
                }
            } catch (e: kotlinx.coroutines.CancellationException) {
                throw e
            } catch (e: Exception) {
                fail("对话失败：${e.message ?: "请稍后重试"}")
            } finally {
                busy = false
                agentProgress = null
                AppState.writingGenerating = false
            }
        }
    }

    // ---------------- 起草 / 继续生成 / 修改 ----------------

    /**
     * 起草初稿；已有正文时生成以当前稿为锚点的新版本。
     * 优先走 SSE 流式接口：正文边生成边在中栏上屏；
     * 服务端未部署流式接口（HTTP 404）时自动回退为一次性生成。
     */
    fun draft(outlineOnly: Boolean = false) {
        val id = task.taskId ?: return
        if (busy) return
        if (hasDraft && content != serverContent) {
            status = "请先保存当前手工修改，再基于这版继续生成"
            return
        }
        busy = true
        AppState.writingGenerating = true
        AppState.writingLastError = null
        status = null
        agentProgress = "正在检索可用资料并准备正文…"
        // 服务端语义是「按当前稿继续生成，旧正文自动归档为 v{n+1}」
        // （task_service._finalize_draft: t.current_content = text，随后 _snapshot 旧版），
        // 不是「在旧文后面续写」。所以开流前必须先清空编辑器：
        // 否则 content += delta 会把新一版直接拼在上一版下面，界面上出现 v1+v2 连体。
        // 保留一份本地旧内容：若生成失败或服务端拒收，立即恢复。
        // 注意：这里**不动** serverContent，让 content 与它保持不一致，
        // 期间 refreshTask() 就不会拿服务端的旧正文把正在流的这一版盖掉。
        draftPreviousContent = content
        content = ""
        val draftStartedAt = System.nanoTime()
        activeJob = scope.launch {
            var streamed = false
            var firstDeltaSeen = false
            var saved = false
            val r = repo.draftStream(
                id,
                outlineOnly,
                onDelta = { delta ->
                    streamed = true
                    if (agentProgress == "正在检索可用资料并准备正文…")
                        agentProgress = "正在生成正文…"
                    if (!firstDeltaSeen) {
                        firstDeltaSeen = true
                        val totalMs = if (writingClickAtNanos > 0)
                            (System.nanoTime() - writingClickAtNanos) / 1_000_000 else 0
                        writingTimeline.info("task=$id first_text_ms=${(System.nanoTime() - draftStartedAt) / 1_000_000} click_to_text_ms=$totalMs")
                    }
                    content += delta
                },
                onReplace = { replacement ->
                    streamed = true
                    content = replacement
                },
                onProgress = { progress ->
                    when (progress.type) {
                        "run" -> currentAgentRunId = progress.runId.takeIf { it.isNotBlank() }
                        "stage" -> if (progress.status == "running" && progress.label.isNotBlank()) {
                            agentProgress = if (progress.key == "repair")
                                "${progress.label}（第 ${progress.repairRound.coerceAtLeast(1)} 轮）"
                            else progress.label
                        }
                        "quality" -> if (progress.qualityLevel == "D") {
                            agentProgress = "校验发现 ${progress.issueCount} 项硬伤，正在定向修复"
                        }
                    }
                },
            )
            when {
                r is ApiResult.Ok -> r.data?.let { d ->
                    applyResponse(d)
                    saved = true
                    d["reply"].str().takeIf { it.isNotBlank() }
                        ?.let { messages = messages + TaskChatMessage("assistant", it, d["revision_summary"].str()) }
                }
                r is ApiResult.Err && r.status == 404 && !streamed -> {
                    // 服务端尚未升级流式接口：回退非流式起草
                    when (val r2 = repo.draft(id, outlineOnly)) {
                        is ApiResult.Ok -> r2.data?.let { d ->
                            applyResponse(d)
                            saved = true
                            d["reply"].str().takeIf { it.isNotBlank() }
                                ?.let { messages = messages + TaskChatMessage("assistant", it, d["revision_summary"].str()) }
                        }
                        is ApiResult.Err -> fail(r2.message)
                    }
                }
                r is ApiResult.Err -> fail(r.message)
            }
            if (!saved) {
                draftPreviousContent?.let { content = it }
                if (status.isNullOrBlank()) fail("生成未返回可保存的正文，请重试")
            } else {
                writingTimeline.info("task=$id draft_done_ms=${(System.nanoTime() - draftStartedAt) / 1_000_000}")
                status = null
            }
            agentProgress = null
            draftPreviousContent = null
            currentAgentRunId = null
            busy = false
            AppState.writingGenerating = false
        }
    }

    /**
     * AI 修改当前文档（快捷按钮与自然语言共用同一后端 revision 逻辑）。
     * mode: expand/polish/condense/normalize/complete/rewrite/revise
     */
    fun revise(instruction: String, mode: String) {
        val id = task.taskId ?: return
        if (busy || !hasDraft) return
        val submittedContent = content
        val submittedVersion = versionNo
        val submittedServerContent = serverContent
        busy = true
        agentProgress = "正在按要求修改并校验文稿…"
        AppState.writingGenerating = true
        AppState.writingLastError = null
        activeJob = scope.launch {
            when (val r = repo.revise(
                id, instruction, mode, submittedContent,
                submittedVersion, submittedServerContent)) {
                is ApiResult.Ok -> r.data?.let { d ->
                    applyResponse(d)
                    d["reply"].str().takeIf { it.isNotBlank() }
                        ?.let { messages = messages + TaskChatMessage("assistant", it, d["revision_summary"].str()) }
                }
                is ApiResult.Err -> fail(r.message)
            }
            busy = false
            agentProgress = null
            AppState.writingGenerating = false
        }
    }

    // ---------------- 字段编辑同步 ----------------

    /** 用户手改左侧字段后同步后端 */
    fun patchContext(patch: Map<String, Any?>) {
        val id = task.taskId ?: return
        scope.launch {
            when (val r = repo.patchContext(id, patch)) {
                is ApiResult.Ok -> r.data?.let { applyResponse(it) }
                is ApiResult.Err -> status = r.message
            }
        }
    }

    fun toggleDocNumber(enabled: Boolean) {
        task = task.copy(documentNumberEnabled = enabled,
            documentNumber = if (enabled) task.documentNumber else "")
        patchContext(mapOf(
            "document_number_enabled" to enabled,
            "document_number" to if (enabled) task.documentNumber else null,
        ))
    }

    fun setDocNumber(number: String) {
        task = task.copy(documentNumber = number)
        patchContext(mapOf("document_number" to number.ifBlank { null },
            "document_number_enabled" to number.isNotBlank()))
    }

    // ---------------- 材料 ----------------

    fun uploadMaterials(files: List<File>) {
        if (files.isEmpty() || busy) return
        val id = task.taskId
        if (id == null) {
            val selected = (entryMaterials + files).distinctBy { it.absolutePath }
            if (selected.size > 5) {
                status = "一次最多添加 5 个材料文件，请分批上传"
                return
            }
            entryMaterials = selected
            status = "已选择 ${entryMaterials.size} 份材料，开始写作后会自动识别并加入上下文"
            return
        }
        busy = true
        status = "上传材料中…"
        scope.launch {
            when (val r = repo.uploadTaskMaterials(id, files)) {
                is ApiResult.Ok -> {
                    materials = materials + r.data.map {
                        ChatAttachment(it["id"].str(), it["filename"].str(),
                            it["kind"].str().ifBlank { "doc" },
                            it["parse_status"].str() == "failed")
                    }
                    imageResults = imageResults + r.data.filter {
                        it["parse_note"].str().contains("识别")
                    }.map {
                        RecognizedImage(it["filename"].str(), it["text"].str(),
                            it["parse_note"].str(), it["parse_status"].str() != "failed")
                    }
                    val failedCount = r.data.count {
                        it["parse_status"].str() == "failed" || it["text"].str().isBlank()
                    }
                    status = "已上传 ${r.data.size} 份材料" +
                        (if (failedCount > 0) "；$failedCount 份未识别出可用文字" else
                            "，识别文本已加入写作上下文")
                }
                is ApiResult.Err -> fail(r.message)
            }
            busy = false
        }
    }

    fun removeEntryMaterial(file: File) {
        entryMaterials = entryMaterials.filterNot { it.absolutePath == file.absolutePath }
    }

    // ---------------- 图片识别（视觉模型） ----------------

    /**
     * 上传图片并由服务端视觉模型（Qwen2.5-VL）识别为文字。
     * 识别结果同时由服务端绑定到任务会话：之后的起草/修改自动把识别文本
     * 作为材料注入上下文，无需再手动粘贴。结果在弹窗中展示，可一键插入正文。
     */
    fun recognizeImages(files: List<File>) {
        val id = task.taskId ?: return
        if (files.isEmpty() || busy || recognizingImages) return
        recognizingImages = true
        status = "正在识别图片（视觉模型，图片较多时可能需要一两分钟）…"
        scope.launch {
            when (val r = repo.recognizeImages(id, files)) {
                is ApiResult.Ok -> {
                    val (items, vision) = r.data
                    imageResults = imageResults + items.map {
                        RecognizedImage(
                            filename = it["filename"].str(),
                            text = it["text"].str(),
                            note = it["parse_note"].str(),
                            ok = it["parse_status"].str() != "failed",
                        )
                    }
                    status = if (vision) {
                        "已识别 ${items.size} 张图片；识别文本已作为材料绑定本次写作，" +
                            "下次起草/修改会自动参考"
                    } else {
                        "服务端未配置视觉模型（VISION_MODEL_URL），本次走 OCR/文本通道"
                    }
                }
                is ApiResult.Err -> fail(r.message)
            }
            recognizingImages = false
        }
    }

    /** 把某条识别结果追加到正文末尾（作为用户手改，不影响服务端版本链） */
    fun insertImageText(item: RecognizedImage) {
        if (item.text.isBlank()) return
        content = (content.trimEnd() + "\n\n" + item.text.trim()).trim()
        status = "已把「${item.filename}」的识别文本插入正文末尾"
    }

    fun dismissImageResults() {
        imageResults = emptyList()
    }

    // ---------------- 版本 / 导出 / 训练 ----------------

    fun saveVersion(note: String? = null) {
        val id = task.taskId ?: return
        if (busy || suggestionBusy || !hasDraft) return
        val submittedContent = content
        val submittedVersion = versionNo
        val submittedServerContent = serverContent
        val submittedFormatting = formattingRequest()
        busy = true
        scope.launch {
            when (val r = repo.saveVersion(
                id, submittedContent, note, submittedVersion, submittedServerContent,
                submittedFormatting)) {
                is ApiResult.Ok -> {
                    r.data?.let { applyResponse(it) }
                    val warnings = r.data?.get("format_warnings").arr()
                        .map { it.str() }.filter { it.isNotBlank() }
                    status = if (r.data?.get("suggestions_reset").bool())
                        "已保存版本 v$versionNo；原逐段建议已失效，请重新获取"
                    else "已保存版本 v$versionNo"
                    if (warnings.isNotEmpty()) status += "；格式校验：${warnings.take(3).joinToString("、")}"
                    when (val check = repo.checkCurrentFormat(id)) {
                        is ApiResult.Ok -> {
                            formatIssues = check.data?.get("issues").arr().mapNotNull { it.obj() }
                            val skipped = check.data?.get("skipped").str()
                            status += if (skipped.isNotBlank()) "；$skipped"
                                else if (formatIssues.isEmpty()) "；格式复检通过"
                                else "；格式复检发现 ${formatIssues.size} 项问题"
                        }
                        is ApiResult.Err -> status += "；格式复检暂不可用：${check.message}"
                    }
                    refreshVersions()
                }
                is ApiResult.Err -> fail(r.message)
            }
            busy = false
        }
    }

    fun refreshVersions() {
        val id = task.taskId ?: return
        scope.launch {
            when (val r = repo.listVersions(id)) {
                is ApiResult.Ok -> versions = r.data
                is ApiResult.Err -> {}
            }
        }
    }

    /** 查看历史版本内容（弹窗预览） */
    fun openVersion(no: Int) {
        val id = task.taskId ?: return
        scope.launch {
            when (val r = repo.getVersion(id, no)) {
                is ApiResult.Ok -> versionPreview = r.data
                is ApiResult.Err -> status = r.message
            }
        }
    }

    fun closeVersionPreview() {
        versionPreview = null
    }

    /** 回退到历史版本：后端先把当前内容自动保存为新版本，再恢复目标版本内容 */
    fun restoreVersion(no: Int) {
        val id = task.taskId ?: return
        if (busy) return
        busy = true
        scope.launch {
            when (val r = repo.restoreVersion(id, no)) {
                is ApiResult.Ok -> {
                    r.data?.let { d ->
                        applyResponse(d)
                        d["reply"].str().takeIf { it.isNotBlank() }?.let { status = it }
                    }
                    versionPreview = null
                    refreshVersions()
                }
                is ApiResult.Err -> fail(r.message)
            }
            busy = false
        }
    }

    // ---------------- 参考材料（知识库文档）查看 / 编辑 ----------------

    /** 打开知识库文档全文（智能写作参考材料可直接查看/编辑） */
    fun openDocument(docId: String) {
        val kr = knowledgeRepo ?: return
        if (docId.isBlank() || docDialogBusy) return
        docDialogBusy = true
        scope.launch {
            when (val r = kr.getDocument(docId)) {
                is ApiResult.Ok -> {
                    val d = r.data
                    if (d != null) {
                        docDialogId = docId
                        docDialogTitle = d["title"].str()
                        docDialogDocType = d["doc_type"].str()
                        docDialogContent = d["content"].str()
                    } else {
                        status = "文档内容为空"
                    }
                }
                is ApiResult.Err -> status = r.message
            }
            docDialogBusy = false
        }
    }

    fun closeDocument() {
        docDialogId = null
        docDialogTitle = ""
        docDialogDocType = ""
        docDialogContent = ""
    }

    /** 保存对知识库文档的编辑：后端重新分块并重建该文档向量 */
    fun saveDocument() {
        val kr = knowledgeRepo ?: return
        val id = docDialogId ?: return
        if (docDialogBusy) return
        docDialogBusy = true
        scope.launch {
            when (val r = kr.updateDocument(id, docDialogTitle, docDialogContent)) {
                is ApiResult.Ok -> {
                    status = "已保存，知识库检索内容已同步更新"
                    closeDocument()
                }
                is ApiResult.Err -> status = r.message
            }
            docDialogBusy = false
        }
    }

    fun export(redHeader: Boolean, target: File) {
        val id = task.taskId ?: return
        if (busy || !hasDraft) return
        val submittedContent = content
        val submittedServerContent = serverContent
        val submittedVersion = versionNo
        val hadPendingFormatting = formatDirty
        val submittedFormatting = formattingRequest()
        busy = true
        status = "导出 Word 中…"
        scope.launch {
            var exportWarnings = emptyList<String>()
            if (submittedContent != submittedServerContent || hadPendingFormatting) {
                when (val saved = repo.saveVersion(id, submittedContent, "导出前保存",
                    submittedVersion, submittedServerContent, submittedFormatting)) {
                    is ApiResult.Ok -> {
                        val payload = saved.data
                        if (payload == null) {
                            fail("保存当前编辑失败，未导出：服务器未返回版本")
                            return@launch
                        }
                        exportWarnings = payload["format_warnings"].arr().map { it.str() }
                        applyResponse(payload)
                    }
                    is ApiResult.Err -> {
                        fail("保存当前编辑失败，未导出：${saved.message}")
                        return@launch
                    }
                }
            }
            val checkResult = repo.checkCurrentFormat(id)
            if (checkResult is ApiResult.Ok) {
                formatIssues = checkResult.data?.get("issues").arr().mapNotNull { it.obj() }
            } else formatIssues = emptyList()
            when (val r = repo.export(id, redHeader, target)) {
                is ApiResult.Ok -> status = "已导出：${target.name}" +
                    (if (exportWarnings.isEmpty()) "" else
                        "；格式预设：${exportWarnings.take(3).joinToString("、")}") +
                    (if (formatIssues.isEmpty()) "" else
                        "；格式复检发现 ${formatIssues.size} 项问题，请核对") +
                    (if (checkResult is ApiResult.Err) "；格式复检暂不可用" else "")
                is ApiResult.Err -> fail(r.message)
            }
            busy = false
        }
    }

    fun newTask() {
        entryMaterials = emptyList()
        suggestionOperation++
        suggestionBusy = false
        // 用户明确放弃当前任务：清掉跨页面恢复标记与上次失败原因，切回页面不应再恢复它
        AppState.pendingWritingTaskId = null
        AppState.writingLastError = null
        // 恢复请求随之作废：它拿到的仍是上一个任务，回来会把内容写进本次新任务
        restoreJob?.cancel()
        restoreJob = null
        restoring = false
        task = WritingTaskState()
        renderProfile = null
        titleFormatting = WritingTextStyle()
        paragraphFormatting = emptyMap()
        formatDirty = false
        formatIssues = emptyList()
        content = ""
        serverContent = ""
        paragraphs = emptyList()
        selectedLineIndex = null
        selectedSuggestion = null
        suggestionText = ""
        suggestionInstruction = ""
        paragraphEditing = false
        versionNo = 0
        taskStatus = "collecting"
        messages = emptyList()
        materials = emptyList()
        references = emptyList()
        referenceItems = emptyList()
        versions = emptyList()
        entryInput = ""
        chatInput = ""
        status = null
        agentProgress = null
        versionPreview = null
        imageResults = emptyList()
        recognizingImages = false
        closeDocument()
    }

    companion object {
        /** SpecPanel 可编辑要素标签 → task_context 字段键（与后端 plan_task 的 fields 标签一致） */
        private val SPEC_FIELD_KEYS = mapOf(
            "文种" to "document_type",
            "报送对象" to "recipient",
            "写作目标" to "purpose",
            "发文机关" to "authority",
            "时间范围" to "time_range",
            "用途" to "purpose",
            "主题" to "topic",
        )
    }
}
