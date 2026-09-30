package com.judicialai.desktop.features.chat

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import com.judicialai.desktop.app.AppScreen
import com.judicialai.desktop.app.AppState
import com.judicialai.desktop.core.network.ApiResult
import com.judicialai.desktop.core.utils.str
import com.judicialai.desktop.data.Repositories
import com.judicialai.desktop.features.chat.model.ChatAttachment
import com.judicialai.desktop.features.chat.model.ChatMessage
import com.judicialai.desktop.features.chat.model.ChatSession
import com.judicialai.desktop.features.chat.model.HistoryCategory
import com.judicialai.desktop.features.chat.model.HistoryItem
import com.judicialai.desktop.features.documents.DocumentsRepository
import com.judicialai.desktop.features.ppt.PptRepository
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import java.io.File

/** 记录标题长度上限：与后端 String(200) 对齐 */
private const val CHAT_HISTORY_TITLE_MAX = 200

class ChatViewModel(
    private val repo: ChatRepository,
    private val documentsRepo: DocumentsRepository = Repositories.documents,
    private val pptRepo: PptRepository = Repositories.ppt,
) {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)

    var sessions by mutableStateOf(listOf<ChatSession>())
        private set
    var currentSessionId by mutableStateOf<String?>(null)
        private set
    var messages by mutableStateOf(listOf<ChatMessage>())
        private set
    var attachments by mutableStateOf(listOf<ChatAttachment>())
        private set
    /** 参考模板：输入区的「参考模板条」仍在使用，故保留（设置入口随欢迎面板移除而消失） */
    var referenceTemplate by mutableStateOf<Pair<String, String>?>(null)
        private set
    var useRag by mutableStateOf(true)
    var sending by mutableStateOf(false)
        private set
    var status by mutableStateOf<String?>(null)

    // ---- 历史记录：只展示当前登录用户自己生成的内容（对话 / 文档 / PPT / 工作流）----
    /** 当前展示的历史分类；四类数据源见 [HistoryCategory] 注释（后端无统一类型字段） */
    var historyCategory by mutableStateOf(HistoryCategory.CHAT)
        private set
    var historyChats by mutableStateOf(listOf<HistoryItem>())
        private set
    var historyDocs by mutableStateOf(listOf<HistoryItem>())
        private set
    var historyPpts by mutableStateOf(listOf<HistoryItem>())
        private set
    var historyWorkflows by mutableStateOf(listOf<HistoryItem>())
        private set
    var historyLoading by mutableStateOf(false)
        private set

    /** 记录写操作进行中：重命名 / 删除期间禁用按钮，避免重复点击 */
    var historyBusy by mutableStateOf(false)
        private set
    /** 记录写操作反馈（成功/失败），UI 用 NoticeBar 展示 */
    var historyMessage by mutableStateOf<String?>(null)
        private set
    var historyMessageError by mutableStateOf(false)
        private set

    // ---- 文档内嵌查看：点文档不离开历史记录入口，仍可切换其他记录 ----
    var openedDoc by mutableStateOf<JsonObject?>(null)
        private set
    var openedDocLoading by mutableStateOf(false)
        private set

    /** 切换历史分类 */
    fun selectHistoryCategory(category: HistoryCategory) {
        historyCategory = category
        historyMessage = null
        loadHistory(category)
    }

    fun clearHistoryMessage() {
        historyMessage = null
        historyMessageError = false
    }

    /**
     * 重命名记录：四类共用同一入口，各自 PATCH/PUT 自己的端点，
     * 成功后用后端返回值刷新当前分类（不本地伪造标题）。
     */
    fun renameHistory(item: HistoryItem, title: String) {
        val name = title.trim()
        if (historyBusy || name.isBlank() || name.length > CHAT_HISTORY_TITLE_MAX) return
        historyBusy = true
        historyMessage = null
        scope.launch {
            val r: ApiResult<JsonElement> = when (item.category) {
                HistoryCategory.CHAT -> repo.renameSession(item.id, name)
                HistoryCategory.DOC -> documentsRepo.rename(item.id, name)
                HistoryCategory.PPT -> pptRepo.renameDocument(item.id, name)
                HistoryCategory.WORKFLOW -> Repositories.workflow.renameInstance(item.id, name)
            }
            when (r) {
                is ApiResult.Ok -> {
                    refreshHistory(item.category)
                    historyMessage = "已重命名为「$name」"
                    historyMessageError = false
                }
                is ApiResult.Err -> {
                    historyMessage = r.message
                    historyMessageError = true
                }
            }
            historyBusy = false
        }
    }

    /**
     * 删除记录：四类共用同一入口（对话走 /chat/sessions/{id}，
     * 文档走 /documents/{id}，PPT 走 /ppt/documents/{id}，工作流走 /workflow/instances/{id}）。
     * 删除的是当前打开的会话/文档时，查看状态回到空态。
     */
    fun deleteHistory(item: HistoryItem) {
        if (historyBusy) return
        historyBusy = true
        historyMessage = null
        scope.launch {
            val r: ApiResult<JsonElement> = when (item.category) {
                HistoryCategory.CHAT -> repo.deleteSession(item.id)
                HistoryCategory.DOC -> documentsRepo.delete(item.id)
                HistoryCategory.PPT -> pptRepo.deleteDocument(item.id)
                HistoryCategory.WORKFLOW -> Repositories.workflow.deleteInstance(item.id)
            }
            when (r) {
                is ApiResult.Ok -> {
                    if (item.category == HistoryCategory.CHAT && currentSessionId == item.id) {
                        newSession()
                    }
                    if (item.category == HistoryCategory.DOC &&
                        openedDoc?.get("id")?.str() == item.id) {
                        closeInlineDoc()
                    }
                    refreshHistory(item.category)
                    historyMessage = "已删除「${item.title}」"
                    historyMessageError = false
                }
                is ApiResult.Err -> {
                    historyMessage = r.message
                    historyMessageError = true
                }
            }
            historyBusy = false
        }
    }

    /** 刷新单个分类：对话走 loadSessions（同步 sessions 与 historyChats） */
    private fun refreshHistory(category: HistoryCategory) {
        when (category) {
            HistoryCategory.CHAT -> loadSessions()
            HistoryCategory.DOC -> loadHistory(HistoryCategory.DOC)
            HistoryCategory.PPT -> loadHistory(HistoryCategory.PPT)
            HistoryCategory.WORKFLOW -> loadHistory(HistoryCategory.WORKFLOW)
        }
    }

    /**
     * 读取历史记录：按分类分别命中四个「后端已按当前用户过滤」的端点，
     * 不做任何客户端二次过滤之外的拼装，也不伪造任何类型。
     */
    fun loadHistory(category: HistoryCategory = historyCategory) {
        historyLoading = true
        scope.launch {
            when (category) {
                HistoryCategory.CHAT -> when (val r = repo.listMyChats()) {
                    is ApiResult.Ok -> historyChats = r.data
                    is ApiResult.Err -> status = r.message
                }
                HistoryCategory.DOC -> when (val r = repo.listMyDocuments()) {
                    is ApiResult.Ok -> historyDocs = r.data
                    is ApiResult.Err -> status = r.message
                }
                HistoryCategory.PPT -> when (val r = repo.listMyPptDocuments()) {
                    is ApiResult.Ok -> historyPpts = r.data
                    is ApiResult.Err -> status = r.message
                }
                HistoryCategory.WORKFLOW ->
                    when (val r = Repositories.workflow.instances()) {
                        is ApiResult.Ok -> historyWorkflows = r.data.map { inst ->
                            HistoryItem(
                                id = inst["id"].str(),
                                title = inst["title"].str().ifBlank { "（未命名工作流）" },
                                category = HistoryCategory.WORKFLOW,
                                time = inst["created_at"].str(),
                                sub = inst["template_name"].str(),
                            )
                        }
                        is ApiResult.Err -> status = r.message
                    }
            }
            historyLoading = false
        }
    }

    /** 指定分类下的历史条目（时间线筛选用） */
    fun historyItemsOf(category: HistoryCategory): List<HistoryItem> = when (category) {
        HistoryCategory.CHAT -> historyChats
        HistoryCategory.DOC -> historyDocs
        HistoryCategory.PPT -> historyPpts
        HistoryCategory.WORKFLOW -> historyWorkflows
    }

    /** 当前分类下的历史条目 */
    fun historyItems(): List<HistoryItem> = historyItemsOf(historyCategory)

    /** 全量历史（时间线视图用）：四类合并、按时间倒序 */
    fun allHistoryItems(): List<HistoryItem> =
        (historyChats + historyDocs + historyPpts + historyWorkflows)
            .sortedByDescending { it.time }

    /** 某分类的条目数（时间线页顶部统计用） */
    fun historyCount(category: HistoryCategory): Int = when (category) {
        HistoryCategory.CHAT -> historyChats.size
        HistoryCategory.DOC -> historyDocs.size
        HistoryCategory.PPT -> historyPpts.size
        HistoryCategory.WORKFLOW -> historyWorkflows.size
    }

    fun loadSessions() {
        scope.launch {
            when (val r = repo.listSessions()) {
                is ApiResult.Ok -> {
                    sessions = r.data
                    // 会话列表与「历史记录 · 对话」同源，保持同步（删除 / 新建后即时可见）
                    historyChats = r.data.map {
                        HistoryItem(it.id, it.title, HistoryCategory.CHAT, it.createdAt)
                    }
                }
                is ApiResult.Err -> status = r.message
            }
        }
    }

    fun selectReferenceTemplate(t: Pair<String, String>) {
        referenceTemplate = t
    }

    fun clearReferenceTemplate() {
        referenceTemplate = null
    }

    fun newSession() {
        currentSessionId = null
        messages = emptyList()
        attachments = emptyList()
        referenceTemplate = null
        closeInlineDoc()
    }

    fun openSession(id: String) {
        closeInlineDoc()
        currentSessionId = id
        scope.launch {
            when (val r = repo.listMessages(id)) {
                is ApiResult.Ok -> messages = r.data
                is ApiResult.Err -> status = r.message
            }
        }
    }

    /** 打开文档预览（弹窗查看；需要编辑时再带 id 跳「我的文档」页） */
    fun openDocumentInline(id: String) {
        openedDocLoading = true
        openedDoc = null
        scope.launch {
            when (val r = documentsRepo.detail(id)) {
                is ApiResult.Ok -> {
                    openedDoc = r.data
                    if (r.data == null) status = "文档不存在或已被删除"
                }
                is ApiResult.Err -> status = r.message
            }
            openedDocLoading = false
        }
    }

    fun closeInlineDoc() {
        openedDoc = null
        openedDocLoading = false
    }

    /**
     * 「继续」：
     * - PPT → 带上文档 id 跳 PPT 工作台继续修改；
     * - 工作流 → 跳工作流页（入口在「科室空间」）；
     * - 对话 / 文档的查看由历史记录页弹窗处理（右侧对话区已移除）。
     */
    fun openHistoryItem(item: HistoryItem) {
        when (item.category) {
            HistoryCategory.CHAT -> openSession(item.id)
            HistoryCategory.DOC -> openDocumentInline(item.id)
            HistoryCategory.PPT -> {
                AppState.pendingPptDocId = item.id
                AppState.navigate(AppScreen.PPT)
            }
            HistoryCategory.WORKFLOW -> AppState.navigate(AppScreen.WORKFLOW)
        }
    }

    fun send(text: String) {
        if (text.isBlank() || sending) return
        messages = messages + ChatMessage("user", text, attachments = attachments)
        sending = true
        status = null
        scope.launch {
            when (val r = repo.send(text, currentSessionId, useRag,
                attachments.map { it.id }, referenceTemplate?.first)) {
                is ApiResult.Ok -> {
                    messages = messages + ChatMessage(
                        "assistant", r.data.reply, sources = r.data.sources,
                        documentId = r.data.documentId,
                        qualityLevel = r.data.qualityLevel,
                        qualityIssues = r.data.qualityIssues,
                        unverifiedCitations = r.data.unverifiedCitations,
                    )
                    if (currentSessionId == null && r.data.sessionId != null) {
                        currentSessionId = r.data.sessionId
                        loadSessions()
                    } else if (currentSessionId != null) {
                        loadSessions()
                    }
                    attachments = emptyList()
                }
                is ApiResult.Err -> status = r.message
            }
            sending = false
        }
    }

    fun upload(files: List<File>) {
        if (files.isEmpty()) return
        status = "上传附件中…"
        scope.launch {
            when (val r = repo.uploadAttachments(files)) {
                is ApiResult.Ok -> {
                    attachments = attachments + r.data
                    status = null
                }
                is ApiResult.Err -> status = r.message
            }
        }
    }

    fun removeAttachment(a: ChatAttachment) {
        scope.launch {
            repo.deleteAttachment(a.id)
            attachments = attachments.filter { it.id != a.id }
        }
    }

    fun export(payload: Map<String, Any?>, redHeader: Boolean, target: File) {
        scope.launch {
            status = when (val r = repo.exportDocx(payload, redHeader, target)) {
                is ApiResult.Ok -> r.data
                is ApiResult.Err -> r.message
            }
        }
    }

    fun lastAssistantMessage(): String =
        messages.lastOrNull { it.role == "assistant" }?.content ?: ""
}
