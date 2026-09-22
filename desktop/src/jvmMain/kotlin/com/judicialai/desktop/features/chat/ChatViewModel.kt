package com.judicialai.desktop.features.chat

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import com.judicialai.desktop.app.AppScreen
import com.judicialai.desktop.app.AppState
import com.judicialai.desktop.core.network.ApiResult
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
import java.io.File

/** 记录标题长度上限：与后端 String(200) 对齐 */
const val HISTORY_TITLE_MAX = 200

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

    // ---- 历史记录：只展示当前登录用户自己生成的内容（对话 / 文档 / PPT）----
    /** 当前展示的历史分类；三类数据源见 [HistoryCategory] 注释（后端无统一类型字段） */
    var historyCategory by mutableStateOf(HistoryCategory.CHAT)
        private set
    var historyChats by mutableStateOf(listOf<HistoryItem>())
        private set
    var historyDocs by mutableStateOf(listOf<HistoryItem>())
        private set
    var historyPpts by mutableStateOf(listOf<HistoryItem>())
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
     * 重命名记录：三类共用同一入口，各自 PATCH 自己的端点，
     * 成功后用后端返回值刷新当前分类（不本地伪造标题）。
     */
    fun renameHistory(item: HistoryItem, title: String) {
        val name = title.trim()
        if (historyBusy || name.isBlank() || name.length > HISTORY_TITLE_MAX) return
        historyBusy = true
        historyMessage = null
        scope.launch {
            val r: ApiResult<JsonElement> = when (item.category) {
                HistoryCategory.CHAT -> repo.renameSession(item.id, name)
                HistoryCategory.DOC -> documentsRepo.rename(item.id, name)
                HistoryCategory.PPT -> pptRepo.renameDocument(item.id, name)
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
     * 删除记录：三类共用同一入口（对话走 /chat/sessions/{id}，
     * 文档走 /documents/{id}，PPT 走 /ppt/documents/{id}）。
     * 删除的是当前打开的会话时，右栏回到新建态。
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
            }
            when (r) {
                is ApiResult.Ok -> {
                    if (item.category == HistoryCategory.CHAT && currentSessionId == item.id) {
                        newSession()
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
        }
    }

    /**
     * 读取历史记录：按分类分别命中三个「后端已按当前用户过滤」的端点，
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
            }
            historyLoading = false
        }
    }

    /** 当前分类下的历史条目 */
    fun historyItems(): List<HistoryItem> = when (historyCategory) {
        HistoryCategory.CHAT -> historyChats
        HistoryCategory.DOC -> historyDocs
        HistoryCategory.PPT -> historyPpts
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
    }

    fun openSession(id: String) {
        currentSessionId = id
        scope.launch {
            when (val r = repo.listMessages(id)) {
                is ApiResult.Ok -> messages = r.data
                is ApiResult.Err -> status = r.message
            }
        }
    }

    /**
     * 「继续」：
     * - 对话 → 载入右栏继续聊；
     * - 文档 → 带 id 跳文档页，由 DocumentsScreen 消费后直接打开这一条（不是只落到列表页）；
     * - PPT → 跳 PPT 工作台。PPT 页没有按 id 打开既有演示的详情路由，
     *   所以这里不伪造「打开单条」，只跳转，按钮文案写明是「打开 PPT 工作台」。
     */
    fun openHistoryItem(item: HistoryItem) {
        when (item.category) {
            HistoryCategory.CHAT -> openSession(item.id)
            HistoryCategory.DOC -> {
                // 先挂待消费参数再导航：navigate() 不清它，由目标页消费后置回 null
                AppState.pendingDocumentId = item.id
                AppState.navigate(AppScreen.DOCUMENTS)
            }
            HistoryCategory.PPT -> AppState.navigate(AppScreen.PPT)
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

    /** 加入训练集：进入候选数据，需审核后才参与训练 */
    fun addToTraining(instruction: String, draft: String, output: String) {
        val sid = currentSessionId ?: ""
        scope.launch {
            status = when (val r = repo.addToTraining(sid, instruction, draft, output)) {
                is ApiResult.Ok -> "已加入训练集（待审核），可在「数据资产中心」查看"
                is ApiResult.Err -> "加入训练集失败：${r.message}"
            }
        }
    }

    fun lastAssistantMessage(): String =
        messages.lastOrNull { it.role == "assistant" }?.content ?: ""
}

